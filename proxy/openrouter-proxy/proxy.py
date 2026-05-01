#!/usr/bin/env python3
"""
Thin proxy: Anthropic SDK → OpenRouter /api/v1/messages
- Strips ?beta=true and Anthropic-specific headers that confuse OpenRouter
- Handles GET /models/* with a fake response so the CLI doesn't fail
"""
import http.server, urllib.request, json, os, sys, time

from langfuse import get_client

OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
LISTEN_PORT = int(os.environ.get("PROXY_PORT", "4001"))

_lf = get_client()

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Claude CLI may do model lookup — return fake success
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        model_id = self.path.split("/")[-1].split("?")[0]
        self.wfile.write(json.dumps({
            "id": model_id, "type": "model",
            "display_name": model_id, "created_at": "2025-01-01T00:00:00Z"
        }).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        req_json: dict = {}
        try:
            req_json = json.loads(body)
        except Exception:
            pass

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/messages",
            data=body, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + OR_KEY)

        model = req_json.get("model", "unknown")
        messages = req_json.get("messages") or req_json.get("prompt")
        meta = {k: req_json[k] for k in ("max_tokens", "system") if k in req_json}

        with _lf.start_as_current_observation(
            name="messages",
            as_type="generation",
            model=model,
            input=messages,
            metadata=meta or None,
        ) as gen:
            t0 = time.monotonic()
            try:
                resp = urllib.request.urlopen(req, timeout=300)
                data = resp.read()
                latency_ms = int((time.monotonic() - t0) * 1000)

                try:
                    resp_json = json.loads(data)
                    usage = resp_json.get("usage", {})
                    gen.update(
                        output=resp_json.get("content"),
                        usage_details={
                            "input": usage.get("input_tokens"),
                            "output": usage.get("output_tokens"),
                        },
                        metadata={"latency_ms": latency_ms},
                    )
                except Exception:
                    gen.update(metadata={"latency_ms": latency_ms})

                self.send_response(resp.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
            except urllib.error.HTTPError as e:
                data = e.read()
                latency_ms = int((time.monotonic() - t0) * 1000)
                gen.update(
                    level="ERROR",
                    status_message=f"HTTP {e.code}",
                    metadata={"latency_ms": latency_ms},
                )
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

print(f"OpenRouter proxy listening on 0.0.0.0:{LISTEN_PORT}", flush=True)
http.server.HTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
