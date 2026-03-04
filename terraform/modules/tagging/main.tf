/**
 * Terraform Module: Enforced Tagging
 *
 * Provides a reusable tagging module that enforces mandatory tags
 * across all infrastructure resources.
 *
 * Usage:
 *   module "tags" {
 *     source = "./modules/tagging"
 *     environment = var.environment
 *     project = var.project_name
 *     team = var.team
 *     cost_center = var.cost_center
 *     additional_tags = var.additional_tags
 *   }
 *
 *   tags = module.tags.common_tags
 */

variable "environment" {
  description = "Environment name (dev, staging, production)"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Environment must be dev, staging, or production."
  }
}

variable "project" {
  description = "Project name"
  type        = string

  validation {
    condition     = length(var.project) > 0 && length(var.project) <= 50
    error_message = "Project name must be between 1 and 50 characters."
  }
}

variable "team" {
  description = "Team responsible for the resource"
  type        = string

  validation {
    condition     = length(var.team) > 0
    error_message = "Team name is required."
  }
}

variable "cost_center" {
  description = "Cost center for billing/chargeback"
  type        = string

  validation {
    condition     = length(var.cost_center) > 0
    error_message = "Cost center is required."
  }
}

variable "owner" {
  description = "Owner email or identifier"
  type        = string
  default     = ""
}

variable "expiry_date" {
  description = "Resource expiry date (YYYY-MM-DD) - optional"
  type        = string
  default     = ""

  validation {
    condition = var.expiry_date == "" || can(regex("^\\d{4}-\\d{2}-\\d{2}$", var.expiry_date))
    error_message = "Expiry date must be in YYYY-MM-DD format."
  }
}

variable "compliance_framework" {
  description = "Compliance framework (SOC2, HIPAA, PCI-DSS, FedRAMP, NIST, etc.)"
  type        = list(string)
  default     = []
}

variable "backup_policy" {
  description = "Backup policy (daily, weekly, monthly, none)"
  type        = string
  default     = "daily"

  validation {
    condition     = contains(["daily", "weekly", "monthly", "none"], var.backup_policy)
    error_message = "Backup policy must be daily, weekly, monthly, or none."
  }
}

variable "encryption_required" {
  description = "Whether encryption is required"
  type        = bool
  default     = true
}

variable "monitoring_required" {
  description = "Whether monitoring is required"
  type        = bool
  default     = true
}

variable "additional_tags" {
  description = "Additional custom tags"
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for k, v in var.additional_tags :
      length(k) <= 128 && length(v) <= 256
    ])
    error_message = "Tag keys must be <= 128 chars, values <= 256 chars."
  }
}

# ============================================================================
# Mandatory Tags (OPA Enforcement)
# ============================================================================

locals {
  mandatory_tags = {
    # Required by policy
    "Environment"      = var.environment
    "Project"          = var.project
    "Team"             = var.team
    "CostCenter"       = var.cost_center
    "Owner"            = var.owner != "" ? var.owner : "unassigned"
    "ManagedBy"        = "infrastructure-automation-platform"
    "CreatedAt"        = timestamp()
    "CreatedBy"        = "terraform"

    # Compliance and operational
    "Compliance"       = length(var.compliance_framework) > 0 ? join(",", var.compliance_framework) : "none"
    "BackupPolicy"     = var.backup_policy
    "EncryptionRequired" = var.encryption_required ? "true" : "false"
    "MonitoringRequired" = var.monitoring_required ? "true" : "false"
  }

  optional_tags = var.expiry_date != "" ? {
    "ExpiryDate" = var.expiry_date
  } : {}

  common_tags = merge(
    local.mandatory_tags,
    local.optional_tags,
    var.additional_tags
  )
}

# ============================================================================
# Tag Validation
# ============================================================================

locals {
  # Validation checks for tag requirements
  validation_checks = {
    has_environment      = contains(keys(local.common_tags), "Environment")
    has_project          = contains(keys(local.common_tags), "Project")
    has_team             = contains(keys(local.common_tags), "Team")
    has_cost_center      = contains(keys(local.common_tags), "CostCenter")
    has_owner            = contains(keys(local.common_tags), "Owner")
    has_managed_by       = contains(keys(local.common_tags), "ManagedBy")
    has_created_at       = contains(keys(local.common_tags), "CreatedAt")
  }
}

# ============================================================================
# Outputs
# ============================================================================

output "common_tags" {
  description = "Map of common tags to apply to all resources"
  value       = local.common_tags
}

output "mandatory_tags" {
  description = "Mandatory tags that must be present"
  value       = local.mandatory_tags
}

output "tag_count" {
  description = "Total number of tags"
  value       = length(local.common_tags)
}

output "validation_status" {
  description = "Tag validation results"
  value = alltrue([
    local.validation_checks.has_environment,
    local.validation_checks.has_project,
    local.validation_checks.has_team,
    local.validation_checks.has_cost_center,
    local.validation_checks.has_owner,
    local.validation_checks.has_managed_by,
    local.validation_checks.has_created_at,
  ]) ? "PASS" : "FAIL"
}

output "tags_as_json" {
  description = "Tags as JSON string (useful for logging/audit)"
  value       = jsonencode(local.common_tags)
}

output "owner_email" {
  description = "Resource owner email"
  value       = var.owner != "" ? var.owner : "unassigned"
}

output "cost_center_code" {
  description = "Cost center for billing"
  value       = var.cost_center
}
