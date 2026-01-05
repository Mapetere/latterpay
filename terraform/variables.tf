# =============================================================================
# LatterPay Terraform Variables
# =============================================================================

# Railway
variable "railway_token" {
  description = "Railway API token"
  type        = string
  sensitive   = true
}

variable "project_name" {
  description = "Railway project name"
  type        = string
  default     = "latterpay"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "production"
}

# GitHub
variable "github_repo" {
  description = "GitHub repository URL"
  type        = string
  default     = "Mapetere/latterpay"
}

variable "github_branch" {
  description = "Git branch to deploy"
  type        = string
  default     = "main"
}

# PostgreSQL
variable "postgres_user" {
  description = "PostgreSQL username"
  type        = string
  default     = "postgres"
}

variable "postgres_password" {
  description = "PostgreSQL password"
  type        = string
  sensitive   = true
}

variable "postgres_db" {
  description = "PostgreSQL database name"
  type        = string
  default     = "latterpay"
}

# WhatsApp
variable "whatsapp_token" {
  description = "WhatsApp API token"
  type        = string
  sensitive   = true
}

variable "phone_number_id" {
  description = "WhatsApp phone number ID"
  type        = string
}

variable "verify_token" {
  description = "Webhook verification token"
  type        = string
  sensitive   = true
}

# Paynow
variable "paynow_zwg_id" {
  description = "Paynow ZWG integration ID"
  type        = string
}

variable "paynow_zwg_key" {
  description = "Paynow ZWG integration key"
  type        = string
  sensitive   = true
}

variable "paynow_usd_id" {
  description = "Paynow USD integration ID"
  type        = string
}

variable "paynow_usd_key" {
  description = "Paynow USD integration key"
  type        = string
  sensitive   = true
}

# Admin
variable "admin_phone" {
  description = "Admin phone number"
  type        = string
}

variable "finance_phone" {
  description = "Finance phone number"
  type        = string
}

# Optional
variable "openai_api_key" {
  description = "OpenAI API key (optional)"
  type        = string
  default     = ""
  sensitive   = true
}
