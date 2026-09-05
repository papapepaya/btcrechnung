def test_customers_crud():
    from app import bookkeeping as bk
    c = bk.upsert_customer("S2 Unit GmbH", "Weg 1,  Berlin")
    assert c["name"] == "S2 Unit GmbH"
    assert bk.search_customers("s2 unit")[0]["address"].startswith("Weg")
    assert bk.delete_customer(c["id"])
    assert bk.search_customers("s2 unit") == []


def test_drafts():
    from app import bookkeeping as bk
    did = bk.save_draft({"customer_name": "Draft Co", "items": []})
    assert did > 0
    assert any(d["_draft_id"] == did for d in bk.list_drafts())
    assert bk.delete_draft(did)


def test_peek_number():
    from app import bookkeeping as bk
    nxt = bk.peek_next_invoice_number()
    assert nxt.startswith("RE-")


def test_invoice_validation():
    from app.main import InvoiceRequest
    r = InvoiceRequest(customer_name="K", customer_address="A",
                       items=[{"description": "x", "quantity": 1, "unit_price": 10}],
                       doc_type="gutschrift", payment_days=14, preview=True)
    assert r.doc_type == "gutschrift" and r.preview is True
