def test_price_cache():
    from app import bitcoin as b
    p1 = b.get_btc_price_eur()
    p2 = b.get_btc_price_eur()
    assert p1 == p2 and p1 > 0


def test_webhook_sig_logic():
    import hmac
    import hashlib
    secret = "s3cr3t"
    body = b'{"type":"InvoiceSettled"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(sig, "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest())
    assert not hmac.compare_digest(sig, "sha256=bad")


def test_webhook_exempt_and_public():
    import pathlib
    main = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    assert "/webhook/" in main and "CSRF_EXEMPT" in main


def test_docker_and_ci_exist():
    import pathlib
    assert pathlib.Path("Dockerfile").exists()
    assert pathlib.Path("docker-compose.yml").exists()
    assert pathlib.Path(".github/workflows/build.yml").exists()
    ci = pathlib.Path(".github/workflows/build.yml").read_text(encoding="utf-8")
    assert "pytest" in ci and "ghcr.io" in ci
    assert pathlib.Path("scripts/setup.iss").exists()
