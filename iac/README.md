# Phase 5.7 — IaC skeleton (Terraform + Ansible)

Skeleton for the Phase 5.7 IaC stack. Drop at `iac/` in `a-desanto/control-plane` or as its own repo.

## Layout

```
terraform/
├── main.tf                          ← per-client root, calls modules
├── variables.tf                     ← client_slug, tier, provider, region, vps_size
├── modules/
│   └── hostinger-vps/
│       ├── main.tf                  ← Hostinger VPS resource (uses hetzner-style provider)
│       ├── variables.tf
│       └── outputs.tf
└── backend.tf                       ← S3 backend for state (~$0.10/mo)

ansible/
├── inventory.yml                    ← dynamic — populated by terraform output
├── bootstrap.yml                    ← Docker, Coolify agent, ufw, time sync
└── roles/
    └── canonical-stack/
        └── tasks/
            └── main.yml             ← deploy paperclipai, paddleocr, etc. via Coolify API

scripts/
└── onboard-client.sh                ← one-command client onboarding (terraform → ansible → paperclip company create)
```

## What's stubbed in this drop

- `terraform/modules/hostinger-vps/main.tf` — minimal Hostinger VPS resource (using `terraform-provider-hostinger` if it exists, or shell-out to Hostinger's API in a `local-exec` provisioner since their official provider is patchy)
- `ansible/bootstrap.yml` — minimal Docker + Coolify agent install + firewall
- `scripts/onboard-client.sh` — orchestrator that calls terraform apply → ansible-playbook → paperclip API

## What's MISSING / would need real work

- **Hostinger Terraform provider** — there's no first-party provider; need either an API-shim wrapper or use Linode/AWS as multi-tenant base instead. For Hostinger specifically, the cleanest path is `local-exec` with `curl` to their REST API.
- **Real `roles/canonical-stack/tasks/main.yml`** — needs Coolify API calls per app (paperclipai, paddleocr, etc.) with per-client env vars
- **Per-client tfvars files** — each new client needs `<slug>.tfvars` with their inputs
- **State management** — S3 backend config + per-workspace state isolation
- **CI/CD** — GitHub Actions to run `terraform plan` on PRs, `terraform apply` on merge
- **Drift detection cron** — `terraform plan` per-client on schedule, alert on drift

## How this connects to Phase 9.1 wizard

The wizard's stubbed `provision_vps`, `bootstrap_vps`, `deploy_canonical_stack` steps would shell out to:
```
./onboard-client.sh <slug> --tier <tier> --provider <provider> --region <region>
```
The script handles the terraform → ansible → coolify chain. Then the wizard continues with the AWS/SES steps (already real) and finishes.

## Effort to fully ship per ROADMAP

5-7 days focused work. This skeleton is ~half a day of layout. The hard parts are the Hostinger provider workaround + per-app Coolify API templates + CI/CD wiring.
