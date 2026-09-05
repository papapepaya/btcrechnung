def test_ocr_parse():
    from app.ocr import parse_receipt
    res = parse_receipt("REWE Markt\nBerliner Str. 1\n05.09.2026\nSumme 12,50 EUR\n")
    assert res["amount"] == 12.5 and res["date"] == "2026-09-05"
    assert res["vendor"].startswith("REWE")


def test_ocr_graceful():
    from app import ocr
    assert isinstance(ocr.is_available(), bool)
    assert ocr.scan(b"nope")["available"] == ocr.is_available()


def test_afa():
    from app import bookkeeping as bk
    from app import db
    gwg = bk.add_asset("S6 GWG", "2026-03-15", 500, 5)
    big = bk.add_asset("S6 Kamera", "2026-03-15", 2400, 3)
    rows = {r["name"]: r for r in bk.afa_for_year(2026)}
    assert rows["S6 GWG"]["afa"] == 500.0
    assert rows["S6 Kamera"]["afa"] == round(800 * 10 / 12, 2)
    assert bk.afa_total(2026) >= 500.0
    c = db.connect()
    c.execute("DELETE FROM assets WHERE id IN (?, ?)", (gwg, big))
    c.close()
