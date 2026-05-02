#!/usr/bin/env python3
"""
fetch_bedrock_model_ids.py — print live Anthropic Claude model IDs + pricing from Bedrock.

Requires IAM SigV4 credentials (NOT the bedrock-proxy Bearer key):
  AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY
  with permissions: bedrock:ListFoundationModels, bedrock:GetFoundationModel,
                    pricing:GetProducts, pricing:DescribeServices  (if --pricing)

Suggested IAM user: cfpa-deploy-script-runner
Inline policy:
  {
    "Effect": "Allow",
    "Action": [
      "bedrock:ListFoundationModels",
      "bedrock:GetFoundationModel",
      "pricing:GetProducts",
      "pricing:DescribeServices"
    ],
    "Resource": "*"
  }

Usage:
  python3 scripts/fetch_bedrock_model_ids.py [--region us-east-2] [--pricing]
"""
import argparse
import json
import sys

TARGET_MODELS = ["Opus 4.7", "Sonnet 4.6", "Haiku 4.5"]

# Friendly name → paperclipai short alias (no date stamp)
FRIENDLY_TO_ALIAS = {
    "Opus 4.7":   "claude-opus-4-7",
    "Sonnet 4.6": "claude-sonnet-4-6",
    "Haiku 4.5":  "claude-haiku-4-5",
}


def _boto3_client(service: str, region: str):
    try:
        import boto3
    except ImportError:
        print("ERROR: boto3 not installed. Run: pip install boto3", file=sys.stderr)
        sys.exit(1)
    return boto3.client(service, region_name=region)


def _handle_auth_error(exc) -> None:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", str(exc))
    if "NoCredentials" in type(exc).__name__ or not code:
        print(
            "ERROR: No AWS credentials found.\n"
            "  Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, "
            "or configure ~/.aws/credentials.\n\n"
            "  Suggested IAM user: cfpa-deploy-script-runner\n"
            "  Required actions: bedrock:ListFoundationModels, bedrock:GetFoundationModel,\n"
            "                    pricing:GetProducts, pricing:DescribeServices",
            file=sys.stderr,
        )
    elif code in ("AccessDenied", "AccessDeniedException"):
        print(
            f"ERROR: Access denied ({code}).\n"
            "  The IAM identity lacks required bedrock: or pricing: permissions.\n"
            "  Add inline policy granting: bedrock:ListFoundationModels, "
            "bedrock:GetFoundationModel,\n"
            "  pricing:GetProducts, pricing:DescribeServices",
            file=sys.stderr,
        )
    else:
        print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(1)


def find_anthropic_models(region: str) -> list[dict]:
    """Return list of dicts for each matching model in the Bedrock catalog."""
    try:
        from botocore.exceptions import ClientError, NoCredentialsError
        client = _boto3_client("bedrock", region)
        resp = client.list_foundation_models()
    except Exception as exc:
        _handle_auth_error(exc)

    results = []
    for m in resp.get("modelSummaries", []):
        if m.get("providerName") != "Anthropic":
            continue
        model_name = m.get("modelName", "")
        target = next((t for t in TARGET_MODELS if t.lower() in model_name.lower()), None)
        if not target:
            continue
        lifecycle = m.get("modelLifecycle", {})
        results.append(
            {
                "modelId":     m["modelId"],
                "modelName":   model_name,
                "target":      target,
                "status":      lifecycle.get("status", "UNKNOWN"),
                "lifecycle":   lifecycle,
            }
        )
    return results


def fetch_pricing(region: str) -> dict[str, dict[str, float]]:
    """
    Return {bedrock_model_id: {"input": usd_per_1m, "output": usd_per_1m}}.
    AWS Pricing API only operates from us-east-1 regardless of target region.
    AWS lists rates per 1K tokens; we convert to per 1M for consistency with
    the proxy's BEDROCK_PRICING dict.
    """
    try:
        from botocore.exceptions import ClientError, NoCredentialsError
        client = _boto3_client("pricing", "us-east-1")
        paginator = client.get_paginator("get_products")
        pages = paginator.paginate(
            ServiceCode="AmazonBedrock",
            Filters=[{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region}],
        )
        products = []
        for page in pages:
            for item in page.get("PriceList", []):
                products.append(json.loads(item) if isinstance(item, str) else item)
    except Exception as exc:
        print(f"  [pricing] Warning: {exc}", file=sys.stderr)
        return {}

    pricing: dict[str, dict[str, float]] = {}
    for p in products:
        attrs = p.get("product", {}).get("attributes", {})
        model_id   = attrs.get("modelId", "")
        token_type = attrs.get("tokenType", "").lower()
        if not model_id or token_type not in ("input", "output"):
            continue

        terms = p.get("terms", {}).get("OnDemand", {})
        for _, term in terms.items():
            for _, pd in term.get("priceDimensions", {}).items():
                raw_rate = pd.get("pricePerUnit", {}).get("USD", "")
                try:
                    rate_per_1k = float(raw_rate)
                except (ValueError, TypeError):
                    continue
                if rate_per_1k <= 0:
                    continue
                # Convert from per-1K to per-1M
                pricing.setdefault(model_id, {})[token_type] = rate_per_1k * 1000

    return pricing


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--region", default="us-east-2", help="AWS region to query (default: us-east-2)"
    )
    parser.add_argument(
        "--pricing", action="store_true", help="Also query AWS Pricing API for per-token rates"
    )
    args = parser.parse_args()

    print(f"Fetching Anthropic model catalog from Bedrock region={args.region} ...\n")
    models = find_anthropic_models(args.region)

    if not models:
        print(f"ERROR: No Anthropic Claude 4.x models found in {args.region}.")
        print(
            "They may not be available in this region yet. "
            "Try --region us-east-1 or us-west-2 to check."
        )
        sys.exit(1)

    active   = [m for m in models if m["status"] == "ACTIVE"]
    inactive = [m for m in models if m["status"] != "ACTIVE"]

    print(f"Results: {len(active)} ACTIVE  /  {len(inactive)} non-ACTIVE\n")
    for m in sorted(models, key=lambda x: x["target"]):
        marker = "✓" if m["status"] == "ACTIVE" else "✗"
        print(f"  {marker}  {m['status']:12s}  {m['modelId']:60s}  ({m['modelName']})")
    if inactive:
        print(f"\n  NOTE: {len(inactive)} non-ACTIVE model(s) not included in output dicts.")

    # Validate: warn on multiple ACTIVE per target
    by_target: dict[str, list[dict]] = {}
    for m in active:
        by_target.setdefault(m["target"], []).append(m)

    warn_multiple = False
    for target, ms in by_target.items():
        if len(ms) > 1:
            warn_multiple = True
            print(f"\nWARNING: Multiple ACTIVE models for {target} — manual disambiguation required:")
            for m in ms:
                print(f"    {m['modelId']}")

    # Pricing
    pricing_data: dict[str, dict[str, float]] = {}
    if args.pricing:
        print(f"\nFetching pricing (Pricing API → us-east-1, regionCode={args.region}) ...")
        pricing_data = fetch_pricing(args.region)
        if pricing_data:
            print(f"  Received pricing for {len(pricing_data)} product(s).")
        else:
            print("  No pricing data returned — all BEDROCK_PRICING values will be UNVERIFIED.")

    # ── Output dicts ──────────────────────────────────────────────────────────
    print("\n" + "─" * 72)
    print("ANTHROPIC_TO_BEDROCK  (ready to paste into proxy.py):\n")

    missing_targets = [t for t in TARGET_MODELS if t not in by_target]
    if missing_targets:
        print(f"  # ⚠ MISSING in {args.region}: {', '.join(missing_targets)}")
        print(f"  # Stop and verify regional availability before deploying.\n")

    import re

    # Check for INFERENCE_PROFILE-only models and use us. prefix for those.
    # All Claude 4.x models in Bedrock currently set inferenceTypesSupported=
    # ["INFERENCE_PROFILE"], meaning bare base model IDs fail for InvokeModel.
    # The system-managed cross-region profile IDs use a regional prefix:
    #   us. for US regions, eu. for EU, ap. for Asia-Pacific.
    region_prefix = "us" if args.region.startswith("us-") else \
                    "eu" if args.region.startswith("eu-") else \
                    "ap" if args.region.startswith("ap-") else None

    inf_profile_models = set()
    for target in TARGET_MODELS:
        ms = by_target.get(target, [])
        for m in ms:
            inf_types = m.get("lifecycle", {})  # lifecycle used as proxy; need re-fetch
            # We'll flag this based on the known findings
            pass

    # Re-fetch inference types from GetFoundationModel
    try:
        bedrock_client = _boto3_client("bedrock", args.region)
        for target in TARGET_MODELS:
            ms = by_target.get(target, [])
            for m in ms:
                detail = bedrock_client.get_foundation_model(modelIdentifier=m["modelId"])
                inf_types = detail.get("modelDetails", {}).get("inferenceTypesSupported", [])
                m["inferenceTypesSupported"] = inf_types
                if inf_types == ["INFERENCE_PROFILE"]:
                    inf_profile_models.add(m["modelId"])
    except Exception as exc:
        print(f"  [warn] Could not fetch inferenceTypesSupported: {exc}", file=sys.stderr)

    if inf_profile_models:
        print(
            f"\n⚠  INFERENCE_PROFILE only: {len(inf_profile_models)} model(s) cannot be called\n"
            f"   via direct InvokeModel. Use the cross-region inference profile IDs\n"
            f"   ({region_prefix}.anthropic.xxx) instead of bare base model IDs.\n"
        )

    def _profile_id(model_id: str) -> str:
        """Return us./eu./ap. prefixed profile ID if INFERENCE_PROFILE only."""
        if model_id in inf_profile_models and region_prefix:
            return f"{region_prefix}.{model_id}"
        return model_id

    model_id_map: dict[str, str] = {}  # alias → invoke_id
    for target in TARGET_MODELS:
        ms = by_target.get(target, [])
        if not ms:
            print(f'    # "{FRIENDLY_TO_ALIAS[target]}": ???,  # NOT FOUND in {args.region}')
            continue
        raw_id   = ms[0]["modelId"]
        invoke_id = _profile_id(raw_id)
        model_id_map[FRIENDLY_TO_ALIAS[target]] = invoke_id
        alias = FRIENDLY_TO_ALIAS[target]
        date_match = re.search(r"(\d{8})", raw_id)
        date_stamp = date_match.group(1) if date_match else None

        if date_stamp:
            dated_key = f"{alias}-{date_stamp}"
            print(f'    "{alias}":  "{invoke_id}",')
            print(f'    "{dated_key}":  "{invoke_id}",')
        else:
            print(f'    "{alias}":  "{invoke_id}",')

    print("\n" + "─" * 72)
    print("BEDROCK_PRICING  (ready to paste into proxy.py):\n")
    print("  # Keys use inference profile IDs to match ANTHROPIC_TO_BEDROCK values.\n")

    for target in TARGET_MODELS:
        ms = by_target.get(target, [])
        if not ms:
            continue
        raw_id    = ms[0]["modelId"]
        invoke_id = _profile_id(raw_id)
        p = pricing_data.get(raw_id, {})
        inp = p.get("input")
        out = p.get("output")

        # Sanity check
        if inp is not None and out is not None:
            if inp <= 0 or out <= 0 or inp > 1000 or out > 1000:
                print(
                    f'    # WARNING: Pricing API returned suspicious values for {model_id}:'
                    f' input={inp}, output={out}. NOT written — verify manually.',
                    file=sys.stderr,
                )
                inp = out = None

        if inp is not None and out is not None:
            print(f'    "{invoke_id}": {{"input": {inp:.3f}, "output": {out:.3f}}},  # verified from AWS Pricing API')
        else:
            print(f'    "{invoke_id}": {{"input": ???, "output": ???}},  # UNVERIFIED — check https://aws.amazon.com/bedrock/pricing/')

    if warn_multiple:
        print("\n⚠  Multiple ACTIVE model IDs detected — resolve before patching proxy.py.")
        sys.exit(2)

    print(
        "\nDone. Copy the dicts above into proxy.py "
        "(ANTHROPIC_TO_BEDROCK and BEDROCK_PRICING)."
    )


if __name__ == "__main__":
    main()
