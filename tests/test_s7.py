import datetime


def _xml(**kw):
    from app.zugferd import generate_zugferd_xml
    base = dict(invoice_number="RE-2026-0099", issue_date=datetime.date(2026, 9, 5),
                seller_name="Firma", seller_address="Str. 1, 12345 Stadt",
                buyer_name="Kunde", buyer_address="Weg 2, 54321 Dorf",
                line_items=[{"description": "x", "quantity": 1, "unit_price": 10,
                             "line_total": 10}],
                total_eur=10.0, seller_tax_id="DE123")
    base.update(kw)
    return generate_zugferd_xml(**base).decode("utf-8")


def test_basic_profile_no_reference():
    xml = _xml()
    assert "factur-x.eu:1p0:basic" in xml
    assert "BuyerReference" not in xml


def test_en16931_profile_with_leitweg():
    xml = _xml(profile="en16931", buyer_reference="991-12345-12")
    assert "urn:cen.eu:en16931:2017" in xml
    assert "<ram:BuyerReference>991-12345-12</ram:BuyerReference>" in xml


def test_validation():
    from app.zugferd import validate_invoice
    assert validate_invoice("basic", "F", "A", "K", "A2", "", None, 10) == []
    errs = validate_invoice("en16931", "F", "A", "K", "A2", "", None, 10)
    assert any("Steuernummer" in e for e in errs) and any("Leitweg" in e for e in errs)
    assert validate_invoice("en16931", "F", "A", "K", "A2", "DE1", "991-12345-12", 10) == []


def test_leitweg_persistence():
    from app import bookkeeping as bk
    from app import db
    c = bk.upsert_customer("S7 Leitweg GmbH", "Weg 1", "991-99999-11")
    assert c["leitweg_id"] == "991-99999-11"
    c2 = bk.upsert_customer("S7 Leitweg GmbH", "Weg 1")
    assert c2["leitweg_id"] == "991-99999-11"  # leer ueberschreibt nicht
    con = db.connect()
    con.execute("DELETE FROM customers WHERE name=?", ("S7 Leitweg GmbH",))
    con.close()
