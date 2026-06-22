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
}


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_json(filepath: str) -> list:
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(filepath: str, data: list):
    _ensure_data_dir()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)


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

def get_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return dict(DEFAULT_SETTINGS)
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        settings = json.load(f)
    # Fehlende Defaults auffüllen
    for key, val in DEFAULT_SETTINGS.items():
        settings.setdefault(key, val)
    return settings


def save_settings(settings: dict):
    _ensure_data_dir()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, default=str, ensure_ascii=False)


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
    log = _load_json(AUDIT_FILE)
    log.append(entry)
    _save_json(AUDIT_FILE, log)


def get_audit_log(record_type: str = None, record_id: str = None) -> list:
    """Gibt das Audit-Log gefiltert zurück."""
    log = _load_json(AUDIT_FILE)
    if record_type:
        log = [e for e in log if e.get("record_type") == record_type]
    if record_id:
        log = [e for e in log if e.get("record_id") == record_id]
    return log


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

def get_all_expenses() -> list:
    data = _load_json(EXPENSES_FILE)
    return _migrate_status(data)


def get_expense(expense_id: str) -> Optional[dict]:
    return next((e for e in get_all_expenses() if e["id"] == expense_id), None)


def create_expense(data: dict) -> dict:
    expenses = get_all_expenses()
    data["status"] = "aktiv"
    year = datetime.date.today().year
    existing = [e for e in expenses if e["id"].startswith(f"EXP-{year}")]
    next_num = len(existing) + 1
    data["id"] = f"EXP-{year}-{next_num:04d}"
    data["audit_hash"] = _compute_checksum(data)
    expenses.append(data)
    _save_json(EXPENSES_FILE, expenses)
    _append_audit_log("create", "expense", data["id"], data)
    return data


def update_expense(expense_id: str, data: dict) -> Optional[dict]:
    expenses = get_all_expenses()
    for i, e in enumerate(expenses):
        if e["id"] == expense_id:
            data["id"] = expense_id
            expenses[i] = data
            _save_json(EXPENSES_FILE, expenses)
            return data
    return None


def cancel_expense(expense_id: str, reason: str = "") -> bool:
    expenses = get_all_expenses()
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
    data = _load_json(INVOICES_FILE)
    return _migrate_status(data)


def get_invoice_by_id(invoice_id: str) -> Optional[dict]:
    for inv in get_all_invoices():
        if inv["id"] == invoice_id:
            return inv
    return None


def log_invoice(data: dict) -> dict:
    invoices = get_all_invoices()
    data["status"] = "aktiv"
    data["audit_hash"] = _compute_checksum(data)
    invoices.append(data)
    _save_json(INVOICES_FILE, invoices)
    _append_audit_log("create", "invoice", data["id"], data)
    return data


def mark_invoice_paid(invoice_id: str, payment_date: str,
                      btc_received: float = None, eur_value: float = None,
                      txid: str = None, payment_method: str = None) -> Optional[dict]:
    invoices = get_all_invoices()
    for inv in invoices:
        if inv["id"] == invoice_id:
            # Alten Stand im Audit-Log speichern
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
    invoices = get_all_invoices()
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

    gross_revenue = sum(i["amount"] for i in invoices)
    total_expenses = sum(expense_totals.values())

    return {
        "year": year,
        "gross_revenue": gross_revenue,
        **expense_totals,
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
