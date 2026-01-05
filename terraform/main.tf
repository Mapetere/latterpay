# =============================================================================
# LatterPay Terraform Configuration
# =============================================================================
# Infrastructure as Code for Railway deployment
# =============================================================================

terraform {
  required_version = ">= 1.0.0"
  
  required_providers {
    railway = {
      source  = "terraform-community-providers/railway"
      version = "~> 0.2"
    }
  }
}

# =============================================================================
# PROVIDER CONFIGURATION
# =============================================================================

provider "railway" {
  token = var.railway_token
}

# =============================================================================
# PROJECT
# =============================================================================

resource "railway_project" "latterpay" {
  name = var.project_name
}

# =============================================================================
# POSTGRESQL DATABASE
# =============================================================================

resource "railway_service" "postgres" {
  project_id = railway_project.latterpay.id
  name       = "postgres"
  
  source {
    image = "postgres:15-alpine"
  }
}

resource "railway_variable" "postgres_user" {
  service_id       = railway_service.postgres.id
  environment_name = var.environment
  name             = "POSTGRES_USER"
  value            = var.postgres_user
}

resource "railway_variable" "postgres_password" {
  service_id       = railway_service.postgres.id
  environment_name = var.environment
  name             = "POSTGRES_PASSWORD"
  value            = var.postgres_password
}

resource "railway_variable" "postgres_db" {
  service_id       = railway_service.postgres.id
  environment_name = var.environment
  name             = "POSTGRES_DB"
  value            = var.postgres_db
}

# =============================================================================
# LATTERPAY APPLICATION
# =============================================================================

resource "railway_service" "latterpay" {
  project_id = railway_project.latterpay.id
  name       = "latterpay"
  
  source {
    repo   = var.github_repo
    branch = var.github_branch
  }
}

# WhatsApp Configuration
resource "railway_variable" "whatsapp_token" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "WHATSAPP_TOKEN"
  value            = var.whatsapp_token
}

resource "railway_variable" "phone_number_id" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "PHONE_NUMBER_ID"
  value            = var.phone_number_id
}

resource "railway_variable" "verify_token" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "VERIFY_TOKEN"
  value            = var.verify_token
}

# Paynow Configuration
resource "railway_variable" "paynow_zwg_id" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "PAYNOW_ZWG_ID"
  value            = var.paynow_zwg_id
}

resource "railway_variable" "paynow_zwg_key" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "PAYNOW_ZWG_KEY"
  value            = var.paynow_zwg_key
}

resource "railway_variable" "paynow_usd_id" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "PAYNOW_USD_ID"
  value            = var.paynow_usd_id
}

resource "railway_variable" "paynow_usd_key" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "PAYNOW_USD_KEY"
  value            = var.paynow_usd_key
}

# Database Connection
resource "railway_variable" "database_url" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "DATABASE_URL"
  value            = "postgresql://${var.postgres_user}:${var.postgres_password}@${railway_service.postgres.name}.railway.internal:5432/${var.postgres_db}"
}

# Admin Configuration
resource "railway_variable" "admin_phone" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "ADMIN_PHONE"
  value            = var.admin_phone
}

resource "railway_variable" "finance_phone" {
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "FINANCE_PHONE"
  value            = var.finance_phone
}

# OpenAI (optional)
resource "railway_variable" "openai_api_key" {
  count            = var.openai_api_key != "" ? 1 : 0
  service_id       = railway_service.latterpay.id
  environment_name = var.environment
  name             = "OPENAI_API_KEY"
  value            = var.openai_api_key
}
