def test_quotes():
    from app import bookkeeping as bk
    q = bk.save_quote({"customer_name": "Q-Test GmbH", "customer_address": "Weg 1",
                       "items": [{"description": "x", "quantity": 2, "unit_price": 50}],
                       "valid_days": 30})
    assert q["id"].startswith("AN-") and q["status"] == "offen"
    assert bk.set_quote_status(q["id"], "abgelehnt")["status"] == "abgelehnt"
    assert bk.get_quote(q["id"])["status"] == "abgelehnt"
    assert bk.peek_next_quote_number().startswith("AN-")
    from app import db
    c = db.connect()
    c.execute("DELETE FROM quotes WHERE id=?", (q["id"],))
    c.close()


def test_timelog():
    from app import bookkeeping as bk
    rid = bk.add_time_entry("2026-09-01", "Z-Kunde", "Shooting", 2.5, 80)
    assert rid > 0
    open_entries = bk.get_time_entries(unbilled_only=True)
    assert any(e["_row_id"] == rid for e in open_entries)
    assert bk.mark_time_billed([rid], "RE-TEST") == 1
    assert all(e["_row_id"] != rid for e in bk.get_time_entries(unbilled_only=True))
    assert bk.delete_time_entry(rid)
