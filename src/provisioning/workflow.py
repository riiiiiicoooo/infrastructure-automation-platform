"""
Provisioning Workflow - Reference Implementation
Temporal workflow that orchestrates the full environment provisioning lifecycle:
request validation -> policy check -> approval gate -> Terraform -> Ansible -> CMDB -> compliance scan.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Optional


class ProvisioningStatus(str, Enum):
    SUBMITTED = "submitted"
    VALIDATING = "validating"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PROVISIONING = "provisioning"
    CONFIGURING = "configuring"
    VALIDATING_COMPLIANCE = "validating_compliance"
    ACTIVE = "active"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class ProvisioningRequest:
    id: str
    org_id: str
    template_id: str
    requested_by: str
    project_name: str
    team: str
    parameters: dict = field(default_factory=dict)
    cost_center: Optional[str] = None


@dataclass
class PolicyResult:
    decision: str  # "allow", "deny"
    policies_evaluated: int
    policies_passed: int
    policies_failed: int
    details: list[dict] = field(default_factory=list)
    requires_approval: bool = False
    approval_reason: Optional[str] = None


@dataclass
class TerraformPlan:
    resources_to_create: int
    resources_to_modify: int
    resources_to_destroy: int
    cost_delta_monthly: float
    plan_output: str  # raw terraform plan text
    resources: list[dict] = field(default_factory=list)


@dataclass
class ApprovalDecision:
    approved: bool
    approved_by: str
    comment: str
    decided_at: str


@dataclass
class ProvisioningResult:
    request_id: str
    status: ProvisioningStatus
    resource_ids: list[str] = field(default_factory=list)
    terraform_state_path: Optional[str] = None
    compliance_status: Optional[str] = None
    estimated_monthly_cost: Optional[float] = None
    failure_reason: Optional[str] = None
    failure_step: Optional[str] = None


# Temporal workflow timeouts
POLICY_EVALUATION_TIMEOUT = timedelta(seconds=30)
TERRAFORM_PLAN_TIMEOUT = timedelta(minutes=10)
TERRAFORM_APPLY_TIMEOUT = timedelta(hours=2)
ANSIBLE_TIMEOUT = timedelta(hours=1)
COMPLIANCE_SCAN_TIMEOUT = timedelta(minutes=15)
APPROVAL_WAIT_TIMEOUT = timedelta(days=7)  # approval expires after 7 days

# Retry policy for transient failures
RETRY_POLICY = {
    "initial_interval": timedelta(seconds=5),
    "backoff_coefficient": 2.0,
    "maximum_interval": timedelta(minutes=5),
    "maximum_attempts": 3,
}


class ProvisioningWorkflow:
    """
    Temporal workflow: provision_environment

    Orchestrates a 7-step provisioning pipeline with durable execution.
    If the platform crashes mid-workflow, Temporal replays from the last
    completed step. No resources are re-provisioned.

    Approval gate uses Temporal signals: the workflow pauses indefinitely
    and resumes when the approver sends an approval or rejection signal
    through the API/portal.

    Each step is an activity function with its own timeout and retry policy.
    """

    def __init__(self, db_pool, vault_client, terraform_runner, ansible_runner,
                 policy_engine, cmdb_client, notification_service):
        self.db = db_pool
        self.vault = vault_client
        self.terraform = terraform_runner
        self.ansible = ansible_runner
        self.policy = policy_engine
        self.cmdb = cmdb_client
        self.notify = notification_service

    async def run(self, request: ProvisioningRequest) -> ProvisioningResult:
        """
        Main workflow execution. Called by Temporal when a provisioning
        workflow is started.

        Steps:
        1. Validate request + evaluate OPA policies
        2. Route to approval (if required) or auto-approve
        3. Acquire Vault dynamic credentials (scoped STS token)
        4. Generate and execute Terraform
        5. Run Ansible hardening
        6. Register in CMDB + configure monitoring
        7. Post-provisioning compliance scan
        """
        result = ProvisioningResult(request_id=request.id, status=ProvisioningStatus.SUBMITTED)

        try:
            # Step 1: Policy evaluation
            await self._update_status(request.id, ProvisioningStatus.VALIDATING)
            template = await self._load_template(request.template_id)
            policy_result = await self._evaluate_policies(request, template)

            if policy_result.decision == "deny":
                await self._update_status(request.id, ProvisioningStatus.REJECTED)
                await self._store_policy_result(request.id, policy_result)
                await self._notify_rejection(request, policy_result)
                result.status = ProvisioningStatus.REJECTED
                result.failure_reason = self._format_policy_failures(policy_result)
                result.failure_step = "policy_evaluation"
                return result

            await self._store_policy_result(request.id, policy_result)

            # Step 2: Approval gate (if required)
            if policy_result.requires_approval:
                plan = await self._generate_terraform_plan(request, template)
                await self._store_plan_for_approver(request.id, plan)
                await self._update_status(request.id, ProvisioningStatus.PENDING_APPROVAL)
                await self._request_approval(request, plan, policy_result)

                # Workflow pauses here. Temporal signal resumes it.
                approval = await self._wait_for_approval_signal(request.id)

                if not approval.approved:
                    await self._update_status(request.id, ProvisioningStatus.REJECTED)
                    await self._store_approval_decision(request.id, approval)
                    result.status = ProvisioningStatus.REJECTED
                    result.failure_reason = f"Rejected by {approval.approved_by}: {approval.comment}"
                    result.failure_step = "approval"
                    return result

                await self._store_approval_decision(request.id, approval)

            await self._update_status(request.id, ProvisioningStatus.APPROVED)

            # Step 3: Acquire scoped dynamic credentials from Vault
            vault_lease = await self._acquire_credentials(request, template)

            try:
                # Step 4: Terraform generate + apply
                await self._update_status(request.id, ProvisioningStatus.PROVISIONING)

                if not policy_result.requires_approval:
                    # Plan wasn't generated for approval, generate now
                    plan = await self._generate_terraform_plan(request, template)

                apply_result = await self._terraform_apply(request, template, plan, vault_lease)
                result.resource_ids = apply_result["resource_ids"]
                result.terraform_state_path = apply_result["state_path"]

                # Step 5: Ansible hardening
                await self._update_status(request.id, ProvisioningStatus.CONFIGURING)
                await self._ansible_configure(request, template, apply_result["resource_ids"])

                # Step 6: CMDB registration + monitoring
                await self._register_resources(request, template, apply_result)
                await self._configure_monitoring(request, apply_result["resource_ids"])

                # Step 7: Post-provisioning compliance scan
                await self._update_status(request.id, ProvisioningStatus.VALIDATING_COMPLIANCE)
                compliance_result = await self._run_compliance_scan(apply_result["resource_ids"])
                result.compliance_status = compliance_result["status"]

                if compliance_result["status"] == "non_compliant":
                    # Quarantine: mark resources but don't tear down
                    await self._quarantine_resources(apply_result["resource_ids"],
                                                     compliance_result["failures"])
                    await self._notify_compliance_failure(request, compliance_result)
                    result.status = ProvisioningStatus.FAILED
                    result.failure_reason = "Post-provisioning compliance scan failed"
                    result.failure_step = "compliance_validation"
                    return result

            finally:
                # Always revoke Vault lease, even on failure
                await self._revoke_credentials(vault_lease)

            # Success
            await self._update_status(request.id, ProvisioningStatus.ACTIVE)
            result.status = ProvisioningStatus.ACTIVE
            result.estimated_monthly_cost = plan.cost_delta_monthly
            await self._notify_success(request, result)
            await self._audit_log(request, "provisioning_request.completed", {
                "resource_ids": result.resource_ids,
                "estimated_monthly_cost": result.estimated_monthly_cost,
                "compliance_status": result.compliance_status,
            })

            return result

        except Exception as e:
            await self._update_status(request.id, ProvisioningStatus.FAILED)
            result.status = ProvisioningStatus.FAILED
            result.failure_reason = str(e)
            await self._notify_failure(request, str(e))
            raise  # Temporal will retry based on retry policy

    # ---------------------------------------------------------------
    # Activity: Policy Evaluation
    # ---------------------------------------------------------------

    async def _evaluate_policies(self, request: ProvisioningRequest,
                                  template: dict) -> PolicyResult:
        """
        Evaluate provisioning request against OPA policy bundle.
        Timeout: 30 seconds. No retries (policy failures are deterministic).

        Input to OPA:
        {
            "request": { template, parameters, team, cost_center },
            "template": { required policies, estimated cost, environment level },
            "org": { budget remaining, active resource count, compliance frameworks }
        }
        """
        org_context = await self._load_org_context(request.org_id)

        opa_input = {
            "request": {
                "template_id": request.template_id,
                "parameters": request.parameters,
                "team": request.team,
                "cost_center": request.cost_center,
                "project_name": request.project_name,
            },
            "template": template,
            "org": org_context,
        }

        raw_result = await self.policy.evaluate(
            policy_bundle=template.get("policy_requirements", []),
            input_data=opa_input,
        )

        requires_approval = (
            template.get("requires_approval", False)
            or raw_result.get("estimated_monthly_cost", 0) > org_context.get("approval_threshold", 500)
            or template.get("name") == "production"
        )

        return PolicyResult(
            decision=raw_result["decision"],
            policies_evaluated=raw_result["total"],
            policies_passed=raw_result["passed"],
            policies_failed=raw_result["failed"],
            details=raw_result.get("details", []),
            requires_approval=requires_approval,
            approval_reason=self._determine_approval_reason(template, raw_result, org_context),
        )

    def _determine_approval_reason(self, template: dict, policy_result: dict,
                                    org_context: dict) -> Optional[str]:
        if template.get("name") == "production":
            return "production_access"
        if policy_result.get("estimated_monthly_cost", 0) > org_context.get("approval_threshold", 500):
            return f"estimated_cost_exceeds_threshold"
        if template.get("requires_approval"):
            return "template_requires_approval"
        return None

    # ---------------------------------------------------------------
    # Activity: Terraform Plan + Apply
    # ---------------------------------------------------------------

    async def _generate_terraform_plan(self, request: ProvisioningRequest,
                                        template: dict) -> TerraformPlan:
        """
        Generate Terraform configuration from template + parameters,
        then run terraform plan.

        Template modules are composed from the internal registry.
        User parameters override template defaults where allowed.
        """
        # Merge template defaults with user overrides
        merged_params = {**template.get("default_parameters", {}), **request.parameters}

        # Generate Terraform HCL from module references
        tf_config = self.terraform.generate_config(
            modules=template["terraform_modules"],
            parameters=merged_params,
            tags={
                "project": request.project_name,
                "team": request.team,
                "cost_center": request.cost_center or "unassigned",
                "managed_by": "infrastructure-automation-platform",
                "provisioning_request_id": request.id,
            },
        )

        # Run terraform plan
        plan_output = await self.terraform.plan(
            config=tf_config,
            state_key=f"{request.org_id}/{request.project_name}",
        )

        # Parse plan JSON output into structured summary
        plan_json = json.loads(plan_output["json"])
        resources = []
        for change in plan_json.get("resource_changes", []):
            resources.append({
                "type": change["type"],
                "name": change["name"],
                "action": change["change"]["actions"][0],
            })

        return TerraformPlan(
            resources_to_create=sum(1 for r in resources if r["action"] == "create"),
            resources_to_modify=sum(1 for r in resources if r["action"] == "update"),
            resources_to_destroy=sum(1 for r in resources if r["action"] == "delete"),
            cost_delta_monthly=plan_output.get("estimated_cost", 0.0),
            plan_output=plan_output["text"],
            resources=resources,
        )

    async def _terraform_apply(self, request: ProvisioningRequest, template: dict,
                                plan: TerraformPlan, vault_lease: dict) -> dict:
        """
        Execute terraform apply using the approved plan.
        Credentials come from the Vault dynamic lease (scoped STS token).
        """
        result = await self.terraform.apply(
            state_key=f"{request.org_id}/{request.project_name}",
            credentials=vault_lease["credentials"],
        )

        resource_ids = []
        for resource in result.get("resources_created", []):
            resource_ids.append(resource["cloud_resource_id"])

        return {
            "resource_ids": resource_ids,
            "state_path": f"s3://tf-state/{request.org_id}/{request.project_name}/terraform.tfstate",
            "resources_detail": result.get("resources_created", []),
        }

    # ---------------------------------------------------------------
    # Activity: Ansible Configuration
    # ---------------------------------------------------------------

    async def _ansible_configure(self, request: ProvisioningRequest,
                                  template: dict, resource_ids: list[str]):
        """
        Run Ansible playbooks for post-provisioning hardening.
        Playbooks are defined in the template and tested with Molecule.

        Standard playbooks:
        - cis_hardening: CIS benchmark compliance
        - datadog_agent: monitoring agent installation
        - ssh_config: SSH hardening (key-only, restricted access)
        """
        playbooks = template.get("ansible_playbooks", [])

        for playbook in playbooks:
            await self.ansible.run(
                playbook_name=playbook["name"],
                playbook_version=playbook["version"],
                target_hosts=resource_ids,
                extra_vars=playbook.get("params", {}),
            )

    # ---------------------------------------------------------------
    # Activity: CMDB Registration
    # ---------------------------------------------------------------

    async def _register_resources(self, request: ProvisioningRequest,
                                   template: dict, apply_result: dict):
        """
        Register all provisioned resources in the CMDB.
        Creates resource records with metadata, tags, and dependency mappings.

        SQL: INSERT INTO resources (...)
        SQL: INSERT INTO resource_dependencies (...)
        """
        for resource in apply_result.get("resources_detail", []):
            async with self.db.acquire() as conn:
                # Insert resource record
                resource_id = await conn.fetchval("""
                    INSERT INTO resources (
                        org_id, request_id, cloud_resource_id, resource_type,
                        name, region, availability_zone, environment, team,
                        project, status, configuration, tags, monthly_cost,
                        provisioned_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                              'active', $11, $12, $13, now())
                    RETURNING id
                """,
                    request.org_id,
                    request.id,
                    resource["cloud_resource_id"],
                    resource["resource_type"],
                    resource["name"],
                    resource["region"],
                    resource.get("availability_zone"),
                    template.get("environment", "dev"),
                    request.team,
                    request.project_name,
                    json.dumps(resource.get("configuration", {})),
                    json.dumps(resource.get("tags", {})),
                    resource.get("estimated_monthly_cost", 0),
                )

                # Register dependencies
                for dep in resource.get("dependencies", []):
                    await conn.execute("""
                        INSERT INTO resource_dependencies (
                            resource_id, depends_on_id, dependency_type, is_critical
                        ) VALUES ($1, $2, $3, $4)
                        ON CONFLICT (resource_id, depends_on_id) DO NOTHING
                    """, resource_id, dep["resource_id"], dep["type"], dep.get("critical", True))

    # ---------------------------------------------------------------
    # Activity: Vault Credential Management
    # ---------------------------------------------------------------

    async def _acquire_credentials(self, request: ProvisioningRequest,
                                    template: dict) -> dict:
        """
        Acquire scoped dynamic credentials from Vault.
        Returns STS session token with 1-hour TTL, scoped to the
        resource types in this template.

        The lease is tracked so it can be revoked on workflow completion.
        """
        org = await self._load_org_settings(request.org_id)
        cloud_provider = org["cloud_provider"]

        if cloud_provider == "aws":
            lease = await self.vault.aws_generate_credentials(
                role=f"provisioning-{template['name']}",
                ttl="1h",
            )
        elif cloud_provider == "azure":
            lease = await self.vault.azure_generate_credentials(
                role=f"provisioning-{template['name']}",
                ttl="1h",
            )
        else:
            raise ValueError(f"Unsupported cloud provider: {cloud_provider}")

        await self._audit_log(request, "vault.credential_issued", {
            "lease_id": lease["lease_id"],
            "role": f"provisioning-{template['name']}",
            "ttl_seconds": 3600,
            "workflow_id": request.id,
        })

        return lease

    async def _revoke_credentials(self, vault_lease: dict):
        """Explicitly revoke Vault lease on workflow completion or failure."""
        if vault_lease and vault_lease.get("lease_id"):
            await self.vault.revoke_lease(vault_lease["lease_id"])

    # ---------------------------------------------------------------
    # Activity: Approval Signal
    # ---------------------------------------------------------------

    async def _wait_for_approval_signal(self, request_id: str) -> ApprovalDecision:
        """
        Pause workflow and wait for approval signal.

        This is a Temporal signal handler. The workflow blocks here until:
        1. An approver sends an approve/reject signal via the API
        2. The approval timeout expires (7 days)

        The portal shows the approver: Terraform plan diff view, cost delta,
        and policy evaluation results.
        """
        # In Temporal, this is: workflow.wait_condition(signal_received, timeout)
        # Simplified here for reference implementation
        pass

    async def _request_approval(self, request: ProvisioningRequest,
                                 plan: TerraformPlan, policy_result: PolicyResult):
        """Send approval notification with plan summary."""
        await self.notify.send_approval_request(
            approver_role=policy_result.approval_reason,
            request_id=request.id,
            requested_by=request.requested_by,
            project_name=request.project_name,
            plan_summary={
                "resources_to_create": plan.resources_to_create,
                "resources_to_modify": plan.resources_to_modify,
                "resources_to_destroy": plan.resources_to_destroy,
                "cost_delta_monthly": plan.cost_delta_monthly,
            },
            policy_summary={
                "evaluated": policy_result.policies_evaluated,
                "passed": policy_result.policies_passed,
                "approval_reason": policy_result.approval_reason,
            },
        )

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    async def _update_status(self, request_id: str, status: ProvisioningStatus):
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE provisioning_requests SET status = $1 WHERE id = $2",
                status.value, request_id,
            )

    async def _audit_log(self, request: ProvisioningRequest, action: str, details: dict):
        async with self.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO audit_log (org_id, actor_id, actor_type, action,
                                       resource_type, resource_id, details)
                VALUES ($1, $2, 'temporal_workflow', $3, 'provisioning_request', $4, $5)
            """, request.org_id, request.requested_by, action,
                request.id, json.dumps(details))

    async def _load_template(self, template_id: str) -> dict:
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM environment_templates WHERE id = $1 AND is_active = true",
                template_id,
            )
            if not row:
                raise ValueError(f"Template {template_id} not found or inactive")
            return dict(row)

    async def _load_org_context(self, org_id: str) -> dict:
        async with self.db.acquire() as conn:
            org = await conn.fetchrow("SELECT * FROM organizations WHERE id = $1", org_id)
            settings = json.loads(org["settings"]) if org["settings"] else {}

            active_count = await conn.fetchval(
                "SELECT COUNT(*) FROM resources WHERE org_id = $1 AND status = 'active'",
                org_id,
            )
            monthly_spend = await conn.fetchval(
                "SELECT COALESCE(SUM(monthly_cost), 0) FROM resources WHERE org_id = $1 AND status = 'active'",
                org_id,
            )

            return {
                "cloud_provider": org["cloud_provider"],
                "compliance_frameworks": settings.get("compliance_frameworks", []),
                "approval_threshold": settings.get("default_approval_threshold_monthly", 500),
                "active_resource_count": active_count,
                "current_monthly_spend": float(monthly_spend),
            }

    async def _load_org_settings(self, org_id: str) -> dict:
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM organizations WHERE id = $1", org_id)
            return dict(row)

    def _format_policy_failures(self, policy_result: PolicyResult) -> str:
        failures = [d for d in policy_result.details if d.get("result") == "fail"]
        return "; ".join(f["policy"] + ": " + f.get("message", "failed") for f in failures)

    async def _store_policy_result(self, request_id: str, result: PolicyResult):
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE provisioning_requests SET policy_result = $1 WHERE id = $2",
                json.dumps({
                    "decision": result.decision,
                    "policies_evaluated": result.policies_evaluated,
                    "policies_passed": result.policies_passed,
                    "policies_failed": result.policies_failed,
                    "details": result.details,
                    "requires_approval": result.requires_approval,
                    "approval_reason": result.approval_reason,
                }),
                request_id,
            )

    async def _store_plan_for_approver(self, request_id: str, plan: TerraformPlan):
        async with self.db.acquire() as conn:
            await conn.execute("""
                UPDATE provisioning_requests
                SET terraform_plan_output = $1, terraform_plan_summary = $2
                WHERE id = $3
            """,
                plan.plan_output,
                json.dumps({
                    "resources_to_create": plan.resources_to_create,
                    "resources_to_modify": plan.resources_to_modify,
                    "resources_to_destroy": plan.resources_to_destroy,
                    "cost_delta_monthly": plan.cost_delta_monthly,
                    "resources": plan.resources,
                }),
                request_id,
            )

    async def _store_approval_decision(self, request_id: str, decision: ApprovalDecision):
        async with self.db.acquire() as conn:
            await conn.execute("""
                UPDATE provisioning_requests
                SET approved_by = $1, approved_at = $2, approval_comment = $3
                WHERE id = $4
            """, decision.approved_by, decision.decided_at, decision.comment, request_id)

    async def _run_compliance_scan(self, resource_ids: list[str]) -> dict:
        """Run post-provisioning compliance scan against all new resources."""
        # Delegates to compliance_scanner.py
        pass

    async def _quarantine_resources(self, resource_ids: list[str], failures: list[dict]):
        """Mark resources as non-compliant. Does not destroy them."""
        async with self.db.acquire() as conn:
            await conn.execute("""
                UPDATE resources SET compliance_status = 'non_compliant'
                WHERE id = ANY($1)
            """, resource_ids)

    async def _configure_monitoring(self, request: ProvisioningRequest,
                                     resource_ids: list[str]):
        """Configure Datadog monitoring and alert rules for new resources."""
        pass

    async def _notify_success(self, request: ProvisioningRequest, result: ProvisioningResult):
        await self.notify.send(
            recipient=request.requested_by,
            template="provisioning_complete",
            data={
                "project_name": request.project_name,
                "resource_count": len(result.resource_ids),
                "estimated_monthly_cost": result.estimated_monthly_cost,
                "compliance_status": result.compliance_status,
            },
        )

    async def _notify_failure(self, request: ProvisioningRequest, reason: str):
        await self.notify.send(
            recipient=request.requested_by,
            template="provisioning_failed",
            data={"project_name": request.project_name, "reason": reason},
        )

    async def _notify_rejection(self, request: ProvisioningRequest, policy_result: PolicyResult):
        await self.notify.send(
            recipient=request.requested_by,
            template="provisioning_rejected",
            data={
                "project_name": request.project_name,
                "reason": self._format_policy_failures(policy_result),
            },
        )

    async def _notify_compliance_failure(self, request: ProvisioningRequest,
                                          compliance_result: dict):
        await self.notify.send(
            recipient=request.requested_by,
            template="provisioning_compliance_failed",
            data={
                "project_name": request.project_name,
                "failures": compliance_result.get("failures", []),
            },
        )
