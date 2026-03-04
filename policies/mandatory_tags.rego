package infrastructure.tags

# Mandatory Tags Policy
#
# Enforces required tags on all resources:
# - environment: dev, staging, or production
# - team: team responsible for resource
# - cost_center: billing/chargeback code
# - owner: email or identifier
# - expiry: (optional) resource expiry date
#
# Fails if any mandatory tag is missing or malformed.

import data.infrastructure.helpers as helpers

# ============================================================================
# Mandatory Tag Validation
# ============================================================================

# Deny if environment tag is missing or invalid
deny[msg] {
    resource := input.resource
    not resource.tags.environment
    msg := sprintf(
        "Resource %s missing required 'environment' tag. Must be dev, staging, or production.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.tags.environment
    not resource.tags.environment in ["dev", "staging", "production"]
    msg := sprintf(
        "Resource %s has invalid environment tag: %s. Must be dev, staging, or production.",
        [resource.id, resource.tags.environment]
    )
}

# Deny if team tag is missing
deny[msg] {
    resource := input.resource
    not resource.tags.team
    msg := sprintf(
        "Resource %s missing required 'team' tag.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.tags.team
    resource.tags.team == ""
    msg := sprintf(
        "Resource %s has empty 'team' tag.",
        [resource.id]
    )
}

# Deny if cost_center tag is missing
deny[msg] {
    resource := input.resource
    not resource.tags.cost_center
    msg := sprintf(
        "Resource %s missing required 'cost_center' tag.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.tags.cost_center
    resource.tags.cost_center == ""
    msg := sprintf(
        "Resource %s has empty 'cost_center' tag.",
        [resource.id]
    )
}

# Deny if owner tag is missing
deny[msg] {
    resource := input.resource
    not resource.tags.owner
    msg := sprintf(
        "Resource %s missing required 'owner' tag.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.tags.owner
    resource.tags.owner == "" or resource.tags.owner == "unassigned"
    msg := sprintf(
        "Resource %s has unassigned 'owner' tag. Must specify responsible person or team.",
        [resource.id]
    )
}

# Validate owner email format (if it looks like an email)
deny[msg] {
    resource := input.resource
    owner := resource.tags.owner
    contains(owner, "@")
    not regex.match("^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$", owner)
    msg := sprintf(
        "Resource %s has invalid email format for 'owner' tag: %s",
        [resource.id, owner]
    )
}

# Validate expiry date format (if provided)
deny[msg] {
    resource := input.resource
    expiry := resource.tags.expiry
    expiry != ""
    not regex.match("^\\d{4}-\\d{2}-\\d{2}$", expiry)
    msg := sprintf(
        "Resource %s has invalid 'expiry' tag format: %s. Must be YYYY-MM-DD.",
        [resource.id, expiry]
    )
}

# Warn if resource is past expiry date
warn[msg] {
    resource := input.resource
    expiry := resource.tags.expiry
    expiry != ""
    time.now_ns() > time.parse_ns("2006-01-02", expiry)
    msg := sprintf(
        "Resource %s has expired (expiry: %s). Should be decommissioned.",
        [resource.id, expiry]
    )
}

# ============================================================================
# Resource Type-Specific Validations
# ============================================================================

# Compute resources must have additional tags
deny[msg] {
    resource := input.resource
    resource.type in ["ec2_instance", "ecs_service", "lambda"]
    not resource.tags.backup_policy
    msg := sprintf(
        "%s resource %s missing required 'backup_policy' tag.",
        [resource.type, resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.type in ["ec2_instance", "ecs_service", "lambda"]
    resource.tags.backup_policy
    not resource.tags.backup_policy in ["daily", "weekly", "monthly", "none"]
    msg := sprintf(
        "%s resource %s has invalid backup_policy: %s. Must be daily, weekly, monthly, or none.",
        [resource.type, resource.id, resource.tags.backup_policy]
    )
}

# Database resources must require encryption tag
deny[msg] {
    resource := input.resource
    resource.type in ["rds_instance", "dynamodb_table", "s3_bucket"]
    not resource.tags.encryption_required
    msg := sprintf(
        "%s resource %s missing required 'encryption_required' tag.",
        [resource.type, resource.id]
    )
}

# Production resources must have monitoring enabled
deny[msg] {
    resource := input.resource
    resource.tags.environment == "production"
    not resource.tags.monitoring_enabled
    msg := sprintf(
        "Production resource %s missing required 'monitoring_enabled' tag.",
        [resource.id]
    )
}

# ============================================================================
# Audit Logging
# ============================================================================

# Record all tag violations for compliance audit
violations[violation] {
    deny_msg := deny[_]
    violation := {
        "type": "tag_violation",
        "rule": "mandatory_tags",
        "message": deny_msg,
        "timestamp": time.now_ns(),
        "severity": "high"
    }
}

warnings[warning] {
    warn_msg := warn[_]
    warning := {
        "type": "tag_warning",
        "rule": "mandatory_tags",
        "message": warn_msg,
        "timestamp": time.now_ns(),
        "severity": "medium"
    }
}

# ============================================================================
# Pass Conditions
# ============================================================================

# Pass if all mandatory tags are present and valid
pass {
    count(deny) == 0
}

# Summary for policy report
summary[s] {
    s := {
        "rule": "mandatory_tags",
        "passed": count(deny) == 0,
        "violations": count(deny),
        "warnings": count(warn),
        "resources_checked": count(input.resource) if is_array(input.resource) else 1
    }
}
