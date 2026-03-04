package infrastructure.encryption

# Encryption Required Policy
#
# Enforces encryption at rest for storage and database resources.
#
# Requires:
# - EBS volumes: encryption enabled
# - RDS databases: encryption at rest
# - S3 buckets: default server-side encryption
# - DynamoDB: KMS encryption
# - ElastiCache: encryption enabled

import data.infrastructure.helpers as helpers

# ============================================================================
# EBS Volume Encryption
# ============================================================================

# Deny unencrypted EBS volumes
deny[msg] {
    resource := input.resource
    resource.type == "ebs_volume"
    resource.properties.encrypted != true
    msg := sprintf(
        "EBS volume %s is not encrypted. Enable encryption at rest.",
        [resource.id]
    )
}

# Deny EBS volumes with AWS-managed key when production (should use customer KMS)
deny[msg] {
    resource := input.resource
    resource.type == "ebs_volume"
    resource.tags.environment == "production"
    not resource.properties.kms_key_id or resource.properties.kms_key_id == "aws/ebs"
    msg := sprintf(
        "Production EBS volume %s uses AWS-managed encryption. Use customer-managed KMS key.",
        [resource.id]
    )
}

# ============================================================================
# RDS Encryption
# ============================================================================

# Deny RDS instances without encryption at rest
deny[msg] {
    resource := input.resource
    resource.type == "rds_instance"
    resource.properties.storage_encrypted != true
    msg := sprintf(
        "RDS instance %s does not have encryption at rest enabled.",
        [resource.id]
    )
}

# Deny RDS databases using AWS-managed keys in production
deny[msg] {
    resource := input.resource
    resource.type == "rds_instance"
    resource.tags.environment == "production"
    not resource.properties.kms_key_id
    msg := sprintf(
        "Production RDS instance %s uses AWS-managed encryption. Specify customer-managed KMS key.",
        [resource.id]
    )
}

# Deny RDS instances without encryption in transit
deny[msg] {
    resource := input.resource
    resource.type == "rds_instance"
    resource.tags.environment == "production"
    resource.properties.iam_database_authentication_enabled != true
    msg := sprintf(
        "Production RDS instance %s should enable IAM database authentication for encrypted connections.",
        [resource.id]
    )
}

# ============================================================================
# S3 Encryption
# ============================================================================

# Deny S3 buckets without default encryption
deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    not resource.properties.server_side_encryption_configuration
    msg := sprintf(
        "S3 bucket %s does not have default server-side encryption configured.",
        [resource.id]
    )
}

# Deny S3 buckets with only AES-256 in production (should use KMS)
deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    resource.tags.environment == "production"
    sse := resource.properties.server_side_encryption_configuration
    sse.rules[_].apply_server_side_encryption_by_default.sse_algorithm == "AES256"
    not sse.rules[_].apply_server_side_encryption_by_default.kms_master_key_id
    msg := sprintf(
        "Production S3 bucket %s uses AES-256. Use KMS for encryption key control.",
        [resource.id]
    )
}

# Deny S3 buckets with non-existent KMS key
deny[msg] {
    resource := input.resource
    resource.type == "s3_bucket"
    sse := resource.properties.server_side_encryption_configuration
    kms_key := sse.rules[_].apply_server_side_encryption_by_default.kms_master_key_id
    kms_key != ""
    not regex.match("^arn:aws:kms:", kms_key)
    msg := sprintf(
        "S3 bucket %s has invalid KMS key format: %s. Must be ARN.",
        [resource.id, kms_key]
    )
}

# ============================================================================
# DynamoDB Encryption
# ============================================================================

# Deny DynamoDB tables without encryption
deny[msg] {
    resource := input.resource
    resource.type == "dynamodb_table"
    not resource.properties.server_side_encryption
    msg := sprintf(
        "DynamoDB table %s does not have server-side encryption enabled.",
        [resource.id]
    )
}

# Deny DynamoDB with AWS-managed key in production
deny[msg] {
    resource := input.resource
    resource.type == "dynamodb_table"
    resource.tags.environment == "production"
    sse := resource.properties.server_side_encryption
    sse.enabled == true
    not sse.kms_master_key_arn or sse.kms_master_key_arn == "aws/dynamodb"
    msg := sprintf(
        "Production DynamoDB table %s uses AWS-managed encryption. Use customer-managed KMS key.",
        [resource.id]
    )
}

# ============================================================================
# ElastiCache Encryption
# ============================================================================

# Deny ElastiCache clusters without encryption at rest
deny[msg] {
    resource := input.resource
    resource.type == "elasticache_cluster"
    resource.properties.at_rest_encryption_enabled != true
    msg := sprintf(
        "ElastiCache cluster %s does not have encryption at rest enabled.",
        [resource.id]
    )
}

# Deny ElastiCache clusters without encryption in transit
deny[msg] {
    resource := input.resource
    resource.type == "elasticache_cluster"
    resource.properties.transit_encryption_enabled != true
    msg := sprintf(
        "ElastiCache cluster %s does not have encryption in transit enabled.",
        [resource.id]
    )
}

# ============================================================================
# Lambda Encryption
# ============================================================================

# Deny Lambda functions storing secrets without encryption
deny[msg] {
    resource := input.resource
    resource.type == "lambda_function"
    resource.properties.environment.variables[key] == value
    contains(key, ["password", "secret", "api_key", "private_key"])
    msg := sprintf(
        "Lambda function %s stores sensitive data in plaintext environment variables.",
        [resource.id]
    )
}

# ============================================================================
# Secrets Manager Encryption
# ============================================================================

# Deny Secrets without encryption
deny[msg] {
    resource := input.resource
    resource.type == "secret"
    not resource.properties.kms_key_id
    msg := sprintf(
        "Secret %s does not have KMS encryption configured.",
        [resource.id]
    )
}

# ============================================================================
# Key Rotation Requirements
# ============================================================================

# Warn if KMS keys don't have rotation enabled
warn[msg] {
    resource := input.resource
    resource.type == "kms_key"
    resource.properties.enable_key_rotation != true
    msg := sprintf(
        "KMS key %s does not have automatic key rotation enabled.",
        [resource.id]
    )
}

# ============================================================================
# Compliance Mapping
# ============================================================================

# NIST 800-53 SC-28: Protection of Information at Rest
compliance["nist_sc28"] {
    count([d | deny[d]; contains(d, "encrypt")]) == 0
}

# PCI DSS 3.2.1: Encryption at Rest
compliance["pci_dss_3_2_1"] {
    count([d | deny[d]; contains(d, "encrypt")]) == 0
}

# SOC 2 CC6.1: Logical and Physical Access Controls
compliance["soc2_cc6_1"] {
    count([d | deny[d]; contains(d, "encrypt")]) == 0
}

# HIPAA § 164.312(a)(2)(ii): Encryption and Decryption
compliance["hipaa_164_312"] {
    count([d | deny[d]; contains(d, "encrypt")]) == 0
}

# FedRAMP SC-28: Protection of Information at Rest
compliance["fedramp_sc28"] {
    count([d | deny[d]; contains(d, "encrypt")]) == 0
}

# ============================================================================
# Violations & Warnings
# ============================================================================

violations[violation] {
    deny_msg := deny[_]
    violation := {
        "type": "encryption_violation",
        "rule": "encryption_required",
        "message": deny_msg,
        "severity": "critical",
        "timestamp": time.now_ns(),
        "compliance_frameworks": [
            "nist_sc28",
            "pci_dss_3_2_1",
            "soc2_cc6_1",
            "hipaa_164_312",
            "fedramp_sc28"
        ]
    }
}

encryption_warnings[warning] {
    warn_msg := warn[_]
    warning := {
        "type": "encryption_warning",
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
        "rule": "encryption_required",
        "passed": count(deny) == 0,
        "violations": count(deny),
        "warnings": count(warn),
        "resources_checked": count(input.resource) if is_array(input.resource) else 1,
        "compliance_frameworks": [
            "nist_800_53_sc28",
            "pci_dss",
            "soc2",
            "hipaa",
            "fedramp"
        ]
    }
}
