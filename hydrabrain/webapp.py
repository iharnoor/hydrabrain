"""hydrabrain web UI — a zero-dependency chat-over-your-brain app.

Served by the Python stdlib http.server (no Flask/FastAPI/uvicorn to install), so it
works the moment someone installs hydrabrain. Built for creators: paste a blog post,
article, or YouTube URL and it's in your brain; then chat with everything you've made
or consumed, with citations.

Run:
  hydrabrain web                 # http://127.0.0.1:8765
  hydrabrain web --port 9000 --open

Endpoints (all JSON):
  GET  /                 the single-page app
  GET  /api/status       {tenant, source, memories}
  POST /api/read         {url}                -> ingest article / YouTube transcript
  POST /api/capture      {text, title}        -> ingest free text
  POST /api/think        {query, k}           -> cited answer + gaps + sources
  POST /api/search       {query, k}           -> raw ranked chunks
"""

from __future__ import annotations

import json
import threading
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_WEB = Path(__file__).resolve().parent / "web"
_INDEX = _WEB / "index.html"
_SETUP = _WEB / "setup.html"


def _answer_to_dict(ans) -> dict:
    return {
        "text": ans.text,
        "gaps": ans.gaps,
        "sources": [
            {"text": c.text, "score": round(c.score, 4), "source_id": c.source_id}
            for c in ans.citations
        ],
    }


class _Handler(BaseHTTPRequestHandler):
    _engine = None          # built lazily once keys exist
    tenant_id = None
    source_id = None

    # quiet the default per-request stderr logging
    def log_message(self, *args):  # noqa: D401
        pass

    @property
    def engine(self):
        from . import config
        if config.needs_onboarding():
            return None
        cls = type(self)
        if cls._engine is None:
            from .engine import BrainEngine
            cls._engine = BrainEngine(tenant_id=cls.tenant_id, source_id=cls.source_id)
        return cls._engine

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        from . import config
        if self.path in ("/", "/index.html"):
            asset = _SETUP if config.needs_onboarding() else _INDEX
            try:
                html = asset.read_bytes()
            except Exception:
                html = b"<h1>hydrabrain</h1><p>UI asset missing.</p>"
            return self._send(200, html, "text/html; charset=utf-8")
        if self.path.startswith("/api/needs-setup"):
            return self._json({"needs_setup": config.needs_onboarding(),
                               "have_gemini": config.have_gemini(),
                               "hydradb_signup": config.HYDRADB_SIGNUP_URL,
                               "gemini_signup": config.GEMINI_SIGNUP_URL})
        if self.path.startswith("/api/status"):
            if not self.engine:
                return self._json({"error": "setup required"}, 409)
            try:
                return self._json(self.engine.status())
            except Exception as e:
                return self._json({"error": str(e)[:300]}, 500)
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        from . import config
        body = self._read_body()
        try:
            if self.path == "/api/setup":
                from . import onboarding
                res = onboarding.apply(body.get("hydradb_key", ""), body.get("gemini_key", ""))
                if res.get("ok"):
                    type(self)._engine = None  # rebuild with the new keys on next call
                return self._json(res, 200 if res.get("ok") else 400)
            if config.needs_onboarding():
                return self._json({"error": "setup required"}, 409)
            if self.path == "/api/think":
                ans = self.engine.think(body.get("query", ""), k=int(body.get("k", 6)))
                return self._json(_answer_to_dict(ans))
            if self.path == "/api/search":
                chunks = self.engine.search(body.get("query", ""), k=int(body.get("k", 8)))
                return self._json({"results": [
                    {"text": c.text, "score": round(c.score, 4), "source_id": c.source_id}
                    for c in chunks]})
            if self.path == "/api/capture":
                self.engine.capture(body.get("text", ""), title=body.get("title", ""))
                return self._json({"ok": True})
            if self.path == "/api/read":
                res = self.engine.ingest_url(body.get("url", ""))
                res.pop("result", None)  # trim the raw HydraDB payload
                return self._json({"ok": True, **res})
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)
        return self._send(404, b"not found", "text/plain")


def serve(tenant_id=None, source_id=None, host="127.0.0.1", port=8765, open_browser=False):
    from . import config

    handler = _Handler
    handler.tenant_id = tenant_id
    handler.source_id = source_id
    handler._engine = None
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    if config.needs_onboarding():
        print(f"hydrabrain web — first-run setup at {url}  (Ctrl-C to stop)")
    else:
        print(f"hydrabrain web — your brain at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
