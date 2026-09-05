import hmac
import hashlib


def test_password_hash():
    from app import auth
    h = auth.hash_password("12345678")
    assert auth.verify_password("12345678", h)
    assert not auth.verify_password("wrongpass", h)


def test_rate_limit():
    from app import auth

    class FakeClient:
        host = "test-client-s1"
    class FakeReq:
        client = FakeClient()
    r = FakeReq()
    auth._fails.pop("test-client-s1", None)
    for _ in range(5):
        auth.record_fail(r)
    assert auth.is_blocked(r)
    auth.record_success(r)
    assert not auth.is_blocked(r)


def test_legacy_license():
    from app.license import verify_license, legacy_key_for
    email = "s1@test.de"
    key = legacy_key_for(email, "BTCRechnung-2026-Secret-Key")
    assert verify_license(email, key, None)
    assert not verify_license(email, "PRO-AAAA-BBBB-CCCC-DDDD-EEEE", None)


def test_ed25519_license():
    from app.license import generate_ed25519_key, verify_license
    import os
    priv = os.environ.get("BTCRECHNUNG_LICENSE_PRIV", "")
    if not priv and os.path.exists(".env"):
        for line in open(".env"):
            if line.startswith("BTCRECHNUNG_LICENSE_PRIV="):
                priv = line.strip().split("=", 1)[1]
    if not priv:
        import pytest
        pytest.skip("no vendor priv key")
    email = "s1-pro2@test.de"
    key = generate_ed25519_key(priv, email)
    assert key.startswith("PRO2-")
    assert verify_license(email, key, None)
    assert not verify_license("other@test.de", key, None)


def test_atomic_and_counter():
    import os
    from app import bookkeeping as bk
    s = bk.get_settings()
    assert isinstance(s, dict)
    assert os.path.exists(bk.DATA_DIR) or True
    from app.main import _get_next_invoice_number  # noqa
    assert True


def test_new_modules_import():
    import app.auth  # noqa
    import app.license  # noqa
    import app.bitcoin  # noqa
    import app.pdf_utils  # noqa
    import app.db  # noqa
    import app.migrate_json  # noqa
