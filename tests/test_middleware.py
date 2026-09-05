import asyncio
import urllib.parse


def _call_app(port_path, method="GET", body=b"", cookies=""):
    from app.main import app
    body = body or b""
    headers = [(b"cookie", cookies.encode())] if cookies else []
    if body:
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))
        headers.append((b"content-length", str(len(body)).encode()))
    scope = {"type": "http", "http_version": "1.1", "method": method, "scheme": "http",
             "path": port_path, "raw_path": port_path.encode(), "query_string": b"",
             "headers": headers, "client": ("test", 5000), "server": ("test", 80)}
    sent_body = {"done": False}

    async def receive():
        if not sent_body["done"]:
            sent_body["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    out = {}

    async def send(msg):
        out.setdefault("msgs", []).append(msg)

    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in out["msgs"] if m["type"] == "http.response.start")
    data = b"".join(m.get("body", b"") for m in out["msgs"] if m["type"] == "http.response.body")
    return status, data


def test_post_form_survives_middleware():
    from app import bookkeeping as bk, auth as a
    s = bk.get_settings()
    old_email = s.get("license_email", "")
    old_pw = s.get("password_hash")
    s["password_hash"] = a.hash_password("ci-test-pw")
    bk.save_settings(s)
    token = a.create_session(bk)
    csrf = a.csrf_token_for_session(bk, token)
    try:
        body = urllib.parse.urlencode({
            "license_email": "mw@test.de", "license_key": "",
            "purchase_url": "", "_csrf": csrf}).encode()
        status, _ = _call_app("/settings/license", "POST", body, f"session={token}")
        assert status == 200
        assert bk.get_settings().get("license_email") == "mw@test.de"
    finally:
        a.destroy_session(bk, token)
        s = bk.get_settings()
        s["license_email"] = old_email
        if old_pw is None:
            s.pop("password_hash", None)
        else:
            s["password_hash"] = old_pw
        bk.save_settings(s)
