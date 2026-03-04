/**
 * Terraform Template: Kubernetes Namespace with RBAC, Network Policies, and Resource Quotas
 *
 * Provisions a secure Kubernetes namespace with:
 * - Resource quotas (CPU/memory limits by environment)
 * - Default deny network policy (explicit allow required)
 * - RBAC role bindings for teams
 * - Service accounts for workloads
 *
 * Usage:
 *   terraform apply -var-file=kubernetes_namespace.tfvars
 */

terraform {
  required_version = ">= 1.0"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.27"
    }
  }
}

# ============================================================================
# Variables
# ============================================================================

variable "namespace_name" {
  description = "Kubernetes namespace name"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace_name))
    error_message = "Namespace name must be lowercase alphanumeric with hyphens."
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
  description = "Team responsible for the namespace"
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

# Resource quotas by environment
variable "cpu_request_limit" {
  description = "Total CPU request limit for the namespace"
  type        = string
  default     = "50"
}

variable "cpu_limit_limit" {
  description = "Total CPU limit for the namespace"
  type        = string
  default     = "100"
}

variable "memory_request_limit" {
  description = "Total memory request limit (Gi)"
  type        = string
  default     = "100"
}

variable "memory_limit_limit" {
  description = "Total memory limit (Gi)"
  type        = string
  default     = "200"
}

variable "pod_quota" {
  description = "Maximum number of pods in namespace"
  type        = number
  default     = 100
}

variable "deployment_quota" {
  description = "Maximum number of Deployments"
  type        = number
  default     = 20
}

variable "statefulset_quota" {
  description = "Maximum number of StatefulSets"
  type        = number
  default     = 5
}

variable "service_quota" {
  description = "Maximum number of Services"
  type        = number
  default     = 20
}

variable "configmap_quota" {
  description = "Maximum number of ConfigMaps"
  type        = number
  default     = 50
}

variable "secret_quota" {
  description = "Maximum number of Secrets"
  type        = number
  default     = 50
}

variable "pvc_quota" {
  description = "Maximum number of PersistentVolumeClaims"
  type        = number
  default     = 10
}

# Network policy configuration
variable "enable_network_policy" {
  description = "Enable default deny network policy"
  type        = bool
  default     = true
}

variable "allowed_namespaces" {
  description = "Namespaces allowed to communicate with this namespace (ingress)"
  type        = list(string)
  default     = []
}

variable "enable_egress_to_external" {
  description = "Allow egress to external networks (DNS, internet)"
  type        = bool
  default     = true
}

# RBAC Configuration
variable "admin_users" {
  description = "Kubernetes users with admin access to namespace"
  type        = list(string)
  default     = []
}

variable "developer_users" {
  description = "Kubernetes users with developer (read/write) access"
  type        = list(string)
  default     = []
}

variable "readonly_users" {
  description = "Kubernetes users with read-only access"
  type        = list(string)
  default     = []
}

# Service accounts for workloads
variable "service_account_names" {
  description = "Service account names to create for workloads"
  type        = list(string)
  default     = []
}

variable "additional_labels" {
  description = "Additional labels to apply to the namespace"
  type        = map(string)
  default     = {}
}

# ============================================================================
# Kubernetes Namespace
# ============================================================================

resource "kubernetes_namespace" "namespace" {
  metadata {
    name = var.namespace_name
    labels = merge(
      local.common_labels,
      var.additional_labels,
      {
        "app.kubernetes.io/name" = var.project_name
        "environment"             = var.environment
      }
    )
    annotations = {
      "description"  = "Namespace for ${var.project_name} in ${var.environment}"
      "team"         = var.team
      "cost_center"  = var.cost_center
      "managed_by"   = "infrastructure-automation-platform"
      "created_at"   = timestamp()
    }
  }
}

# ============================================================================
# Resource Quotas
# ============================================================================

resource "kubernetes_resource_quota" "compute_quota" {
  metadata {
    name      = "${var.namespace_name}-compute-quota"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  spec {
    hard = {
      "requests.cpu"    = var.cpu_request_limit
      "limits.cpu"      = var.cpu_limit_limit
      "requests.memory" = "${var.memory_request_limit}Gi"
      "limits.memory"   = "${var.memory_limit_limit}Gi"
    }

    scope_selector {
      match_expression {
        operator       = "In"
        scope_name     = "PriorityClass"
        values         = ["high", "medium", "low"]
      }
    }
  }
}

resource "kubernetes_resource_quota" "object_quota" {
  metadata {
    name      = "${var.namespace_name}-object-quota"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  spec {
    hard = {
      "pods"                        = var.pod_quota
      "deployments.apps"            = var.deployment_quota
      "statefulsets.apps"           = var.statefulset_quota
      "services"                    = var.service_quota
      "configmaps"                  = var.configmap_quota
      "secrets"                     = var.secret_quota
      "persistentvolumeclaims"      = var.pvc_quota
      "pods.running"                = var.pod_quota
    }
  }
}

# ============================================================================
# Network Policies (Default Deny + Explicit Allow)
# ============================================================================

# Default: Deny all ingress traffic
resource "kubernetes_network_policy" "default_deny_ingress" {
  count = var.enable_network_policy ? 1 : 0

  metadata {
    name      = "${var.namespace_name}-default-deny-ingress"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  spec {
    pod_selector {
      # Applies to all pods in the namespace
    }

    policy_types = ["Ingress"]

    # No ingress rules = deny all
  }
}

# Default: Deny all egress traffic (except DNS)
resource "kubernetes_network_policy" "default_deny_egress" {
  count = var.enable_network_policy ? 1 : 0

  metadata {
    name      = "${var.namespace_name}-default-deny-egress"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  spec {
    pod_selector {
      # Applies to all pods in the namespace
    }

    policy_types = ["Egress"]

    # Allow DNS (required for any external communication)
    egress {
      to = [
        {
          namespace_selector = {
            match_labels = {
              "name" = "kube-system"
            }
          }
        }
      ]

      ports = [
        {
          protocol = "UDP"
          port     = "53"
        }
      ]
    }

    # Allow egress to external networks if enabled
    dynamic "egress" {
      for_each = var.enable_egress_to_external ? [1] : []
      content {
        to = [
          {
            ip_block = {
              cidr = "0.0.0.0/0"
              except = [
                "169.254.169.254/32"  # Block EC2 metadata service
              ]
            }
          }
        ]

        ports = [
          {
            protocol = "TCP"
            port     = "443"
          },
          {
            protocol = "TCP"
            port     = "80"
          }
        ]
      }
    }
  }
}

# Allow traffic between pods in the same namespace
resource "kubernetes_network_policy" "allow_internal" {
  count = var.enable_network_policy ? 1 : 0

  metadata {
    name      = "${var.namespace_name}-allow-internal"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  spec {
    pod_selector {
      # Applies to all pods in the namespace
    }

    policy_types = ["Ingress"]

    ingress {
      from = [
        {
          pod_selector = {
            # Pods in the same namespace
          }
        }
      ]
    }
  }
}

# Allow ingress from specified namespaces
resource "kubernetes_network_policy" "allow_from_namespaces" {
  count = var.enable_network_policy && length(var.allowed_namespaces) > 0 ? 1 : 0

  metadata {
    name      = "${var.namespace_name}-allow-from-namespaces"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  spec {
    pod_selector {
      # Applies to all pods in the namespace
    }

    policy_types = ["Ingress"]

    dynamic "ingress" {
      for_each = var.allowed_namespaces

      content {
        from = [
          {
            namespace_selector = {
              match_labels = {
                "name" = ingress.value
              }
            }
          }
        ]
      }
    }
  }
}

# ============================================================================
# Service Accounts
# ============================================================================

resource "kubernetes_service_account" "workload_sa" {
  for_each = toset(var.service_account_names)

  metadata {
    name      = each.value
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }
}

# Default service account for the namespace
resource "kubernetes_service_account" "default" {
  metadata {
    name      = "default"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }
}

# ============================================================================
# RBAC: ClusterRole (namespace-scoped read/write)
# ============================================================================

resource "kubernetes_cluster_role" "namespace_admin" {
  metadata {
    name   = "${var.namespace_name}-admin"
    labels = local.common_labels
  }

  rule {
    api_groups = ["*"]
    resources  = ["*"]
    verbs      = ["*"]
  }
}

resource "kubernetes_cluster_role" "namespace_developer" {
  metadata {
    name   = "${var.namespace_name}-developer"
    labels = local.common_labels
  }

  rule {
    api_groups = ["apps"]
    resources  = ["deployments", "statefulsets", "daemonsets"]
    verbs      = ["get", "list", "watch", "create", "update", "patch"]
  }

  rule {
    api_groups = [""]
    resources  = ["pods", "pods/logs", "services", "configmaps"]
    verbs      = ["get", "list", "watch", "create", "update", "patch"]
  }

  rule {
    api_groups = ["batch"]
    resources  = ["jobs", "cronjobs"]
    verbs      = ["get", "list", "watch", "create", "update", "patch"]
  }
}

resource "kubernetes_cluster_role" "namespace_readonly" {
  metadata {
    name   = "${var.namespace_name}-readonly"
    labels = local.common_labels
  }

  rule {
    api_groups = ["*"]
    resources  = ["*"]
    verbs      = ["get", "list", "watch"]
  }
}

# ============================================================================
# RBAC: RoleBinding (namespace-scoped)
# ============================================================================

resource "kubernetes_role_binding" "admin_binding" {
  for_each = toset(var.admin_users)

  metadata {
    name      = "${each.value}-admin"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role.namespace_admin.metadata[0].name
  }

  subject {
    kind = "User"
    name = each.value
  }
}

resource "kubernetes_role_binding" "developer_binding" {
  for_each = toset(var.developer_users)

  metadata {
    name      = "${each.value}-developer"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role.namespace_developer.metadata[0].name
  }

  subject {
    kind = "User"
    name = each.value
  }
}

resource "kubernetes_role_binding" "readonly_binding" {
  for_each = toset(var.readonly_users)

  metadata {
    name      = "${each.value}-readonly"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role.namespace_readonly.metadata[0].name
  }

  subject {
    kind = "User"
    name = each.value
  }
}

# ============================================================================
# Pod Security Policy (PSP) - Restricted
# ============================================================================

resource "kubernetes_pod_security_policy" "restricted" {
  metadata {
    name   = "${var.namespace_name}-restricted"
    labels = local.common_labels
  }

  spec {
    privileged                 = false
    allow_privilege_escalation = false

    required_drop_capabilities = [
      "ALL"
    ]

    allowed_capabilities = [
      "NET_BIND_SERVICE"
    ]

    volumes = [
      "configMap",
      "emptyDir",
      "projected",
      "secret",
      "downwardAPI",
      "persistentVolumeClaim"
    ]

    host_network = false
    host_ipc     = false
    host_pid     = false

    run_as_user {
      rule = "MustRunAsNonRoot"
    }

    se_linux {
      rule = "MustRunAs"
      se_linux_options {
        level = "s0:c123,c456"
      }
    }

    fs_group {
      rule = "MustRunAs"
      range {
        min = 1
        max = 65535
      }
    }

    read_only_root_filesystem = false
  }
}

# ============================================================================
# LimitRange (default requests/limits for pods)
# ============================================================================

resource "kubernetes_limit_range" "compute_limits" {
  metadata {
    name      = "${var.namespace_name}-limit-range"
    namespace = kubernetes_namespace.namespace.metadata[0].name
    labels    = local.common_labels
  }

  spec {
    limit {
      type = "Pod"

      max = {
        "cpu"    = "4"
        "memory" = "8Gi"
      }

      min = {
        "cpu"    = "10m"
        "memory" = "32Mi"
      }
    }

    limit {
      type = "Container"

      max = {
        "cpu"    = "2"
        "memory" = "4Gi"
      }

      min = {
        "cpu"    = "10m"
        "memory" = "32Mi"
      }

      default = {
        "cpu"    = "500m"
        "memory" = "512Mi"
      }

      default_request = {
        "cpu"    = "250m"
        "memory" = "256Mi"
      }
    }
  }
}

# ============================================================================
# Local Variables
# ============================================================================

locals {
  common_labels = {
    "app.kubernetes.io/name"       = var.project_name
    "app.kubernetes.io/instance"   = var.namespace_name
    "app.kubernetes.io/managed-by" = "infrastructure-automation-platform"
    "environment"                  = var.environment
    "team"                         = var.team
  }
}

# ============================================================================
# Outputs
# ============================================================================

output "namespace_name" {
  description = "Name of the created Kubernetes namespace"
  value       = kubernetes_namespace.namespace.metadata[0].name
}

output "resource_quota_name" {
  description = "Name of the resource quota"
  value       = kubernetes_resource_quota.compute_quota.metadata[0].name
}

output "network_policy_count" {
  description = "Number of network policies created"
  value = (
    var.enable_network_policy ?
    (length(var.allowed_namespaces) > 0 ? 4 : 3) :
    0
  )
}

output "service_accounts" {
  description = "Service account names"
  value       = concat([kubernetes_service_account.default.metadata[0].name], [for sa in kubernetes_service_account.workload_sa : sa.metadata[0].name])
}

output "rbac_roles_count" {
  description = "Number of RBAC roles configured"
  value       = (
    length(var.admin_users) +
    length(var.developer_users) +
    length(var.readonly_users)
  )
}
