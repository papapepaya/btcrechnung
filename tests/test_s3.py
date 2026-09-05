def test_bank_csv():
    from app.bankimport import parse_csv
    rows = parse_csv("Datum;Zweck;Betrag\r\n05.09.2026;RE-2026-0001 Test;250,00\r\n".encode())
    assert rows[0]["date"] == "2026-09-05" and rows[0]["amount"] == 250.0


def test_bank_camt():
    from app.bankimport import parse_camt053
    xml = b"""<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
    <BkToCstmrStmt><Stmt><Ntry><Amt Ccy="EUR">100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
    <BookgDt><Dt>2026-09-01</Dt></BookgDt><RmtInf><Ustrd>RE-2026-0001</Ustrd></RmtInf></Ntry></Stmt>
    </BkToCstmrStmt></Document>"""
    rows = parse_camt053(xml)
    assert rows[0]["amount"] == 100.0 and "RE-2026-0001" in rows[0]["purpose"]


def test_recurring_crud():
    from app import bookkeeping as bk
    pid = bk.save_recurring_profile({"name": "T", "customer_name": "K",
                                     "items": [], "frequency": "monthly",
                                     "next_run": "2099-01-01", "active": True})
    assert pid > 0
    assert bk.get_recurring_profile(pid)["name"] == "T"
    assert bk.run_due_recurring(lambda p: {"invoice_no": "X"}) == []
    assert bk.delete_recurring_profile(pid)


def test_invoicing_totals():
    from app.invoicing import totals
    n, v, g, klein = totals([{"description": "a", "quantity": 1, "unit_price": 100, "vat_rate": 0.19}],
                            "regulaer", True)
    assert (n, v, g) == (100.0, 19.0, 119.0) and not klein


def test_dunning_and_overdue():
    from app import bookkeeping as bk
    assert isinstance(bk.overdue_invoices(), list)
    assert isinstance(bk.get_cashbook_entries(), list)
    assert isinstance(bk.get_bank_transactions(), list)
