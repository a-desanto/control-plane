# Hostinger has no first-party Terraform provider. Two options:
#
#   1. local-exec with curl to Hostinger API (this file uses this approach as a stub)
#   2. Use null_resource + remote-exec to ssh-and-provision-via-Hostinger-API
#
# For real impl, swap to option 2 once you've validated the Hostinger API endpoints
# and added authentication via HOSTINGER_API_TOKEN env var.

variable "client_slug" { type = string }
variable "tier"        { type = string }
variable "region"      { type = string }
variable "vps_size"    { type = string }

resource "null_resource" "hostinger_vps" {
  triggers = {
    client_slug = var.client_slug
    tier        = var.tier
    region      = var.region
    vps_size    = var.vps_size
  }

  # STUB — replace with real Hostinger API call:
  #   curl -X POST https://developers.hostinger.com/api/vps/v1/virtual-machines \
  #     -H "Authorization: Bearer $HOSTINGER_API_TOKEN" \
  #     -d '{"plan_id":"...","region":"...","template_id":"ubuntu-24.04",...}'
  #
  # Capture the returned IP + UUID into terraform state so outputs can return them.
  provisioner "local-exec" {
    command = "echo 'STUB: would provision Hostinger VPS for ${var.client_slug} tier=${var.tier} region=${var.region}'"
  }
}

output "vps_ip"   { value = "STUB-IP" }   # Replace with actual API response capture
output "vps_uuid" { value = "STUB-UUID" }
