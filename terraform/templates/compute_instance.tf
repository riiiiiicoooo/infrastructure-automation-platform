/**
 * Terraform Template: EC2 Compute Instance
 *
 * Provisions a standardized EC2 instance with security group, IAM role,
 * CloudWatch monitoring, and enforced tagging standards.
 *
 * Usage:
 *   terraform apply -var-file=compute_instance.tfvars
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

variable "instance_type" {
  description = "EC2 instance type (e.g., t3.medium, c5.large, m5.xlarge)"
  type        = string
  default     = "t3.medium"

  validation {
    condition = can(regex("^(t3|t4g|c5|c6i|m5|m6i|r5|r6i|i3|i4i)\\.", var.instance_type))
    error_message = "Instance type must be from supported families (t3, t4g, c5, c6i, m5, m6i, r5, r6i, i3, i4i)."
  }
}

variable "environment" {
  description = "Environment name (dev, staging, production)"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Environment must be dev, staging, or production."
  }
}

variable "team" {
  description = "Team responsible for this resource"
  type        = string
}

variable "project_name" {
  description = "Project or application name"
  type        = string
}

variable "cost_center" {
  description = "Cost center for billing/chargeback"
  type        = string
  default     = "unassigned"
}

variable "ami_id" {
  description = "AMI ID (Amazon Linux 2 or custom hardened image)"
  type        = string
  default     = "ami-0c55b159cbfafe1f0"  # AL2 x86_64 EBS-backed (example)
}

variable "vpc_id" {
  description = "VPC ID for the instance"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID for the instance"
  type        = string
}

variable "key_name" {
  description = "EC2 Key Pair name for SSH access"
  type        = string
  default     = ""
}

variable "associate_public_ip" {
  description = "Assign public IP address"
  type        = bool
  default     = false
}

variable "enable_monitoring" {
  description = "Enable detailed CloudWatch monitoring"
  type        = bool
  default     = true
}

variable "root_volume_size" {
  description = "Root volume size in GB"
  type        = number
  default     = 20
}

variable "root_volume_type" {
  description = "Root volume type (gp3 recommended)"
  type        = string
  default     = "gp3"
}

variable "enable_encryption" {
  description = "Enable EBS root volume encryption"
  type        = bool
  default     = true
}

variable "allowed_security_group_ids" {
  description = "Security group IDs allowed to connect to this instance"
  type        = list(string)
  default     = []
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks allowed for SSH access"
  type        = list(string)
  default     = []
}

variable "additional_tags" {
  description = "Additional tags to apply to the instance"
  type        = map(string)
  default     = {}
}

# ============================================================================
# Data Sources
# ============================================================================

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# ============================================================================
# IAM Role for EC2 Instance
# ============================================================================

resource "aws_iam_role" "instance_role" {
  name_prefix = "${var.project_name}-${var.environment}-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = local.tags
}

# CloudWatch agent permissions
resource "aws_iam_role_policy_attachment" "cloudwatch_agent_policy" {
  role       = aws_iam_role.instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# SSM Session Manager (for secure shell access without SSH keys)
resource "aws_iam_role_policy_attachment" "ssm_managed_instance_core" {
  role       = aws_iam_role.instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# CloudWatch Logs permissions
resource "aws_iam_role_policy_attachment" "cloudwatch_logs_policy" {
  role       = aws_iam_role.instance_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsAgentServerPolicy"
}

# Instance profile
resource "aws_iam_instance_profile" "instance_profile" {
  name_prefix = "${var.project_name}-"
  role        = aws_iam_role.instance_role.name
}

# ============================================================================
# Security Group
# ============================================================================

resource "aws_security_group" "instance_sg" {
  name_prefix = "${var.project_name}-${var.environment}-"
  description = "Security group for ${var.project_name} in ${var.environment}"
  vpc_id      = var.vpc_id

  # Egress: Allow all outbound (restrictive in production)
  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

# SSH access from CIDR blocks (if provided)
resource "aws_security_group_rule" "ingress_ssh_cidr" {
  count = length(var.allowed_cidr_blocks) > 0 ? 1 : 0

  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = var.allowed_cidr_blocks
  security_group_id = aws_security_group.instance_sg.id
  description       = "SSH access from allowed CIDR blocks"
}

# SSH access from other security groups (if provided)
resource "aws_security_group_rule" "ingress_ssh_sg" {
  count = length(var.allowed_security_group_ids) > 0 ? 1 : 0

  type                     = "ingress"
  from_port                = 22
  to_port                  = 22
  protocol                 = "tcp"
  security_group_id        = aws_security_group.instance_sg.id
  source_security_group_id = var.allowed_security_group_ids[0]
  description              = "SSH access from allowed security groups"
}

# ============================================================================
# EC2 Instance
# ============================================================================

resource "aws_instance" "compute" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  iam_instance_profile   = aws_iam_instance_profile.instance_profile.name
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.instance_sg.id]
  key_name               = var.key_name != "" ? var.key_name : null
  associate_public_ip_address = var.associate_public_ip

  # Root volume configuration
  root_block_device {
    volume_type           = var.root_volume_type
    volume_size           = var.root_volume_size
    delete_on_termination = true
    encrypted             = var.enable_encryption

    tags = merge(
      local.tags,
      {
        Name = "${var.project_name}-${var.environment}-root"
      }
    )
  }

  # Monitoring
  monitoring = var.enable_monitoring

  # User data for initial configuration
  user_data = base64encode(local.user_data)

  # CPU credits for burstable instances
  cpu_credits = contains(["t3", "t4g"], split(".", var.instance_type)[0]) ? "unlimited" : null

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"  # IMDSv2 enforced
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "enabled"
  }

  # Enable detailed CloudWatch monitoring
  dynamic "monitoring" {
    for_each = var.enable_monitoring ? [1] : []
    content {
      enabled = true
    }
  }

  tags = merge(
    local.tags,
    {
      Name = "${var.project_name}-${var.environment}-instance"
    }
  )

  depends_on = [
    aws_iam_role_policy_attachment.cloudwatch_agent_policy,
    aws_iam_role_policy_attachment.ssm_managed_instance_core
  ]
}

# ============================================================================
# CloudWatch Alarms
# ============================================================================

resource "aws_cloudwatch_metric_alarm" "cpu_utilization" {
  alarm_name          = "${var.project_name}-${var.environment}-cpu-utilization"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = var.environment == "production" ? 80 : 85
  alarm_description   = "Alert when CPU utilization exceeds threshold"

  dimensions = {
    InstanceId = aws_instance.compute.id
  }

  tags = local.tags
}

resource "aws_cloudwatch_metric_alarm" "status_check" {
  alarm_name          = "${var.project_name}-${var.environment}-status-check"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Alert when instance fails status checks"

  dimensions = {
    InstanceId = aws_instance.compute.id
  }

  tags = local.tags
}

# ============================================================================
# Local Variables & Tagging Module
# ============================================================================

locals {
  tags = merge(
    var.additional_tags,
    {
      Name            = "${var.project_name}-${var.environment}"
      Environment     = var.environment
      Team            = var.team
      CostCenter      = var.cost_center
      Project         = var.project_name
      ManagedBy       = "infrastructure-automation-platform"
      CreatedAt       = timestamp()
      Compliance      = "required"
    }
  )

  user_data = <<-EOF
              #!/bin/bash
              set -e

              # Update system
              yum update -y

              # Install CloudWatch agent
              wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
              rpm -U ./amazon-cloudwatch-agent.rpm

              # Install SSM agent
              yum install -y amazon-ssm-agent
              systemctl enable amazon-ssm-agent
              systemctl start amazon-ssm-agent

              # Configure CloudWatch logs
              mkdir -p /opt/aws/amazon-cloudwatch-agent/etc/
              cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'CWCONFIG'
              {
                "metrics": {
                  "namespace": "CustomMetrics",
                  "metrics_collected": {
                    "cpu": {
                      "measurement": [
                        { "name": "cpu_usage_idle", "rename": "CPU_IDLE", "unit": "Percent" }
                      ],
                      "metrics_collection_interval": 60
                    },
                    "mem": {
                      "measurement": [
                        { "name": "mem_used_percent", "rename": "MEM_USED_PERCENT", "unit": "Percent" }
                      ],
                      "metrics_collection_interval": 60
                    },
                    "disk": {
                      "measurement": [
                        { "name": "used_percent", "rename": "DISK_USED_PERCENT", "unit": "Percent" }
                      ],
                      "metrics_collection_interval": 60,
                      "resources": ["/"]
                    }
                  }
                },
                "logs": {
                  "logs_collected": {
                    "files": {
                      "collect_list": [
                        {
                          "file_path": "/var/log/messages",
                          "log_group_name": "/aws/ec2/${var.project_name}/${var.environment}",
                          "log_stream_name": "{instance_id}/messages"
                        }
                      ]
                    }
                  }
                }
              }
              CWCONFIG

              # Start CloudWatch agent
              /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
                -a fetch-config \
                -m ec2 \
                -s \
                -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

              # Log successful initialization
              echo "Instance initialization completed at $(date)" >> /var/log/startup.log
              EOF
}

# ============================================================================
# Outputs
# ============================================================================

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.compute.id
}

output "instance_arn" {
  description = "EC2 instance ARN"
  value       = "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:instance/${aws_instance.compute.id}"
}

output "private_ip" {
  description = "Private IP address of the instance"
  value       = aws_instance.compute.private_ip
}

output "public_ip" {
  description = "Public IP address of the instance (if assigned)"
  value       = aws_instance.compute.public_ip
}

output "security_group_id" {
  description = "Security group ID attached to the instance"
  value       = aws_security_group.instance_sg.id
}

output "iam_role_arn" {
  description = "IAM role ARN attached to the instance"
  value       = aws_iam_role.instance_role.arn
}

output "root_volume_id" {
  description = "Root volume ID"
  value       = aws_instance.compute.root_block_device[0].volume_id
}
