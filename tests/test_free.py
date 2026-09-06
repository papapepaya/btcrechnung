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


def test_monthly_count():
    from app import bookkeeping as bk
    import datetime
    ym = datetime.date.today().strftime("%Y-%m")
    invs = bk.invoices_this_month(ym)
    assert isinstance(invs, list)
    assert all(i.get("status") != "storniert" for i in invs)
