import json
import os
import sys
import datetime
from typing import List, Optional, Dict
from pathlib import Path

# PyInstaller: Datenverzeichnis neben der App, nicht im Bundle
if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(os.path.dirname(sys.executable), 'data')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_DIR = os.path.dirname(BASE_DIR)
    DATA_DIR = os.path.join(PROJECT_DIR, "data")

EXPENSES_FILE = os.path.join(DATA_DIR, "expenses.json")
INVOICES_FILE = os.path.join(DATA_DIR, "invoices.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
AUDIT_FILE = os.path.join(DATA_DIR, "audit.json")

DEFAULT_SETTINGS = {
    "business_name": "",
    "business_address": "",
    "business_slogan": "",
    "business_phone": "",
    "business_email": "",
    "business_type": "kleinunternehmer",
    "bank_iban": "",
    "bank_bic": "",
    "bank_name": "",
    "bank_account_name": "",
    "btc_xpub": None,
    "logo_hidden": False,
    "btc_address_index": 0,
    "email_smtp_server": "",
    "email_smtp_port": 587,
    "email_address": "",
    "email_password": "",
    "email_notify_on_payment": False,
    "password_hash": None,
    "session_secret": None,
    "tax_id": "",
    "license_email": "",
    "license_key": "",
    "license_salt": None,
    "btc_discount_percent": 0,
    "lightning_address": None,
    "default_payment_days": 14,
    "btcpay_url": "",
    "btcpay_webhook_secret": "",
    "dunning_fee_1": 5.0,
    "dunning_fee_2": 7.5,
    "dunning_fee_3": 10.0,
    "default_interest_rate": 8.62,
}


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _atomic_write_json(filepath: str, data):
    _ensure_data_dir()
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, filepath)


def _lock_file(fp):
    try:
        import fcntl
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
    except (ImportError, OSError, AttributeError):
        pass


def _unlock_file(fp):
    try:
        import fcntl
        fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
    except (ImportError, OSError, AttributeError):
        pass


def _load_json(filepath: str) -> list:
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        _lock_file(f)
        try:
            return json.load(f)
        finally:
            _unlock_file(f)


def _save_json(filepath: str, data: list):
    _atomic_write_json(filepath, data)


def _migrate_status(data: list, default: str = "aktiv"):
    for item in data:
        if "status" not in item:
            item["status"] = default
    return data


def get_active_invoices() -> list:
    all_invs = get_all_invoices()
    return [i for i in all_invs if i.get("status", "aktiv") == "aktiv"]


def get_active_expenses() -> list:
    all_exps = get_all_expenses()
    return [e for e in all_exps if e.get("status", "aktiv") == "aktiv"]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_DB_INIT_DONE = False


def _db_ready() -> bool:
    global _DB_INIT_DONE
    try:
        from . import db as dbmod
        from . import migrate_json as migmod
        dbmod.init_schema()
        if not _DB_INIT_DONE:
            try:
                migmod.migrate_once()
            except Exception as e:
                print(f"Migration übersprungen: {e}")
            _DB_INIT_DONE = True
        return True
    except Exception as e:
        print(f"DB deaktiviert, JSON-Fallback: {e}")
        return False


def _json_get_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return dict(DEFAULT_SETTINGS)
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        settings = json.load(f)
    for key, val in DEFAULT_SETTINGS.items():
        settings.setdefault(key, val)
    return settings


def get_settings() -> dict:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                rows = con.execute("SELECT key, value FROM kv_settings").fetchall()
                settings = dict(DEFAULT_SETTINGS)
                for k, v in rows:
                    try:
                        settings[k] = json.loads(v)
                    except Exception:
                        settings[k] = v
                if not rows and os.path.exists(SETTINGS_FILE):
                    js = _json_get_settings()
                    for k, v in js.items():
                        con.execute("INSERT OR REPLACE INTO kv_settings (key, value) VALUES (?, ?)",
                                    (k, json.dumps(v, ensure_ascii=False, default=str)))
                    return js
                return settings
            finally:
                con.close()
        except Exception as e:
            print(f"get_settings DB-Fallback: {e}")
    return _json_get_settings()


def save_settings(settings: dict):
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                with con:
                    for k, v in settings.items():
                        con.execute("INSERT OR REPLACE INTO kv_settings (key, value) VALUES (?, ?)",
                                    (k, json.dumps(v, ensure_ascii=False, default=str)))
                _atomic_write_json(SETTINGS_FILE, settings)
                return
            finally:
                con.close()
        except Exception as e:
            print(f"save_settings DB-Fallback: {e}")
    _atomic_write_json(SETTINGS_FILE, settings)


# ---------------------------------------------------------------------------
# GoBD – Audit-Log & Prüfsummen
# ---------------------------------------------------------------------------

def _compute_checksum(data: dict) -> str:
    """Berechnet SHA-256 Prüfsumme eines Datensatzes (ohne audit_* Felder)."""
    import hashlib
    # Audit-Felder ausschließen
    clean = {k: v for k, v in data.items() if not k.startswith("audit_")}
    data_str = json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(data_str.encode("utf-8")).hexdigest()[:16]


def _append_audit_log(action: str, record_type: str, record_id: str, data_snapshot: dict):
    """Hängt einen Eintrag zum Audit-Log an."""
    _ensure_data_dir()
    import datetime
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "action": action,
        "record_type": record_type,
        "record_id": record_id,
        "checksum": _compute_checksum(data_snapshot),
        "data": data_snapshot,
    }
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                with con:
                    con.execute("INSERT INTO audit (data) VALUES (?)",
                                (json.dumps(entry, ensure_ascii=False, default=str),))
                return
            finally:
                con.close()
        except Exception as e:
            print(f"audit DB-Fallback: {e}")
    log = _load_json(AUDIT_FILE)
    log.append(entry)
    _save_json(AUDIT_FILE, log)


def get_audit_log(record_type: str = None, record_id: str = None) -> list:
    """Gibt das Audit-Log gefiltert zurück."""
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                rows = con.execute("SELECT data FROM audit ORDER BY seq").fetchall()
                log = [json.loads(r[0]) for r in rows]
                if record_type:
                    log = [e for e in log if e.get("record_type") == record_type]
                if record_id:
                    log = [e for e in log if e.get("record_id") == record_id]
                return log
            finally:
                con.close()
        except Exception:
            pass
    log = _load_json(AUDIT_FILE)
    if record_type:
        log = [e for e in log if e.get("record_type") == record_type]
    if record_id:
        log = [e for e in log if e.get("record_id") == record_id]
    return log


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

def _db_all(table: str) -> list:
    from . import db as dbmod
    con = dbmod.connect()
    try:
        rows = con.execute(f"SELECT data FROM {table}").fetchall()
        return [json.loads(r[0]) for r in rows]
    finally:
        con.close()


def get_all_expenses() -> list:
    if _db_ready():
        try:
            return _migrate_status(_db_all("expenses"))
        except Exception as e:
            print(f"expenses DB-Fallback: {e}")
    data = _load_json(EXPENSES_FILE)
    return _migrate_status(data)


def get_expense(expense_id: str) -> Optional[dict]:
    return next((e for e in get_all_expenses() if e["id"] == expense_id), None)


def create_expense(data: dict) -> dict:
    data["status"] = "aktiv"
    year = datetime.date.today().year
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                with con:
                    cur = con.execute("SELECT id FROM expenses WHERE id LIKE ?", (f"EXP-{year}%",))
                    nums = []
                    for (eid,) in cur.fetchall():
                        try:
                            nums.append(int(eid.rsplit("-", 1)[-1]))
                        except ValueError:
                            pass
                    next_num = (max(nums) + 1) if nums else 1
                    data["id"] = f"EXP-{year}-{next_num:04d}"
                    data["audit_hash"] = _compute_checksum(data)
                    con.execute("INSERT INTO expenses (id, data) VALUES (?, ?)",
                                (data["id"], json.dumps(data, ensure_ascii=False, default=str)))
                _append_audit_log("create", "expense", data["id"], data)
                return data
            finally:
                con.close()
        except Exception as e:
            print(f"create_expense DB-Fallback: {e}")
    expenses = get_all_expenses()
    nums = []
    for e in expenses:
        eid = e.get("id", "")
        if eid.startswith(f"EXP-{year}"):
            try:
                nums.append(int(eid.rsplit("-", 1)[-1]))
            except ValueError:
                pass
    next_num = (max(nums) + 1) if nums else 1
    data["id"] = f"EXP-{year}-{next_num:04d}"
    data["audit_hash"] = _compute_checksum(data)
    expenses.append(data)
    _save_json(EXPENSES_FILE, expenses)
    _append_audit_log("create", "expense", data["id"], data)
    return data


def update_expense(expense_id: str, data: dict) -> Optional[dict]:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                row = con.execute("SELECT data FROM expenses WHERE id=?", (expense_id,)).fetchone()
                if row:
                    data["id"] = expense_id
                    with con:
                        con.execute("UPDATE expenses SET data=? WHERE id=?",
                                    (json.dumps(data, ensure_ascii=False, default=str), expense_id))
                    return data
                return None
            finally:
                con.close()
        except Exception:
            pass
    expenses = _load_json(EXPENSES_FILE)
    for i, e in enumerate(expenses):
        if e["id"] == expense_id:
            data["id"] = expense_id
            expenses[i] = data
            _save_json(EXPENSES_FILE, expenses)
            return data
    return None


def cancel_expense(expense_id: str, reason: str = "") -> bool:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                row = con.execute("SELECT data FROM expenses WHERE id=?", (expense_id,)).fetchone()
                if not row:
                    return False
                e = json.loads(row[0])
                if e.get("status") == "storniert":
                    return False
                e["status"] = "storniert"
                e["cancelled_at"] = datetime.datetime.now().isoformat()
                e["cancelled_reason"] = reason
                with con:
                    con.execute("UPDATE expenses SET data=? WHERE id=?",
                                (json.dumps(e, ensure_ascii=False, default=str), expense_id))
                _append_audit_log("cancel", "expense", expense_id, dict(e))
                return True
            finally:
                con.close()
        except Exception:
            pass
    expenses = _load_json(EXPENSES_FILE)
    for e in expenses:
        if e["id"] == expense_id:
            if e.get("status") == "storniert":
                return False
            e["status"] = "storniert"
            e["cancelled_at"] = datetime.datetime.now().isoformat()
            e["cancelled_reason"] = reason
            _append_audit_log("cancel", "expense", expense_id, dict(e))
            _save_json(EXPENSES_FILE, expenses)
            return True
    return False


# ---------------------------------------------------------------------------
# Invoices (Income)
# ---------------------------------------------------------------------------

def get_all_invoices() -> list:
    if _db_ready():
        try:
            return _migrate_status(_db_all("invoices"))
        except Exception as e:
            print(f"invoices DB-Fallback: {e}")
    data = _load_json(INVOICES_FILE)
    return _migrate_status(data)


def get_invoice_by_id(invoice_id: str) -> Optional[dict]:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                row = con.execute("SELECT data FROM invoices WHERE id=?", (invoice_id,)).fetchone()
                if row:
                    inv = json.loads(row[0])
                    if "status" not in inv:
                        inv["status"] = "aktiv"
                    return inv
            finally:
                con.close()
        except Exception:
            pass
    for inv in get_all_invoices():
        if inv["id"] == invoice_id:
            return inv
    return None


def log_invoice(data: dict) -> dict:
    data["status"] = "aktiv"
    data["audit_hash"] = _compute_checksum(data)
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                with con:
                    con.execute("INSERT OR REPLACE INTO invoices (id, data) VALUES (?, ?)",
                                (data["id"], json.dumps(data, ensure_ascii=False, default=str)))
                _append_audit_log("create", "invoice", data["id"], data)
                return data
            finally:
                con.close()
        except Exception as e:
            print(f"log_invoice DB-Fallback: {e}")
    invoices = _load_json(INVOICES_FILE)
    invoices.append(data)
    _save_json(INVOICES_FILE, invoices)
    _append_audit_log("create", "invoice", data["id"], data)
    return data


def _update_invoice_row(invoice_id: str, mutator) -> Optional[dict]:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                row = con.execute("SELECT data FROM invoices WHERE id=?", (invoice_id,)).fetchone()
                if not row:
                    return None
                inv = json.loads(row[0])
                result = mutator(inv)
                if result is False:
                    return None
                inv["audit_hash"] = _compute_checksum(inv)
                with con:
                    con.execute("UPDATE invoices SET data=? WHERE id=?",
                                (json.dumps(inv, ensure_ascii=False, default=str), invoice_id))
                return inv
            finally:
                con.close()
        except Exception:
            pass
    return None


def mark_invoice_paid(invoice_id: str, payment_date: str,
                      btc_received: float = None, eur_value: float = None,
                      txid: str = None, payment_method: str = None) -> Optional[dict]:
    def _mut(inv):
        _append_audit_log("update_old", "invoice", invoice_id, dict(inv))
        inv["payment_received"] = True
        inv["payment_date"] = payment_date
        if btc_received is not None:
            inv["btc_amount_received"] = btc_received
        if eur_value is not None:
            inv["eur_value_at_payment"] = eur_value
        if txid is not None:
            inv["payment_txid"] = txid
        if payment_method is not None:
            inv["payment_method"] = payment_method
    updated = _update_invoice_row(invoice_id, _mut)
    if updated is not None:
        _append_audit_log("update_new", "invoice", invoice_id, dict(updated))
        return updated
    invoices = _load_json(INVOICES_FILE)
    for inv in invoices:
        if inv["id"] == invoice_id:
            _append_audit_log("update_old", "invoice", invoice_id, dict(inv))
            inv["payment_received"] = True
            inv["payment_date"] = payment_date
            if btc_received is not None:
                inv["btc_amount_received"] = btc_received
            if eur_value is not None:
                inv["eur_value_at_payment"] = eur_value
            if txid is not None:
                inv["payment_txid"] = txid
            if payment_method is not None:
                inv["payment_method"] = payment_method
            inv["audit_hash"] = _compute_checksum(inv)
            _save_json(INVOICES_FILE, invoices)
            _append_audit_log("update_new", "invoice", invoice_id, dict(inv))
            return inv
    return None


def cancel_invoice(invoice_id: str, reason: str = "") -> bool:
    def _mut(inv):
        if inv.get("status") == "storniert":
            return False
        _append_audit_log("cancel_old", "invoice", invoice_id, dict(inv))
        inv["status"] = "storniert"
        inv["cancelled_at"] = datetime.datetime.now().isoformat()
        inv["cancelled_reason"] = reason
    if _db_ready():
        updated = _update_invoice_row(invoice_id, _mut)
        if updated is not None:
            _append_audit_log("cancel_new", "invoice", invoice_id, dict(updated))
            return True
        inv = get_invoice_by_id(invoice_id)
        if inv is None:
            return False
    invoices = _load_json(INVOICES_FILE)
    for inv in invoices:
        if inv["id"] == invoice_id:
            if inv.get("status") == "storniert":
                return False
            _append_audit_log("cancel_old", "invoice", invoice_id, dict(inv))
            inv["status"] = "storniert"
            inv["cancelled_at"] = datetime.datetime.now().isoformat()
            inv["cancelled_reason"] = reason
            inv["audit_hash"] = _compute_checksum(inv)
            _save_json(INVOICES_FILE, invoices)
            _append_audit_log("cancel_new", "invoice", invoice_id, dict(inv))
            return True
    return False


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def _customer_rows_to_dicts(rows) -> list:
    out = []
    for r in rows:
        out.append({"id": r[0], "name": r[1], "address": r[2] or ""})
    return out


def get_all_customers() -> list:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                dbmod.init_schema(con)
                rows = con.execute("SELECT id, name, address FROM customers ORDER BY name COLLATE NOCASE").fetchall()
                if not rows:
                    import datetime
                    now = datetime.datetime.now().isoformat()
                    seen: dict[str, str] = {}
                    try:
                        inv_rows = con.execute("SELECT data FROM invoices").fetchall()
                        for (d,) in inv_rows:
                            try:
                                inv = json.loads(d)
                            except Exception:
                                continue
                            n = (inv.get("customer_name") or "").strip()
                            if n and n not in seen:
                                seen[n] = (inv.get("customer_address") or "").strip()
                    except Exception:
                        pass
                    if seen:
                        with con:
                            for n, a in seen.items():
                                con.execute(
                                    "INSERT OR IGNORE INTO customers (name, address, created, updated) VALUES (?, ?, ?, ?)",
                                    (n, a, now, now))
                        rows = con.execute("SELECT id, name, address FROM customers ORDER BY name COLLATE NOCASE").fetchall()
                return _customer_rows_to_dicts(rows)
            finally:
                con.close()
        except Exception as e:
            print(f"customers DB-Fallback: {e}")
    seen: dict[str, str] = {}
    for inv in get_all_invoices():
        n = (inv.get("customer_name") or "").strip()
        if n and n not in seen:
            seen[n] = inv.get("customer_address") or ""
    return [{"id": i + 1, "name": n, "address": a} for i, (n, a) in enumerate(sorted(seen.items()))]


def search_customers(query: str, limit: int = 10) -> list:
    q = (query or "").strip().lower()
    allc = get_all_customers()
    if not q:
        return allc[:limit]
    return [c for c in allc if q in c["name"].lower()][:limit]


def upsert_customer(name: str, address: str = "") -> dict | None:
    name = (name or "").strip()
    if not name:
        return None
    address = (address or "").strip()
    if _db_ready():
        try:
            from . import db as dbmod
            import datetime
            con = dbmod.connect()
            try:
                dbmod.init_schema(con)
                now = datetime.datetime.now().isoformat()
                with con:
                    con.execute(
                        "INSERT INTO customers (name, address, created, updated) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET address=excluded.address, updated=excluded.updated",
                        (name, address, now, now))
                row = con.execute("SELECT id, name, address FROM customers WHERE name=?", (name,)).fetchone()
                return {"id": row[0], "name": row[1], "address": row[2] or ""}
            finally:
                con.close()
        except Exception as e:
            print(f"upsert_customer fallback: {e}")
    return {"id": 0, "name": name, "address": address}


def delete_customer(customer_id: int) -> bool:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                with con:
                    cur = con.execute("DELETE FROM customers WHERE id=?", (customer_id,))
                return cur.rowcount > 0
            finally:
                con.close()
        except Exception:
            pass
    return False


def save_draft(data: dict) -> int:
    import datetime
    if _db_ready():
        from . import db as dbmod
        con = dbmod.connect()
        try:
            dbmod.init_schema(con)
            now = datetime.datetime.now().isoformat()
            with con:
                cur = con.execute("INSERT INTO drafts (data, updated) VALUES (?, ?)",
                                  (json.dumps(data, ensure_ascii=False, default=str), now))
                return cur.lastrowid
        finally:
            con.close()
    return 0


def list_drafts() -> list:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                rows = con.execute("SELECT id, data, updated FROM drafts ORDER BY id DESC LIMIT 20").fetchall()
                out = []
                for did, data, updated in rows:
                    try:
                        d = json.loads(data)
                    except Exception:
                        d = {}
                    d["_draft_id"] = did
                    d["_updated"] = updated
                    out.append(d)
                return out
            finally:
                con.close()
        except Exception:
            pass
    return []


def delete_draft(draft_id: int) -> bool:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                with con:
                    cur = con.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
                return cur.rowcount > 0
            finally:
                con.close()
        except Exception:
            pass
    return False


def peek_next_invoice_number() -> str:
    import datetime as _dt
    year = _dt.date.today().year
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                row = con.execute("SELECT last_number FROM counters WHERE year=?", (year,)).fetchone()
                last = row[0] if row else 0
                try:
                    rows = con.execute("SELECT id FROM invoices WHERE id LIKE ?", (f"RE-{year}%",)).fetchall()
                    nums = []
                    for (eid,) in rows:
                        try:
                            nums.append(int(eid.rsplit("-", 1)[-1]))
                        except ValueError:
                            pass
                    if nums:
                        last = max(last, max(nums))
                except Exception:
                    pass
                return f"RE-{year}-{last + 1:04d}"
            finally:
                con.close()
        except Exception:
            pass
    return f"RE-{year}-???"



# ---------------------------------------------------------------------------
# Recurring / Bank / Cashbook
# ---------------------------------------------------------------------------

def _generic_all(table: str) -> list:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                dbmod.init_schema(con)
                rows = con.execute(f"SELECT id, data FROM {table}").fetchall()
                out = []
                for rid, d in rows:
                    try:
                        e = json.loads(d)
                    except Exception:
                        continue
                    e["_row_id"] = rid
                    out.append(e)
                return out
            finally:
                con.close()
        except Exception as e:
            print(f"{table} DB-Fallback: {e}")
    return []


def _generic_insert(table: str, data: dict) -> int:
    if _db_ready():
        from . import db as dbmod
        con = dbmod.connect()
        try:
            dbmod.init_schema(con)
            with con:
                cur = con.execute(f"INSERT INTO {table} (data) VALUES (?)",
                                  (json.dumps(data, ensure_ascii=False, default=str),))
                return cur.lastrowid
        finally:
            con.close()
    return 0


def _generic_update(table: str, row_id: int, data: dict) -> bool:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                with con:
                    cur = con.execute(f"UPDATE {table} SET data=? WHERE id=?",
                                      (json.dumps(data, ensure_ascii=False, default=str), row_id))
                return cur.rowcount > 0
            finally:
                con.close()
        except Exception:
            pass
    return False


def _generic_delete(table: str, row_id: int) -> bool:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                with con:
                    cur = con.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
                return cur.rowcount > 0
            finally:
                con.close()
        except Exception:
            pass
    return False


def _generic_get(table: str, row_id: int) -> dict | None:
    for e in _generic_all(table):
        if e.get("_row_id") == row_id:
            return e
    return None


def get_recurring_profiles() -> list:
    return _generic_all("recurring")


def get_recurring_profile(row_id: int) -> dict | None:
    return _generic_get("recurring", row_id)


def save_recurring_profile(data: dict, row_id: int | None = None) -> int:
    data = dict(data)
    data.setdefault("active", True)
    if row_id:
        _generic_update("recurring", row_id, data)
        return row_id
    return _generic_insert("recurring", data)


def delete_recurring_profile(row_id: int) -> bool:
    return _generic_delete("recurring", row_id)


def run_due_recurring(create_fn) -> list:
    """Prüft fällige Abos (next_run <= heute), erstellt Rechnungen via create_fn(payload)->dict.
    Gibt Liste erstellter Rechnungsnummern zurück. Lazy-Cron: Aufruf bei Dashboard-Besuch."""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    created = []
    for p in get_recurring_profiles():
        if not p.get("active"):
            continue
        if (p.get("next_run") or "9999") > today:
            continue
        try:
            payload = {
                "customer_name": p.get("customer_name", ""),
                "customer_address": p.get("customer_address", ""),
                "items": p.get("items", []),
                "enable_btc": bool(p.get("enable_btc", False)),
                "doc_type": p.get("doc_type", "rechnung"),
                "payment_days": p.get("payment_days", 14),
                "discount_days": p.get("discount_days", 0),
                "discount_percent": p.get("discount_percent", 0),
            }
            res = create_fn(payload)
            created.append(res.get("invoice_no", "?"))
        except Exception as e:
            print(f"Recurring {p.get('_row_id')} fehlgeschlagen: {e}")
            continue
        freq = p.get("frequency", "monthly")
        try:
            nxt = _dt.date.fromisoformat(p.get("next_run") or today)
        except ValueError:
            nxt = _dt.date.today()
        if freq == "weekly":
            nxt = nxt + _dt.timedelta(days=7)
        elif freq == "quarterly":
            m = nxt.month + 3
            y = nxt.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            import calendar
            nxt = nxt.replace(year=y, month=m, day=min(nxt.day, calendar.monthrange(y, m)[1]))
        elif freq == "yearly":
            try:
                nxt = nxt.replace(year=nxt.year + 1)
            except ValueError:
                nxt = nxt + _dt.timedelta(days=365)
        else:
            m = nxt.month + 1
            y = nxt.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            import calendar
            nxt = nxt.replace(year=y, month=m, day=min(nxt.day, calendar.monthrange(y, m)[1]))
        p["next_run"] = nxt.isoformat()
        p["last_run"] = today
        _generic_update("recurring", p["_row_id"], {k: v for k, v in p.items() if not k.startswith("_")})
    return created


def get_bank_transactions() -> list:
    return _generic_all("bank_tx")


def import_bank_transactions(rows: list) -> int:
    n = 0
    existing = {(e.get("date"), e.get("amount"), e.get("purpose")) for e in get_bank_transactions()}
    for r in rows:
        key = (r.get("date"), r.get("amount"), r.get("purpose"))
        if key in existing:
            continue
        r.setdefault("matched_invoice", None)
        r.setdefault("status", "offen")
        _generic_insert("bank_tx", r)
        existing.add(key)
        n += 1
    return n


def set_bank_tx_match(row_id: int, invoice_id: str | None, status: str = "zugeordnet") -> bool:
    e = _generic_get("bank_tx", row_id)
    if not e:
        return False
    e["matched_invoice"] = invoice_id
    e["status"] = status
    return _generic_update("bank_tx", row_id, {k: v for k, v in e.items() if not k.startswith("_")})


def auto_match_bank() -> int:
    """Ordnet Bankbuchungen automatisch Rechnungen zu (Betrag + Nr. im Zweck)."""
    import re
    n = 0
    invoices = {i["id"]: i for i in get_all_invoices()}
    amounts: dict[str, list] = {}
    for iid, inv in invoices.items():
        if inv.get("payment_received"):
            continue
        amounts.setdefault(f"{float(inv.get('amount', 0)):.2f}", []).append(iid)
    for tx in get_bank_transactions():
        if tx.get("matched_invoice") or tx.get("status") != "offen":
            continue
        amt = float(tx.get("amount", 0))
        if amt <= 0:
            continue
        key = f"{amt:.2f}"
        cands = amounts.get(key, [])
        if not cands:
            continue
        chosen = None
        m = re.search(r"(RE|GS)-\d{4}-\d{2,6}", tx.get("purpose", "") or "")
        if m and m.group(0) in cands:
            chosen = m.group(0)
        elif len(cands) == 1:
            chosen = cands[0]
        if chosen:
            set_bank_tx_match(tx["_row_id"], chosen, "vorgeschlagen")
            n += 1
    return n


def get_cashbook_entries() -> list:
    entries = _generic_all("cashbook")
    for exp in get_active_expenses():
        if exp.get("payment_method") == "cash":
            entries.append({"_row_id": 0, "date": exp.get("date"), "type": "ausgabe",
                            "description": exp.get("description"), "amount": -abs(float(exp.get("amount", 0))),
                            "source": exp.get("id")})
    for inv in get_active_invoices():
        if inv.get("payment_received") and inv.get("payment_method") == "cash":
            entries.append({"_row_id": 0, "date": inv.get("payment_date") or inv.get("date"),
                            "type": "einnahme", "description": f"{inv.get('id')} {inv.get('customer_name')}",
                            "amount": abs(float(inv.get("amount", 0))), "source": inv.get("id")})
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    return entries


def overdue_invoices() -> list:
    import datetime as _dt
    today = _dt.date.today().isoformat()
    out = []
    for inv in get_active_invoices():
        if inv.get("payment_received") or inv.get("doc_type") == "gutschrift":
            continue
        due = inv.get("due_date") or inv.get("date")
        if due and due < today:
            try:
                days = (_dt.date.today() - _dt.date.fromisoformat(due[:10])).days
            except ValueError:
                days = 0
            inv = dict(inv)
            inv["_overdue_days"] = days
            out.append(inv)
    out.sort(key=lambda i: i.get("due_date") or "", reverse=False)
    return out


def apply_dunning(invoice_id: str, level: int, fee: float) -> dict | None:
    import datetime as _dt
    inv = get_invoice_by_id(invoice_id)
    if not inv or inv.get("payment_received"):
        return None
    def _mut(r):
        _append_audit_log("dunning_old", "invoice", invoice_id, dict(r))
        r["dunning_level"] = level
        r["dunning_fees"] = round(float(r.get("dunning_fees", 0)) + fee, 2)
        r["last_reminder"] = _dt.date.today().isoformat()
    updated = _update_invoice_row(invoice_id, _mut)
    if updated is not None:
        _append_audit_log("dunning_new", "invoice", invoice_id, dict(updated))
        return updated
    return None


# ---------------------------------------------------------------------------
# Angebote & Zeiterfassung
# ---------------------------------------------------------------------------

def _quote_rows() -> list:
    if _db_ready():
        try:
            from . import db as dbmod
            con = dbmod.connect()
            try:
                dbmod.init_schema(con)
                rows = con.execute("SELECT id, data FROM quotes ORDER BY id DESC").fetchall()
                out = []
                for rid, d in rows:
                    try:
                        out.append(json.loads(d))
                    except Exception:
                        continue
                return out
            finally:
                con.close()
        except Exception as e:
            print(f"quotes DB-Fallback: {e}")
    return []


def peek_next_quote_number() -> str:
    import datetime as _dt
    year = _dt.date.today().year
    nums = []
    for q in _quote_rows():
        if q.get("id", "").startswith(f"AN-{year}"):
            try:
                nums.append(int(q["id"].rsplit("-", 1)[-1]))
            except ValueError:
                pass
    return f"AN-{year}-{max(nums, default=0) + 1:04d}"


def save_quote(data: dict) -> dict:
    import datetime as _dt
    data = dict(data)
    if not data.get("id"):
        data["id"] = peek_next_quote_number()
    data.setdefault("date", _dt.date.today().isoformat())
    data.setdefault("status", "offen")
    if _db_ready():
        from . import db as dbmod
        con = dbmod.connect()
        try:
            dbmod.init_schema(con)
            with con:
                con.execute("INSERT OR REPLACE INTO quotes (id, data) VALUES (?, ?)",
                            (data["id"], json.dumps(data, ensure_ascii=False, default=str)))
            return data
        finally:
            con.close()
    return data


def get_quote(quote_id: str) -> dict | None:
    for q in _quote_rows():
        if q.get("id") == quote_id:
            return q
    return None


def get_all_quotes() -> list:
    return _quote_rows()


def set_quote_status(quote_id: str, status: str) -> dict | None:
    q = get_quote(quote_id)
    if not q:
        return None
    q["status"] = status
    return save_quote(q)


def get_time_entries(unbilled_only: bool = False) -> list:
    entries = [e for e in _generic_all("timelog")]
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    if unbilled_only:
        entries = [e for e in entries if not e.get("billed_invoice")]
    return entries


def add_time_entry(date: str, customer_name: str, description: str, hours: float, rate: float) -> int:
    return _generic_insert("timelog", {
        "date": date, "customer_name": (customer_name or "").strip(),
        "description": (description or "").strip(),
        "hours": float(hours), "rate": float(rate),
        "amount": round(float(hours) * float(rate), 2),
        "billed_invoice": None,
    })


def delete_time_entry(row_id: int) -> bool:
    return _generic_delete("timelog", row_id)


def mark_time_billed(row_ids: list, invoice_id: str) -> int:
    n = 0
    for rid in row_ids:
        e = _generic_get("timelog", int(rid))
        if e and not e.get("billed_invoice"):
            e["billed_invoice"] = invoice_id
            if _generic_update("timelog", int(rid), {k: v for k, v in e.items() if not k.startswith("_")}):
                n += 1
    return n


# ---------------------------------------------------------------------------
# Anlagevermögen / AfA
# ---------------------------------------------------------------------------

GWG_LIMIT = 800.0


def get_assets() -> list:
    entries = _generic_all("assets")
    entries.sort(key=lambda e: e.get("purchase_date", ""))
    return entries


def add_asset(name: str, purchase_date: str, cost: float, years: int) -> int:
    cost = float(cost)
    is_gwg = cost <= GWG_LIMIT
    return _generic_insert("assets", {
        "name": name.strip(), "purchase_date": purchase_date,
        "cost": round(cost, 2), "years": int(years) if not is_gwg else 1,
        "is_gwg": is_gwg,
    })


def delete_asset(row_id: int) -> bool:
    return _generic_delete("assets", row_id)


def afa_for_year(year: int) -> list:
    """Lineare AfA pro Anlagegut für ein Jahr (pro-rata Monat ab Kaufmonat).
    GWG (<=800 EUR): voll im Kaufjahr."""
    out = []
    for a in get_assets():
        try:
            pdate = a.get("purchase_date", "")[:10]
            py, pm = int(pdate[:4]), int(pdate[5:7])
        except (ValueError, TypeError):
            continue
        cost = float(a.get("cost", 0))
        if a.get("is_gwg"):
            if py == year:
                out.append({**a, "afa": round(cost, 2), "note": "GWG-Sofortabschreibung"})
            continue
        years = max(1, int(a.get("years", 3)))
        annual = cost / years
        first_year_months = 13 - pm
        if year == py:
            out.append({**a, "afa": round(annual * first_year_months / 12, 2),
                        "note": f"pro-rata {first_year_months}/12"})
        elif py < year < py + years:
            if year == py + years - 1 and first_year_months < 12:
                rest = round(cost - sum(
                    (annual * first_year_months / 12) if y == py else annual
                    for y in range(py, year)), 2)
                out.append({**a, "afa": rest, "note": "Restjahr"})
            else:
                out.append({**a, "afa": round(annual, 2), "note": "volles Jahr"})
    return out


def afa_total(year: int) -> float:
    return round(sum(e["afa"] for e in afa_for_year(year)), 2)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def get_monthly_summary(year: int, month: int) -> dict:
    month_str = f"{year}-{month:02d}"
    invoices = [i for i in get_active_invoices() if i["date"].startswith(month_str)]
    expenses = [e for e in get_active_expenses() if e["date"].startswith(month_str)]

    total_income = sum(i["amount"] for i in invoices)
    total_expenses = sum(e["amount"] for e in expenses)

    expenses_by_category = {}
    for e in expenses:
        cat = e["category"]
        expenses_by_category[cat] = expenses_by_category.get(cat, 0) + e["amount"]

    return {
        "year": year,
        "month": month,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "profit": total_income - total_expenses,
        "income_count": len(invoices),
        "expense_count": len(expenses),
        "expenses_by_category": expenses_by_category,
    }


def get_yearly_summary(year: int) -> dict:
    monthly = [get_monthly_summary(year, m) for m in range(1, 13)]
    return {
        "year": year,
        "total_income": sum(m["total_income"] for m in monthly),
        "total_expenses": sum(m["total_expenses"] for m in monthly),
        "profit": sum(m["profit"] for m in monthly),
        "monthly_breakdown": monthly,
    }


def get_recent_transactions(limit: int = 10) -> list:
    """Get recent income and expenses combined, sorted by date descending."""
    transactions = []
    for inv in get_active_invoices():
        transactions.append({
            "date": inv["date"],
            "type": "Einnahme",
            "description": f"{inv['id']} – {inv['customer_name']}",
            "amount": inv["amount"],
        })
    for exp in get_active_expenses():
        transactions.append({
            "date": exp["date"],
            "type": "Ausgabe",
            "description": exp["description"],
            "amount": -exp["amount"],
        })
    transactions.sort(key=lambda t: t["date"], reverse=True)
    return transactions[:limit]


def generate_euer(year: int) -> dict:
    expenses = [e for e in get_active_expenses() if e["date"].startswith(str(year))]
    invoices = [i for i in get_active_invoices() if i["date"].startswith(str(year))]

    category_mapping = {
        "material_costs": ["studio_supplies"],
        "depreciation": ["equipment", "equipment_repair"],
        "vehicle_costs": ["vehicle", "travel"],
        "rent_costs": ["rent"],
        "advertising_costs": ["marketing", "website"],
        "other_business_expenses": [
            "software", "office_supplies", "internet_phone",
            "education", "insurance", "legal_tax",
            "bank_fees", "other",
        ],
    }

    expense_totals = {}
    for tax_cat, app_cats in category_mapping.items():
        expense_totals[tax_cat] = sum(
            e["amount"] for e in expenses if e["category"] in app_cats
        )

    afa = afa_total(year)
    expense_totals["depreciation"] = expense_totals.get("depreciation", 0) + afa
    gross_revenue = sum(i["amount"] for i in invoices)
    total_expenses = sum(expense_totals.values())

    return {
        "year": year,
        "gross_revenue": gross_revenue,
        **expense_totals,
        "afa_amount": afa,
        "total_expenses": total_expenses,
        "operating_result": gross_revenue - total_expenses,
    }


# ---------------------------------------------------------------------------
# UStVA (Umsatzsteuervoranmeldung)
# ---------------------------------------------------------------------------

def calculate_ustva(year: int, period: int, period_type: str = "quarter") -> dict:
    """Berechnet die UStVA für ein Quartal oder Monat.
    period_type: 'quarter' (period: 1-4) oder 'month' (period: 1-12)"""
    invoices = get_active_invoices()
    expenses = get_active_expenses()

    if period_type == "month":
        months = [period]
        period_label = f"Monat {period}/{year}"
    else:
        quarter_months = {1: [1,2,3], 2: [4,5,6], 3: [7,8,9], 4: [10,11,12]}
        months = quarter_months.get(period, [1,2,3])
        period_label = f"Q{period}/{year}"

    # Umsatzsteuer auf Einnahmen
    ust_19 = 0.0
    ust_7 = 0.0
    net_19 = 0.0
    net_7 = 0.0
    revenue_total = 0.0

    for inv in invoices:
        inv_date = inv["date"]
        try:
            inv_year = int(inv_date[:4])
            inv_month = int(inv_date[5:7])
        except (ValueError, IndexError):
            continue
        if inv_year == year and inv_month in months:
            revenue_total += inv["amount"]
            for item in inv.get("items", []):
                item_net = item["quantity"] * item["unit_price"]
                vat_rate = item.get("vat_rate", 0.0)
                vat_amount = item_net * vat_rate
                if vat_rate == 0.19:
                    ust_19 += vat_amount
                    net_19 += item_net
                elif vat_rate == 0.07:
                    ust_7 += vat_amount
                    net_7 += item_net

    # Vorsteuer auf Ausgaben
    vorsteuer_total = 0.0
    expenses_total = 0.0

    for exp in expenses:
        exp_date = exp["date"]
        try:
            exp_year = int(exp_date[:4])
            exp_month = int(exp_date[5:7])
        except (ValueError, IndexError):
            continue
        if exp_year == year and exp_month in months:
            expenses_total += exp["amount"]
            vorsteuer_total += exp.get("vat_amount", 0.0)

    ustva_betrag = ust_19 + ust_7 - vorsteuer_total

    return {
        "year": year,
        "period": period,
        "period_type": period_type,
        "period_label": period_label,
        "months": months,
        "ust_19": round(ust_19, 2),
        "ust_7": round(ust_7, 2),
        "net_19": round(net_19, 2),
        "net_7": round(net_7, 2),
        "vorsteuer": round(vorsteuer_total, 2),
        "ustva_betrag": round(ustva_betrag, 2),
        "is_erstattung": ustva_betrag < 0,
        "revenue_total": round(revenue_total, 2),
        "expenses_total": round(expenses_total, 2),
    }
