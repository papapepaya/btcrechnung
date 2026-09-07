def test_free_key():
    from app.license import free_key_for, verify_free, license_tier
    k = free_key_for("free@test.de")
    assert k.startswith("FREE-")
    assert verify_free("free@test.de", k)
    assert not verify_free("other@test.de", k)
    assert license_tier("free@test.de", k, None) == "free"
    assert license_tier("x@y.de", "PRO-AAAA-BBBB-CCCC-DDDD", None) == "none"


def test_basic_key():
    from app.license import basic_key_for, verify_basic, license_tier
    k = basic_key_for("b@test.de")
    assert k.startswith("BASIC-")
    assert verify_basic("b@test.de", k)
    assert not verify_basic("other@test.de", k)
    assert license_tier("b@test.de", k, None) == "basic"


def test_pro_not_free():
    from app.license import is_pro, legacy_key_for
    k = legacy_key_for("p@test.de", "BTCRechnung-2026-Secret-Key")
    assert is_pro("p@test.de", k)
    from app.license import free_key_for
    assert not is_pro("free@test.de", free_key_for("free@test.de"))


def test_main_wrapper_free():
    from app.main import verify_license, is_pro_license
    from app import bookkeeping as bk
    from app.license import free_key_for
    s = bk.get_settings()
    old_email, old_key = s.get("license_email", ""), s.get("license_key", "")
    try:
        assert verify_license("free@test.de", free_key_for("free@test.de"))
        assert not verify_license("free@test.de", "FREE-AAAA-BBBB-CCCC-DDDD")
        s["license_email"] = "free@test.de"
        s["license_key"] = free_key_for("free@test.de")
        bk.save_settings(s)
        assert not is_pro_license()
        from app.main import get_license_tier
        assert get_license_tier() == "free"
    finally:
        s["license_email"] = old_email
        s["license_key"] = old_key
        bk.save_settings(s)


def _call(method, path, body=b"", cookies=""):
    import asyncio
    from app.main import app
    headers = [(b"cookie", cookies.encode())] if cookies else []
    if body:
        headers += [(b"content-type", b"application/x-www-form-urlencoded"),
                    (b"content-length", str(len(body)).encode())]
    scope = {"type": "http", "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": headers, "client": ("test", 5000), "server": ("test", 80)}
    done = {"n": False}

    async def receive():
        if not done["n"]:
            done["n"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    out = {}

    async def send(msg):
        out.setdefault("msgs", []).append(msg)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in out["msgs"] if m["type"] == "http.response.start")
    return start["status"], dict(start.get("headers", [])).get(b"location", b"").decode()


def test_license_gate():
    from app import bookkeeping as bk, auth as a
    from app.license import free_key_for
    s = bk.get_settings()
    old_email, old_key, old_pw = s.get("license_email", ""), s.get("license_key", ""), s.get("password_hash")
    s["password_hash"] = a.hash_password("gate-pw")
    s["license_email"] = ""
    s["license_key"] = ""
    bk.save_settings(s)
    token = a.create_session(bk)
    try:
        status, loc = _call("GET", "/dashboard", cookies=f"session={token}")
        assert status == 302 and "license_required=1" in loc
        status, _ = _call("GET", "/settings", cookies=f"session={token}")
        assert status == 200
        status, _ = _call("POST", "/generate-pdf", b"{}", cookies=f"session={token}")
        assert status == 402
        s["license_email"] = "free@test.de"
        s["license_key"] = free_key_for("free@test.de")
        bk.save_settings(s)
        status, _ = _call("GET", "/dashboard", cookies=f"session={token}")
        assert status == 200
    finally:
        a.destroy_session(bk, token)
        s["license_email"] = old_email
        s["license_key"] = old_key
        if old_pw is None:
            s.pop("password_hash", None)
        else:
            s["password_hash"] = old_pw
        bk.save_settings(s)


def test_monthly_count():
    from app import bookkeeping as bk
    import datetime
    ym = datetime.date.today().strftime("%Y-%m")
    invs = bk.invoices_this_month(ym)
    assert isinstance(invs, list)
    assert all(i.get("status") != "storniert" for i in invs)
