/**
 * Terraform Template: VPC with Multi-AZ Networking
 *
 * Provisions a production-grade VPC with:
 * - Public and private subnets across 3 AZs
 * - NAT gateways for private subnet egress
 * - VPC Flow Logs for network monitoring
 * - Proper CIDR allocation and route tables
 * - VPC endpoints for AWS services
 *
 * Usage:
 *   terraform apply -var-file=vpc_network.tfvars
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

variable "vpc_name" {
  description = "Name of the VPC"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC (e.g., 10.0.0.0/16)"
  type        = string

  validation {
    condition = can(cidrhost(var.vpc_cidr, 0))
    error_message = "VPC CIDR must be valid."
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
  description = "Team responsible for the VPC"
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

# Availability zones (default to 3)
variable "availability_zones" {
  description = "List of availability zones (will use first N from region)"
  type        = number
  default     = 3

  validation {
    condition     = var.availability_zones >= 2 && var.availability_zones <= 4
    error_message = "Number of AZs must be between 2 and 4."
  }
}

# DNS
variable "enable_dns_hostnames" {
  description = "Enable DNS hostnames in the VPC"
  type        = bool
  default     = true
}

variable "enable_dns_support" {
  description = "Enable DNS support in the VPC"
  type        = bool
  default     = true
}

# NAT Gateway
variable "enable_nat_gateway" {
  description = "Enable NAT gateways for private subnet egress"
  type        = bool
  default     = true
}

variable "nat_per_az" {
  description = "Create NAT gateway in each AZ (for HA) or single"
  type        = bool
  default     = true
}

# VPC Flow Logs
variable "enable_flow_logs" {
  description = "Enable VPC Flow Logs"
  type        = bool
  default     = true
}

variable "flow_logs_retention_days" {
  description = "CloudWatch Logs retention for VPC Flow Logs"
  type        = number
  default     = 30
}

# VPC Endpoints
variable "enable_s3_endpoint" {
  description = "Create gateway endpoint for S3"
  type        = bool
  default     = true
}

variable "enable_dynamodb_endpoint" {
  description = "Create gateway endpoint for DynamoDB"
  type        = bool
  default     = true
}

variable "enable_secrets_manager_endpoint" {
  description = "Create interface endpoint for Secrets Manager"
  type        = bool
  default     = true
}

# Tags
variable "additional_tags" {
  description = "Additional tags"
  type        = map(string)
  default     = {}
}

# ============================================================================
# Data Sources
# ============================================================================

data "aws_region" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# ============================================================================
# VPC
# ============================================================================

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = var.enable_dns_hostnames
  enable_dns_support   = var.enable_dns_support

  tags = merge(
    local.common_tags,
    {
      Name = var.vpc_name
    }
  )
}

# ============================================================================
# Internet Gateway
# ============================================================================

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-igw"
    }
  )

  depends_on = [aws_vpc.main]
}

# ============================================================================
# Public Subnets (one per AZ)
# ============================================================================

resource "aws_subnet" "public" {
  count                   = var.availability_zones
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-public-${data.aws_availability_zones.available.names[count.index]}"
      Tier = "Public"
    }
  )
}

# ============================================================================
# Private Subnets (one per AZ)
# ============================================================================

resource "aws_subnet" "private" {
  count             = var.availability_zones
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + 4)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-private-${data.aws_availability_zones.available.names[count.index]}"
      Tier = "Private"
    }
  )
}

# ============================================================================
# Elastic IPs for NAT Gateways
# ============================================================================

resource "aws_eip" "nat" {
  count  = var.enable_nat_gateway ? (var.nat_per_az ? var.availability_zones : 1) : 0
  domain = "vpc"

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-nat-eip-${count.index + 1}"
    }
  )

  depends_on = [aws_internet_gateway.main]
}

# ============================================================================
# NAT Gateways
# ============================================================================

resource "aws_nat_gateway" "main" {
  count         = var.enable_nat_gateway ? (var.nat_per_az ? var.availability_zones : 1) : 0
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-nat-${count.index + 1}"
    }
  )

  depends_on = [aws_internet_gateway.main]
}

# ============================================================================
# Route Tables: Public
# ============================================================================

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block      = "0.0.0.0/0"
    gateway_id      = aws_internet_gateway.main.id
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-public-rt"
      Tier = "Public"
    }
  )
}

resource "aws_route_table_association" "public" {
  count          = var.availability_zones
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ============================================================================
# Route Tables: Private (one per NAT or shared)
# ============================================================================

resource "aws_route_table" "private" {
  count  = var.nat_per_az ? var.availability_zones : 1
  vpc_id = aws_vpc.main.id

  dynamic "route" {
    for_each = var.enable_nat_gateway ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = var.nat_per_az ? aws_nat_gateway.main[count.index].id : aws_nat_gateway.main[0].id
    }
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-private-rt-${count.index + 1}"
      Tier = "Private"
    }
  )
}

resource "aws_route_table_association" "private" {
  count          = var.availability_zones
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = var.nat_per_az ? aws_route_table.private[count.index].id : aws_route_table.private[0].id
}

# ============================================================================
# VPC Flow Logs
# ============================================================================

resource "aws_cloudwatch_log_group" "flow_logs" {
  count             = var.enable_flow_logs ? 1 : 0
  name              = "/aws/vpc/flowlogs/${var.vpc_name}"
  retention_in_days = var.flow_logs_retention_days

  tags = local.common_tags
}

resource "aws_iam_role" "flow_logs_role" {
  count       = var.enable_flow_logs ? 1 : 0
  name_prefix = "${var.vpc_name}-flow-logs-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "vpc-flow-logs.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "flow_logs_policy" {
  count       = var.enable_flow_logs ? 1 : 0
  name_prefix = "${var.vpc_name}-flow-logs-"
  role        = aws_iam_role.flow_logs_role[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Effect   = "Allow"
        Resource = "${aws_cloudwatch_log_group.flow_logs[0].arn}:*"
      }
    ]
  })
}

resource "aws_flow_log" "vpc" {
  count                   = var.enable_flow_logs ? 1 : 0
  iam_role_arn            = aws_iam_role.flow_logs_role[0].arn
  log_destination         = "${aws_cloudwatch_log_group.flow_logs[0].arn}:*"
  traffic_type            = "ALL"
  vpc_id                  = aws_vpc.main.id
  log_format              = "${local.flow_log_format}"
  log_destination_type    = "cloud-watch-logs"

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-flow-logs"
    }
  )

  depends_on = [
    aws_cloudwatch_log_group.flow_logs,
    aws_iam_role_policy.flow_logs_policy
  ]
}

# ============================================================================
# VPC Endpoints
# ============================================================================

# S3 Gateway Endpoint
resource "aws_vpc_endpoint" "s3" {
  count           = var.enable_s3_endpoint ? 1 : 0
  vpc_id          = aws_vpc.main.id
  service_name    = "com.amazonaws.${data.aws_region.current.name}.s3"
  route_table_ids = concat([aws_route_table.public.id], aws_route_table.private[*].id)

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-s3-endpoint"
    }
  )
}

# DynamoDB Gateway Endpoint
resource "aws_vpc_endpoint" "dynamodb" {
  count           = var.enable_dynamodb_endpoint ? 1 : 0
  vpc_id          = aws_vpc.main.id
  service_name    = "com.amazonaws.${data.aws_region.current.name}.dynamodb"
  route_table_ids = concat([aws_route_table.public.id], aws_route_table.private[*].id)

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-dynamodb-endpoint"
    }
  )
}

# Secrets Manager Interface Endpoint
resource "aws_security_group" "endpoint_sg" {
  count       = var.enable_secrets_manager_endpoint ? 1 : 0
  name_prefix = "${var.vpc_name}-endpoint-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_vpc_endpoint" "secrets_manager" {
  count               = var.enable_secrets_manager_endpoint ? 1 : 0
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoint_sg[0].id]
  private_dns_enabled = true

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-secrets-manager-endpoint"
    }
  )
}

# ============================================================================
# Network ACLs (Additional security layer)
# ============================================================================

resource "aws_network_acl" "public" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = aws_subnet.public[*].id

  # Inbound: Allow HTTPS, HTTP
  ingress {
    protocol   = "tcp"
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 80
    to_port    = 80
  }

  ingress {
    protocol   = "tcp"
    rule_no    = 110
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 443
    to_port    = 443
  }

  # Inbound: Allow SSH (restricted in practice via security groups)
  ingress {
    protocol   = "tcp"
    rule_no    = 120
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 22
    to_port    = 22
  }

  # Inbound: Allow ephemeral ports (for return traffic)
  ingress {
    protocol   = "tcp"
    rule_no    = 130
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 1024
    to_port    = 65535
  }

  # Outbound: Allow all
  egress {
    protocol   = "-1"
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-public-nacl"
    }
  )
}

resource "aws_network_acl" "private" {
  vpc_id     = aws_vpc.main.id
  subnet_ids = aws_subnet.private[*].id

  # Inbound: Allow VPC traffic
  ingress {
    protocol   = "-1"
    rule_no    = 100
    action     = "allow"
    cidr_block = var.vpc_cidr
    from_port  = 0
    to_port    = 0
  }

  # Inbound: Allow ephemeral ports (for return traffic)
  ingress {
    protocol   = "tcp"
    rule_no    = 110
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 1024
    to_port    = 65535
  }

  # Outbound: Allow all
  egress {
    protocol   = "-1"
    rule_no    = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }

  tags = merge(
    local.common_tags,
    {
      Name = "${var.vpc_name}-private-nacl"
    }
  )
}

# ============================================================================
# CloudWatch Alarms for VPC Health
# ============================================================================

resource "aws_cloudwatch_metric_alarm" "nat_gateway_error_port_allocation" {
  count = var.enable_nat_gateway ? (var.nat_per_az ? var.availability_zones : 1) : 0

  alarm_name          = "${var.vpc_name}-nat-error-port-allocation-${count.index + 1}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ErrorPortAllocation"
  namespace           = "AWS/NatGateway"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Alert when NAT gateway has port allocation errors"

  dimensions = {
    NatGatewayId = aws_nat_gateway.main[count.index].id
  }
}

resource "aws_cloudwatch_metric_alarm" "nat_gateway_bandwidth" {
  count = var.enable_nat_gateway ? (var.nat_per_az ? var.availability_zones : 1) : 0

  alarm_name          = "${var.vpc_name}-nat-bandwidth-${count.index + 1}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "BytesOutToDestination"
  namespace           = "AWS/NatGateway"
  period              = 300
  statistic           = "Average"
  threshold           = 45000000  # ~45 MB/s warning threshold
  alarm_description   = "Alert when NAT gateway bandwidth exceeds threshold"

  dimensions = {
    NatGatewayId = aws_nat_gateway.main[count.index].id
  }
}

# ============================================================================
# Local Variables
# ============================================================================

locals {
  common_tags = merge(
    var.additional_tags,
    {
      Name            = var.vpc_name
      Environment     = var.environment
      Team            = var.team
      CostCenter      = var.cost_center
      Project         = var.project_name
      ManagedBy       = "infrastructure-automation-platform"
      CreatedAt       = timestamp()
    }
  )

  flow_log_format = "$${version} $${account_id} $${interface_id} $${srcaddr} $${dstaddr} $${srcport} $${dstport} $${protocol} $${packets} $${bytes} $${windowstart} $${windowend} $${action} $${tcpflags} $${type} $${pkt_srcaddr} $${pkt_dstaddr} $${region} $${vpc_id} $${flow_logs_status} $${traffic_type} $${subnet_id} $${instance_id} $${tcp_flags} $${format} $${version}"
}

# ============================================================================
# Outputs
# ============================================================================

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "VPC CIDR block"
  value       = aws_vpc.main.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "internet_gateway_id" {
  description = "Internet Gateway ID"
  value       = aws_internet_gateway.main.id
}

output "nat_gateway_ids" {
  description = "NAT Gateway IDs"
  value       = var.enable_nat_gateway ? aws_nat_gateway.main[*].id : []
}

output "nat_gateway_ips" {
  description = "Elastic IP addresses for NAT Gateways"
  value       = var.enable_nat_gateway ? aws_eip.nat[*].public_ip : []
}

output "public_route_table_id" {
  description = "Public route table ID"
  value       = aws_route_table.public.id
}

output "private_route_table_ids" {
  description = "Private route table IDs"
  value       = aws_route_table.private[*].id
}

output "s3_endpoint_id" {
  description = "S3 VPC Endpoint ID"
  value       = var.enable_s3_endpoint ? aws_vpc_endpoint.s3[0].id : null
}

output "dynamodb_endpoint_id" {
  description = "DynamoDB VPC Endpoint ID"
  value       = var.enable_dynamodb_endpoint ? aws_vpc_endpoint.dynamodb[0].id : null
}

output "secrets_manager_endpoint_id" {
  description = "Secrets Manager VPC Endpoint ID"
  value       = var.enable_secrets_manager_endpoint ? aws_vpc_endpoint.secrets_manager[0].id : null
}

output "flow_logs_group_name" {
  description = "CloudWatch Logs group for VPC Flow Logs"
  value       = var.enable_flow_logs ? aws_cloudwatch_log_group.flow_logs[0].name : null
}

output "availability_zones" {
  description = "Availability zones used"
  value       = slice(data.aws_availability_zones.available.names, 0, var.availability_zones)
}
