"""
Template Generator - Reference Implementation
Generates Terraform HCL and Ansible playbook configurations from
provisioning request parameters and approved base modules.
"""

from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class TerraformModule:
    source: str            # "registry.internal/modules/compute"
    version: str
    defaults: dict
    required_for: list[str] = field(default_factory=list)   # ["dev", "staging", "production"]


@dataclass
class TerraformPlan:
    """Structured representation of what Terraform will create."""
    resources_to_create: int
    resources_to_modify: int
    resources_to_destroy: int
    cost_delta_monthly: float
    resources: list[dict]
    raw_hcl: str


# Internal module registry - version-controlled, security-reviewed modules
MODULE_REGISTRY = {
    "compute": TerraformModule(
        source="registry.internal/modules/compute",
        version="2.1.0",
        defaults={
            "instance_type": "t3.medium",
            "ami_id": "ami-0abcdef1234567890",
            "volume_size_gb": 50,
            "volume_type": "gp3",
            "volume_encrypted": True,
        },
        required_for=["dev", "staging", "production"],
    ),
    "networking": TerraformModule(
        source="registry.internal/modules/networking",
        version="1.8.0",
        defaults={
            "vpc_cidr": "10.0.0.0/16",
            "subnet_type": "private",
            "enable_nat_gateway": True,
            "enable_flow_logs": True,
        },
        required_for=["dev", "staging", "production"],
    ),
    "storage": TerraformModule(
        source="registry.internal/modules/storage",
        version="1.5.0",
        defaults={
            "s3_versioning": True,
            "s3_encryption": "AES256",
            "lifecycle_glacier_days": 90,
        },
        required_for=["staging", "production"],
    ),
    "database": TerraformModule(
        source="registry.internal/modules/database",
        version="2.0.0",
        defaults={
            "engine": "postgres",
            "engine_version": "15.4",
            "instance_class": "db.t3.medium",
            "allocated_storage": 50,
            "multi_az": False,
            "backup_retention_days": 7,
            "encryption": True,
            "performance_insights": True,
        },
        required_for=[],  # optional, enabled by parameter
    ),
    "monitoring": TerraformModule(
        source="registry.internal/modules/monitoring",
        version="1.3.0",
        defaults={
            "datadog_agent_version": "7.45.0",
            "cloudwatch_detailed": True,
            "alert_channel": "#platform-alerts",
        },
        required_for=["dev", "staging", "production"],
    ),
    "security": TerraformModule(
        source="registry.internal/modules/security",
        version="1.6.0",
        defaults={
            "kms_key_rotation": True,
            "guardduty_enabled": True,
            "cloudtrail_enabled": True,
        },
        required_for=["staging", "production"],
    ),
    "loadbalancer": TerraformModule(
        source="registry.internal/modules/loadbalancer",
        version="1.2.0",
        defaults={
            "type": "application",
            "internal": True,
            "ssl_policy": "ELBSecurityPolicy-TLS13-1-2-2021-06",
            "health_check_path": "/health",
            "idle_timeout": 60,
        },
        required_for=["staging", "production"],
    ),
}

# Required tags for all resources
REQUIRED_TAGS = ["project", "team", "cost_center", "environment", "managed_by", "provisioned_at"]


class TemplateGenerator:
    """
    Generates Terraform configurations by composing approved base modules
    with request-specific parameters. Also generates Ansible inventory
    for post-provisioning hardening.
    """

    def __init__(self, module_registry: dict = None):
        self.modules = module_registry or MODULE_REGISTRY

    def generate_terraform(
        self,
        environment: str,
        project_name: str,
        team: str,
        parameters: dict,
    ) -> TerraformPlan:
        """
        Generate a complete Terraform configuration from request parameters.

        1. Select base modules required for the environment type
        2. Overlay user parameters onto module defaults
        3. Inject security groups, tagging, and naming standards
        4. Return structured plan + raw HCL
        """
        # Select modules for this environment
        selected_modules = self._select_modules(environment, parameters)

        # Merge defaults with user parameters
        module_configs = self._merge_parameters(selected_modules, parameters)

        # Generate HCL
        hcl = self._render_hcl(
            project_name=project_name,
            environment=environment,
            team=team,
            module_configs=module_configs,
            parameters=parameters,
        )

        # Build plan summary
        resources = self._enumerate_resources(module_configs, environment)

        return TerraformPlan(
            resources_to_create=len(resources),
            resources_to_modify=0,
            resources_to_destroy=0,
            cost_delta_monthly=self._estimate_cost(resources),
            resources=resources,
            raw_hcl=hcl,
        )

    def _select_modules(self, environment: str, parameters: dict) -> dict:
        """Select which modules to include based on environment and parameters."""
        selected = {}

        for name, module in self.modules.items():
            # Include if required for this environment
            if environment in module.required_for:
                selected[name] = module
                continue

            # Include optional modules if explicitly enabled
            if name == "database" and parameters.get("rds_enabled"):
                selected[name] = module
            elif name == "loadbalancer" and parameters.get("load_balancer_enabled"):
                selected[name] = module

        return selected

    def _merge_parameters(
        self, selected_modules: dict, user_params: dict
    ) -> dict:
        """Merge user parameters onto module defaults."""
        configs = {}

        for name, module in selected_modules.items():
            config = {**module.defaults}

            # Apply user overrides for this module
            param_mapping = {
                "compute": {
                    "instance_type": "instance_type",
                    "volume_size_gb": "volume_size_gb",
                },
                "database": {
                    "rds_instance_class": "instance_class",
                    "rds_storage_gb": "allocated_storage",
                    "multi_az": "multi_az",
                },
                "networking": {
                    "subnet_type": "subnet_type",
                },
            }

            if name in param_mapping:
                for user_key, module_key in param_mapping[name].items():
                    if user_key in user_params:
                        config[module_key] = user_params[user_key]

            configs[name] = {
                "source": module.source,
                "version": module.version,
                "config": config,
            }

        return configs

    def _render_hcl(
        self,
        project_name: str,
        environment: str,
        team: str,
        module_configs: dict,
        parameters: dict,
    ) -> str:
        """Render Terraform HCL configuration."""
        from datetime import datetime

        tags = {
            "project": project_name,
            "team": team,
            "environment": environment,
            "cost_center": parameters.get("tags", {}).get("cost_center", "unassigned"),
            "managed_by": "infrastructure-automation-platform",
            "provisioned_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        lines = []
        lines.append("# Auto-generated by Infrastructure Automation Platform")
        lines.append(f"# Project: {project_name}")
        lines.append(f"# Environment: {environment}")
        lines.append(f"# Team: {team}")
        lines.append("")
        lines.append('terraform {')
        lines.append('  required_version = ">= 1.5.0"')
        lines.append("")
        lines.append("  backend \"s3\" {")
        lines.append(f'    bucket         = "tfstate-{team}"')
        lines.append(f'    key            = "{project_name}/{environment}/terraform.tfstate"')
        lines.append('    region         = "us-east-1"')
        lines.append('    dynamodb_table = "terraform-locks"')
        lines.append('    encrypt        = true')
        lines.append("  }")
        lines.append("}")
        lines.append("")

        # Local tags block
        lines.append("locals {")
        lines.append("  common_tags = {")
        for key, value in tags.items():
            lines.append(f'    {key} = "{value}"')
        lines.append("  }")
        lines.append("}")
        lines.append("")

        # Module blocks
        for name, mod_config in module_configs.items():
            lines.append(f'module "{name}" {{')
            lines.append(f'  source  = "{mod_config["source"]}"')
            lines.append(f'  version = "{mod_config["version"]}"')
            lines.append("")
            for key, value in mod_config["config"].items():
                if isinstance(value, bool):
                    lines.append(f"  {key} = {str(value).lower()}")
                elif isinstance(value, (int, float)):
                    lines.append(f"  {key} = {value}")
                else:
                    lines.append(f'  {key} = "{value}"')
            lines.append("")
            lines.append("  tags = local.common_tags")
            lines.append("}")
            lines.append("")

        return "\n".join(lines)

    def _enumerate_resources(self, module_configs: dict, environment: str) -> list[dict]:
        """List resources that will be created."""
        resources = []

        resource_map = {
            "compute": [
                {"type": "aws_instance", "name": "app-server"},
                {"type": "aws_ebs_volume", "name": "app-data"},
            ],
            "networking": [
                {"type": "aws_vpc", "name": "main"},
                {"type": "aws_subnet", "name": "private"},
                {"type": "aws_security_group", "name": "app-sg"},
                {"type": "aws_nat_gateway", "name": "nat"},
            ],
            "database": [
                {"type": "aws_db_instance", "name": "app-db"},
                {"type": "aws_db_subnet_group", "name": "db-subnets"},
            ],
            "monitoring": [
                {"type": "aws_cloudwatch_log_group", "name": "app-logs"},
                {"type": "datadog_monitor", "name": "cpu-alert"},
                {"type": "datadog_monitor", "name": "error-rate-alert"},
            ],
            "security": [
                {"type": "aws_kms_key", "name": "app-key"},
                {"type": "aws_guardduty_detector", "name": "detector"},
            ],
            "storage": [
                {"type": "aws_s3_bucket", "name": "app-assets"},
            ],
            "loadbalancer": [
                {"type": "aws_lb", "name": "app-alb"},
                {"type": "aws_lb_target_group", "name": "app-tg"},
                {"type": "aws_lb_listener", "name": "https"},
            ],
        }

        for module_name in module_configs:
            for resource in resource_map.get(module_name, []):
                resources.append({**resource, "action": "create"})

        return resources

    def _estimate_cost(self, resources: list[dict]) -> float:
        """Rough cost estimate based on resource types."""
        cost_map = {
            "aws_instance": 85.0,
            "aws_db_instance": 350.0,
            "aws_lb": 25.0,
            "aws_nat_gateway": 45.0,
            "aws_s3_bucket": 5.0,
            "aws_ebs_volume": 10.0,
        }
        total = sum(cost_map.get(r["type"], 0) for r in resources)
        return round(total, 2)

    def generate_ansible_inventory(
        self,
        project_name: str,
        environment: str,
        resource_ids: dict,
    ) -> str:
        """
        Generate Ansible inventory for post-provisioning hardening.
        Called after Terraform apply returns resource IDs.
        """
        lines = []
        lines.append("# Auto-generated Ansible inventory")
        lines.append(f"# Project: {project_name}")
        lines.append(f"# Environment: {environment}")
        lines.append("")
        lines.append(f"[{project_name}_{environment}]")

        for resource_name, resource_id in resource_ids.items():
            if "instance" in resource_name:
                lines.append(
                    f"{resource_id} ansible_user=ec2-user "
                    f"ansible_ssh_private_key_file=~/.ssh/{project_name}-{environment}.pem"
                )

        lines.append("")
        lines.append(f"[{project_name}_{environment}:vars]")
        lines.append(f"environment={environment}")
        lines.append(f"project={project_name}")
        lines.append("datadog_api_key={{ vault_datadog_api_key }}")
        lines.append("hardening_profile=cis_level_1")

        return "\n".join(lines)


def generate_example():
    """Example: generate Terraform config for a staging environment."""
    generator = TemplateGenerator()

    plan = generator.generate_terraform(
        environment="staging",
        project_name="payment-gateway-v2",
        team="payments",
        parameters={
            "instance_type": "t3.large",
            "volume_size_gb": 100,
            "rds_enabled": True,
            "rds_instance_class": "db.r5.large",
            "multi_az": False,
            "tags": {"cost_center": "ENG-2024-Q1"},
        },
    )

    print(f"Resources to create: {plan.resources_to_create}")
    print(f"Estimated cost delta: ${plan.cost_delta_monthly}/month")
    print()
    for resource in plan.resources:
        print(f"  + {resource['type']}.{resource['name']}")
    print()
    print("Generated HCL:")
    print(plan.raw_hcl)


if __name__ == "__main__":
    generate_example()
