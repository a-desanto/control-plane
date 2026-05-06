#!/usr/bin/env python3
"""
Phase 12 Stage 1.5 — SES receipt rule + S3 bucket policy.

Requires AWS admin credentials:
  export AWS_ADMIN_ACCESS_KEY_ID=<key>
  export AWS_ADMIN_SECRET_ACCESS_KEY=<secret>

What this does:
  1. Adds a bucket policy statement to cfpa-doc-intake-bd80728d
     allowing ses.amazonaws.com to PutObject under inbox/*
  2. Creates (or re-uses) the cfpa-inbound SES receipt rule set
  3. Creates (or updates) the cfpa-sekuirtek-com-intake receipt rule:
       - Recipients: cfpa.sekuirtek.com
       - Action: S3Action → cfpa-doc-intake-bd80728d / inbox/
     (S3 event notification already wired → SNS → webhook, so no
      separate SES SNS action needed)
  4. Sets cfpa-inbound as the active receipt rule set
"""

import boto3
import json
import os
import sys
from botocore.exceptions import ClientError

REGION     = 'us-east-2'
ACCOUNT_ID = '678051794702'
BUCKET     = 'cfpa-doc-intake-bd80728d'
DOMAIN     = 'cfpa.sekuirtek.com'
RULE_SET   = 'cfpa-inbound'
RULE_NAME  = 'cfpa-sekuirtek-com-intake'
INBOX_PFX  = 'inbox/'

ADMIN_KEY    = os.environ.get('AWS_ADMIN_ACCESS_KEY_ID')
ADMIN_SECRET = os.environ.get('AWS_ADMIN_SECRET_ACCESS_KEY')

if not ADMIN_KEY or not ADMIN_SECRET:
    print("ERROR: Set AWS_ADMIN_ACCESS_KEY_ID and AWS_ADMIN_SECRET_ACCESS_KEY")
    sys.exit(1)

session = boto3.Session(
    aws_access_key_id=ADMIN_KEY,
    aws_secret_access_key=ADMIN_SECRET,
    region_name=REGION,
)
s3  = session.client('s3')
ses = session.client('ses')


# ── 1. S3 bucket policy — allow SES to write into inbox/ ─────────────────────
print(f"[1/4] Updating S3 bucket policy: allow ses.amazonaws.com → {BUCKET}/inbox/*")

ses_policy_sid = 'AllowSESInboundPuts'
bucket_arn = f'arn:aws:s3:::{BUCKET}'
inbox_arn  = f'{bucket_arn}/{INBOX_PFX}*'

ses_statement = {
    "Sid": ses_policy_sid,
    "Effect": "Allow",
    "Principal": {"Service": "ses.amazonaws.com"},
    "Action": "s3:PutObject",
    "Resource": inbox_arn,
    "Condition": {
        "StringEquals": {"aws:Referer": ACCOUNT_ID}
    }
}

try:
    existing = json.loads(s3.get_bucket_policy(Bucket=BUCKET)['Policy'])
except ClientError as e:
    if e.response['Error']['Code'] == 'NoSuchBucketPolicy':
        existing = {"Version": "2012-10-17", "Statement": []}
    else:
        raise

# Remove any stale version of the same SID, then append
existing['Statement'] = [
    s for s in existing['Statement'] if s.get('Sid') != ses_policy_sid
]
existing['Statement'].append(ses_statement)

s3.put_bucket_policy(Bucket=BUCKET, Policy=json.dumps(existing))
print(f"      Bucket policy updated — SID '{ses_policy_sid}' set")


# ── 2. Create receipt rule set (idempotent) ───────────────────────────────────
print(f"[2/4] Ensuring SES receipt rule set: {RULE_SET}")

existing_sets = [
    rs['Name'] for rs in ses.list_receipt_rule_sets().get('RuleSets', [])
]
if RULE_SET not in existing_sets:
    ses.create_receipt_rule_set(RuleSetName=RULE_SET)
    print(f"      Created rule set '{RULE_SET}'")
else:
    print(f"      Rule set '{RULE_SET}' already exists")


# ── 3. Create (or update) receipt rule ────────────────────────────────────────
print(f"[3/4] Upserting SES receipt rule: {RULE_NAME}")

rule = {
    'Name': RULE_NAME,
    'Enabled': True,
    'TlsPolicy': 'Optional',
    'Recipients': [DOMAIN],   # matches *@cfpa.sekuirtek.com
    'Actions': [
        {
            'S3Action': {
                'BucketName': BUCKET,
                'ObjectKeyPrefix': INBOX_PFX,
                # No separate KmsKeyArn — SSE-S3 on the bucket handles encryption
            }
        }
    ],
    'ScanEnabled': False,
}

# Check if rule already exists in the set
existing_rules = ses.describe_receipt_rule_set(RuleSetName=RULE_SET).get('Rules', [])
rule_names = [r['Name'] for r in existing_rules]

if RULE_NAME in rule_names:
    ses.update_receipt_rule(RuleSetName=RULE_SET, Rule=rule)
    print(f"      Updated existing rule '{RULE_NAME}'")
else:
    ses.create_receipt_rule(RuleSetName=RULE_SET, Rule=rule)
    print(f"      Created rule '{RULE_NAME}'")


# ── 4. Set cfpa-inbound as the active rule set ────────────────────────────────
print(f"[4/4] Setting '{RULE_SET}' as the active receipt rule set")

try:
    active = ses.describe_active_receipt_rule_set()
    active_name = active.get('Metadata', {}).get('Name')
except ClientError:
    active_name = None

if active_name != RULE_SET:
    ses.set_active_receipt_rule_set(RuleSetName=RULE_SET)
    print(f"      Active rule set → '{RULE_SET}'")
else:
    print(f"      '{RULE_SET}' is already active")

print()
print("SES receipt rule setup complete.")
print(f"  Domain:  {DOMAIN}")
print(f"  Bucket:  s3://{BUCKET}/{INBOX_PFX}")
print(f"  Rule:    {RULE_SET}/{RULE_NAME}")
print()
print("Test: send an email to intake@cfpa.sekuirtek.com and watch")
print("  docker logs -f document-intake-webhook")
