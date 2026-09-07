import os
import io
import csv
import base64
import datetime
import json
import hashlib
import hmac
import secrets
import sys
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, Response, HTTPException, Form, UploadFile, File, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from pydantic import BaseModel
import qrcode
from jinja2 import Environment, FileSystemLoader
import requests

from .zugferd import generate_zugferd_xml
from . import bookkeeping as bk
from .models import (
    CATEGORY_LABELS, PAYMENT_METHOD_LABELS, CATEGORY_EUER_LINE,
    ExpenseCreate,
)

# PDF und ZUGFeRD Bibliotheken mit sicherem Import
try:
    import xhtml2pdf.pisa as pisa
except ImportError:
    pisa = None

try:
    import facturx
except ImportError:
    facturx = None

try:
    from bip_utils import Bip84, Bip84Coins, Bip44Changes
except ImportError:
    Bip84 = None

app = FastAPI(title="BTCRechnung")

# PyInstaller: sys._MEIPASS ist das temporäre Verzeichnis beim Entpacken
if getattr(sys, '_MEIPASS', False):
    BASE_DIR = os.path.join(sys._MEIPASS, 'app')
    PROJECT_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_DIR = os.path.dirname(BASE_DIR)

# Datenverzeichnis: Immer neben der App (nicht im Bundle)
if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(os.path.dirname(sys.executable), 'data')
else:
    DATA_DIR = os.path.join(PROJECT_DIR, 'data')

TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
LOGO_PATH = os.path.join(PROJECT_DIR, "logo.png")
CUSTOM_LOGO_PATH = os.path.join(DATA_DIR, "logo.png")
BTC_ICON_PATH = os.path.join(PROJECT_DIR, "Bitcoin.png")
if not os.path.exists(BTC_ICON_PATH):
    BTC_ICON_PATH = os.path.join(PROJECT_DIR, "Bitcoin.svg")
COUNTER_FILE = os.path.join(DATA_DIR, "invoice_counter.json")
PDF_DIR = os.path.join(DATA_DIR, "invoices")
RECEIPTS_DIR = os.path.join(DATA_DIR, "receipts")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(RECEIPTS_DIR, exist_ok=True)

env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


class SimpleTemplates:
    """Einfache Template-Klasse die raw Jinja2 statt Starlette's Jinja2Templates nutzt.
    Vermeidet den 'unhashable dict' Bug mit PyInstaller."""
    def __init__(self, env):
        self.env = env
    def TemplateResponse(self, name, context, status_code: int = 200):
        from starlette.responses import HTMLResponse
        # Business-Typ und Pro-Status automatisch injizieren
        if "is_pro" not in context:
            try:
                context["is_pro"] = is_pro_license()
            except Exception:
                context["is_pro"] = False
        if "has_license" not in context:
            try:
                context["has_license"] = get_license_tier() != "none"
            except Exception:
                context["has_license"] = False
        if "business_type" not in context:
            try:
                bt = bk.get_settings().get("business_type", "kleinunternehmer")
                # Ohne Pro-Lizenz immer Kleinunternehmer
                context["business_type"] = bt if context.get("is_pro") else "kleinunternehmer"
            except Exception:
                context["business_type"] = "kleinunternehmer"
        if "csrf_token" not in context:
            try:
                from . import auth as authmod
                req = context.get("request")
                tok = req.cookies.get("session") if req is not None else None
                context["csrf_token"] = authmod.csrf_token_for_session(bk, tok) if tok else ""
            except Exception:
                context["csrf_token"] = ""
        if "purchase_url" not in context:
            context["purchase_url"] = os.environ.get(
                "PURCHASE_URL", "https://buy.stripe.com/8x2eV64zxeFh7F9bf628804")
        if "app_version" not in context:
            try:
                from .version import get_version
                context["app_version"] = get_version()
            except Exception:
                context["app_version"] = "?"
        html = self.env.get_template(name).render(**context)
        return HTMLResponse(html, status_code=status_code)


templates = SimpleTemplates(env)

# Static files (PWA manifest, icons, service worker)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Auth – Passwort-Login
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    from . import auth as authmod
    return authmod.hash_password(password)


def _verify_password(password: str, stored: str) -> bool:
    from . import auth as authmod
    return authmod.verify_password(password, stored)


# ---------------------------------------------------------------------------
# Lizenzschlüssel-System
# ---------------------------------------------------------------------------

LICENSE_SECRET = "BTCRechnung-2026-Secret-Key"


def ensure_license_salt() -> str:
    """Stellt sicher, dass ein Salt existiert und gibt ihn zurück."""
    settings = bk.get_settings()
    if not settings.get("license_salt"):
        import secrets
        settings["license_salt"] = secrets.token_hex(16)
        bk.save_settings(settings)
    return settings["license_salt"]


def generate_license_key(email: str) -> str:
    from . import license as licmod
    settings = bk.get_settings()
    secret = settings.get("license_salt") or LICENSE_SECRET
    return licmod.legacy_key_for(email, secret)


def verify_license(email: str, license_key: str) -> bool:
    from . import license as licmod
    if not email or not license_key:
        return False
    lk = license_key.strip()
    if lk.upper().startswith("PRO2-"):
        return licmod.verify_ed25519(email, lk)
    if lk.upper().startswith("FREE-"):
        return licmod.verify_free(email, lk)
    if lk.upper().startswith("BASIC-"):
        return licmod.verify_basic(email, lk)
    settings = bk.get_settings()
    if licmod.verify_legacy(email, lk, settings.get("license_salt")):
        return True
    return licmod.verify_legacy(email, lk, None)


def is_pro_license() -> bool:
    """Prüft ob eine gültige Pro-Lizenz vorhanden ist (Free-Keys zählen nicht)."""
    settings = bk.get_settings()
    key = settings.get("license_key", "")
    if key.strip().upper().startswith(("FREE-", "BASIC-")):
        return False
    return verify_license(
        settings.get("license_email", ""),
        key
    )


def get_license_tier() -> str:
    """Gibt 'pro', 'free' oder 'none' zurück."""
    from .license import license_tier
    settings = bk.get_settings()
    return license_tier(settings.get("license_email", ""),
                        settings.get("license_key", ""),
                        settings.get("license_salt"))


def free_limit_reached() -> bool:
    """True wenn Free-Tarif am Monatslimit (3 Rechnungen) ist. Pro/unlizenziert: False."""
    from .license import FREE_MONTHLY_LIMIT
    if get_license_tier() != "free":
        return False
    return len(bk.invoices_this_month()) >= FREE_MONTHLY_LIMIT


def get_license_status() -> dict:
    """Gibt den Lizenzstatus zurück."""
    settings = bk.get_settings()
    email = settings.get("license_email", "")
    key = settings.get("license_key", "")
    is_valid = verify_license(email, key) if email and key else False
    tier = get_license_tier() if is_valid else "none"
    return {
        "email": email,
        "key": key,
        "is_valid": is_valid,
        "type": tier,
        "free_used": len(bk.invoices_this_month()) if tier == "free" else 0,
        "free_limit": 3,
    }


def _get_session_secret() -> str:
    settings = bk.get_settings()
    secret = settings.get("session_secret")
    if not secret:
        secret = secrets.token_hex(32)
        settings["session_secret"] = secret
        bk.save_settings(settings)
    return secret


def _is_setup_needed() -> bool:
    settings = bk.get_settings()
    return settings.get("password_hash") is None


def _is_authenticated(request: Request) -> bool:
    from . import auth as authmod
    return authmod.is_valid_session(bk, request.cookies.get("session"))


def _make_session_token() -> str:
    from . import auth as authmod
    return authmod.create_session(bk)


def _set_session_cookie(response: Response, token: str, request: Request | None = None):
    secure = False
    try:
        if request is not None and request.url.scheme == "https":
            secure = True
    except Exception:
        pass
    response.set_cookie("session", token, httponly=True, samesite="lax", secure=secure, max_age=86400 * 30)


# ---------------------------------------------------------------------------
# Endpoints – Login
# ---------------------------------------------------------------------------

PUBLIC_PATHS = {"/login", "/setup", "/health", "/favicon.ico"}


@app.get("/setup")
async def setup_page(request: Request):
    if not _is_setup_needed():
        return Response(status_code=302, headers={"Location": "/login"})
    return templates.TemplateResponse("setup.html", {"request": request})


@app.post("/setup")
async def setup_save(request: Request):
    if not _is_setup_needed():
        return Response(status_code=302, headers={"Location": "/login"})
    form = await request.form()
    password = form.get("password", "")
    password_confirm = form.get("password_confirm", "")
    if len(password) < 8:
        return templates.TemplateResponse("setup.html", {
            "request": request, "error": "Passwort muss mindestens 8 Zeichen lang sein."
        })
    if password != password_confirm:
        return templates.TemplateResponse("setup.html", {
            "request": request, "error": "Passwörter stimmen nicht überein."
        })
    settings = bk.get_settings()
    settings["password_hash"] = _hash_password(password)
    bk.save_settings(settings)
    response = Response(status_code=302, headers={"Location": "/"})
    _set_session_cookie(response, _make_session_token(), request)
    return response


@app.get("/login")
async def login_page(request: Request):
    if _is_setup_needed():
        return Response(status_code=302, headers={"Location": "/setup"})
    if _is_authenticated(request):
        return Response(status_code=302, headers={"Location": "/"})
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login_submit(request: Request):
    from . import auth as authmod
    if authmod.is_blocked(request):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Zu viele Versuche. Bitte 60 Sekunden warten."
        })
    form = await request.form()
    password = form.get("password", "")
    settings = bk.get_settings()
    if _is_setup_needed():
        return Response(status_code=302, headers={"Location": "/setup"})
    if _verify_password(password, settings.get("password_hash", "")):
        authmod.record_success(request)
        response = Response(status_code=302, headers={"Location": "/"})
        _set_session_cookie(response, _make_session_token(), request)
        return response
    authmod.record_fail(request)
    return templates.TemplateResponse("login.html", {
        "request": request, "error": "Falsches Passwort."
    })


@app.get("/logout")
async def logout(request: Request):
    from . import auth as authmod
    authmod.destroy_session(bk, request.cookies.get("session"))
    response = Response(status_code=302, headers={"Location": "/login"})
    response.delete_cookie("session")
    return response


CSRF_EXEMPT = {"/login", "/setup", "/health", "/generate-pdf", "/webhook/btcpay"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    from . import auth as authmod
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static") or path.startswith("/pay/") or path.startswith("/api/pay/") or path.startswith("/webhook/"):
        return await call_next(request)
    if _is_setup_needed():
        return Response(status_code=302, headers={"Location": "/setup"})
    if not _is_authenticated(request):
        return Response(status_code=302, headers={"Location": "/login"})
    # Lizenz-Gate: ohne gültigen Key (free/pro) nur Einstellungen + Lizenz-Aktivierung.
    # Öffentlich bleiben: /settings (GET), /settings/license (POST), /logout, API zahlt 402.
    if get_license_tier() == "none" and path not in ("/settings", "/settings/license", "/logout"):
        if path.startswith("/api/") or path in ("/generate-pdf", "/drafts/save"):
            return Response(status_code=402, content="Lizenz erforderlich – bitte Key unter Einstellungen → Lizenz eintragen.")
        return Response(status_code=302, headers={"Location": "/settings?license_required=1"})
    if request.method == "POST" and path not in CSRF_EXEMPT:
        try:
            # body() ZUERST aufrufen: cached den Body, damit Downstream
            # (Route) das Formular erneut lesen kann (Starlette replayt nur
            # _body, nicht einen per stream() konsumierten Body).
            await request.body()
            form = await request.form()
            provided = form.get("_csrf") or request.headers.get("x-csrf-token")
        except Exception:
            provided = request.headers.get("x-csrf-token")
        if not authmod.check_csrf(bk, request.cookies.get("session"), provided):
            return Response(status_code=403, content="CSRF-Check fehlgeschlagen")
    resp = await call_next(request)
    if request.cookies.get("session") and "csrf_token" not in request.cookies:
        try:
            resp.set_cookie("csrf_token", authmod.csrf_token_for_session(bk, request.cookies.get("session")), samesite="lax", max_age=86400 * 30)
        except Exception:
            pass
    return resp

MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni",
               "Juli", "August", "September", "Oktober", "November", "Dezember"]


def get_business_info():
    """Liest Firmendaten aus settings.json."""
    s = bk.get_settings()
    return {
        "name": s.get("business_name") or "Firma",
        "address": s.get("business_address") or "",
        "slogan": s.get("business_slogan") or "",
        "phone": s.get("business_phone") or "",
        "email": s.get("business_email") or "",
    }


def _get_available_years():
    """Liest alle Jahre aus invoices.json und expenses.json,
    plus aktuelles Jahr und 4 Vorjahre, gibt sortierte Liste zurück."""
    all_years = set()
    for inv in bk.get_all_invoices():
        if inv.get("date"):
            try:
                all_years.add(int(inv["date"][:4]))
            except (ValueError, IndexError):
                pass
    for exp in bk.get_all_expenses():
        if exp.get("date"):
            try:
                all_years.add(int(exp["date"][:4]))
            except (ValueError, IndexError):
                pass
    current = datetime.date.today().year
    # Immer aktuelles Jahr + 4 Vorjahre anbieten
    for y in range(current - 4, current + 1):
        all_years.add(y)
    return sorted(all_years, reverse=True)


# ---------------------------------------------------------------------------
# Invoice-Counter (persistente Rechnungsnummer)
# ---------------------------------------------------------------------------

def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _get_next_invoice_number() -> str:
    _ensure_data_dir()
    year = datetime.date.today().year
    try:
        from . import db as dbmod
        dbmod.init_schema()
        con = dbmod.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
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
            last += 1
            con.execute("INSERT OR REPLACE INTO counters (year, last_number) VALUES (?, ?)", (year, last))
            con.execute("COMMIT")
            return f"RE-{year}-{last:04d}"
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            con.close()
    except Exception as e:
        print(f"Counter DB-Fallback: {e}")
    counter = {"year": year, "last_number": 0}
    lock_path = COUNTER_FILE + ".lock"
    try:
        import fcntl
        use_fcntl = True
    except ImportError:
        use_fcntl = False
    os.makedirs(os.path.dirname(COUNTER_FILE), exist_ok=True)
    with open(lock_path, "w") as lock_fp:
        try:
            if use_fcntl:
                fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)
            if os.path.exists(COUNTER_FILE):
                try:
                    with open(COUNTER_FILE, "r") as f:
                        saved = json.load(f)
                    if saved.get("year") == year:
                        counter = saved
                except (json.JSONDecodeError, IOError):
                    pass
            counter["year"] = year
            counter["last_number"] += 1
            tmp = COUNTER_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(counter, f)
            os.replace(tmp, COUNTER_FILE)
        finally:
            try:
                if use_fcntl:
                    fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    return f"RE-{year}-{counter['last_number']:04d}"


class InvoiceItem(BaseModel):
    description: str
    quantity: float
    unit_price: float
    vat_rate: float = 0.0


class InvoiceRequest(BaseModel):
    customer_name: str
    customer_address: str
    items: List[InvoiceItem]
    # Bitcoin Details (optional)
    btc_address: Optional[str] = None
    # Bank Details (optional, aus Settings geladen)
    iban: Optional[str] = None
    bic: Optional[str] = None
    bank_name: Optional[str] = None
    # Bitcoin aktivieren
    enable_btc: bool = False
    doc_type: str = "rechnung"
    buyer_reference: Optional[str] = None
    time_entry_ids: List[int] = []
    payment_days: int = 14
    discount_days: int = 0
    discount_percent: float = 0.0
    invoice_date: Optional[str] = None
    preview: bool = False


def get_logo_path():
    """Gibt den Pfad zum Logo zurück: Custom Logo oder Fallback.
    Gibt None zurück wenn Logo ausgeblendet ist."""
    settings = bk.get_settings()
    if settings.get("logo_hidden"):
        return None
    if os.path.exists(CUSTOM_LOGO_PATH):
        return CUSTOM_LOGO_PATH
    if os.path.exists(LOGO_PATH):
        return LOGO_PATH
    return None


from .pdf_utils import get_image_base64 as _get_image_base64
from .pdf_utils import generate_qr_base64 as _generate_qr_base64
from .pdf_utils import generate_girocode_data as _generate_girocode_data
from . import bitcoin as btcmod


def get_image_base64(path, max_height=None):
    return _get_image_base64(path, max_height)


def generate_qr_base64(data: str):
    return _generate_qr_base64(data)


def generate_girocode_data(name: str, iban: str, bic: str, amount: float, purpose: str):
    return _generate_girocode_data(name, iban, bic, amount, purpose)


def get_btc_price_eur():
    return btcmod.get_btc_price_eur()


def derive_btc_address(xpub: str, index: int) -> str:
    return btcmod.derive_btc_address(xpub, index)


def get_next_btc_address() -> Optional[str]:
    return btcmod.get_next_btc_address(bk)


def check_btc_payment(address: str) -> dict:
    return btcmod.check_btc_payment(address)


# ---------------------------------------------------------------------------
# Endpoints – Rechnungen
# ---------------------------------------------------------------------------

@app.get("/")
async def root_redirect():
    return Response(status_code=302, headers={"Location": "/dashboard"})


@app.get("/invoice")
async def form_page(request: Request):
    """Zeigt das Eingabeformular für Rechnungen."""
    settings = bk.get_settings()
    business_type = settings.get("business_type", "kleinunternehmer")
    if not is_pro_license():
        business_type = "kleinunternehmer"
    return templates.TemplateResponse("form.html", {
        "request": request,
        "active_page": "invoice",
        "business_type": business_type,
        "has_iban": bool(settings.get("bank_iban")),
        "has_btc": bool(settings.get("btc_xpub")),
        "next_invoice_no": bk.peek_next_invoice_number(),
        "customers": bk.get_all_customers(),
        "drafts": bk.list_drafts(),
        "default_payment_days": settings.get("default_payment_days", 14),
    })


@app.get("/api/customers")
async def api_customers(q: str = ""):
    return bk.search_customers(q)


@app.get("/customers")
async def customers_page(request: Request):
    return templates.TemplateResponse("customers.html", {
        "request": request,
        "active_page": "customers",
        "customers": bk.get_all_customers(),
    })


@app.post("/customers")
async def customers_create(
    request: Request,
    name: str = Form(...),
    address: str = Form(""),
    leitweg_id: str = Form(""),
):
    bk.upsert_customer(name, address, leitweg_id)
    return Response(status_code=302, headers={"Location": "/customers"})


@app.post("/customers/{customer_id}/delete")
async def customers_delete(customer_id: int):
    bk.delete_customer(customer_id)
    return Response(status_code=302, headers={"Location": "/customers"})


@app.post("/drafts/save")
async def drafts_save(request: Request):
    form = await request.form()
    import json as _json
    raw = form.get("data", "{}")
    try:
        data = _json.loads(raw)
    except Exception:
        data = {}
    did = bk.save_draft(data)
    return {"id": did}


@app.post("/drafts/{draft_id}/delete")
async def drafts_delete(draft_id: int):
    bk.delete_draft(draft_id)
    return Response(status_code=302, headers={"Location": "/invoice"})


@app.get("/api/next-invoice-no")
async def api_next_invoice_no():
    return {"next": bk.peek_next_invoice_number()}


# ---------------------------------------------------------------------------
# Endpoints – Angebote & Zeiterfassung
# ---------------------------------------------------------------------------

@app.get("/quotes")
async def quotes_page(request: Request):
    return templates.TemplateResponse("quotes.html", {
        "request": request, "active_page": "quotes",
        "quotes": bk.get_all_quotes(),
        "next_no": bk.peek_next_quote_number(),
        "customers": bk.get_all_customers(),
        "today": datetime.date.today().isoformat(),
    })


@app.post("/quotes")
async def quotes_create(request: Request):
    form = await request.form()
    import json as _json
    try:
        items = _json.loads(form.get("items_json", "[]"))
    except Exception:
        items = []
    if not items:
        items = [{"description": (form.get("item_desc") or "").strip(), "quantity": 1,
                  "unit_price": float((form.get("item_price") or "0").replace(",", ".") or 0), "vat_rate": 0}]
    valid_days = int(form.get("valid_days") or 30)
    qdate = form.get("quote_date") or datetime.date.today().isoformat()
    try:
        valid_until = (datetime.date.fromisoformat(qdate) + datetime.timedelta(days=valid_days)).isoformat()
    except ValueError:
        valid_until = qdate
    bk.save_quote({
        "customer_name": (form.get("customer_name") or "").strip(),
        "customer_address": form.get("customer_address", ""),
        "items": items, "date": qdate, "valid_until": valid_until,
        "valid_days": valid_days, "status": "offen", "notes": form.get("notes", ""),
    })
    try:
        bk.upsert_customer(form.get("customer_name", ""), form.get("customer_address", ""))
    except Exception:
        pass
    return Response(status_code=302, headers={"Location": "/quotes"})


@app.post("/quotes/{quote_id}/status")
async def quotes_status(quote_id: str, status: str = Form(...)):
    if status not in ("offen", "angenommen", "abgelehnt"):
        raise HTTPException(status_code=400, detail="Ungültiger Status")
    bk.set_quote_status(quote_id, status)
    return Response(status_code=302, headers={"Location": "/quotes"})


@app.get("/quotes/{quote_id}/pdf")
async def quotes_pdf(quote_id: str):
    q = bk.get_quote(quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Angebot nicht gefunden")
    biz = get_business_info()
    total = sum(float(i.get("quantity", 0)) * float(i.get("unit_price", 0)) for i in q.get("items", []))
    html_out = env.get_template("angebot.html").render(
        studio_name=biz["name"], studio_address=biz["address"],
        studio_phone=biz["phone"], studio_email=biz["email"],
        customer_name=q.get("customer_name"), customer_address=q.get("customer_address"),
        items=q.get("items", []), total_gross=total,
        quote_number=q["id"], quote_date=q.get("date", ""),
        valid_until=q.get("valid_until", ""))
    pdf_buffer = io.BytesIO()
    if pisa:
        result = pisa.CreatePDF(io.BytesIO(html_out.encode("utf-8")), dest=pdf_buffer)
        if result.err:
            raise HTTPException(status_code=500, detail="PDF-Generierung fehlgeschlagen")
    else:
        raise HTTPException(status_code=500, detail="xhtml2pdf nicht installiert")
    return Response(content=pdf_buffer.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=Angebot_{quote_id}.pdf"})


@app.post("/quotes/{quote_id}/convert")
async def quotes_convert(quote_id: str, request: Request):
    from . import invoicing as invmod
    q = bk.get_quote(quote_id)
    if not q:
        raise HTTPException(status_code=404, detail="Angebot nicht gefunden")
    settings = bk.get_settings()
    biz = get_business_info()
    btc_rate = get_btc_price_eur()
    business_type = settings.get("business_type", "kleinunternehmer")
    pro = is_pro_license()
    if not pro:
        business_type = "kleinunternehmer"
    if free_limit_reached():
        raise HTTPException(status_code=402, detail="Free-Limit erreicht (3 Rechnungen/Monat). Upgrade auf Basic oder Pro für unbegrenzte Rechnungen.")
    logo_path = get_logo_path()
    result = invmod.create_invoice(
        {"customer_name": q.get("customer_name"), "customer_address": q.get("customer_address"),
         "items": q.get("items", []), "enable_btc": False,
         "payment_days": settings.get("default_payment_days", 14)},
        settings=settings, biz=biz, jinja_env=env, pdf_dir=PDF_DIR,
        logo_paths={"custom": CUSTOM_LOGO_PATH if logo_path == CUSTOM_LOGO_PATH else logo_path,
                    "default": LOGO_PATH, "btc_icon": BTC_ICON_PATH},
        is_pro=pro, business_type=business_type, btc_rate=btc_rate,
        number_provider=_get_next_invoice_number, peek_provider=bk.peek_next_invoice_number,
        address_provider=get_next_btc_address, preview=False)
    bk.set_quote_status(quote_id, "angenommen")
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return {"invoice": result["invoice_no"]}
    return Response(status_code=302, headers={"Location": "/income"})


@app.get("/zeiten")
async def timelog_page(request: Request):
    entries = bk.get_time_entries()
    unbilled = sum(float(e.get("amount", 0)) for e in entries if not e.get("billed_invoice"))
    return templates.TemplateResponse("timelog.html", {
        "request": request, "active_page": "timelog",
        "entries": entries[:200], "unbilled_total": unbilled,
        "customers": bk.get_all_customers(),
        "today": datetime.date.today().isoformat(),
    })


@app.post("/zeiten")
async def timelog_add(request: Request, date: str = Form(...), customer_name: str = Form(...),
                      description: str = Form(...), hours: str = Form(...), rate: str = Form(...)):
    try:
        h = float(hours.replace(",", "."))
        r = float(rate.replace(",", "."))
    except ValueError:
        raise HTTPException(status_code=400, detail="Stunden/Satz ungültig")
    if h <= 0 or r < 0:
        raise HTTPException(status_code=400, detail="Stunden müssen > 0 sein")
    bk.add_time_entry(date, customer_name, description, h, r)
    return Response(status_code=302, headers={"Location": "/zeiten"})


@app.post("/zeiten/{row_id}/delete")
async def timelog_delete(row_id: int):
    bk.delete_time_entry(row_id)
    return Response(status_code=302, headers={"Location": "/zeiten"})


@app.get("/api/timelog/unbilled")
async def api_timelog_unbilled(customer: str = ""):
    entries = bk.get_time_entries(unbilled_only=True)
    if customer:
        entries = [e for e in entries if e.get("customer_name") == customer]
    return entries


@app.get("/anlagen")
async def assets_page(request: Request, year: Optional[int] = None):
    year = year or datetime.date.today().year
    return templates.TemplateResponse("assets.html", {
        "request": request, "active_page": "assets", "year": year,
        "assets": bk.get_assets(), "afa_rows": bk.afa_for_year(year),
        "afa_total": bk.afa_total(year), "gwg_limit": bk.GWG_LIMIT,
        "years": _get_available_years(), "today": datetime.date.today().isoformat(),
    })


@app.post("/anlagen")
async def assets_add(request: Request, name: str = Form(...), purchase_date: str = Form(...),
                     cost: str = Form(...), years: str = Form("3")):
    try:
        c = float(cost.replace(",", "."))
        y = int(years)
    except ValueError:
        raise HTTPException(status_code=400, detail="Kosten/Dauer ungültig")
    if c <= 0 or y < 1 or y > 50:
        raise HTTPException(status_code=400, detail="Kosten müssen > 0, Dauer 1–50 Jahre sein")
    bk.add_asset(name, purchase_date, c, y)
    return Response(status_code=302, headers={"Location": "/anlagen"})


@app.post("/anlagen/{row_id}/delete")
async def assets_delete(row_id: int):
    bk.delete_asset(row_id)
    return Response(status_code=302, headers={"Location": "/anlagen"})


def _recurring_create_fn(payload: dict) -> dict:
    from . import invoicing as invmod
    if free_limit_reached():
        raise ValueError("Free-Limit erreicht (3 Rechnungen/Monat) – Abo übersprungen.")
    settings = bk.get_settings()
    biz = get_business_info()
    btc_rate = get_btc_price_eur()
    business_type = settings.get("business_type", "kleinunternehmer")
    pro = is_pro_license()
    if not pro:
        business_type = "kleinunternehmer"
    logo_path = get_logo_path()
    return invmod.create_invoice(
        payload, settings=settings, biz=biz, jinja_env=env, pdf_dir=PDF_DIR,
        logo_paths={"custom": CUSTOM_LOGO_PATH if logo_path == CUSTOM_LOGO_PATH else logo_path,
                    "default": LOGO_PATH, "btc_icon": BTC_ICON_PATH},
        is_pro=pro, business_type=business_type, btc_rate=btc_rate,
        number_provider=_get_next_invoice_number, peek_provider=bk.peek_next_invoice_number,
        address_provider=get_next_btc_address, preview=False,
    )


@app.get("/recurring")
async def recurring_page(request: Request, ran: Optional[int] = None, created: str = ""):
    created_list = [c for c in created.split(",") if c] if ran else None
    return templates.TemplateResponse("recurring.html", {
        "request": request, "active_page": "recurring",
        "profiles": bk.get_recurring_profiles(),
        "customers": bk.get_all_customers(),
        "today": datetime.date.today().isoformat(),
        "run_result": created_list,
    })


@app.post("/recurring")
async def recurring_create(request: Request):
    form = await request.form()
    import json as _json
    items_raw = form.get("items_json", "[]")
    try:
        items = _json.loads(items_raw)
    except Exception:
        items = [{"description": form.get("item_desc", ""), "quantity": 1,
                  "unit_price": float((form.get("item_price", "0") or "0").replace(",", "."))}]
    data = {
        "name": form.get("name", ""),
        "customer_name": form.get("customer_name", ""),
        "customer_address": form.get("customer_address", ""),
        "items": items,
        "frequency": form.get("frequency", "monthly"),
        "next_run": form.get("next_run") or datetime.date.today().isoformat(),
        "payment_days": int(form.get("payment_days") or 14),
        "enable_btc": form.get("enable_btc") == "1",
        "doc_type": "rechnung",
        "active": True,
    }
    bk.save_recurring_profile(data)
    return Response(status_code=302, headers={"Location": "/recurring"})


@app.post("/recurring/{row_id}/toggle")
async def recurring_toggle(row_id: int):
    p = bk.get_recurring_profile(row_id)
    if p:
        p["active"] = not p.get("active", True)
        bk.save_recurring_profile({k: v for k, v in p.items() if not k.startswith("_")}, row_id)
    return Response(status_code=302, headers={"Location": "/recurring"})


@app.post("/recurring/{row_id}/delete")
async def recurring_delete(row_id: int):
    bk.delete_recurring_profile(row_id)
    return Response(status_code=302, headers={"Location": "/recurring"})


@app.post("/recurring/run")
async def recurring_run(request: Request):
    created = bk.run_due_recurring(_recurring_create_fn)
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return {"created": created}
    import urllib.parse
    q = urllib.parse.urlencode({"ran": 1, "created": ",".join(created)})
    return Response(status_code=302, headers={"Location": f"/recurring?{q}"})


@app.post("/income/{invoice_id}/remind")
async def remind_invoice(invoice_id: str):
    inv = bk.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    settings = bk.get_settings()
    level = int(inv.get("dunning_level", 0)) + 1
    if level > 3:
        level = 3
    fee = float(settings.get(f"dunning_fee_{level}", 5.0))
    updated = bk.apply_dunning(invoice_id, level, fee)
    if not updated:
        raise HTTPException(status_code=400, detail="Mahnung nicht möglich")
    return Response(status_code=302, headers={"Location": "/income"})


@app.get("/income/{invoice_id}/mahnung")
async def mahnung_pdf(invoice_id: str):
    inv = bk.get_invoice_by_id(invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    import datetime as _dt
    settings = bk.get_settings()
    biz = get_business_info()
    level = max(1, int(inv.get("dunning_level", 1)))
    titles = {1: "Zahlungserinnerung", 2: "1. Mahnung", 3: "2. Mahnung (letzte Mahnung)"}
    fee_total = float(inv.get("dunning_fees", 0))
    rate = float(settings.get("default_interest_rate", 8.62))
    due = inv.get("due_date") or inv.get("date")
    try:
        days = max(0, (_dt.date.today() - _dt.date.fromisoformat(due[:10])).days)
    except (ValueError, TypeError):
        days = 0
    interest = round(float(inv.get("amount", 0)) * rate / 100 / 365 * days, 2) if days > 0 else 0.0
    total = round(float(inv.get("amount", 0)) + fee_total + interest, 2)
    new_due = (_dt.date.today() + _dt.timedelta(days=7)).strftime("%d.%m.%Y")
    try:
        due_fmt = _dt.date.fromisoformat(due[:10]).strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        due_fmt = due
    html_out = env.get_template("mahnung.html").render(
        studio_name=biz["name"], studio_address=biz["address"],
        invoice=inv, level=level, level_title=titles.get(level, "Mahnung"),
        fee=fee_total, interest=interest, interest_rate=rate, days=days, total=total,
        due=due_fmt, new_due=new_due,
        iban=settings.get("bank_iban", ""), bic=settings.get("bank_bic", ""))
    pdf_buffer = io.BytesIO()
    if pisa:
        result = pisa.CreatePDF(io.BytesIO(html_out.encode("utf-8")), dest=pdf_buffer)
        if result.err:
            raise HTTPException(status_code=500, detail="PDF-Generierung fehlgeschlagen")
    else:
        raise HTTPException(status_code=500, detail="xhtml2pdf nicht installiert")
    return Response(content=pdf_buffer.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename=Mahnung_{invoice_id}.pdf"})


@app.post("/webhook/btcpay")
async def webhook_btcpay(request: Request):
    """BTCPay Server Webhook: markiert Rechnung bei InvoiceSettled automatisch bezahlt.
    Inaktiv ohne btcpay_webhook_secret (Einstellungen oder BTCPAY_WEBHOOK_SECRET)."""
    import hmac as _hmac
    import hashlib as _hl
    settings = bk.get_settings()
    secret = settings.get("btcpay_webhook_secret") or os.environ.get("BTCPAY_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=404, detail="BTCPay nicht konfiguriert")
    raw = await request.body()
    sig = request.headers.get("BTCPay-Sig", "")
    expected = "sha256=" + _hmac.new(secret.encode(), raw, _hl.sha256).hexdigest()
    if not _hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=401, detail="Ungültige Signatur")
    try:
        event = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Ungültiges JSON")
    etype = event.get("type", "")
    if etype not in ("InvoiceSettled", "InvoicePaymentSettled", "InvoicePaid"):
        return {"ok": True, "ignored": etype}
    meta = event.get("metadata") or {}
    order_id = meta.get("orderId") or event.get("orderId") or ""
    inv = bk.get_invoice_by_id(order_id) if order_id else None
    if not inv:
        return {"ok": False, "error": "Rechnung nicht gefunden"}
    payment = event.get("payment") or {}
    btc_val = payment.get("value") or event.get("amountPaid")
    try:
        btc_amount = float(btc_val) if btc_val else None
    except (ValueError, TypeError):
        btc_amount = None
    bk.mark_invoice_paid(order_id, datetime.date.today().isoformat(),
                         btc_received=btc_amount, txid=event.get("invoiceId"),
                         payment_method="bitcoin")
    return {"ok": True, "invoice": order_id}


@app.get("/api/btcpay/status")
async def btcpay_status():
    settings = bk.get_settings()
    url = settings.get("btcpay_url") or os.environ.get("BTCPAY_SERVER_URL", "")
    secret = settings.get("btcpay_webhook_secret") or os.environ.get("BTCPAY_WEBHOOK_SECRET", "")
    return {"configured": bool(url and secret), "url": bool(url), "webhook": bool(secret)}


def _require_pro(request: Request, feature_name: str):
    if not is_pro_license():
        return templates.TemplateResponse("upsell.html", {
            "request": request, "active_page": "",
            "feature_name": feature_name,
        }, status_code=403)
    return None


@app.get("/bank")
async def bank_page(request: Request):
    gated = _require_pro(request, "Bankimport & Abgleich")
    if gated is not None:
        return gated
    return templates.TemplateResponse("bank.html", {
        "request": request, "active_page": "bank",
        "transactions": sorted(bk.get_bank_transactions(), key=lambda t: t.get("date", ""), reverse=True)[:200],
        "invoices": [i for i in bk.get_active_invoices() if not i.get("payment_received")],
    })


@app.post("/bank/import")
async def bank_import(request: Request, file: UploadFile = File(...)):
    gated = _require_pro(request, "Bankimport & Abgleich")
    if gated is not None:
        return gated
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Datei zu groß (max. 5 MB).")
    name = (file.filename or "").lower()
    if name.endswith(".xml"):
        from .bankimport import parse_camt053
        rows = parse_camt053(contents)
    else:
        from .bankimport import parse_csv
        rows = parse_csv(contents)
    n = bk.import_bank_transactions(rows)
    m = bk.auto_match_bank()
    return Response(status_code=302, headers={"Location": f"/bank?imported={n}&matched={m}"})


@app.post("/bank/{row_id}/match")
async def bank_match(request: Request, row_id: int, invoice_id: str = Form(""), action: str = Form("match")):
    gated = _require_pro(request, "Bankimport & Abgleich")
    if gated is not None:
        return gated
    if action == "mark_paid" and invoice_id:
        bk.mark_invoice_paid(invoice_id, datetime.date.today().isoformat(), payment_method="bank_transfer")
        bk.set_bank_tx_match(row_id, invoice_id, "verbucht")
    elif action == "unmatch":
        bk.set_bank_tx_match(row_id, None, "offen")
    else:
        bk.set_bank_tx_match(row_id, invoice_id or None, "zugeordnet" if invoice_id else "offen")
    return Response(status_code=302, headers={"Location": "/bank"})


@app.get("/kassenbuch")
async def cashbook_page(request: Request, year: Optional[int] = None):
    gated = _require_pro(request, "Kassenbuch")
    if gated is not None:
        return gated
    year = year or datetime.date.today().year
    entries = [e for e in bk.get_cashbook_entries() if (e.get("date") or "").startswith(str(year))]
    balance = sum(float(e.get("amount", 0)) for e in entries)
    return templates.TemplateResponse("cashbook.html", {
        "request": request, "active_page": "cashbook", "year": year,
        "entries": entries, "balance": balance,
        "years": _get_available_years(), "today": datetime.date.today().isoformat(),
    })


@app.get("/gobd/export")
async def gobd_export(year: Optional[int] = None):
    import io as _io
    import zipfile as _zf
    year = year or datetime.date.today().year
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w", _zf.ZIP_DEFLATED) as z:
        for inv in bk.get_active_invoices():
            if (inv.get("date") or "").startswith(str(year)):
                p = os.path.join(PDF_DIR, f"{inv['id']}.pdf")
                if os.path.exists(p):
                    z.write(p, arcname=f"belege/{inv['id']}.pdf")
        if os.path.isdir(RECEIPTS_DIR):
            for fn in sorted(os.listdir(RECEIPTS_DIR)):
                z.write(os.path.join(RECEIPTS_DIR, fn), arcname=f"belege/ausgaben/{fn}")
        euer = bk.generate_euer(year)
        z.writestr(f"euer/EUER_{year}.json", json.dumps(euer, ensure_ascii=False, indent=2))
        z.writestr(f"audit/audit_{year}.json",
                   json.dumps(bk.get_audit_log(), ensure_ascii=False, indent=2))
        settings = bk.get_settings()
        biz = get_business_info()
        doku = env.get_template("verfahrensdoku.html").render(
            business_name=biz["name"], business_address=biz["address"],
            year=year, today=datetime.date.today().strftime("%d.%m.%Y"),
            version="1.0", tax_id=settings.get("tax_id", ""))
        z.writestr("verfahrensdokumentation.html", doku)
        z.writestr("README.txt",
                   f"GoBD-Export {year}\nErstellt: {datetime.date.today()}\n"
                   "Inhalt: belege/, euer/, audit/, Verfahrensdokumentation.\n"
                   "Hinweis: kein Ersatz für Steuerberatung.\n")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=GoBD_{year}.zip"})


@app.get("/api/drafts/{draft_id}")
async def api_draft(draft_id: int):
    for d in bk.list_drafts():
        if d.get("_draft_id") == draft_id:
            return d
    raise HTTPException(status_code=404, detail="Entwurf nicht gefunden")


@app.get("/health")
async def health():
    return {"status": "ok", "zugferd": facturx is not None}


@app.post("/generate-pdf")
async def generate_pdf(request: InvoiceRequest):
    from . import invoicing as invmod
    try:
        settings = bk.get_settings()
        biz = get_business_info()
        btc_rate = get_btc_price_eur()
        business_type = settings.get("business_type", "kleinunternehmer")
        if not is_pro_license():
            business_type = "kleinunternehmer"
        payload = {
            "customer_name": request.customer_name,
            "customer_address": request.customer_address,
            "items": [{"description": i.description, "quantity": i.quantity,
                       "unit_price": i.unit_price, "vat_rate": i.vat_rate} for i in request.items],
            "enable_btc": request.enable_btc,
            "btc_address": request.btc_address,
            "iban": request.iban, "bic": request.bic, "bank_name": request.bank_name,
            "doc_type": request.doc_type, "payment_days": request.payment_days,
            "discount_days": request.discount_days, "discount_percent": request.discount_percent,
            "invoice_date": request.invoice_date,
            "buyer_reference": request.buyer_reference,
        }
        if not request.preview and free_limit_reached():
            raise HTTPException(status_code=402, detail="Free-Limit erreicht (3 Rechnungen/Monat). Upgrade auf Basic oder Pro für unbegrenzte Rechnungen.")
        logo_path = get_logo_path()
        result = invmod.create_invoice(
            payload, settings=settings, biz=biz, jinja_env=env, pdf_dir=PDF_DIR,
            logo_paths={"custom": CUSTOM_LOGO_PATH if logo_path == CUSTOM_LOGO_PATH else logo_path,
                        "default": LOGO_PATH, "btc_icon": BTC_ICON_PATH},
            is_pro=is_pro_license(), business_type=business_type, btc_rate=btc_rate,
            number_provider=_get_next_invoice_number, peek_provider=bk.peek_next_invoice_number,
            address_provider=get_next_btc_address, preview=bool(request.preview),
        )
        invoice_no = result["invoice_no"]
        pdf_content = result["pdf"]
        if result.get("preview"):
            return Response(content=pdf_content, media_type="application/pdf",
                            headers={"Content-Disposition": f"inline; filename=Vorschau_{invoice_no}.pdf"})
        if request.time_entry_ids:
            try:
                bk.mark_time_billed(list(request.time_entry_ids), invoice_no)
            except Exception as e:
                print(f"Zeiten markieren fehlgeschlagen: {e}")
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Rechnung_{invoice_no}.pdf"}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Fehler: {str(e)}")


# ---------------------------------------------------------------------------
# Endpoints – Zahlungsseite
# ---------------------------------------------------------------------------

@app.get("/pay/{invoice_id}")
async def pay_page(request: Request, invoice_id: str):
    """Öffentliche Zahlungsseite – kein Login nötig."""
    invoice = bk.get_invoice_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    btc_rate = get_btc_price_eur()
    settings = bk.get_settings()
    btc_discount_percent = settings.get("btc_discount_percent", 0)
    total_eur = invoice["amount"]
    
    if btc_discount_percent != 0 and invoice.get("btc_address"):
        discount_factor = 1 - (btc_discount_percent / 100)
        btc_amount = (total_eur * discount_factor) / btc_rate if btc_rate > 0 else 0
    else:
        btc_amount = total_eur / btc_rate if btc_rate > 0 else 0
    
    # QR-Code server-seitig generieren
    qr_btc = None
    if invoice.get("btc_address"):
        btc_uri = f"bitcoin:{invoice['btc_address']}?amount={btc_amount:.8f}"
        lightning_address = settings.get("lightning_address")
        if lightning_address:
            btc_uri += f"&lightning={lightning_address}"
        qr_btc = generate_qr_base64(btc_uri)
    return templates.TemplateResponse("pay.html", {
        "request": request,
        "invoice": invoice,
        "studio_name": get_business_info()["name"],
        "btc_rate": btc_rate,
        "btc_amount": btc_amount,
        "qr_btc": qr_btc,
        "btc_discount_percent": btc_discount_percent,
        "lightning_address": settings.get("lightning_address"),
    })


@app.get("/api/pay/{invoice_id}")
async def pay_api(invoice_id: str):
    """JSON-API für die Zahlungsseite (AJAX Refresh + Payment Detection)."""
    invoice = bk.get_invoice_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    btc_rate = get_btc_price_eur()
    settings = bk.get_settings()
    btc_discount_percent = settings.get("btc_discount_percent", 0)
    total_eur = invoice["amount"]
    
    if btc_discount_percent != 0 and invoice.get("btc_address"):
        discount_factor = 1 - (btc_discount_percent / 100)
        total_btc = (total_eur * discount_factor) / btc_rate if btc_rate > 0 else 0
    else:
        total_btc = total_eur / btc_rate if btc_rate > 0 else 0

    # Zahlung prüfen falls noch nicht als bezahlt markiert
    if not invoice.get("payment_received") and invoice.get("btc_address"):
        payment = check_btc_payment(invoice["btc_address"])
        if payment["received"]:
            pass

    return {
        "id": invoice["id"],
        "customer_name": invoice["customer_name"],
        "amount_eur": total_eur,
        "btc_rate": btc_rate,
        "btc_amount": total_btc,
        "btc_address": invoice.get("btc_address"),
        "payment_received": invoice.get("payment_received", False),
        "payment_date": invoice.get("payment_date"),
        "btc_amount_received": invoice.get("btc_amount_received"),
        "eur_value_at_payment": invoice.get("eur_value_at_payment"),
        "payment_txid": invoice.get("payment_txid"),
        "btc_discount_percent": btc_discount_percent,
    }


# ---------------------------------------------------------------------------
# Endpoints – Dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard")
async def dashboard_page(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    year = year or datetime.date.today().year
    month = month or (datetime.date.today().month if year == datetime.date.today().year else 1)
    try:
        created_recurring = bk.run_due_recurring(_recurring_create_fn)
    except Exception as e:
        print(f"Recurring-Lauf fehlgeschlagen: {e}")
        created_recurring = []
    summary = bk.get_monthly_summary(year, month)
    yearly = bk.get_yearly_summary(year)
    transactions = bk.get_recent_transactions(limit=10)
    overdue = bk.overdue_invoices()
    open_quotes = [q for q in bk.get_all_quotes() if q.get("status") == "offen"]
    unbilled_total = sum(float(e.get("amount", 0)) for e in bk.get_time_entries(unbilled_only=True))
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "year": year,
        "selected_month": month,
        "month_name": MONTH_NAMES[month - 1],
        "summary": summary,
        "yearly": yearly,
        "transactions": transactions,
        "month_names": MONTH_NAMES,
        "years": _get_available_years(),
        "created_recurring": created_recurring,
        "overdue": overdue,
        "overdue_count": len(overdue),
        "open_quotes": open_quotes,
        "unbilled_total": unbilled_total,
    })


# ---------------------------------------------------------------------------
# Endpoints – Ausgaben
# ---------------------------------------------------------------------------

@app.get("/expenses")
async def expenses_page(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    year = year or datetime.date.today().year
    all_expenses = bk.get_all_expenses()

    # Filter by year and optionally month
    filtered = [e for e in all_expenses if e["date"].startswith(str(year))]
    if month:
        filtered = [e for e in filtered if e["date"].startswith(f"{year}-{month:02d}")]

    # Enrich with labels
    receipt_names = set()
    try:
        if os.path.isdir(RECEIPTS_DIR):
            receipt_names = {os.path.splitext(f)[0] for f in os.listdir(RECEIPTS_DIR)}
    except OSError:
        pass
    for e in filtered:
        e["category_label"] = CATEGORY_LABELS.get(e["category"], e["category"])
        e["has_receipt"] = e.get("id") in receipt_names

    total = sum(e["amount"] for e in filtered if e.get("status", "aktiv") != "storniert")

    return templates.TemplateResponse("expenses.html", {
        "request": request,
        "active_page": "expenses",
        "year": year,
        "today": datetime.date.today().isoformat(),
        "categories": CATEGORY_LABELS,
        "payment_methods": PAYMENT_METHOD_LABELS,
        "expenses": filtered,
        "total": total,
        "selected_month": month,
        "month_names": MONTH_NAMES,
        "years": _get_available_years(),
    })


@app.post("/expenses")
async def create_expense(
    date: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    vendor: str = Form(""),
    amount: str = Form(...),
    payment_method: str = Form("bank_transfer"),
    vat_rate: Optional[str] = Form(None),
    notes: str = Form(""),
    receipt: UploadFile = File(None),
):
    # Komma zu Punkt konvertieren (deutsche Eingabe)
    amount_float = float(amount.replace(",", "."))

    # Vorsteuer berechnen (nur bei regulärem Unternehmen)
    vat_rate_float = float(vat_rate.replace(",", ".")) if vat_rate else 0.0
    # Vorsteuer = Brutto * (MwSt-Satz / (1 + MwSt-Satz))
    vat_amount = round(amount_float * vat_rate_float / (1 + vat_rate_float), 2) if vat_rate_float > 0 else 0.0

    data = {
        "date": date,
        "category": category,
        "description": description,
        "vendor": vendor or None,
        "amount": amount_float,
        "vat_rate": vat_rate_float,
        "vat_amount": vat_amount,
        "payment_method": payment_method,
        "notes": notes or None,
    }
    created = bk.create_expense(data)
    if receipt and receipt.filename:
        contents = await receipt.read()
        if contents and len(contents) <= 5 * 1024 * 1024:
            ext = os.path.splitext(receipt.filename or "")[1].lower()[:5] or ".jpg"
            if ext not in (".jpg", ".jpeg", ".png", ".pdf", ".webp"):
                ext = ".jpg"
            os.makedirs(RECEIPTS_DIR, exist_ok=True)
            with open(os.path.join(RECEIPTS_DIR, f"{created['id']}{ext}"), "wb") as f:
                f.write(contents)
    return Response(status_code=302, headers={"Location": "/expenses"})


@app.post("/expenses/ocr")
async def expenses_ocr(file: UploadFile = File(...)):
    from . import ocr as ocrmod
    contents = await file.read()
    if not contents or len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Datei leer oder zu groß (max. 5 MB).")
    res = ocrmod.scan(contents)
    res["ocr_available"] = ocrmod.is_available()
    return res


@app.get("/expenses/{expense_id}/receipt")
async def expense_receipt(expense_id: str):
    for ext in (".jpg", ".jpeg", ".png", ".pdf", ".webp"):
        p = os.path.join(RECEIPTS_DIR, f"{expense_id}{ext}")
        if os.path.exists(p):
            from starlette.responses import FileResponse
            return FileResponse(p)
    raise HTTPException(status_code=404, detail="Kein Beleg vorhanden")


@app.post("/expenses/{expense_id}/cancel")
async def cancel_expense(expense_id: str):
    bk.cancel_expense(expense_id)
    return Response(status_code=302, headers={"Location": "/expenses"})


# ---------------------------------------------------------------------------
# Endpoints – Einnahmen
# ---------------------------------------------------------------------------

@app.get("/income")
async def income_page(request: Request, year: Optional[int] = None, month: Optional[int] = None,
                      highlight: str = ""):
    year = year or datetime.date.today().year
    all_invoices = bk.get_all_invoices()

    filtered = [i for i in all_invoices if i["date"].startswith(str(year))]
    if month:
        filtered = [i for i in filtered if i["date"].startswith(f"{year}-{month:02d}")]

    total = sum(i["amount"] for i in filtered if i.get("status", "aktiv") != "storniert")
    settings = bk.get_settings()
    overdue_ids = {i["id"] for i in bk.overdue_invoices()}

    return templates.TemplateResponse("income.html", {
        "request": request,
        "active_page": "income",
        "year": year,
        "invoices": filtered,
        "total": total,
        "selected_month": month,
        "month_names": MONTH_NAMES,
        "years": _get_available_years(),
        "payment_methods": PAYMENT_METHOD_LABELS,
        "overdue_ids": overdue_ids,
        "interest_rate": settings.get("default_interest_rate", 8.62),
        "highlight": highlight,
    })


@app.get("/income/add")
async def add_income_page(request: Request):
    return templates.TemplateResponse("income_add.html", {
        "request": request,
        "active_page": "income",
        "payment_methods": PAYMENT_METHOD_LABELS,
        "today": datetime.date.today().isoformat(),
    })


@app.post("/income/add")
async def add_income(
    date: str = Form(...),
    amount: str = Form(...),
    customer_name: str = Form(...),
    items_description: str = Form(...),
    payment_received: str = Form("false"),
    payment_date: str = Form(""),
    payment_method: str = Form("bank_transfer"),
):
    try:
        amount_float = float(amount.replace(",", "."))
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiger Betrag.")
    invoice_no = _get_next_invoice_number()
    
    invoice_data = {
        "id": invoice_no,
        "date": date,
        "customer_name": customer_name,
        "customer_address": "",
        "amount": amount_float,
        "items_description": items_description,
        "payment_received": payment_received == "true",
        "invoice_filename": None,
    }
    
    if payment_received == "true" and payment_date:
        invoice_data["payment_date"] = payment_date
        invoice_data["payment_method"] = payment_method
    
    bk.log_invoice(invoice_data)
    
    return Response(status_code=302, headers={"Location": "/income"})


@app.get("/income/{invoice_id}/paid")
async def paid_form(request: Request, invoice_id: str):
    invoice = bk.get_invoice_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    return templates.TemplateResponse("paid.html", {
        "request": request,
        "active_page": "income",
        "invoice": invoice,
        "payment_methods": PAYMENT_METHOD_LABELS,
        "today": datetime.date.today().isoformat(),
    })


@app.post("/income/{invoice_id}/paid")
async def mark_paid(
    invoice_id: str,
    payment_date: str = Form(...),
    payment_method: str = Form("bank_transfer"),
    btc_received: str = Form(""),
    txid: str = Form(""),
):
    btc_amount = None
    if btc_received.strip():
        btc_amount = float(btc_received.replace(",", ".").strip())
    bk.mark_invoice_paid(
        invoice_id,
        payment_date,
        btc_received=btc_amount,
        txid=txid.strip() or None,
        payment_method=payment_method,
    )
    return Response(status_code=302, headers={"Location": "/income"})


@app.post("/income/{invoice_id}/cancel")
async def cancel_income(invoice_id: str):
    bk.cancel_invoice(invoice_id)
    return Response(status_code=302, headers={"Location": "/income"})


@app.get("/income/{invoice_id}/pdf")
async def serve_invoice_pdf(invoice_id: str):
    invoice = bk.get_invoice_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    filename = invoice.get("invoice_filename") or f"Rechnung_{invoice_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, f"{invoice_id}.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF-Datei nicht gefunden")
    with open(pdf_path, "rb") as f:
        pdf_content = f.read()
    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )


# ---------------------------------------------------------------------------
# Endpoints – EÜR
# ---------------------------------------------------------------------------

@app.get("/euer")
async def euer_page(request: Request, year: Optional[int] = None):
    year = year or datetime.date.today().year
    euer_data = bk.generate_euer(year)
    biz = get_business_info()
    settings = bk.get_settings()
    business_type = settings.get("business_type", "kleinunternehmer")
    if not is_pro_license():
        business_type = "kleinunternehmer"
    return templates.TemplateResponse("euer.html", {
        "request": request,
        "active_page": "euer",
        "year": year,
        "euer": euer_data,
        "business_name": biz["name"],
        "business_address": biz["address"],
        "tax_id": settings.get("tax_id", ""),
        "years": _get_available_years(),
        "business_type": business_type,
    })


@app.get("/ustva")
async def ustva_page(request: Request, year: Optional[int] = None, period: Optional[int] = None, type: Optional[str] = None):
    if not is_pro_license():
        return Response(status_code=302, headers={"Location": "/euer"})
    settings = bk.get_settings()
    if settings.get("business_type") == "kleinunternehmer":
        return Response(status_code=302, headers={"Location": "/euer"})

    year = year or datetime.date.today().year
    period_type = type or "quarter"
    if period is None:
        if period_type == "month":
            period = datetime.date.today().month
        else:
            period = (datetime.date.today().month - 1) // 3 + 1
    biz = get_business_info()
    ustva_data = bk.calculate_ustva(year, period, period_type)

    return templates.TemplateResponse("ustva.html", {
        "request": request,
        "active_page": "ustva",
        "year": year,
        "period": period,
        "period_type": period_type,
        "ustva": ustva_data,
        "business_name": biz["name"],
        "tax_id": settings.get("tax_id", ""),
        "years": _get_available_years(),
        "month_names": MONTH_NAMES,
    })


@app.get("/ustva/pdf")
async def ustva_pdf(year: Optional[int] = None, period: Optional[int] = None, type: Optional[str] = None):
    if not is_pro_license():
        raise HTTPException(status_code=403, detail="Pro-Lizenz erforderlich")
    year = year or datetime.date.today().year
    period_type = type or "quarter"
    if period is None:
        period = (datetime.date.today().month - 1) // 3 + 1 if period_type == "quarter" else datetime.date.today().month
    biz = get_business_info()
    ustva_data = bk.calculate_ustva(year, period, period_type)

    html_out = env.get_template('ustva_pdf.html').render(
        ustva=ustva_data,
        business_name=biz["name"],
        tax_id=bk.get_settings().get("tax_id", ""),
        year=year,
        period=period,
        period_type=period_type,
        today=datetime.date.today().strftime("%d.%m.%Y"),
    )

    pdf_buffer = io.BytesIO()
    if pisa:
        result = pisa.CreatePDF(io.BytesIO(html_out.encode("utf-8")), dest=pdf_buffer)
        if result.err:
            raise HTTPException(status_code=500, detail="PDF-Generierung fehlgeschlagen")
    else:
        raise HTTPException(status_code=500, detail="xhtml2pdf nicht installiert")

    return Response(
        content=pdf_buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=UStVA_{period}_{year}.pdf"}
    )


@app.get("/ustva/csv")
async def ustva_csv(year: Optional[int] = None, period: Optional[int] = None, type: Optional[str] = None):
    if not is_pro_license():
        raise HTTPException(status_code=403, detail="Pro-Lizenz erforderlich")
    year = year or datetime.date.today().year
    period_type = type or "quarter"
    if period is None:
        period = (datetime.date.today().month - 1) // 3 + 1 if period_type == "quarter" else datetime.date.today().month
    ustva_data = bk.calculate_ustva(year, period, period_type)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([f"UStVA {ustva_data['period_label']}"])
    writer.writerow([])
    writer.writerow(["Zeile", "Bezeichnung", "Netto", "Steuer"])
    writer.writerow(["81", "Steuer 19%", f"{ustva_data['net_19']:.2f}".replace(".", ","), f"{ustva_data['ust_19']:.2f}".replace(".", ",")])
    writer.writerow(["86", "Steuer 7%", f"{ustva_data['net_7']:.2f}".replace(".", ","), f"{ustva_data['ust_7']:.2f}".replace(".", ",")])
    writer.writerow(["66", "Vorsteuer", "", f"{ustva_data['vorsteuer']:.2f}".replace(".", ",")])
    writer.writerow([])
    writer.writerow(["Zahllast/Erstattung", f"{ustva_data['ustva_betrag']:.2f}".replace(".", ",")])

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=UStVA_{period}_{year}.csv"}
    )


@app.get("/euer/pdf")
async def euer_pdf(year: Optional[int] = None):
    year = year or datetime.date.today().year
    euer_data = bk.generate_euer(year)
    biz = get_business_info()

    template = env.get_template('euer_pdf.html')
    html_out = template.render(
        business_name=biz["name"],
        business_address=biz["address"],
        tax_id=bk.get_settings().get("tax_id", ""),
        year=year,
        euer=euer_data,
        generated_date=datetime.date.today().strftime("%d.%m.%Y"),
    )

    pdf_buffer = io.BytesIO()
    if pisa:
        result = pisa.CreatePDF(io.BytesIO(html_out.encode("utf-8")), dest=pdf_buffer)
        if result.err:
            raise HTTPException(status_code=500, detail="PDF-Generierung fehlgeschlagen")
    else:
        raise HTTPException(status_code=500, detail="xhtml2pdf nicht installiert")

    return Response(
        content=pdf_buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=EUR_{year}.pdf"}
    )


@app.get("/euer/csv")
async def euer_csv(year: Optional[int] = None):
    year = year or datetime.date.today().year
    biz = get_business_info()
    invoices = [i for i in bk.get_active_invoices() if i["date"].startswith(str(year))]
    expenses = [e for e in bk.get_active_expenses() if e["date"].startswith(str(year))]
    euer = bk.generate_euer(year)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    # Kopfzeile
    writer.writerow([f"EÜR {year} – {biz['name']}"])
    writer.writerow([])

    # --- Einnahmen ---
    writer.writerow(["EINNAHMEN"])
    writer.writerow(["Datum", "Rechnung", "Kunde", "Beschreibung", "Betrag (EUR)", "BTC Betrag", "BTC Adresse"])
    for inv in sorted(invoices, key=lambda x: x["date"]):
        writer.writerow([
            inv["date"],
            inv["id"],
            inv.get("customer_name", ""),
            inv.get("items_description", ""),
            f"{inv['amount']:.2f}".replace(".", ","),
            f"{inv.get('btc_amount', 0):.8f}" if inv.get("btc_address") else "",
            inv.get("btc_address", ""),
        ])
    writer.writerow(["", "", "", "", f"{euer['gross_revenue']:.2f}".replace(".", ",")])
    writer.writerow([])

    # --- Ausgaben ---
    writer.writerow(["AUSGABEN"])
    writer.writerow(["Datum", "Kategorie", "Beschreibung", "Betrag (EUR)", "Zahlungsart"])
    for exp in sorted(expenses, key=lambda x: x["date"]):
        writer.writerow([
            exp["date"],
            exp.get("category", ""),
            exp.get("description", ""),
            f"{exp['amount']:.2f}".replace(".", ","),
            exp.get("payment_method", ""),
        ])
    writer.writerow(["", "", "", f"{euer['total_expenses']:.2f}".replace(".", ",")])
    writer.writerow([])

    # --- EÜR Zusammenfassung ---
    writer.writerow(["EÜR ZUSAMMENFASSUNG"])
    writer.writerow(["Betriebseinnahmen", f"{euer['gross_revenue']:.2f}".replace(".", ",")])
    writer.writerow(["Betriebsausgaben", f"{euer['total_expenses']:.2f}".replace(".", ",")])
    writer.writerow(["Gewinn / Verlust", f"{euer['operating_result']:.2f}".replace(".", ",")])

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM für Excel
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=EUR_{year}.csv"}
    )


@app.get("/datev/export")
async def datev_export(year: Optional[int] = None):
    if not is_pro_license():
        raise HTTPException(status_code=403, detail="Business-Lizenz erforderlich")
    year = year or datetime.date.today().year
    biz = get_business_info()
    settings = bk.get_settings()
    invoices = [i for i in bk.get_active_invoices() if i["date"].startswith(str(year))]
    expenses = [e for e in bk.get_active_expenses() if e["date"].startswith(str(year))]

    output = io.StringIO()
    w = csv.writer(output, delimiter=";")

    # DATEV Header
    w.writerow(["EXTF", "510", "21", "Buchungsstapel", "3",
                datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
                datetime.datetime.now().strftime("%Y%m%d%H%M%S"), "", ""])
    w.writerow([f"EXTF_accounting_510", "Kasus_Mandantenberater", biz["name"], "", ""])
    w.writerow([f"EXTF_accounting_510", "Kasus_Rechnungslegungskreis", "01", "", ""])
    w.writerow([f"EXTF_accounting_510", "Kasus_Belegnummer", "1", "", ""])
    w.writerow([f"EXTF_accounting_510", "Kasus_Jahr", str(year), "", ""])
    w.writerow([f"EXTF_accounting_510", "Kasus_Währung", "EUR", "", ""])
    w.writerow([f"EXTF_accounting_510", "Kasus_Buchungskonto_Erloese", "8400", "", ""])
    w.writerow([f"EXTF_accounting_510", "Kasus_Buchungskonto_Aufwand", "4980", "", ""])
    w.writerow([])

    # Buchungen
    w.writerow(["Belegnummer", "Belegdatum", "SollKonto", "HabenKonto",
                "Betrag", "Buchungstext", "Beleglink"])

    beleg_nr = 1
    # Einnahmen (Gutschriften mit umgekehrten Konten)
    for inv in sorted(invoices, key=lambda x: x["date"]):
        is_credit = inv.get("doc_type") == "gutschrift" or inv["id"].startswith("GS-")
        w.writerow([
            beleg_nr,
            inv["date"],
            "8400" if is_credit else "1200",
            "1200" if is_credit else "8400",
            f"{inv['amount']:.2f}".replace(".", ","),
            f"{'Gutschrift' if is_credit else 'Rechnung'} {inv['id']}",
            "",
        ])
        beleg_nr += 1
        if float(inv.get("dunning_fees", 0) or 0) > 0:
            w.writerow([
                beleg_nr, inv.get("last_reminder") or inv["date"],
                "1200", "8600",
                f"{float(inv['dunning_fees']):.2f}".replace(".", ","),
                f"Mahngebühren {inv['id']}", "",
            ])
            beleg_nr += 1

    # Ausgaben
    for exp in sorted(expenses, key=lambda x: x["date"]):
        w.writerow([
            beleg_nr,
            exp["date"],
            "4980",  # Aufwand (Soll)
            "1200",  # Verbindlichkeiten (Haben)
            f"{exp['amount']:.2f}".replace(".", ","),
            f"Ausgabe {exp.get('description', '')}",
            "",
        ])
        beleg_nr += 1

    csv_bytes = output.getvalue().encode("utf-8-sig")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=DATEV_{year}.csv"}
    )


# ---------------------------------------------------------------------------
# Endpoints – Einstellungen
# ---------------------------------------------------------------------------

@app.get("/settings")
async def settings_page(request: Request, license_required: int = 0):
    settings = bk.get_settings()
    settings["has_custom_logo"] = os.path.exists(CUSTOM_LOGO_PATH)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "settings": settings,
        "message": None,
        "license_status": get_license_status(),
        "license_required": bool(license_required),
    })


@app.post("/settings")
async def settings_save(
    request: Request,
    business_name: str = Form(""),
    business_address: str = Form(""),
    business_slogan: str = Form(""),
    business_phone: str = Form(""),
    business_email: str = Form(""),
    business_type: str = Form("kleinunternehmer"),
    bank_iban: str = Form(""),
    bank_bic: str = Form(""),
    bank_name: str = Form(""),
    bank_account_name: str = Form(""),
    tax_id: str = Form(""),
    btc_xpub: str = Form(""),
    btc_discount_percent: str = Form("0"),
    lightning_address: str = Form(""),
    logo: UploadFile = File(None),
    delete_logo: str = Form(""),
    logo_hidden: Optional[str] = Form(None),
    xrechnung_profile: str = Form("basic"),
    btcpay_url: str = Form(""),
    btcpay_webhook_secret: str = Form(""),
    default_payment_days: str = Form("14"),
    dunning_fee_1: str = Form("5"),
    dunning_fee_2: str = Form("7.5"),
    dunning_fee_3: str = Form("10"),
    default_interest_rate: str = Form("8.62"),
):
    settings = bk.get_settings()
    settings["business_name"] = business_name.strip()
    settings["business_address"] = business_address.strip()
    settings["business_slogan"] = business_slogan.strip()
    settings["business_phone"] = business_phone.strip()
    settings["business_email"] = business_email.strip()
    # Business-Typ nur ändern wenn Pro-Lizenz vorhanden
    if is_pro_license():
        settings["business_type"] = business_type
    else:
        settings["business_type"] = "kleinunternehmer"
    settings["bank_iban"] = bank_iban.strip()
    settings["bank_bic"] = bank_bic.strip()
    settings["bank_name"] = bank_name.strip()
    settings["bank_account_name"] = bank_account_name.strip()
    settings["tax_id"] = tax_id.strip()
    settings["btc_xpub"] = btc_xpub.strip() or None
    try:
        settings["btc_discount_percent"] = float(btc_discount_percent) if btc_discount_percent else 0
    except ValueError:
        settings["btc_discount_percent"] = 0
    settings["lightning_address"] = lightning_address.strip() or None
    settings["xrechnung_profile"] = xrechnung_profile if xrechnung_profile in ("basic", "en16931") else "basic"
    settings["btcpay_url"] = btcpay_url.strip()
    if btcpay_webhook_secret.strip():
        settings["btcpay_webhook_secret"] = btcpay_webhook_secret.strip()
    settings["logo_hidden"] = logo_hidden == "1"
    try:
        settings["default_payment_days"] = max(0, min(90, int(default_payment_days or 14)))
    except ValueError:
        settings["default_payment_days"] = 14
    for _k, _v in (("dunning_fee_1", dunning_fee_1), ("dunning_fee_2", dunning_fee_2),
                   ("dunning_fee_3", dunning_fee_3), ("default_interest_rate", default_interest_rate)):
        try:
            settings[_k] = max(0.0, float((_v or "0").replace(",", ".")))
        except ValueError:
            pass

    message = "Einstellungen gespeichert."

    # Logo löschen
    if delete_logo == "1" and os.path.exists(CUSTOM_LOGO_PATH):
        os.remove(CUSTOM_LOGO_PATH)
        message = "Einstellungen gespeichert. Logo entfernt."

    # Logo hochladen
    if logo and logo.filename:
        contents = await logo.read()
        allowed_ext = (".png", ".jpg", ".jpeg")
        fname = (logo.filename or "").lower()
        ctype = (logo.content_type or "").lower()
        if len(contents) > 2 * 1024 * 1024:  # Max 2 MB
            message = "Logo zu groß (max. 2 MB)."
        elif not fname.endswith(allowed_ext) or (ctype and ctype not in ("image/png", "image/jpeg")):
            message = "Nur PNG/JPG erlaubt."
        elif contents[:8:2] == b'\x89PNG\r\n\x1a\n'[::2] or contents[:2] == b'\xff\xd8':
            os.makedirs(os.path.dirname(CUSTOM_LOGO_PATH), exist_ok=True)
            with open(CUSTOM_LOGO_PATH, "wb") as f:
                f.write(contents)
            message = "Einstellungen gespeichert. Logo hochgeladen."
        else:
            try:
                from PIL import Image
                import io as _io
                Image.open(_io.BytesIO(contents)).verify()
                os.makedirs(os.path.dirname(CUSTOM_LOGO_PATH), exist_ok=True)
                with open(CUSTOM_LOGO_PATH, "wb") as f:
                    f.write(contents)
                message = "Einstellungen gespeichert. Logo hochgeladen."
            except Exception:
                message = "Ungültige Bilddatei."

    bk.save_settings(settings)
    settings["has_custom_logo"] = os.path.exists(CUSTOM_LOGO_PATH)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "settings": settings,
        "message": message,
        "license_status": get_license_status(),
    })


@app.post("/settings/license")
async def settings_license(request: Request):
    form = await request.form()
    email = form.get("license_email", "").strip()
    key = form.get("license_key", "").strip()

    settings = bk.get_settings()
    settings["license_email"] = email
    settings["license_key"] = key
    bk.save_settings(settings)

    license_message = None
    license_valid = False
    if email and key:
        if verify_license(email, key):
            license_valid = True
            if key.strip().upper().startswith("FREE-"):
                license_message = "Free-Tarif aktiviert (3 Rechnungen/Monat)!"
            elif key.strip().upper().startswith("BASIC-"):
                license_message = "Basic-Lizenz aktiviert (unbegrenzte Rechnungen)!"
            else:
                license_message = "Business-Lizenz aktiviert!"
        else:
            license_message = "Ungültiger Lizenzschlüssel oder falsche E-Mail."
    elif email or key:
        license_message = "Bitte E-Mail und Lizenzschlüssel eingeben."

    settings["has_custom_logo"] = os.path.exists(CUSTOM_LOGO_PATH)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "settings": settings,
        "message": None,
        "license_status": get_license_status(),
        "license_message": license_message,
        "license_valid": license_valid,
    })


@app.post("/settings/password")
async def settings_password(request: Request):
    form = await request.form()
    current = form.get("current_password", "")
    new_pw = form.get("new_password", "")
    new_pw_confirm = form.get("new_password_confirm", "")
    settings = bk.get_settings()

    error_msg = None
    if not _verify_password(current, settings.get("password_hash", "")):
        error_msg = "Aktuelles Passwort ist falsch."
    elif len(new_pw) < 8:
        error_msg = "Neues Passwort muss mindestens 8 Zeichen lang sein."
    elif new_pw != new_pw_confirm:
        error_msg = "Neue Passwörter stimmen nicht überein."
    else:
        settings["password_hash"] = _hash_password(new_pw)
        bk.save_settings(settings)

    settings["has_custom_logo"] = os.path.exists(CUSTOM_LOGO_PATH)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "settings": settings,
        "message": None,
        "license_status": get_license_status(),
        "pw_message": "Passwort geändert." if not error_msg else error_msg,
        "pw_error": bool(error_msg),
    })
