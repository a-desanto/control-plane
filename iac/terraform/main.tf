# Per-client root. Run with: terraform apply -var-file=clients/<slug>.tfvars -auto-approve

terraform {
  required_version = ">= 1.6"
  required_providers {
    hostinger = {
      source  = "hashicorp/null"  # placeholder — real Hostinger provider TBD
      version = "~> 3.0"
    }
  }

  # Uncomment once an S3 bucket exists for state:
  # backend "s3" {
  #   bucket = "cfpa-terraform-state"
  #   key    = "clients/${var.client_slug}/terraform.tfstate"
  #   region = "us-east-2"
  # }
}

variable "client_slug"   { type = string }
variable "client_name"   { type = string }
variable "tier"          { type = string }   # standard | compliance-hipaa | premium
variable "provider_name" { type = string }   # hostinger | linode | aws
variable "region"        { type = string  default = "us-east-2" }
variable "vps_size"      { type = string  default = "kvm-2" }

module "vps" {
  source = "./modules/hostinger-vps"

  client_slug = var.client_slug
  tier        = var.tier
  region      = var.region
  vps_size    = var.vps_size
}

output "vps_ip"      { value = module.vps.vps_ip }
output "vps_uuid"    { value = module.vps.vps_uuid }
output "client_slug" { value = var.client_slug }
