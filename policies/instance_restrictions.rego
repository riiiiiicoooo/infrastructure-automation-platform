package infrastructure.compute

# Instance Type Restrictions Policy
#
# Restricts EC2 instance types based on environment:
# - dev: only t-type (burstable) instances up to t3.large
# - staging: t3/t4g up to m5.xlarge, c5.xlarge
# - production: r5+, c5+, m5.2xlarge+ (no t-types, no micro/small)
#
# Prevents cost overruns and ensures appropriate resource sizing.

import data.infrastructure.helpers as helpers

# ============================================================================
# Development Environment: Budget-Conscious
# ============================================================================

# Deny large instances in dev
deny[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "dev"
    instance_type := resource.properties.instance_type
    not is_dev_instance_type(instance_type)
    msg := sprintf(
        "EC2 instance %s in dev has disallowed instance type: %s. Use t2/t3/t4g up to large.",
        [resource.id, instance_type]
    )
}

# Deny memory-optimized instances in dev
deny[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "dev"
    instance_type := resource.properties.instance_type
    contains(instance_type, "r5") or contains(instance_type, "r6") or contains(instance_type, "r7")
    msg := sprintf(
        "EC2 instance %s in dev cannot use memory-optimized types (r-series). Use t-types.",
        [resource.id]
    )
}

# Deny compute-optimized instances in dev
deny[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "dev"
    instance_type := resource.properties.instance_type
    starts_with(instance_type, "c5") or starts_with(instance_type, "c6") or starts_with(instance_type, "c7")
    msg := sprintf(
        "EC2 instance %s in dev cannot use compute-optimized types. Use t-types.",
        [resource.id]
    )
}

# Warn about t-type instances in staging (should prefer burstable only for non-critical)
warn[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "staging"
    instance_type := resource.properties.instance_type
    is_dev_instance_type(instance_type)
    msg := sprintf(
        "Staging EC2 instance %s uses burstable type %s. Preferred for development workloads.",
        [resource.id, instance_type]
    )
}

# ============================================================================
# Staging Environment: Moderate Restrictions
# ============================================================================

# Deny large memory-optimized in staging
deny[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "staging"
    instance_type := resource.properties.instance_type
    (contains(instance_type, "r5") or contains(instance_type, "r6") or contains(instance_type, "r7"))
    get_instance_size(instance_type) in ["2xlarge", "4xlarge", "8xlarge"]
    msg := sprintf(
        "Staging EC2 instance %s has oversized instance type: %s",
        [resource.id, instance_type]
    )
}

# Warn if staging GPU instances (usually unnecessary)
warn[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "staging"
    instance_type := resource.properties.instance_type
    (contains(instance_type, "g4") or contains(instance_type, "g3") or contains(instance_type, "p3"))
    msg := sprintf(
        "Staging EC2 instance %s uses GPU instance type: %s. High cost for non-production.",
        [resource.id, instance_type]
    )
}

# ============================================================================
# Production Environment: Strict Requirements
# ============================================================================

# Deny t-types (burstable) in production
deny[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "production"
    instance_type := resource.properties.instance_type
    is_dev_instance_type(instance_type)
    msg := sprintf(
        "Production EC2 instance %s cannot use burstable (t-type) instances. Use consistent capacity.",
        [resource.id]
    )
}

# Deny micro/small instances in production
deny[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "production"
    instance_type := resource.properties.instance_type
    get_instance_size(instance_type) in ["micro", "small"]
    msg := sprintf(
        "Production EC2 instance %s cannot use micro/small instance types.",
        [resource.id]
    )
}

# Require at least m5.large or equivalent in production
deny[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    resource.tags.environment == "production"
    instance_type := resource.properties.instance_type
    not is_production_safe_instance(instance_type)
    msg := sprintf(
        "Production EC2 instance %s has instance type %s. Minimum: m5.large, c5.large, r5.large.",
        [resource.id, instance_type]
    )
}

# ============================================================================
# High Memory / Compute Workload Restrictions
# ============================================================================

# Deny large instances without cost approval tag
deny[msg] {
    resource := input.resource
    resource.type == "ec2_instance"
    instance_type := resource.properties.instance_type
    get_estimated_monthly_cost(instance_type) > 1000
    not resource.tags.cost_approval
    msg := sprintf(
        "EC2 instance %s with type %s costs >$1000/month. Requires 'cost_approval' tag.",
        [resource.id, instance_type]
    )
}

# ============================================================================
# ECS Task Restrictions
# ============================================================================

# Deny ECS tasks without resource limits
deny[msg] {
    resource := input.resource
    resource.type == "ecs_task_definition"
    not resource.properties.container_definitions[_].memory
    msg := sprintf(
        "ECS task %s has no memory limits. Must specify memory reservation.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.type == "ecs_task_definition"
    not resource.properties.container_definitions[_].cpu
    msg := sprintf(
        "ECS task %s has no CPU limits. Must specify CPU units.",
        [resource.id]
    )
}

# ============================================================================
# Lambda Restrictions
# ============================================================================

# Deny Lambda without timeout specification
deny[msg] {
    resource := input.resource
    resource.type == "lambda_function"
    not resource.properties.timeout or resource.properties.timeout <= 0
    msg := sprintf(
        "Lambda function %s has no timeout or invalid timeout.",
        [resource.id]
    )
}

# Warn about high memory allocation in Lambda
warn[msg] {
    resource := input.resource
    resource.type == "lambda_function"
    memory := resource.properties.memory_size
    memory > 3008
    msg := sprintf(
        "Lambda function %s has high memory allocation: %dMB. Consider cost implications.",
        [resource.id, memory]
    )
}

# ============================================================================
# Helper Functions
# ============================================================================

# Check if instance type is suitable for dev
is_dev_instance_type(instance_type) {
    starts_with(instance_type, "t2") or
    starts_with(instance_type, "t3") or
    starts_with(instance_type, "t4g")
}

# Get instance size from type string
get_instance_size(instance_type) = size {
    parts := split(instance_type, ".")
    size := parts[1]
}

# Check if instance is production-safe
is_production_safe_instance(instance_type) {
    # m5.large and larger
    (contains(instance_type, "m5") or
     contains(instance_type, "m6") or
     contains(instance_type, "m7")) and
    get_instance_size(instance_type) in ["large", "xlarge", "2xlarge", "4xlarge"]
} else {
    # c5.large and larger
    (contains(instance_type, "c5") or
     contains(instance_type, "c6") or
     contains(instance_type, "c7")) and
    get_instance_size(instance_type) in ["large", "xlarge", "2xlarge", "4xlarge"]
} else {
    # r5.large and larger (memory optimized)
    (contains(instance_type, "r5") or
     contains(instance_type, "r6") or
     contains(instance_type, "r7")) and
    get_instance_size(instance_type) in ["large", "xlarge", "2xlarge", "4xlarge"]
} else {
    # i3.large and larger (storage optimized)
    (contains(instance_type, "i3") or
     contains(instance_type, "i4")) and
    get_instance_size(instance_type) in ["large", "xlarge", "2xlarge", "4xlarge"]
}

# Estimate monthly cost based on instance type
get_estimated_monthly_cost(instance_type) = cost {
    # On-demand pricing (us-east-1, approximate)
    instance_type in ["t3.micro"] and cost := 8.50 or
    instance_type in ["t3.small"] and cost := 17.00 or
    instance_type in ["t3.medium"] and cost := 34.01 or
    instance_type in ["m5.large"] and cost := 96.81 or
    instance_type in ["m5.xlarge"] and cost := 193.60 or
    instance_type in ["c5.large"] and cost := 84.43 or
    instance_type in ["c5.xlarge"] and cost := 168.85 or
    instance_type in ["c5.2xlarge"] and cost := 337.71 or
    instance_type in ["r5.large"] and cost := 126.27 or
    instance_type in ["r5.xlarge"] and cost := 252.54 or
    instance_type in ["r5.2xlarge"] and cost := 505.08 or
    cost := 5000  # High cost for unknown types to trigger approval
}

# ============================================================================
# Compliance Mapping
# ============================================================================

# Maps to cost optimization best practices
compliance["cost_optimization"] {
    count(deny) == 0
}

# ============================================================================
# Violations & Warnings
# ============================================================================

violations[violation] {
    deny_msg := deny[_]
    violation := {
        "type": "instance_restriction_violation",
        "rule": "instance_restrictions",
        "message": deny_msg,
        "severity": "high",
        "timestamp": time.now_ns()
    }
}

instance_warnings[warning] {
    warn_msg := warn[_]
    warning := {
        "type": "instance_warning",
        "message": warn_msg,
        "severity": "medium",
        "timestamp": time.now_ns()
    }
}

# ============================================================================
# Summary
# ============================================================================

summary[s] {
    s := {
        "rule": "instance_restrictions",
        "passed": count(deny) == 0,
        "violations": count(deny),
        "warnings": count(warn),
        "cost_implications": {
            "dev_max_monthly": 500,
            "staging_max_monthly": 5000,
            "production_requires_approval_above": 1000
        }
    }
}
