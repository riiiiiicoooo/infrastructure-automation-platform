package infrastructure.tags

# Test cases for mandatory_tags policy

# ============================================================================
# PASS Test Cases
# ============================================================================

test_pass_ec2_with_all_tags {
    input := {
        "resource": {
            "id": "i-1234567890abcdef0",
            "type": "ec2_instance",
            "tags": {
                "environment": "production",
                "team": "platform-engineering",
                "cost_center": "CC-12345",
                "owner": "john.doe@company.com",
                "backup_policy": "daily"
            }
        }
    }

    # Should have no denials
    count(deny) == 0
}

test_pass_rds_with_encryption_tag {
    input := {
        "resource": {
            "id": "payment-db-prod",
            "type": "rds_instance",
            "tags": {
                "environment": "production",
                "team": "database-reliability",
                "cost_center": "CC-67890",
                "owner": "db-team@company.com",
                "encryption_required": "true",
                "monitoring_enabled": "true"
            },
            "properties": {
                "storage_encrypted": true,
                "multi_az": true
            }
        }
    }

    count(deny) == 0
}

test_pass_dev_with_minimal_tags {
    input := {
        "resource": {
            "id": "dev-app-001",
            "type": "ec2_instance",
            "tags": {
                "environment": "dev",
                "team": "platform-engineering",
                "cost_center": "CC-00000",
                "owner": "engineer@company.com"
            }
        }
    }

    count(deny) == 0
}

# ============================================================================
# FAIL Test Cases
# ============================================================================

test_fail_missing_environment_tag {
    input := {
        "resource": {
            "id": "i-badtags001",
            "type": "ec2_instance",
            "tags": {
                "team": "platform-engineering",
                "cost_center": "CC-12345",
                "owner": "john@company.com"
            }
        }
    }

    # Should fail - missing environment
    count(deny) > 0
    deny[_] contains "environment"
}

test_fail_invalid_environment {
    input := {
        "resource": {
            "id": "i-badenv001",
            "type": "ec2_instance",
            "tags": {
                "environment": "staging-new",
                "team": "platform-engineering",
                "cost_center": "CC-12345",
                "owner": "john@company.com"
            }
        }
    }

    # Should fail - invalid environment value
    count(deny) > 0
}

test_fail_missing_team_tag {
    input := {
        "resource": {
            "id": "i-notable001",
            "type": "ec2_instance",
            "tags": {
                "environment": "production",
                "cost_center": "CC-12345",
                "owner": "john@company.com"
            }
        }
    }

    # Should fail - missing team
    count(deny) > 0
    deny[_] contains "team"
}

test_fail_missing_cost_center {
    input := {
        "resource": {
            "id": "i-nocc001",
            "type": "ec2_instance",
            "tags": {
                "environment": "production",
                "team": "platform-engineering",
                "owner": "john@company.com"
            }
        }
    }

    # Should fail - missing cost_center
    count(deny) > 0
}

test_fail_missing_owner {
    input := {
        "resource": {
            "id": "i-noowner001",
            "type": "ec2_instance",
            "tags": {
                "environment": "production",
                "team": "platform-engineering",
                "cost_center": "CC-12345"
            }
        }
    }

    # Should fail - missing owner
    count(deny) > 0
}

test_fail_invalid_owner_email {
    input := {
        "resource": {
            "id": "i-bademail001",
            "type": "ec2_instance",
            "tags": {
                "environment": "production",
                "team": "platform-engineering",
                "cost_center": "CC-12345",
                "owner": "invalid-email-format"
            }
        }
    }

    # Should fail - invalid email
    count(deny) > 0
}

test_fail_invalid_expiry_format {
    input := {
        "resource": {
            "id": "i-badexpiry001",
            "type": "ec2_instance",
            "tags": {
                "environment": "dev",
                "team": "platform-engineering",
                "cost_center": "CC-12345",
                "owner": "john@company.com",
                "expiry": "2024/12/31"
            }
        }
    }

    # Should fail - invalid date format
    count(deny) > 0
}

test_fail_compute_missing_backup_policy {
    input := {
        "resource": {
            "id": "i-nobackup001",
            "type": "ec2_instance",
            "tags": {
                "environment": "production",
                "team": "platform-engineering",
                "cost_center": "CC-12345",
                "owner": "john@company.com"
            }
        }
    }

    # Should fail - EC2 requires backup_policy
    count(deny) > 0
}

test_fail_rds_missing_encryption_tag {
    input := {
        "resource": {
            "id": "db-noenctag001",
            "type": "rds_instance",
            "tags": {
                "environment": "production",
                "team": "database-reliability",
                "cost_center": "CC-67890",
                "owner": "db-team@company.com"
            }
        }
    }

    # Should fail - RDS requires encryption_required tag
    count(deny) > 0
}

test_fail_production_missing_monitoring {
    input := {
        "resource": {
            "id": "prod-app-001",
            "type": "ec2_instance",
            "tags": {
                "environment": "production",
                "team": "platform-engineering",
                "cost_center": "CC-12345",
                "owner": "john@company.com",
                "backup_policy": "daily"
            }
        }
    }

    # Should fail - production requires monitoring_enabled
    count(deny) > 0
}

# ============================================================================
# Edge Cases
# ============================================================================

test_warn_expired_resource {
    input := {
        "resource": {
            "id": "dev-temporary-001",
            "type": "ec2_instance",
            "tags": {
                "environment": "dev",
                "team": "platform-engineering",
                "cost_center": "CC-00000",
                "owner": "engineer@company.com",
                "expiry": "2020-12-31"
            }
        }
    }

    # Should warn - resource is past expiry
    count(warn) > 0
}

test_empty_tag_values {
    input := {
        "resource": {
            "id": "i-emptytags001",
            "type": "ec2_instance",
            "tags": {
                "environment": "production",
                "team": "",
                "cost_center": "",
                "owner": "unassigned"
            }
        }
    }

    # Should fail - empty tag values
    count(deny) > 0
}
