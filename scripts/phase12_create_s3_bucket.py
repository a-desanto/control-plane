#!/usr/bin/env python3
"""
Phase 12 — Create S3 drop bucket for document intake.

Uses backup-runner-srv1408380 credentials. IAM policy was extended manually
via AWS console to include s3:CreateBucket + bucket config actions scoped to
cfpa-doc-intake-* and sns:CreateTopic scoped to cfpa-document-intake-*.
"""

import boto3
import json
import os
import sys
from botocore.exceptions import ClientError

REGION     = 'us-east-2'
BUCKET     = 'cfpa-doc-intake-bd80728d'
IAM_USER   = 'backup-runner-srv1408380'

AWS_KEY    = os.environ['AWS_ACCESS_KEY_ID']
AWS_SECRET = os.environ['AWS_SECRET_ACCESS_KEY']

session = boto3.Session(
    aws_access_key_id=AWS_KEY,
    aws_secret_access_key=AWS_SECRET,
    region_name=REGION,
)
s3 = session.client('s3')


# ── 1. Create bucket ───────────────────────────────────────────────────────────
print(f"[1/3] Creating bucket: {BUCKET}")
try:
    s3.create_bucket(
        Bucket=BUCKET,
        CreateBucketConfiguration={'LocationConstraint': REGION},
    )
    print(f"      Created: s3://{BUCKET}")
except ClientError as e:
    if e.response['Error']['Code'] in ('BucketAlreadyOwnedByYou', 'BucketAlreadyExists'):
        print(f"      Already exists — continuing")
    else:
        raise


# ── 2. Block public access, versioning, encryption ────────────────────────────
print("[2/3] Configuring bucket: public-access-block, versioning, SSE-S3")
s3.put_public_access_block(
    Bucket=BUCKET,
    PublicAccessBlockConfiguration={
        'BlockPublicAcls': True,
        'IgnorePublicAcls': True,
        'BlockPublicPolicy': True,
        'RestrictPublicBuckets': True,
    },
)

s3.put_bucket_versioning(
    Bucket=BUCKET,
    VersioningConfiguration={'Status': 'Enabled'},
)
print("      Versioning enabled")

s3.put_bucket_encryption(
    Bucket=BUCKET,
    ServerSideEncryptionConfiguration={
        'Rules': [{
            'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'},
            'BucketKeyEnabled': True,
        }]
    },
)
print("      SSE-S3 encryption enabled")


# ── 3. Smoke test: upload + list + delete ─────────────────────────────────────
print("[3/3] Smoke test: upload, list, delete test object")
TEST_KEY = 'test/iam-smoke-test.pdf'
s3.put_object(Bucket=BUCKET, Key=TEST_KEY, Body=b'%PDF-1.4 smoke-test')
print(f"      PutObject: s3://{BUCKET}/{TEST_KEY} OK")

objs = s3.list_objects_v2(Bucket=BUCKET, Prefix='test/')
found = any(o['Key'] == TEST_KEY for o in objs.get('Contents', []))
print(f"      ListBucket: {'found' if found else 'NOT FOUND'}")

s3.delete_object(Bucket=BUCKET, Key=TEST_KEY)
print(f"      DeleteObject: cleaned up")
print()
print("Bucket setup complete. Run phase12_setup_sns.py next to wire SNS.")
