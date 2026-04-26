"""Middleware that verifies HMAC-signed gateway claims on all /intent* requests.

The api-gateway signs X-Caller-Type, X-App-Id, X-Capabilities, X-Budget-Pool
with HMAC-SHA256 and sends the signature as X-Claims-Signature. Any request
that reaches /intent* without a valid signature is rejected with 401.

Set API_GATEWAY_SIGNING_SECRET to the shared secret (same value as in api-gateway).
Set BYPASS_CLAIMS_CHECK=1 in development/testing when running paperclipai directly
without going through api-gateway.
"""

import hashlib
import hmac
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def _should_bypass() -> bool:
    return os.environ.get("BYPASS_CLAIMS_CHECK", "").lower() in ("1", "true", "yes")


def _secret() -> bytes | None:
    secret = os.environ.get("API_GATEWAY_SIGNING_SECRET", "")
    return secret.encode() if secret else None


def _verify(headers) -> bool:
    secret = _secret()
    if secret is None:
        return False
    try:
        caller_type = headers.get("x-caller-type", "")
        app_id = headers.get("x-app-id", "")
        caps_b64 = headers.get("x-capabilities", "")
        budget_pool = headers.get("x-budget-pool", "")
        provided_sig = headers.get("x-claims-signature", "")
        if not all([caller_type, app_id, caps_b64, budget_pool, provided_sig]):
            return False
        canonical = f"{caller_type}|{app_id}|{caps_b64}|{budget_pool}"
        expected = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, provided_sig)
    except Exception:
        return False


class ClaimsVerificationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/intent"):
            if _should_bypass():
                return await call_next(request)
            if not _verify(request.headers):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "missing or invalid gateway claims signature"},
                )
            # Expose verified claims on request state for downstream handlers.
            request.state.caller_type = request.headers.get("x-caller-type", "")
            request.state.app_id = request.headers.get("x-app-id", "")
        return await call_next(request)
