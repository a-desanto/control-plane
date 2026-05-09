"""Phase 9.1 Stage 2: client onboarding orchestrator.

Each step writes events to `client_onboarding_events`. The dashboard's live progress page
polls those events.

Real provisioning calls are STUBBED — they log "would do X" events and sleep briefly. To make
this drive real infra, replace the body of each step function (search for `# TODO`).

The orchestrator is intentionally simple — sequential, no concurrency. Reliability comes from
being able to retry from a failed step rather than from parallelism.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Awaitable, Callable

import asyncpg


DB_URL = os.environ.get(
    "PAPERCLIP_DB_URL",
    "postgresql://paperclip:paperclip@paperclip:54329/paperclip",
)
SLUG_REGEX = re.compile(r"^[a-z][a-z0-9]{1,15}$")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
AWS_ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "")  # used for SNS topic ARN construction
SES_INCOMING_HOST = f"inbound-smtp.{AWS_REGION}.amazonaws.com"


def _boto3():
    """Lazy-import boto3 so the module imports cleanly even if boto3 isn't installed."""
    import boto3  # type: ignore
    return boto3


async def _emit(
    conn: asyncpg.Connection, client_uuid: str, step: str, status: str,
    message: str | None = None, payload: dict | None = None,
) -> None:
    await conn.execute("""
        INSERT INTO client_onboarding_events (client_uuid, step_name, status, message, payload)
        VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
    """, client_uuid, step, status, message, json.dumps(payload or {}))


# ── Step implementations (each returns a payload dict on success, raises on failure) ──

async def step_validate(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    slug = inputs.get("slug", "")
    if not SLUG_REGEX.match(slug):
        raise ValueError(f"slug '{slug}' invalid (must be 2-16 lowercase alnum, start with letter)")
    existing = await conn.fetchval("SELECT 1 FROM client_configs WHERE slug = $1", slug)
    if existing:
        raise ValueError(f"slug '{slug}' already in use")
    if inputs.get("tier") not in ("standard", "compliance-hipaa"):
        raise ValueError(f"invalid tier {inputs.get('tier')}")
    return {"slug": slug, "tier": inputs["tier"]}


async def step_insert_client_config(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """The wizard creates the company + client_configs rows up front so we have a UUID
    to anchor events to. This is idempotent — UPSERT on company_id."""
    company_id = client_uuid
    name = inputs["display_name"]
    slug = inputs["slug"]
    tier = inputs["tier"]
    intake_email = f"intake@{slug}.sekuirtek.com"

    # Insert company first (FK target)
    await conn.execute("""
        INSERT INTO companies (id, name, status)
        VALUES ($1::uuid, $2, 'active')
        ON CONFLICT (id) DO NOTHING
    """, company_id, name)

    # Insert client_configs
    await conn.execute("""
        INSERT INTO client_configs (
            company_id, tier, slug,
            intake_email_address, onboarding_status, onboarding_started_at
        )
        VALUES ($1::uuid, $2, $3, $4, 'provisioning', now())
        ON CONFLICT (company_id) DO UPDATE
        SET tier = EXCLUDED.tier,
            slug = EXCLUDED.slug,
            intake_email_address = EXCLUDED.intake_email_address,
            onboarding_status = 'provisioning',
            onboarding_started_at = COALESCE(client_configs.onboarding_started_at, now())
    """, company_id, tier, slug, intake_email)
    return {"company_id": company_id, "slug": slug, "tier": tier, "intake_email": intake_email}


async def step_provision_vps(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Single-tenant phase: shared VPS — no provisioning needed, just record the assignment.
    Multi-tenant: invokes Phase 5.7 IaC (terraform apply with per-client variables)."""
    provider = inputs.get("vps_provider", "shared-srv1408380")
    if provider.startswith("shared"):
        return {"vps_provider": provider, "skipped": True,
                "reason": "single-tenant phase — shared VPS srv1408380, no provisioning needed"}
    # TODO Phase 5.7: shell out to `terraform apply -var "client_slug=$slug" -auto-approve`
    raise NotImplementedError(
        f"VPS provisioning for provider '{provider}' requires Phase 5.7 IaC (terraform). "
        f"Choose 'shared-srv1408380' in the wizard for now, or implement Phase 5.7."
    )


async def step_bootstrap_vps(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Single-tenant phase: shared VPS already bootstrapped. Multi-tenant: ansible-playbook bootstrap.yml."""
    provider = inputs.get("vps_provider", "shared-srv1408380")
    if provider.startswith("shared"):
        return {"skipped": True, "reason": "single-tenant — shared VPS already bootstrapped"}
    # TODO Phase 5.7: ansible-playbook -i <vps_ip>, bootstrap.yml
    raise NotImplementedError("VPS bootstrap requires Phase 5.7 IaC (ansible playbook).")


async def step_deploy_canonical_stack(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Single-tenant: shared VPS already runs the canonical container stack — no per-client deploy.
    Multi-tenant: Coolify API to create per-client app instances."""
    provider = inputs.get("vps_provider", "shared-srv1408380")
    if provider.startswith("shared"):
        return {"skipped": True,
                "reason": "single-tenant — canonical stack already running on shared VPS",
                "shared_containers": ["paperclip", "bedrock-proxy", "langfuse-langfuse-web-1",
                                       "paddleocr-service", "document-processor",
                                       "document-intake-webhook", "cfpa-watchdog",
                                       "cfpa-backup-runner", "openclaw-pgvector-db"]}
    # TODO Phase 5.7: Coolify API per-app create+deploy
    raise NotImplementedError("Canonical container stack deploy requires Coolify API integration.")


async def step_create_s3_bucket(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Real boto3: create_bucket + block public access + enable versioning + default encryption."""
    bucket = f"cfpa-doc-intake-{client_uuid}"
    boto3 = _boto3()
    s3 = boto3.client("s3", region_name=AWS_REGION)

    # create_bucket — idempotent if we already own it
    try:
        if AWS_REGION == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": AWS_REGION})
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass

    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    await conn.execute("UPDATE client_configs SET s3_intake_bucket = $1 WHERE company_id = $2::uuid",
                        bucket, client_uuid)
    return {"bucket": bucket, "region": AWS_REGION}


async def step_create_sns_topic(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Real boto3: SNS create_topic (idempotent) + set policy permitting SES + S3 to publish."""
    slug = inputs["slug"]
    bucket = f"cfpa-doc-intake-{client_uuid}"
    topic_name = f"cfpa-document-intake-events-{slug}"
    boto3 = _boto3()
    sns = boto3.client("sns", region_name=AWS_REGION)
    sts = boto3.client("sts", region_name=AWS_REGION)

    account_id = AWS_ACCOUNT_ID or sts.get_caller_identity()["Account"]
    resp = sns.create_topic(Name=topic_name)  # idempotent — returns existing if present
    topic_arn = resp["TopicArn"]

    # Allow SES + S3 to publish notifications to this topic
    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowS3BucketPublish",
                "Effect": "Allow",
                "Principal": {"Service": "s3.amazonaws.com"},
                "Action": "SNS:Publish",
                "Resource": topic_arn,
                "Condition": {
                    "ArnLike":      {"aws:SourceArn": f"arn:aws:s3:::{bucket}"},
                    "StringEquals": {"aws:SourceAccount": account_id},
                },
            },
            {
                "Sid": "AllowSESPublish",
                "Effect": "Allow",
                "Principal": {"Service": "ses.amazonaws.com"},
                "Action": "SNS:Publish",
                "Resource": topic_arn,
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                },
            },
        ],
    })
    sns.set_topic_attributes(TopicArn=topic_arn, AttributeName="Policy", AttributeValue=policy)

    await conn.execute("UPDATE client_configs SET sns_intake_topic_arn = $1 WHERE company_id = $2::uuid",
                        topic_arn, client_uuid)
    return {"topic_arn": topic_arn, "topic_name": topic_name, "account_id": account_id}


async def step_apply_s3_bucket_policy(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Real boto3: put_bucket_policy granting SES delivery to write into the intake bucket."""
    bucket = f"cfpa-doc-intake-{client_uuid}"
    boto3 = _boto3()
    s3 = boto3.client("s3", region_name=AWS_REGION)
    sts = boto3.client("sts", region_name=AWS_REGION)
    account_id = AWS_ACCOUNT_ID or sts.get_caller_identity()["Account"]

    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowSESPuts",
            "Effect": "Allow",
            "Principal": {"Service": "ses.amazonaws.com"},
            "Action": "s3:PutObject",
            "Resource": f"arn:aws:s3:::{bucket}/inbox/*",
            "Condition": {
                "StringEquals": {"aws:Referer": account_id},
            },
        }],
    })
    s3.put_bucket_policy(Bucket=bucket, Policy=policy)
    return {"bucket": bucket, "policy_applied": True}


async def step_create_ses_identity(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Real boto3: SES verify_domain_identity + verify_domain_dkim. Returns real DKIM tokens."""
    slug = inputs["slug"]
    domain = f"{slug}.sekuirtek.com"
    boto3 = _boto3()
    ses = boto3.client("ses", region_name=AWS_REGION)

    ses.verify_domain_identity(Domain=domain)  # idempotent
    dkim_resp = ses.verify_domain_dkim(Domain=domain)
    tokens = dkim_resp.get("DkimTokens", [])

    dkim_cnames = [
        {"name": f"{tok}._domainkey.{domain}",
         "value": f"{tok}.dkim.amazonses.com",
         "verified": False}
        for tok in tokens
    ]
    mx_record = {"host": slug, "value": SES_INCOMING_HOST, "verified": False}

    await conn.execute("""
        UPDATE client_configs
        SET dns_dkim_cnames = $1::jsonb,
            dns_mx_record = $2::jsonb,
            ses_identity_status = 'pending'
        WHERE company_id = $3::uuid
    """, json.dumps(dkim_cnames), json.dumps(mx_record), client_uuid)
    return {"domain": domain, "dkim_cnames": dkim_cnames, "mx_record": mx_record,
            "dkim_token_count": len(tokens)}


async def step_pause_for_dns(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Sets onboarding_status='awaiting_dns'. The orchestrator stops here.
    Operator clicks 'verify DNS' which kicks off poll_dns_until_resolved as a separate task."""
    await conn.execute("UPDATE client_configs SET onboarding_status = 'awaiting_dns' WHERE company_id = $1::uuid",
                        client_uuid)
    await _emit(conn, client_uuid, "pause_for_dns", "awaiting_operator",
                "Add the 4 DNS records in Namecheap, then click 'I've added the records'.",
                {})
    return {"awaiting": True}


async def step_create_ses_receipt_rule(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Real boto3: create_receipt_rule on the default rule set, S3 + SNS actions for intake@<slug>...
    Requires the receipt rule set to exist + be active. Most ops have a single 'default-rule-set'."""
    slug = inputs["slug"]
    rule_name = f"{slug}-sekuirtek-com-intake"
    bucket = f"cfpa-doc-intake-{client_uuid}"
    domain = f"{slug}.sekuirtek.com"
    boto3 = _boto3()
    ses = boto3.client("ses", region_name=AWS_REGION)

    # Pull the SNS topic ARN we just created
    topic_arn_row = await conn.fetchrow(
        "SELECT sns_intake_topic_arn FROM client_configs WHERE company_id = $1::uuid", client_uuid)
    topic_arn = topic_arn_row["sns_intake_topic_arn"] if topic_arn_row else None

    # Find or create the active rule set
    sets = ses.list_receipt_rule_sets()
    active_meta = None
    try:
        active_meta = ses.describe_active_receipt_rule_set().get("Metadata")
    except ses.exceptions.RuleSetDoesNotExistException:
        pass

    rule_set_name = active_meta["Name"] if active_meta else "default-rule-set"
    if not active_meta:
        try:
            ses.create_receipt_rule_set(RuleSetName=rule_set_name)
        except ses.exceptions.AlreadyExistsException:
            pass
        ses.set_active_receipt_rule_set(RuleSetName=rule_set_name)

    actions = [{"S3Action": {"BucketName": bucket, "ObjectKeyPrefix": "inbox/"}}]
    if topic_arn:
        actions[0]["S3Action"]["TopicArn"] = topic_arn

    rule = {
        "Name": rule_name,
        "Enabled": True,
        "Recipients": [f"intake@{domain}"],
        "Actions": actions,
        "ScanEnabled": True,
        "TlsPolicy": "Optional",
    }
    try:
        ses.create_receipt_rule(RuleSetName=rule_set_name, Rule=rule)
    except ses.exceptions.AlreadyExistsException:
        ses.update_receipt_rule(RuleSetName=rule_set_name, Rule=rule)

    await conn.execute("UPDATE client_configs SET ses_receipt_rule_name = $1 WHERE company_id = $2::uuid",
                        rule_name, client_uuid)
    return {"rule_set": rule_set_name, "rule_name": rule_name, "recipient": f"intake@{domain}"}


async def step_bootstrap_paperclipai(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Verify company is registered in paperclip, emit operator instructions for board API key issuance.

    The company row was already created in step_insert_client_config (direct SQL via the same
    paperclip DB), so paperclip already 'knows' about it. The remaining work — issuing a Board API
    key — is intentionally manual in paperclip's design (CLI auth challenge → operator UI approval).
    Automation can't bypass this without bypassing paperclip's auth model.
    """
    # Confirm company exists where paperclip expects it
    row = await conn.fetchrow("SELECT name, status FROM companies WHERE id = $1::uuid", client_uuid)
    if not row:
        raise RuntimeError(f"company {client_uuid} not found in paperclip DB — step_insert_client_config must run first")

    # Try the REST API health to confirm paperclip is up
    paperclip_url = os.environ.get("PAPERCLIP_INTERNAL_URL", "http://paperclip:8000")
    try:
        from urllib import request as _urlreq
        with _urlreq.urlopen(f"{paperclip_url}/api/health", timeout=5) as r:
            health = json.loads(r.read())
    except Exception as e:
        return {"company_name": row["name"], "status": row["status"],
                "warning": f"paperclip /api/health unreachable: {e}",
                "operator_action": "verify paperclip is running, then re-trigger or skip"}

    return {
        "company_name": row["name"],
        "company_status": row["status"],
        "paperclip_health": health,
        "operator_action": (
            f"Issue a Board API key for company {client_uuid} ({row['name']}): "
            f"run `paperclip cli auth login`, approve via the paperclipai UI when prompted, "
            f"then save the key to your secrets manager."
        ),
    }


async def step_install_addons(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Adds rows to operator_client_addons for each selected add-on (enabled=true)."""
    selected = inputs.get("addons", [])
    for key in selected:
        await conn.execute("""
            INSERT INTO operator_client_addons (company_id, addon_key, enabled, installed_at)
            VALUES ($1::uuid, $2, true, now())
            ON CONFLICT (company_id, addon_key) DO UPDATE
            SET enabled = true, installed_at = COALESCE(operator_client_addons.installed_at, now())
        """, client_uuid, key)
    # TODO: invoke per-addon install() functions (none defined yet)
    return {"installed": selected}


async def step_configure_backups(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    # TODO: configure cfpa-backup-runner to back this client up to S3 with per-client prefix
    await asyncio.sleep(0.2)
    return {"note": "STUB — real impl: register client in backup-runner config"}


async def step_send_welcome_email(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    """Real boto3: SES send_email to the client owner."""
    to_addr = inputs.get("client_owner_email") or ""
    if not to_addr:
        return {"skipped": True, "reason": "no client_owner_email provided in wizard inputs"}

    sender = os.environ.get("WELCOME_EMAIL_FROM", "noreply@cfpa.sekuirtek.com")
    slug = inputs["slug"]
    intake_email = f"intake@{slug}.sekuirtek.com"
    subject = f"Welcome to CFPA — your client portal is ready"
    body_text = (
        f"Hi,\n\n"
        f"Your CFPA platform instance is provisioned and active.\n\n"
        f"Intake email: {intake_email}\n"
        f"Forward documents to that address and they'll be processed automatically.\n\n"
        f"Operator dashboard: https://costs.cfpa.sekuirtek.com/client/{client_uuid}\n\n"
        f"— CFPA team\n"
    )

    boto3 = _boto3()
    ses = boto3.client("ses", region_name=AWS_REGION)
    resp = ses.send_email(
        Source=sender,
        Destination={"ToAddresses": [to_addr]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
        },
    )
    return {"to": to_addr, "from": sender, "message_id": resp.get("MessageId")}


async def step_finalize(conn: asyncpg.Connection, client_uuid: str, inputs: dict) -> dict:
    await conn.execute("""
        UPDATE client_configs
        SET onboarding_status = 'active',
            onboarding_completed_at = now()
        WHERE company_id = $1::uuid
    """, client_uuid)
    return {"finalized": True}


# Step registry: ordered. Each entry is (key, callable, label).
ORCHESTRATOR_STEPS: list[tuple[str, Callable[[asyncpg.Connection, str, dict], Awaitable[dict]], str]] = [
    ("validate",                step_validate,                  "Validate inputs"),
    ("insert_client_config",    step_insert_client_config,      "Create company + client_config"),
    ("provision_vps",           step_provision_vps,             "Provision VPS (Phase 5.7 IaC)"),
    ("bootstrap_vps",           step_bootstrap_vps,             "Bootstrap VPS (Ansible)"),
    ("deploy_canonical_stack",  step_deploy_canonical_stack,    "Deploy canonical container stack"),
    ("create_s3_bucket",        step_create_s3_bucket,          "Create S3 intake bucket"),
    ("create_sns_topic",        step_create_sns_topic,          "Create SNS topic"),
    ("apply_s3_bucket_policy",  step_apply_s3_bucket_policy,    "Apply S3 bucket policy"),
    ("create_ses_identity",     step_create_ses_identity,       "Create SES domain identity"),
    ("pause_for_dns",           step_pause_for_dns,             "PAUSE: operator adds DNS records"),
    # The next steps run after operator clicks "verify DNS" + DNS polls succeed
    ("create_ses_receipt_rule", step_create_ses_receipt_rule,   "Create SES receipt rule"),
    ("bootstrap_paperclipai",   step_bootstrap_paperclipai,     "Bootstrap paperclipai company"),
    ("install_addons",          step_install_addons,            "Install selected add-ons"),
    ("configure_backups",       step_configure_backups,         "Configure backups"),
    ("send_welcome_email",      step_send_welcome_email,        "Send welcome email"),
    ("finalize",                step_finalize,                  "Finalize"),
]


async def run_orchestrator(client_uuid: str, inputs: dict, start_from: str | None = None) -> None:
    """Sequential step runner. Stops on the first awaiting_operator status or the first failure.

    The first two steps (validate + insert_client_config) run without event emission because
    client_onboarding_events has a FK on client_configs.company_id — that row doesn't exist yet.
    We bootstrap the row first, then emit events for all subsequent steps.
    """
    conn = await asyncpg.connect(DB_URL)
    try:
        # Bootstrap phase: run validate + insert_client_config before the event loop.
        # Emit a single "validate.started/completed" pair only AFTER insert_client_config
        # has created the FK-target row. On retry (start_from is set), skip bootstrap.
        if start_from is None:
            try:
                validate_payload = await step_validate(conn, client_uuid, inputs)
            except Exception as e:
                # No row exists yet — log to operator_audit_log instead of events table
                await conn.execute(
                    "INSERT INTO operator_audit_log (operator_email, action, details) "
                    "VALUES ($1, 'wizard.validate_failed', $2::jsonb)",
                    os.environ.get("OPERATOR_EMAIL", "operator"),
                    json.dumps({"client_uuid": client_uuid, "error": str(e)}),
                )
                return
            config_payload = await step_insert_client_config(conn, client_uuid, inputs)
            # Row now exists — safe to emit both bootstrap steps as completed
            await _emit(conn, client_uuid, "validate", "completed", "Validate inputs", validate_payload)
            await _emit(conn, client_uuid, "insert_client_config", "completed",
                        "Create company + client_config", config_payload)

        skip = start_from is not None
        for key, fn, label in ORCHESTRATOR_STEPS:
            if key in ("validate", "insert_client_config"):
                continue  # already handled above
            if skip:
                if key == start_from:
                    skip = False
                else:
                    continue
            await _emit(conn, client_uuid, key, "started", label, {})
            try:
                payload = await fn(conn, client_uuid, inputs)
            except Exception as e:
                await _emit(conn, client_uuid, key, "failed", str(e), {"error": str(e)})
                await conn.execute(
                    "UPDATE client_configs SET onboarding_status = 'failed' WHERE company_id = $1::uuid",
                    client_uuid)
                return
            # The pause step emits awaiting_operator inside its body; everything else completes
            if key == "pause_for_dns":
                return
            await _emit(conn, client_uuid, key, "completed", None, payload)
    finally:
        await conn.close()


async def resume_after_dns(client_uuid: str, inputs: dict) -> None:
    """Called when the operator clicks 'verify DNS'. Polls DNS via health_poller.check_dns,
    waits up to ~10 min, then resumes from create_ses_receipt_rule."""
    import health_poller
    conn = await asyncpg.connect(DB_URL)
    try:
        config = await conn.fetchrow("""
            SELECT slug, dns_dkim_cnames, dns_mx_record
            FROM client_configs WHERE company_id = $1::uuid
        """, client_uuid)
        if not config:
            return
        slug = config["slug"]
        dkim = config["dns_dkim_cnames"]
        mx = config["dns_mx_record"]
        # asyncpg may return JSONB as string
        if isinstance(dkim, str):
            dkim = json.loads(dkim)
        if isinstance(mx, str):
            mx = json.loads(mx)

        await _emit(conn, client_uuid, "verify_dns", "in_progress", "Polling DNS records...", {})
        max_attempts = 20  # 20 × 30s = 10 min
        for attempt in range(1, max_attempts + 1):
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, health_poller.check_dns, slug, dkim, mx)
            if result.get("ok"):
                await _emit(conn, client_uuid, "verify_dns", "completed",
                            f"All DNS records resolve (attempt {attempt}).", result)
                break
            await _emit(conn, client_uuid, "verify_dns", "in_progress",
                        f"Attempt {attempt}/{max_attempts} — not all records resolved yet.",
                        {"unresolved": [r for r in result.get("records", []) if not r.get("match")]})
            await asyncio.sleep(30)
        else:
            await _emit(conn, client_uuid, "verify_dns", "failed",
                        "Timed out waiting for DNS to propagate (10 min). Check Namecheap entries and retry.", {})
            await conn.execute("UPDATE client_configs SET onboarding_status = 'failed' WHERE company_id = $1::uuid",
                                client_uuid)
            return
    finally:
        await conn.close()
    # Resume orchestrator from the step after pause_for_dns
    await run_orchestrator(client_uuid, inputs, start_from="create_ses_receipt_rule")
