# Infrastructure Automation Platform - Incident Runbooks

---

## Incident 1: Deployment Simulation Failure (Inaccurate Prediction)

### Context
On March 15 at 2:15 PM, a critical deployment is simulated and passes all checks. The simulation predicts "safe to deploy." Upon production deployment, the service crashes: database migration script fails due to a schema incompatibility with the new application code. Simulation missed this edge case. Production is down for 20 minutes; ~2,000 requests failed before rollback.

### Detection
- **Alert:** Deployment fails (crashes after 5+ minutes) OR error rate spikes >50% post-deployment
- **Symptoms:**
  - Error logs show "database migration failed: table structure mismatch"
  - Service crashes; 5xx errors spike
  - Simulation had flagged as "safe"; confidence was high (98%)

### Diagnosis (15 minutes)

**Step 1: Compare simulation vs. actual**
```bash
# Review simulation logs
cat deployment_simulation_20260315_141500.log

# Output shows:
# - Database schema validation: PASS ✓
# - App code analysis: PASS ✓
# - Data migration test: PASS ✓
# (But simulation used staging DB schema, not production schema!)

# Check actual error
tail -100 /var/log/app/error.log | grep -i "migration\|schema"
# Output: "Migration failed: Column 'user_id' type changed from INT to BIGINT without explicit conversion"
```

**Step 2: Root cause analysis**
```
Simulation used: Staging database schema (outdated, has INT user_id)
Production has: Current schema (BIGINT user_id from separate migration 2 weeks ago)
Simulation didn't see the schema mismatch because staging was stale!

Why simulation passed:
- Simulation validated: "App expects BIGINT" ✓
- But simulated against old schema: INT ✗
- Simulation didn't fail because the mismatch wasn't detected
```

**Step 3: Check for similar issues**
```sql
-- Are there other schema version mismatches between staging and prod?
SELECT
  table_name,
  column_name,
  staging_type,
  prod_type,
  CASE WHEN staging_type != prod_type THEN 'MISMATCH' ELSE 'OK' END as status
FROM schema_comparison
WHERE env = 'staging' OR env = 'prod'
  AND updated_at > NOW() - INTERVAL 30 DAYS
ORDER BY status DESC;

-- Result: 3 additional schema mismatches (security risk!)
```

### Remediation

**Immediate (0-5 min): Rollback**
```bash
# Trigger rollback to previous deployment
deployment rollback --deployment-id=20260315_141500 --reason="Schema incompatibility"

# Monitor service health
watch -n 5 'curl http://localhost:5000/health'
# Expected: Service returns 200 after ~30 seconds

# Validate error rate returned to baseline
# Expected: Error rate drops from 50% back to <1%
```

**Short-term (5-30 min): Fix schema sync**
```bash
# Sync staging schema to match production
pg_dump --schema-only prod_db > prod_schema.sql
psql staging_db < prod_schema.sql

# Verify schemas now match
psql -d staging_db -c "\d user" | grep user_id
psql -d prod_db -c "\d user" | grep user_id
# Expected: Both show "user_id bigint"

# Re-run simulation with synchronized schema
python -m simulator.validate \
  --deployment=20260315_141500 \
  --schema-source=prod_db \
  --output=simulation_retry.log

# Expected: Simulation now FAILS with "schema mismatch" warning
```

**Root cause remediation (30 min - 1 hour):**

1. **Update simulation to use production schema:**
   ```python
   def validate_deployment(deployment, simulation_config):
       # OLD: Simulated against staging schema
       # staging_schema = connect_to_db('staging')

       # NEW: Simulate against production schema (read-only)
       prod_schema = connect_to_db('prod', read_only=True)

       # Validate app code against actual prod schema
       validation_result = validate_app_against_schema(
           app_code=deployment.code,
           schema=prod_schema
       )

       return validation_result
   ```

2. **Add continuous schema validation:**
   ```bash
   # Hourly job: Compare staging schema to production
   0 * * * * python -m schema_validator.compare_env \
     --from=staging --to=prod \
     --alert_on_mismatch=true
   ```

3. **Block deployments if schema mismatches detected:**
   ```python
   def can_deploy(deployment):
       schema_match = schema_validator.compare(
           env_1='staging',
           env_2='prod'
       )

       if not schema_match.all_columns_match:
           return False, f"Schema mismatch: {schema_match.mismatches}"

       return True, "Schemas synchronized"
   ```

4. **Improve simulation to detect schema version drift:**
   ```python
   def simulate_with_version_awareness(deployment):
       # Record schema version used in simulation
       schema_version = get_schema_version('prod')

       # Later, validate that schema version hasn't drifted
       if current_schema_version() != schema_version:
           alert.warn(
               f"Schema version mismatch; simulation may be stale: "
               f"simulated with v{schema_version}, prod now v{current_schema_version()}"
           )
   ```

**Validate fix:**
```bash
# Re-deploy the failed deployment
deployment deploy --deployment-id=20260315_141500 \
  --simulation-result=verified \
  --schema-source=prod_db

# Expected: Deployment succeeds; service healthy; zero errors
```

### Communication Template

**Internal (Slack #incidents)**
```
INFRASTRUCTURE AUTOMATION INCIDENT: Simulation Failure
Severity: P2 (Production Outage - 20 min downtime, ~2K failed requests)
Duration: 14:15-14:35 UTC
Affected: Critical service

Root Cause: Deployment simulation used outdated staging database schema. Production had newer schema (BIGINT user_id vs INT). Simulation passed (false positive); actual deployment failed on schema mismatch.

Actions:
1. Rolled back to previous deployment (service restored 14:35 UTC)
2. Synced staging schema to match production
3. Updated simulation to use production schema (read-only copy)
4. Added continuous schema version monitoring

Resolution: Re-deployed same code successfully by 14:50 UTC (now with correct schema).

ETA: Fully validated and procedures updated by 15:30 UTC
Assigned to: [PLATFORM_ENGINEER], [DBA]
```

**Customer (Status page update)**
```
Incident Resolved: Brief Outage

We experienced a 20-minute service outage at 14:15 UTC due to a deployment issue. We've identified the root cause (schema mismatch) and implemented safeguards to prevent recurrence.

All systems are now healthy and fully operational.

Apologies for the disruption. We take reliability seriously and will continue improving our deployment validation.
```

### Postmortem Questions
1. Why was staging schema not synced to production regularly?
2. Can we automate schema synchronization between environments?
3. Should simulation always use production schema (read-only)?

---

## Incident 2: Multi-Cloud Drift Not Detected (Compliance Violation)

### Context
On March 12, a junior engineer manually modified a security group in AWS to "debug" an issue (added rule allowing 0.0.0.0/0 port 443 access). The change was supposed to be temporary, but they forgot to revert it. Drift detection didn't flag the change (polling was delayed). One week later (March 19), during a compliance audit, the unauthorized security group rule is discovered. This violates cloud governance policies and created a security risk.

### Detection
- **Alert:** Manual infrastructure change detected (drift) via IaC comparison OR compliance scanner finds non-compliant resource
- **Symptoms:**
  - Compliance audit finds security group rule not in IaC
  - AWS Config shows drift (manual change detected)
  - Drift detection logs show missed/delayed detection

### Diagnosis (30 minutes)

**Step 1: Validate the drift**
```bash
# Check AWS Config for drift
aws configservice describe-compliance-by-config-rule \
  --compliance-types NON_COMPLIANT \
  --region us-east-1

# Output: Security group sg-12345 is NON_COMPLIANT
# Rule: Allows 0.0.0.0/0 port 443 (not in Terraform)

# Check when change was made
aws ec2 describe-security-groups --group-ids sg-12345 \
  --query 'SecurityGroups[0].IpPermissions'

# Check CloudTrail for who made the change
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=sg-12345 \
  --region us-east-1 \
  | grep AuthorizeSecurityGroupIngress

# Output: March 12 14:22 UTC, user=junior_engineer@company.com
```

**Step 2: Determine detection failure**
```bash
# Why wasn't this flagged by drift detection?
# Check drift detector logs

kubectl logs deployment/drift-detector --since=7d | grep "sg-12345"
# Result: EMPTY (no logs for this security group)

# Check polling schedule
grep -r "polling_interval" /etc/drift-detector/
# Result: polling_interval = 120 minutes (2 hours!)
# So drift detector only polls every 2 hours; might have missed it

# Check if drift detector was running on March 12
kubectl logs deployment/drift-detector --since=8d | grep "2026-03-12"
# Result: Drift detector had issues on March 12; restarted 5 times
```

**Step 3: Impact assessment**
```sql
-- Find other resources with similar drift
SELECT
  resource_id,
  resource_type,
  drift_status,
  drift_detected_at,
  time_since_change_hours
FROM infrastructure_drift_audit
WHERE drift_status = 'UNDETECTED'
  AND created_at > NOW() - INTERVAL 7 DAYS
  AND resource_type IN ('security_group', 'iam_policy', 'network_acl');

-- Result: 3 other undetected drifts (security-related)
```

### Remediation

**Immediate (0-10 min): Remediate non-compliant resource**
```bash
# Option 1: Revert to IaC
cd infrastructure-as-code/
git show HEAD:terraform/security-groups.tf | grep sg-12345
# Shows original config (no 0.0.0.0/0 rule)

# Revert manually created rule
aws ec2 revoke-security-group-ingress \
  --group-id sg-12345 \
  --ip-permissions IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges='[{CidrIp=0.0.0.0/0}]'

# Verify it's gone
aws ec2 describe-security-groups --group-ids sg-12345 | grep 0.0.0.0
# Expected: No results
```

**Short-term (10-30 min): Identify and fix other drift**
```bash
# Fix the 3 other undetected drifts
for resource_id in $(list_undetected_drifts); do
    echo "Fixing drift for $resource_id"
    # Get IaC definition
    iac_def=$(get_iac_definition $resource_id)
    # Apply IaC to cloud
    apply_iac($iac_def)
done

# Verify all drifts are now resolved
aws configservice start-config-rules-evaluation
# Wait for evaluation to complete
```

**Root cause remediation (1-2 hours):**

1. **Improve drift detection frequency:**
   ```bash
   # Was: Every 120 minutes (2 hours)
   # Now: Every 30 minutes for security-sensitive resources

   # Configure detection frequency by resource type
   detection_config = {
       'security_group': 30,        # Every 30 min
       'iam_policy': 30,            # Every 30 min
       'network_acl': 30,
       'ec2_instance': 60,          # Every 60 min
       'storage_bucket': 120        # Every 120 min
   }
   ```

2. **Implement event-driven drift detection:**
   ```python
   # Instead of polling, subscribe to cloud events
   # When AWS Config detects drift → immediate alert

   def setup_drift_detection():
       # Set up AWS Config rules for continuous monitoring
       for resource_type in CRITICAL_RESOURCES:
           create_config_rule(resource_type, evaluation_mode='continuous')

       # Subscribe to drift events
       subscribe_to_sns_topic('aws-config-drift-notifications')
   ```

3. **Block manual infrastructure changes:**
   ```bash
   # Policy: Only allow infrastructure changes via IaC (terraform plan/apply)
   # Enforce via IAM policies that deny direct API calls (except plan/apply role)

   {
       "Effect": "Deny",
       "Action": "ec2:AuthorizeSecurityGroupIngress",
       "Principal": "*",
       "Condition": {
           "StringNotLike": {
               "aws:PrincipalArn": "arn:aws:iam::*:role/terraform-apply-role"
           }
       }
   }
   ```

4. **Implement drift remediation automation:**
   ```python
   def auto_remediate_drift(resource_id, detected_drift):
       # If drift is detected, automatically revert to IaC definition
       iac_definition = get_iac_definition(resource_id)

       # Apply IaC (this will revert manual changes)
       terraform.apply(iac_definition)

       # Log remediation
       audit_log.info(f"Auto-remediated drift for {resource_id}")
   ```

5. **Alert on drift detector health:**
   ```python
   def monitor_drift_detector():
       health = drift_detector.health_check()
       if not health.is_healthy:
           alert.error("Drift detector unhealthy; manual changes may be undetected")

       # Check last successful poll
       last_poll = drift_detector.last_successful_poll_time()
       if now() - last_poll > 60:  # Haven't polled in >60 min
           alert.warn(f"Drift detector lagging; last poll was {ago} ago")
   ```

### Communication Template

**Internal (Slack #security-incidents)**
```
COMPLIANCE INCIDENT: Undetected Infrastructure Drift
Severity: P2 (Compliance Violation + Security Risk)
Duration: March 12 14:22 (manual change) → March 19 10:00 (audit discovered)
Affected: AWS security group; exposed security risk for 7 days

Root Cause: (1) Drift detection polling interval was 120 min (too infrequent), (2) Drift detector was unstable on March 12 (missed the change), (3) No preventive blocks on manual infrastructure changes.

Actions:
1. Immediately reverted unauthorized security group rule
2. Fixed 3 other undetected drifts
3. Reduced drift detection polling to 30 min for security resources
4. Implemented event-driven drift detection (AWS Config continuous)
5. Blocked direct infrastructure API calls (enforce IaC-only changes)

Resolution: All drift remediated; drift detection now near-real-time (seconds not hours).

ETA: All fixes deployed by end of day
Assigned to: [SECURITY_LEAD], [PLATFORM_ENGINEER]
```

**Compliance Notification**
```
Subject: Compliance Incident Report - Undetected Infrastructure Drift

During the March 12-19 period, a security group was manually modified outside of infrastructure-as-code, creating a temporary compliance violation.

Details:
- Resource: AWS Security Group sg-12345
- Unauthorized rule: 0.0.0.0/0 port 443 (allowed by junior engineer for debugging)
- Duration: 7 days (March 12-19)
- Risk: Low (engineering environment; no customer data accessed)
- Remediation: Rule reverted; drift detection improved

Preventive measures implemented:
- Drift detection frequency increased from 120 min → 30 min
- Event-driven drift detection enabled (real-time AWS Config)
- IAM policies enforced (only Terraform can modify infrastructure)

This incident is now closed. Please contact [SECURITY] if you have questions.
```

### Postmortem Questions
1. Why was drift detection polling at 120-minute intervals?
2. Why was there no alert when drift detector failed on March 12?
3. Should we implement "golden image" validation (periodic full state audit)?

---

## Incident 3: Rollback Failure (Can't Undo Deployment)

### Context
On March 16 at 9:30 AM, a deployment rolls out successfully. At 10:15 AM, a critical bug is discovered. The team triggers an automatic rollback. However, the rollback fails partway through: the database migration (forward) completed, but rollback migration (backward) fails with "can't migrate down; no rolldown script". Service is stuck in an inconsistent state; 15% of requests fail with "schema version mismatch".

### Detection
- **Alert:** Rollback fails OR rollback completes but service is unhealthy (error rate >5%)
- **Symptoms:**
  - Rollback triggered but doesn't complete
  - Error logs show "migration rollback failed"
  - Service returns 500 errors; schema version checks fail

### Diagnosis (10 minutes)

**Step 1: Validate rollback failure**
```bash
# Check rollback logs
tail -100 /var/log/deployment/rollback_20260316_101500.log

# Output:
# [ROLLBACK STARTED] Reverting to deployment d12345
# [DB MIGRATION] Starting migration rollback...
# [DB MIGRATION] Error: No rollback script for migration v2.6_add_user_type
# [DB MIGRATION] Rolling back stopped at v2.6; manual intervention required

# Check service health
curl http://localhost:5000/health
# Output: 500 Internal Server Error
# Reason: "Database schema version mismatch; expected v2.5, found v2.6"
```

**Step 2: Identify root cause**
```
Forward migration (v2.5 → v2.6):
  - File: migrations/v2.6_add_user_type.sql
  - SQL: ALTER TABLE users ADD COLUMN user_type VARCHAR(50);

Rollback migration (v2.6 → v2.5):
  - Expected file: migrations/v2.6_add_user_type.rolldown.sql
  - Actual: FILE DOESN'T EXIST ❌

Why rollback failed:
- Migration has no corresponding rollback script
- System tried to find rolldown; it didn't exist
- Rollback process stopped; service stuck in v2.6 schema, but code reverted to v2.5
```

**Step 3: Check for other missing rollbacks**
```bash
# Find migrations without rollback scripts
ls migrations/*.sql | while read forward; do
    rollback="${forward%.sql}.rolldown.sql"
    if [ ! -f "$rollback" ]; then
        echo "⚠️  Missing rollback: $forward"
    fi
done

# Result: 3 migrations are missing rollback scripts (high risk!)
```

### Remediation

**Immediate (0-5 min): Restore manually**
```bash
# Option 1: Manually execute rollback migration
psql production_db -c "ALTER TABLE users DROP COLUMN user_type;"

# Verify schema matches v2.5 expectation
psql production_db -c "SELECT * FROM information_schema.columns WHERE table_name='users';"
# Expected: No user_type column

# Restart service with v2.5 code
docker restart app-service-prod

# Verify health
curl http://localhost:5000/health
# Expected: 200 OK

# Check error rate dropped
# Expected: Error rate from 15% → <1%
```

**Short-term (5-30 min): Create missing rollback scripts**
```bash
# Generate rollback script for v2.6 migration
# Forward: ALTER TABLE users ADD COLUMN user_type VARCHAR(50);
# Rollback: ALTER TABLE users DROP COLUMN user_type;

cat > migrations/v2.6_add_user_type.rolldown.sql << 'EOF'
-- Rollback for v2.6_add_user_type
-- Removes the user_type column added in forward migration
ALTER TABLE users DROP COLUMN user_type;
EOF

# Create rollback scripts for other 2 missing migrations
# (similar process)

# Commit to git
git add migrations/*.rolldown.sql
git commit -m "Add missing database rollback scripts for emergency recovery"
```

**Root cause remediation (30 min - 1 hour):**

1. **Require rollback scripts in CI/CD:**
   ```bash
   # Pre-commit hook: Verify every forward migration has rollback
   #!/bin/bash
   for forward_migration in $(git diff --name-only --cached | grep "migrations.*\.sql$" | grep -v ".rolldown.sql"); do
       rollback="${forward_migration%.sql}.rolldown.sql"
       if [ ! -f "$rollback" ]; then
           echo "ERROR: Missing rollback script for $forward_migration"
           exit 1
       fi
   done
   ```

2. **Test rollback scripts in CI:**
   ```bash
   # In CI pipeline: Apply forward migration, then rollback, verify schema
   test_migration_rollback() {
       # 1. Apply forward migration
       psql test_db -f migrations/v2.6_add_user_type.sql

       # 2. Verify forward migration worked
       psql test_db -c "SELECT user_type FROM users LIMIT 1;" || exit 1

       # 3. Apply rollback migration
       psql test_db -f migrations/v2.6_add_user_type.rolldown.sql

       # 4. Verify rollback worked (column gone)
       psql test_db -c "SELECT user_type FROM users LIMIT 1;" && exit 1  # Should fail
   }
   ```

3. **Validate rollback before allowing deployment:**
   ```python
   def validate_deployment(deployment):
       # Check that all migrations have rollback scripts
       for migration in deployment.migrations:
           if not migration.has_rollback_script():
               return False, f"Migration {migration.name} missing rollback script"

       # Test rollback in staging
       if not test_rollback_in_staging(deployment):
           return False, "Rollback failed in staging; deployment blocked"

       return True, "Deployment can proceed"
   ```

4. **Improve rollback monitoring:**
   ```python
   def monitor_rollback():
       rollback_result = deployment.rollback()

       if not rollback_result.success:
           alert.critical(f"Rollback failed: {rollback_result.error}")
           # Don't just notify; take action
           escalate_to_dba()  # Get database expert involved

       # Verify service health after rollback
       health = service.health_check()
       if not health.is_healthy:
           alert.critical("Service unhealthy after rollback; manual recovery needed")
   ```

### Communication Template

**Internal (Slack #incidents)**
```
INFRASTRUCTURE AUTOMATION INCIDENT: Rollback Failure
Severity: P1 (Partial Outage - Service in degraded state)
Duration: 10:15-11:00 UTC (45 min)
Affected: Production service; 15% error rate

Root Cause: Automatic rollback triggered but failed halfway through. Database forward migration (add user_type column) completed, but rollback script didn't exist. Service code reverted but schema didn't; data inconsistency.

Actions:
1. Manually executed rollback SQL: ALTER TABLE users DROP COLUMN user_type
2. Verified schema matched reverted code
3. Restarted service (health restored to 100%)
4. Created missing rollback scripts for 3 migrations
5. Added CI/CD validation (rollback scripts required + tested)

Resolution: Service restored by 11:00 UTC. All rollback scripts now tested before deployment.

ETA: Fully validated and safeguards deployed by 12:00 UTC
Assigned to: [DBA], [PLATFORM_ENGINEER]
```

**Customer (Status page)**
```
Partial Outage Resolved

We experienced a brief service degradation (15% error rate) at 10:15 UTC due to a deployment issue and subsequent rollback failure. We've restored service health and implemented additional safeguards to prevent this in the future.

All systems are now fully operational.

We take reliability seriously and apologize for any disruption to your services.
```

### Postmortem Questions
1. Why weren't rollback scripts required in the deployment process?
2. Can we test all rollback scripts automatically before deployment?
3. Should we implement automatic rollback testing in staging?

---

## General Escalation Path
1. **P3 (Deployment delayed, simulation warning):** Assign to engineer; investigate
2. **P2 (Deployment failed, <5 min downtime, rollback succeeded):** Escalate to platform lead within 10 min
3. **P1 (Partial/full outage, rollback failed, data inconsistency):** Page engineering lead + DBA immediately
4. **All incidents >5% deployment failure rate:** Require postmortem + preventive control

