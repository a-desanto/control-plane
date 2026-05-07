#!/bin/bash
# Phase 5.7 — one-command client onboarding orchestrator
# Usage: ./onboard-client.sh <slug> --tier <tier> --provider <provider> --region <region>
#
# Drives terraform → ansible → Coolify in sequence. Designed to be the back-end of
# Phase 9.1's wizard's stubbed VPS-stage steps.

set -euo pipefail

CLIENT_SLUG="${1:-}"
shift || true

if [ -z "$CLIENT_SLUG" ]; then
  echo "Usage: $0 <slug> --tier <tier> --provider <provider> --region <region>" >&2
  exit 1
fi

TIER="standard"
PROVIDER="hostinger"
REGION="us-east-2"
VPS_SIZE="kvm-2"

while [ $# -gt 0 ]; do
  case "$1" in
    --tier)     TIER="$2";     shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --region)   REGION="$2";   shift 2 ;;
    --vps-size) VPS_SIZE="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TFVARS_DIR="$REPO_ROOT/terraform/clients"
mkdir -p "$TFVARS_DIR"

TFVARS_FILE="$TFVARS_DIR/${CLIENT_SLUG}.tfvars"
cat > "$TFVARS_FILE" <<EOF
client_slug   = "$CLIENT_SLUG"
client_name   = "$CLIENT_SLUG"
tier          = "$TIER"
provider_name = "$PROVIDER"
region        = "$REGION"
vps_size      = "$VPS_SIZE"
EOF

echo "==> Running terraform apply for $CLIENT_SLUG ($TIER, $PROVIDER, $REGION, $VPS_SIZE)"
cd "$REPO_ROOT/terraform"
terraform init -input=false
terraform apply -var-file="$TFVARS_FILE" -auto-approve

VPS_IP=$(terraform output -raw vps_ip)
VPS_UUID=$(terraform output -raw vps_uuid)
echo "==> VPS provisioned: $VPS_IP (uuid=$VPS_UUID)"

# Wait for SSH to come up
echo "==> Waiting for SSH on $VPS_IP..."
for i in $(seq 1 30); do
  if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 root@"$VPS_IP" 'echo ok' >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

echo "==> Running bootstrap.yml against $VPS_IP"
cd "$REPO_ROOT/ansible"
ansible-playbook -i "${VPS_IP}," bootstrap.yml -u root

echo "==> Triggering canonical-stack deploy via Coolify API"
ansible-playbook -i "${VPS_IP}," roles/canonical-stack/tasks/main.yml -u root \
  -e "client_slug=$CLIENT_SLUG"

echo "==> Done. VPS=$VPS_IP slug=$CLIENT_SLUG"
echo "    Next: Phase 9.1 wizard creates the paperclipai company + AWS resources + DNS records."
