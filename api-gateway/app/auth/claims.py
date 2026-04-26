import base64
import hashlib
import hmac
import json
import os


def _secret() -> bytes:
    secret = os.environ.get("API_GATEWAY_SIGNING_SECRET", "")
    if not secret:
        raise RuntimeError("API_GATEWAY_SIGNING_SECRET is not set")
    return secret.encode()


def build_claims_headers(
    caller_type: str,
    app_id: str,
    capabilities: list[str],
    budget_pool: str,
) -> dict[str, str]:
    caps_b64 = base64.b64encode(json.dumps(capabilities).encode()).decode()
    canonical = f"{caller_type}|{app_id}|{caps_b64}|{budget_pool}"
    sig = hmac.new(_secret(), canonical.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Caller-Type": caller_type,
        "X-App-Id": app_id,
        "X-Capabilities": caps_b64,
        "X-Budget-Pool": budget_pool,
        "X-Claims-Signature": sig,
    }


def verify_claims_headers(headers: dict[str, str]) -> bool:
    try:
        caller_type = headers.get("x-caller-type") or headers.get("X-Caller-Type", "")
        app_id = headers.get("x-app-id") or headers.get("X-App-Id", "")
        caps_b64 = headers.get("x-capabilities") or headers.get("X-Capabilities", "")
        budget_pool = headers.get("x-budget-pool") or headers.get("X-Budget-Pool", "")
        provided_sig = headers.get("x-claims-signature") or headers.get("X-Claims-Signature", "")
        if not all([caller_type, app_id, caps_b64, budget_pool, provided_sig]):
            return False
        canonical = f"{caller_type}|{app_id}|{caps_b64}|{budget_pool}"
        expected = hmac.new(_secret(), canonical.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, provided_sig)
    except Exception:
        return False
