#!/usr/bin/env python3
"""
Phase 12 — S3 + SNS wiring script.

Run ONCE after the S3 bucket cfpa-doc-intake-bd80728d has been created with
admin credentials. This script uses the backup-runner IAM credentials (which
must already have been extended with PutObject + ListBucket on the bucket).

Steps performed:
  1. Create SNS topic: cfpa-document-intake-events
  2. Set SNS topic policy to allow S3 to publish to it
  3. Configure S3 PUT event notification → SNS topic
  4. Subscribe https://paperclipai.cfpa.sekuirtek.com/api/webhooks/document-intake
     to the SNS topic (HTTP/HTTPS subscription)

Note: The HTTPS subscription will trigger a SubscriptionConfirmation POST to
the webhook URL. The document-intake-webhook sidecar auto-confirms by fetching
the SubscribeURL in the message. Watch sidecar logs for confirmation:
  docker logs -f document-intake-webhook
"""

import boto3
import json
import os
import sys

AWS_KEY    = os.environ['AWS_ACCESS_KEY_ID']
AWS_SECRET = os.environ['AWS_SECRET_ACCESS_KEY']
REGION     = 'us-east-2'
ACCOUNT_ID = '678051794702'
BUCKET     = 'cfpa-doc-intake-bd80728d'
TOPIC_NAME = 'cfpa-document-intake-events'
WEBHOOK_URL = 'https://paperclipai.cfpa.sekuirtek.com/api/webhooks/document-intake'

session = boto3.Session(
    aws_access_key_id=AWS_KEY,
    aws_secret_access_key=AWS_SECRET,
    region_name=REGION,
)
sns = session.client('sns')
s3  = session.client('s3')


# ── 1. Create SNS topic ───────────────────────────────────────────────────────
print(f"[1/4] Creating SNS topic: {TOPIC_NAME}")
topic = sns.create_topic(Name=TOPIC_NAME)
topic_arn = topic['TopicArn']
print(f"      Topic ARN: {topic_arn}")


# ── 2. Set SNS topic policy (allow S3 bucket to publish) ─────────────────────
print("[2/4] Setting SNS topic policy for S3 publish permission")
topic_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowS3BucketPublish",
            "Effect": "Allow",
            "Principal": {"Service": "s3.amazonaws.com"},
            "Action": "SNS:Publish",
            "Resource": topic_arn,
            "Condition": {
                "ArnLike": {
                    "aws:SourceArn": f"arn:aws:s3:::{BUCKET}"
                }
            },
        }
    ],
}
sns.set_topic_attributes(
    TopicArn=topic_arn,
    AttributeName='Policy',
    AttributeValue=json.dumps(topic_policy),
)
print("      SNS topic policy set")


# ── 3. Configure S3 PUT event notification → SNS ─────────────────────────────
print("[3/4] Configuring S3 bucket notification (PUT → SNS)")
s3.put_bucket_notification_configuration(
    Bucket=BUCKET,
    NotificationConfiguration={
        'TopicConfigurations': [
            {
                'Id': 'document-intake-put-events',
                'TopicArn': topic_arn,
                'Events': ['s3:ObjectCreated:*'],
            }
        ]
    },
)
print("      S3 notification configuration applied")


# ── 4. Subscribe webhook to SNS topic ─────────────────────────────────────────
print(f"[4/4] Subscribing webhook to SNS topic: {WEBHOOK_URL}")
sub = sns.subscribe(
    TopicArn=topic_arn,
    Protocol='https',
    Endpoint=WEBHOOK_URL,
    ReturnSubscriptionArn=True,
    # Do NOT set RawMessageDelivery=True — we need the SNS envelope for
    # signature verification and SubscriptionConfirmation handling.
)
sub_arn = sub['SubscriptionArn']
print(f"      Subscription ARN: {sub_arn}")
print()
print("Done. Watch sidecar logs for SubscriptionConfirmation auto-confirm:")
print("  docker logs -f document-intake-webhook")
print()
print("If confirmation fails, manually visit the SubscribeURL from the SNS")
print("console or re-run the subscribe step once the sidecar is reachable.")
