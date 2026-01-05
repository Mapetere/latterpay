# =============================================================================
# LatterPay Terraform Outputs
# =============================================================================

output "project_id" {
  description = "Railway project ID"
  value       = railway_project.latterpay.id
}

output "latterpay_service_id" {
  description = "LatterPay service ID"
  value       = railway_service.latterpay.id
}

output "postgres_service_id" {
  description = "PostgreSQL service ID"
  value       = railway_service.postgres.id
}

output "deployment_url" {
  description = "Deployment URL hint"
  value       = "${var.project_name}-production.up.railway.app"
}
