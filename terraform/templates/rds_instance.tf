/**
 * Terraform Template: RDS PostgreSQL Instance
 *
 * Provisions a managed PostgreSQL RDS instance with:
 * - Encryption at rest (KMS customer-managed keys)
 * - Automated backups with 7-day retention
 * - Multi-AZ for production environments
 * - Enhanced monitoring and parameter customization
 * - Security group with restricted access
 *
 * Usage:
 *   terraform apply -var-file=rds_instance.tfvars
 */

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ============================================================================
# Variables
# ============================================================================

variable "identifier" {
  description = "Database instance identifier"
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9\\-]*[a-z0-9]$", var.identifier))
    error_message = "Identifier must start with lowercase letter and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "15.3"
}

variable "instance_class" {
  description = "Database instance class (e.g., db.t3.medium, db.r6i.large)"
  type        = string
  default     = "db.t3.medium"

  validation {
    condition = can(regex("^db\\.(t3|t4g|r6i|r7g|c6i|c7g)\\.", var.instance_class))
    error_message = "Instance class must be from supported families."
  }
}

variable "environment" {
  description = "Environment (dev, staging, production)"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Environment must be dev, staging, or production."
  }
}

variable "team" {
  description = "Team responsible for the database"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
}

variable "cost_center" {
  description = "Cost center for chargeback"
  type        = string
  default     = "unassigned"
}

# Database configuration
variable "database_name" {
  description = "Initial database name"
  type        = string
  default     = ""
}

variable "db_username" {
  description = "Master username for the database"
  type        = string
  default     = "postgres"
  sensitive   = true
}

variable "db_password" {
  description = "Master password (min 8 characters, must include uppercase, lowercase, number, special char)"
  type        = string
  sensitive   = true

  validation {
    condition = (
      length(var.db_password) >= 8 &&
      can(regex("[A-Z]", var.db_password)) &&
      can(regex("[a-z]", var.db_password)) &&
      can(regex("[0-9]", var.db_password)) &&
      can(regex("[!@#$%^&*()_+\\-=\\[\\]{};':\"\\\\|,.<>\\/?]", var.db_password))
    )
    error_message = "Password must be at least 8 characters with uppercase, lowercase, number, and special character."
  }
}

variable "allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
  default     = 20

  validation {
    condition     = var.allocated_storage >= 20 && var.allocated_storage <= 65536
    error_message = "Storage must be between 20 and 65536 GB."
  }
}

variable "max_allocated_storage" {
  description = "Maximum auto-scaling storage (0 = disabled)"
  type        = number
  default     = 100
}

variable "storage_type" {
  description = "Storage type (gp3 recommended)"
  type        = string
  default     = "gp3"

  validation {
    condition     = contains(["gp2", "gp3", "io1", "io2"], var.storage_type)
    error_message = "Storage type must be gp2, gp3, io1, or io2."
  }
}

variable "storage_iops" {
  description = "IOPS for io1/io2/gp3 (gp3: 3000-16000, io1/io2: 1000-64000)"
  type        = number
  default     = 3000
}

variable "storage_throughput" {
  description = "Throughput for gp3 (125-1000 MB/s)"
  type        = number
  default     = 125
}

# High availability
variable "multi_az" {
  description = "Enable Multi-AZ deployment (automatic failover)"
  type        = bool
  default     = true
}

variable "backup_retention_period" {
  description = "Automated backup retention (days)"
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_period >= 1 && var.backup_retention_period <= 35
    error_message = "Backup retention must be between 1 and 35 days."
  }
}

variable "backup_window" {
  description = "Preferred backup window (UTC, 24h format)"
  type        = string
  default     = "03:00-04:00"
}

variable "maintenance_window" {
  description = "Preferred maintenance window"
  type        = string
  default     = "sun:04:00-sun:05:00"
}

# Encryption
variable "storage_encrypted" {
  description = "Enable encryption at rest"
  type        = bool
  default     = true
}

variable "kms_key_id" {
  description = "KMS key ID for encryption (if blank, AWS managed key is used)"
  type        = string
  default     = ""
}

variable "enable_iam_database_auth" {
  description = "Enable IAM database authentication"
  type        = bool
  default     = true
}

# Monitoring
variable "enable_enhanced_monitoring" {
  description = "Enable RDS Enhanced Monitoring"
  type        = bool
  default     = true
}

variable "monitoring_interval" {
  description = "Enhanced monitoring interval (0, 1, 5, 10, 15, 30, 60)"
  type        = number
  default     = 60
}

variable "enable_cloudwatch_logs" {
  description = "Enable CloudWatch Logs"
  type        = bool
  default     = true
}

variable "enable_performance_insights" {
  description = "Enable Performance Insights"
  type        = bool
  default     = true
}

variable "performance_insights_retention" {
  description = "Performance Insights retention period (7 days free, then 7-31 days paid)"
  type        = number
  default     = 7
}

# Network
variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "db_subnet_group_name" {
  description = "DB subnet group name (must exist)"
  type        = string
}

variable "allowed_security_group_ids" {
  description = "Security group IDs allowed to access the database"
  type        = list(string)
  default     = []
}

variable "allow_public_ip" {
  description = "Make database publicly accessible (not recommended)"
  type        = bool
  default     = false
}

# Parameters
variable "parameter_group_family" {
  description = "Parameter group family (postgres15, etc.)"
  type        = string
  default     = "postgres15"
}

variable "custom_parameters" {
  description = "Custom PostgreSQL parameters"
  type        = map(string)
  default     = {}
}

variable "additional_tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

# ============================================================================
# Data Sources
# ============================================================================

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# ============================================================================
# IAM Role for Enhanced Monitoring
# ============================================================================

resource "aws_iam_role" "rds_monitoring_role" {
  count       = var.enable_enhanced_monitoring ? 1 : 0
  name_prefix = "${var.identifier}-monitoring-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "monitoring.rds.amazonaws.com"
        }
      }
    ]
  })

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "rds_monitoring_policy" {
  count      = var.enable_enhanced_monitoring ? 1 : 0
  role       = aws_iam_role.rds_monitoring_role[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ============================================================================
# IAM Role for Performance Insights
# ============================================================================

resource "aws_iam_role" "rds_pi_role" {
  count       = var.enable_performance_insights ? 1 : 0
  name_prefix = "${var.identifier}-pi-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
        }
      }
    ]
  })

  tags = local.tags
}

# ============================================================================
# Security Group
# ============================================================================

resource "aws_security_group" "rds_sg" {
  name_prefix = "${var.identifier}-"
  description = "Security group for RDS ${var.identifier}"
  vpc_id      = var.vpc_id

  # Egress: Allow all outbound
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

# PostgreSQL port access from security groups
resource "aws_security_group_rule" "rds_ingress_sg" {
  for_each = toset(var.allowed_security_group_ids)

  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds_sg.id
  source_security_group_id = each.value
  description              = "PostgreSQL access from ${each.value}"
}

# ============================================================================
# RDS Parameter Group
# ============================================================================

resource "aws_db_parameter_group" "parameters" {
  name_prefix = "${var.identifier}-"
  family      = var.parameter_group_family
  description = "Parameters for ${var.identifier}"

  # Standard optimizations for production
  parameter {
    name  = "shared_buffers"
    value = "{DBInstanceClassMemory/32768}"
  }

  parameter {
    name  = "effective_cache_size"
    value = "{DBInstanceClassMemory/2048}"
  }

  parameter {
    name  = "work_mem"
    value = "16000"
  }

  parameter {
    name  = "maintenance_work_mem"
    value = "524288"
  }

  parameter {
    name  = "log_statement"
    value = "all"
  }

  parameter {
    name  = "log_duration"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"  # Log queries slower than 1 second
  }

  parameter {
    name  = "max_connections"
    value = "200"
  }

  parameter {
    name  = "ssl"
    value = "1"
  }

  # Apply custom parameters
  dynamic "parameter" {
    for_each = var.custom_parameters
    content {
      name  = parameter.key
      value = parameter.value
    }
  }

  tags = local.tags

  lifecycle {
    create_before_destroy = true
  }
}

# ============================================================================
# KMS Key for Encryption (if specified)
# ============================================================================

resource "aws_kms_key" "rds_key" {
  count                   = var.storage_encrypted && var.kms_key_id == "" ? 1 : 0
  description             = "KMS key for RDS ${var.identifier}"
  deletion_window_in_days = 10
  enable_key_rotation     = true

  tags = local.tags
}

resource "aws_kms_alias" "rds_key_alias" {
  count         = var.storage_encrypted && var.kms_key_id == "" ? 1 : 0
  name          = "alias/${var.identifier}"
  target_key_id = aws_kms_key.rds_key[0].key_id
}

# ============================================================================
# RDS Instance
# ============================================================================

resource "aws_db_instance" "postgres" {
  identifier            = var.identifier
  engine                = "postgres"
  engine_version        = var.engine_version
  instance_class        = var.instance_class
  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = var.storage_type
  storage_iops          = var.storage_type != "gp2" ? var.storage_iops : null
  storage_throughput    = var.storage_type == "gp3" ? var.storage_throughput : null

  # Credentials
  db_name  = var.database_name != "" ? var.database_name : null
  username = var.db_username
  password = var.db_password

  # High availability
  multi_az = var.multi_az

  # Networking
  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = [aws_security_group.rds_sg.id]
  publicly_accessible    = var.allow_public_ip

  # Parameter group
  parameter_group_name = aws_db_parameter_group.parameters.name

  # Backups
  backup_retention_period = var.backup_retention_period
  backup_window           = var.backup_window
  copy_tags_to_snapshot   = true
  delete_automated_backups = false
  skip_final_snapshot     = false
  final_snapshot_identifier = "${var.identifier}-final-snapshot-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  # Maintenance
  maintenance_window            = var.maintenance_window
  auto_minor_version_upgrade    = true

  # Encryption
  storage_encrypted = var.storage_encrypted
  kms_key_id        = var.storage_encrypted && var.kms_key_id != "" ? var.kms_key_id : (var.storage_encrypted && length(aws_kms_key.rds_key) > 0 ? aws_kms_key.rds_key[0].arn : null)

  # IAM authentication
  iam_database_authentication_enabled = var.enable_iam_database_auth

  # Monitoring
  enabled_cloudwatch_logs_exports = var.enable_cloudwatch_logs ? ["postgresql"] : []
  enable_iam_database_authentication = var.enable_iam_database_auth

  # Enhanced monitoring
  enabled_cloudwatch_logs_exports  = ["postgresql"]
  monitoring_interval              = var.enable_enhanced_monitoring ? var.monitoring_interval : 0
  monitoring_role_arn              = var.enable_enhanced_monitoring ? aws_iam_role.rds_monitoring_role[0].arn : null

  # Performance Insights
  performance_insights_enabled          = var.enable_performance_insights
  performance_insights_retention_period = var.enable_performance_insights ? var.performance_insights_retention : null

  # Tags
  tags = local.tags

  depends_on = [
    aws_db_parameter_group.parameters,
    aws_security_group.rds_sg
  ]
}

# ============================================================================
# RDS Event Subscription (SNS notifications)
# ============================================================================

resource "aws_sns_topic" "rds_events" {
  name_prefix = "${var.identifier}-events-"
  tags        = local.tags
}

resource "aws_db_event_subscription" "rds_events" {
  name_prefix = "${var.identifier}-"
  sns_topic   = aws_sns_topic.rds_events.arn
  source_type = "db-instance"

  event_categories = [
    "availability",
    "backup",
    "failover",
    "failure",
    "maintenance",
    "notification",
    "recovery"
  ]

  depends_on = [aws_db_instance.postgres]
}

# ============================================================================
# CloudWatch Alarms
# ============================================================================

resource "aws_cloudwatch_metric_alarm" "db_cpu_utilization" {
  alarm_name          = "${var.identifier}-cpu-utilization"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.environment == "production" ? 75 : 85
  alarm_description   = "Alert when database CPU exceeds threshold"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.id
  }

  tags = local.tags
}

resource "aws_cloudwatch_metric_alarm" "db_connections" {
  alarm_name          = "${var.identifier}-connections"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 150
  alarm_description   = "Alert when database connection count is high"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.id
  }

  tags = local.tags
}

resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${var.identifier}-storage"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.allocated_storage * 1024 * 1024 * 1024 * 0.1  # Alert at 10% free
  alarm_description   = "Alert when free storage drops below threshold"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.id
  }

  tags = local.tags
}

resource "aws_cloudwatch_metric_alarm" "db_replication_lag" {
  count               = var.multi_az ? 1 : 0
  alarm_name          = "${var.identifier}-replication-lag"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "AuroraBinlogReplicaLag"
  namespace           = "AWS/RDS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1000  # milliseconds
  alarm_description   = "Alert when replication lag exceeds threshold"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.id
  }

  tags = local.tags
}

# ============================================================================
# Local Variables
# ============================================================================

locals {
  tags = merge(
    var.additional_tags,
    {
      Name            = var.identifier
      Environment     = var.environment
      Team            = var.team
      CostCenter      = var.cost_center
      Project         = var.project_name
      ManagedBy       = "infrastructure-automation-platform"
      CreatedAt       = timestamp()
      Engine          = "PostgreSQL"
      BackupRetention = "${var.backup_retention_period} days"
      MultiAZ         = var.multi_az ? "enabled" : "disabled"
      Encryption      = var.storage_encrypted ? "enabled" : "disabled"
    }
  )
}

# ============================================================================
# Outputs
# ============================================================================

output "db_instance_id" {
  description = "Database instance identifier"
  value       = aws_db_instance.postgres.id
}

output "db_instance_arn" {
  description = "Database instance ARN"
  value       = aws_db_instance.postgres.arn
}

output "db_endpoint" {
  description = "Database endpoint (host:port)"
  value       = aws_db_instance.postgres.endpoint
}

output "db_address" {
  description = "Database hostname"
  value       = aws_db_instance.postgres.address
}

output "db_port" {
  description = "Database port"
  value       = aws_db_instance.postgres.port
}

output "db_name" {
  description = "Database name"
  value       = aws_db_instance.postgres.db_name
}

output "db_username" {
  description = "Master username"
  value       = aws_db_instance.postgres.username
  sensitive   = true
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.rds_sg.id
}

output "parameter_group_name" {
  description = "Parameter group name"
  value       = aws_db_parameter_group.parameters.name
}

output "kms_key_id" {
  description = "KMS key ID for encryption"
  value       = var.storage_encrypted && var.kms_key_id == "" ? aws_kms_key.rds_key[0].id : var.kms_key_id
}

output "sns_topic_arn" {
  description = "SNS topic ARN for RDS events"
  value       = aws_sns_topic.rds_events.arn
}

output "multi_az_enabled" {
  description = "Whether Multi-AZ is enabled"
  value       = aws_db_instance.postgres.multi_az
}

output "backup_retention_period" {
  description = "Backup retention period in days"
  value       = aws_db_instance.postgres.backup_retention_period
}
