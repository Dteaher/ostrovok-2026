import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.agent_transport import model_json


def test_consecutive_llm_calls_reuse_one_authenticated_connection(monkeypatch):
    from app.agent_transport import provider_session
    seen = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.client_address[1], self.headers.get("Authorization"), request))
            payload = json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": '{"ok":true}'}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("LLM_MODEL", "test")
    monkeypatch.setenv("LLM_API_KEY", "pool-test-key")
    monkeypatch.setenv("LLM_TRUST_ENV", "0")

    async def run():
        async with provider_session():
            for _ in range(2):
                assert await model_json([], deadline=time.monotonic() + 2) == {"ok": True}
    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    assert len(seen) == 2
    assert seen[0][0] == seen[1][0]
    assert all(row[1] == "Bearer pool-test-key" for row in seen)
