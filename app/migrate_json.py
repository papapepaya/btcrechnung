import json
import os
import shutil
import zipfile
import datetime

from . import db as dbmod


def _load_list(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except Exception:
        return []


def _load_dict(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def backup_json(data_dir: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(data_dir, f"backup-json-{ts}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("invoices.json", "expenses.json", "settings.json", "audit.json", "invoice_counter.json"):
            p = os.path.join(data_dir, name)
            if os.path.exists(p):
                z.write(p, arcname=name)
    return dest


def migrate_once() -> bool:
    dbmod.init_schema()
    con = dbmod.connect()
    try:
        if not dbmod.is_empty(con):
            return False
        data_dir = dbmod.DATA_DIR
        inv = _load_list(os.path.join(data_dir, "invoices.json"))
        exp = _load_list(os.path.join(data_dir, "expenses.json"))
        audit = _load_list(os.path.join(data_dir, "audit.json"))
        settings = _load_dict(os.path.join(data_dir, "settings.json"))
        counter = _load_dict(os.path.join(data_dir, "invoice_counter.json"))
        if not inv and not exp and not settings:
            return False
        backup_json(data_dir)
        con.execute("BEGIN IMMEDIATE")
        try:
            for k, v in settings.items():
                con.execute("INSERT OR REPLACE INTO kv_settings (key, value) VALUES (?, ?)",
                            (k, json.dumps(v, ensure_ascii=False, default=str)))
            for row in inv:
                rid = row.get("id")
                if rid:
                    con.execute("INSERT OR REPLACE INTO invoices (id, data) VALUES (?, ?)",
                                (rid, json.dumps(row, ensure_ascii=False, default=str)))
            for row in exp:
                rid = row.get("id")
                if rid:
                    con.execute("INSERT OR REPLACE INTO expenses (id, data) VALUES (?, ?)",
                                (rid, json.dumps(row, ensure_ascii=False, default=str)))
            for entry in audit:
                con.execute("INSERT INTO audit (data) VALUES (?)",
                            (json.dumps(entry, ensure_ascii=False, default=str),))
            if counter.get("year"):
                con.execute("INSERT OR REPLACE INTO counters (year, last_number) VALUES (?, ?)",
                            (int(counter["year"]), int(counter.get("last_number", 0))))
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        return True
    finally:
        con.close()
