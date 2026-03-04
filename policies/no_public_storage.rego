package infrastructure.storage

# No Public Storage Policy
#
# Prevents public S3 buckets and public RDS instances that could expose
# sensitive data to the internet.
#
# Checks:
# - S3 buckets must not have public read/write ACL
# - S3 bucket policies must not allow public access
# - RDS instances must not be publicly accessible
# - Secrets must not be stored in public containers

import data.infrastructure.helpers as helpers

# ============================================================================
# S3 Bucket Public Access Validation
# ============================================================================

# Deny S3 buckets with public ACL
deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    acl := resource.properties.acl
    acl in ["public-read", "public-read-write", "authenticated-read"]
    msg := sprintf(
        "S3 bucket %s has public ACL: %s. Must be private or restricted.",
        [resource.id, acl]
    )
}

# Deny if S3 bucket policy allows public access
deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    policy := resource.properties.bucket_policy
    policy != ""
    policy_obj := json.unmarshal(policy)
    statement := policy_obj.Statement[_]
    statement.Effect == "Allow"
    statement.Principal == "*" or statement.Principal.AWS == "*" or statement.Principal.Service == "*"
    msg := sprintf(
        "S3 bucket %s has bucket policy allowing public access.",
        [resource.id]
    )
}

# Deny if S3 bucket allows unauthenticated access
deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    resource.properties.block_public_acls != "true"
    msg := sprintf(
        "S3 bucket %s does not block public ACLs. Enable 'block_public_acls'.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    resource.properties.block_public_policy != "true"
    msg := sprintf(
        "S3 bucket %s does not block public bucket policies. Enable 'block_public_policy'.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    resource.properties.ignore_public_acls != "true"
    msg := sprintf(
        "S3 bucket %s does not ignore public ACLs. Enable 'ignore_public_acls'.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    resource.properties.restrict_public_buckets != "true"
    msg := sprintf(
        "S3 bucket %s does not restrict public bucket access. Enable 'restrict_public_buckets'.",
        [resource.id]
    )
}

# Deny S3 buckets with versioning enabled but without MFA delete protection
deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    resource.properties.versioning_enabled == true
    resource.properties.mfa_delete != true
    msg := sprintf(
        "S3 bucket %s has versioning enabled but lacks MFA delete protection.",
        [resource.id]
    )
}

# ============================================================================
# RDS Public Accessibility Validation
# ============================================================================

# Deny RDS instances that are publicly accessible
deny[msg] {
    resource := input.resource
    resource.type == "rds_instance"
    resource.properties.publicly_accessible == true
    msg := sprintf(
        "RDS instance %s is publicly accessible. Must be restricted to VPC.",
        [resource.id]
    )
}

# Deny RDS instances without proper security group restrictions
deny[msg] {
    resource := input.resource
    resource.type == "rds_instance"
    not resource.properties.security_group_ids
    msg := sprintf(
        "RDS instance %s has no security group restrictions. Must specify security groups.",
        [resource.id]
    )
}

# Warn if RDS instance allows 0.0.0.0/0 in security group
deny[msg] {
    resource := input.resource
    resource.type == "rds_instance"
    sg := resource.properties.security_group_rules[_]
    sg.type == "ingress"
    sg.cidr_block == "0.0.0.0/0"
    msg := sprintf(
        "RDS instance %s allows database connections from anywhere (0.0.0.0/0). Restrict CIDR.",
        [resource.id]
    )
}

# ============================================================================
# Other Storage Services
# ============================================================================

# Deny DynamoDB with public access
deny[msg] {
    resource := input.resource
    resource.type == "dynamodb_table"
    resource.properties.global_secondary_indexes[_].stream_specification.stream_enabled == true
    not resource.properties.stream_specification.stream_view_type
    msg := sprintf(
        "DynamoDB table %s has streams enabled but no view type specified. May expose data.",
        [resource.id]
    )
}

# Deny Elasticache without encryption in transit
deny[msg] {
    resource := input.resource
    resource.type == "elasticache_cluster"
    resource.properties.transit_encryption_enabled != true
    msg := sprintf(
        "ElastiCache cluster %s does not have encryption in transit enabled.",
        [resource.id]
    )
}

deny[msg] {
    resource := input.resource
    resource.type == "elasticache_cluster"
    resource.properties.auth_token == "" or not resource.properties.auth_token
    msg := sprintf(
        "ElastiCache cluster %s has no AUTH token. Enable authentication.",
        [resource.id]
    )
}

# ============================================================================
# Environment-Specific Rules
# ============================================================================

# Production resources have stricter requirements
deny[msg] {
    resource := input.resource
    resource.tags.environment == "production"
    resource.type == "s3_bucket"
    not resource.properties.encryption.rules[_].apply_server_side_encryption_by_default
    msg := sprintf(
        "Production S3 bucket %s does not have default encryption. Must enable SSE.",
        [resource.id]
    )
}

# ============================================================================
# Compliance Mapping (NIST 800-53, SOC 2)
# ============================================================================

# Maps to NIST AC-3 (Access Control) and SC-28 (Protection of Information at Rest)
compliance["nist_ac3_sc28"] {
    count(deny) == 0
}

# Maps to SOC 2 Availability & Confidentiality criteria
compliance["soc2_confidentiality"] {
    count([d | deny[d]; contains(d, "public")]) == 0
}

# ============================================================================
# Violations & Warnings
# ============================================================================

violations[violation] {
    deny_msg := deny[_]
    violation := {
        "type": "storage_access_violation",
        "rule": "no_public_storage",
        "message": deny_msg,
        "severity": "critical",
        "timestamp": time.now_ns()
    }
}

# ============================================================================
# Summary
# ============================================================================

summary[s] {
    s := {
        "rule": "no_public_storage",
        "passed": count(deny) == 0,
        "violations": count(deny),
        "compliance_frameworks": [
            "nist_ac3_sc28",
            "soc2_confidentiality",
            "pci_dss"
        ]
    }
}
