def test_free_key():
    from app.license import free_key_for, verify_free, license_tier
    k = free_key_for("free@test.de")
    assert k.startswith("FREE-")
    assert verify_free("free@test.de", k)
    assert not verify_free("other@test.de", k)
    assert license_tier("free@test.de", k, None) == "free"
    assert license_tier("x@y.de", "PRO-AAAA-BBBB-CCCC-DDDD", None) == "none"


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


def test_monthly_count():
    from app import bookkeeping as bk
    import datetime
    ym = datetime.date.today().strftime("%Y-%m")
    invs = bk.invoices_this_month(ym)
    assert isinstance(invs, list)
    assert all(i.get("status") != "storniert" for i in invs)
