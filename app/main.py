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
STATIC_DIR = os.path.join(BASE_DIR, "static")

env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


class SimpleTemplates:
    """Einfache Template-Klasse die raw Jinja2 statt Starlette's Jinja2Templates nutzt.
    Vermeidet den 'unhashable dict' Bug mit PyInstaller."""
    def __init__(self, env):
        self.env = env
    def TemplateResponse(self, name, context):
        from starlette.responses import HTMLResponse
        # Business-Typ und Pro-Status automatisch injizieren
        if "is_pro" not in context:
            try:
                context["is_pro"] = is_pro_license()
            except Exception:
                context["is_pro"] = False
        if "business_type" not in context:
            try:
                bt = bk.get_settings().get("business_type", "kleinunternehmer")
                # Ohne Pro-Lizenz immer Kleinunternehmer
                context["business_type"] = bt if context.get("is_pro") else "kleinunternehmer"
            except Exception:
                context["business_type"] = "kleinunternehmer"
        html = self.env.get_template(name).render(**context)
        return HTMLResponse(html)


templates = SimpleTemplates(env)

# Static files (PWA manifest, icons, service worker)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Auth – Passwort-Login
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, hash_hex = stored.split("$", 1)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return hmac.compare_digest(h.hex(), hash_hex)


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
    """Generiert einen Lizenzschlüssel basierend auf E-Mail.
    Falls ein lokaler Salt existiert, wird dieser verwendet,
    sonst der Server-Secret (für Rückwärtskompatibilität)."""
    settings = bk.get_settings()
    secret = settings.get("license_salt") or LICENSE_SECRET
    key = hmac.new(secret.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:20]
    return "PRO-" + "-".join([key[i:i+4].upper() for i in range(0, 20, 4)])


def verify_license(email: str, license_key: str) -> bool:
    """Verifiziert ob der Lizenzschlüssel zur E-Mail passt.
    Prüft sowohl lokalen Salt als auch Server-Secret (Rückwärtskompatibilität)."""
    if not email or not license_key:
        return False
    
    # Mit lokalem Salt prüfen (neue Installationen)
    settings = bk.get_settings()
    if settings.get("license_salt"):
        expected = generate_license_key(email)
        if hmac.compare_digest(expected.upper(), license_key.upper().strip()):
            return True
    
    # Mit Server-Secret prüfen (ältere Keys/Rückwärtskompatibilität)
    settings = bk.get_settings()
    secret = LICENSE_SECRET
    expected = hmac.new(secret.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:20]
    expected = "PRO-" + "-".join([expected[i:i+4].upper() for i in range(0, 20, 4)])
    return hmac.compare_digest(expected.upper(), license_key.upper().strip())


def is_pro_license() -> bool:
    """Prüft ob eine gültige Pro-Lizenz vorhanden ist."""
    settings = bk.get_settings()
    return verify_license(
        settings.get("license_email", ""),
        settings.get("license_key", "")
    )


def get_license_status() -> dict:
    """Gibt den Lizenzstatus zurück."""
    settings = bk.get_settings()
    email = settings.get("license_email", "")
    key = settings.get("license_key", "")
    is_valid = verify_license(email, key) if email and key else False
    return {
        "email": email,
        "key": key,
        "is_valid": is_valid,
        "type": "pro" if is_valid else "basic",
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
    token = request.cookies.get("session")
    if not token:
        return False
    secret = _get_session_secret()
    expected = hmac.new(secret.encode(), b"authenticated", hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, expected)


def _make_session_token() -> str:
    secret = _get_session_secret()
    return hmac.new(secret.encode(), b"authenticated", hashlib.sha256).hexdigest()


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
    if len(password) < 4:
        return templates.TemplateResponse("setup.html", {
            "request": request, "error": "Passwort muss mindestens 4 Zeichen lang sein."
        })
    if password != password_confirm:
        return templates.TemplateResponse("setup.html", {
            "request": request, "error": "Passwörter stimmen nicht überein."
        })
    settings = bk.get_settings()
    settings["password_hash"] = _hash_password(password)
    bk.save_settings(settings)
    response = Response(status_code=302, headers={"Location": "/"})
    response.set_cookie("session", _make_session_token(), httponly=True, max_age=86400 * 30)
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
    form = await request.form()
    password = form.get("password", "")
    settings = bk.get_settings()
    if _is_setup_needed():
        return Response(status_code=302, headers={"Location": "/setup"})
    if _verify_password(password, settings.get("password_hash", "")):
        response = Response(status_code=302, headers={"Location": "/"})
        response.set_cookie("session", _make_session_token(), httponly=True, max_age=86400 * 30)
        return response
    return templates.TemplateResponse("login.html", {
        "request": request, "error": "Falsches Passwort."
    })


@app.get("/logout")
async def logout():
    response = Response(status_code=302, headers={"Location": "/login"})
    response.delete_cookie("session")
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Öffentliche Pfade
    if path in PUBLIC_PATHS or path.startswith("/static") or path.startswith("/pay/") or path.startswith("/api/pay/"):
        return await call_next(request)
    # Auth-Check
    if _is_setup_needed():
        return Response(status_code=302, headers={"Location": "/setup"})
    if not _is_authenticated(request):
        return Response(status_code=302, headers={"Location": "/login"})
    return await call_next(request)

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
    data_dir = os.path.join(PROJECT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)


def _get_next_invoice_number() -> str:
    _ensure_data_dir()
    year = datetime.date.today().year
    counter = {"year": year, "last_number": 0}

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

    with open(COUNTER_FILE, "w") as f:
        json.dump(counter, f)

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


def get_image_base64(path, max_height=None):
    if os.path.exists(path):
        mime_type = "image/svg+xml" if path.endswith(".svg") else "image/png"
        if max_height and not path.endswith(".svg"):
            try:
                from PIL import Image
                img = Image.open(path)
                if img.height > max_height:
                    ratio = max_height / img.height
                    new_width = int(img.width * ratio)
                    img = img.resize((new_width, max_height), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                return f"data:image/png;base64,{b64}"
            except Exception:
                pass
        with open(path, "rb") as image_file:
            b64 = base64.b64encode(image_file.read()).decode()
            return f"data:{mime_type};base64,{b64}"
    return None


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


def generate_qr_base64(data: str):
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode()}"


def generate_girocode_data(name: str, iban: str, bic: str, amount: float, purpose: str):
    iban_clean = iban.replace(" ", "")
    lines = ["BCD", "002", "1", "SCT", bic, name, iban_clean, f"EUR{amount:.2f}", "", "", purpose, ""]
    return "\n".join(lines)


def get_btc_price_eur():
    try:
        url = "https://api.kraken.com/0/public/Ticker?pair=XBTEUR"
        response = requests.get(url, timeout=5)
        data = response.json()
        price = float(data["result"]["XXBTZEUR"]["c"][0])
        return price
    except Exception as e:
        print(f"Kurs-Fehler: {e}")
        return 62500.0


# ---------------------------------------------------------------------------
# Bitcoin – Adressen-Ableitung & Zahlungsprüfung
# ---------------------------------------------------------------------------

def derive_btc_address(xpub: str, index: int) -> str:
    """Leitet eine BIP-84 Native SegWit Adresse aus zpub + index ab.
    zpub ist bereits auf Account-Ebene, daher direkt Change + AddressIndex."""
    if not Bip84:
        raise RuntimeError("bip-utils nicht installiert (pip install bip-utils)")
    bip84_ctx = Bip84.FromExtendedKey(xpub, Bip84Coins.BITCOIN)
    addr_ctx = bip84_ctx.Change(Bip44Changes.CHAIN_EXT).AddressIndex(index)
    return addr_ctx.PublicKey().ToAddress()


def get_next_btc_address() -> Optional[str]:
    """Gibt die nächste einzigartige BTC-Adresse zurück (aus xpub).
    Falls keine xpub konfiguriert ist, wird None zurückgegeben."""
    settings = bk.get_settings()
    xpub = settings.get("btc_xpub")
    if not xpub:
        return None
    index = settings.get("btc_address_index", 0)
    address = derive_btc_address(xpub, index)
    # Index für nächste Rechnung hochzählen
    settings["btc_address_index"] = index + 1
    bk.save_settings(settings)
    return address


def check_btc_payment(address: str) -> dict:
    """Prüft via Blockstream API ob Zahlung auf Adresse eingegangen ist.
    Returns: {"received": bool, "btc_amount": float, "txid": str|None, "sats": int}"""
    try:
        url = f"https://blockstream.info/api/address/{address}/utxo"
        response = requests.get(url, timeout=10)
        utxos = response.json()
        total_sats = sum(u.get("value", 0) for u in utxos)
        total_btc = total_sats / 100_000_000
        txid = utxos[0].get("txid") if utxos else None
        return {
            "received": total_btc > 0,
            "btc_amount": total_btc,
            "txid": txid,
            "sats": total_sats,
        }
    except Exception as e:
        print(f"Blockstream API Fehler: {e}")
        return {"received": False, "btc_amount": 0, "txid": None, "sats": 0}


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
    })


@app.get("/health")
async def health():
    return {"status": "ok", "zugferd": facturx is not None}


@app.post("/generate-pdf")
async def generate_pdf(request: InvoiceRequest):
    try:
        settings = bk.get_settings()
        biz = get_business_info()
        btc_rate = get_btc_price_eur()
        business_type = settings.get("business_type", "kleinunternehmer")

        # MwSt-Berechnung (nur mit Pro-Lizenz)
        if business_type == "regulaer" and is_pro_license():
            # unit_price ist Netto, MwSt wird berechnet
            total_net = sum(item.quantity * item.unit_price for item in request.items)
            total_vat = sum(item.quantity * item.unit_price * item.vat_rate for item in request.items)
            total_gross = total_net + total_vat
            is_kleinunternehmer = False
        else:
            # Kleinunternehmer: unit_price ist Brutto, keine MwSt
            total_net = sum(item.quantity * item.unit_price for item in request.items)
            total_vat = 0
            total_gross = total_net
            is_kleinunternehmer = True

        total_btc = total_gross / btc_rate
        invoice_no = _get_next_invoice_number()

        # Bankdaten aus Settings
        iban = request.iban or settings.get("bank_iban", "")
        bic = request.bic or settings.get("bank_bic", "")
        bank_name = request.bank_name or settings.get("bank_name", "")

        # Bankverbindung prüfen (nur wenn kein Bitcoin aktiviert)
        if not iban and not request.enable_btc:
            raise HTTPException(
                status_code=400,
                detail="Keine Bankverbindung hinterlegt. Bitte IBAN und BIC in den Einstellungen eintragen."
            )

        # QR Codes
        # Zahlungsseiten-QR (Haupt-QR)
        pay_url = f"https://btcrechnung.de/pay/{invoice_no}"
        pay_qr = generate_qr_base64(pay_url)

        # BTC-Adresse: xpub-basiert (unique pro Rechnung) oder manuell
        btc_address = None
        btc_qr = None
        btc_discount_percent = settings.get("btc_discount_percent", 0)
        lightning_address = settings.get("lightning_address")
        if request.enable_btc:
            try:
                btc_address = get_next_btc_address() or request.btc_address
                if btc_address:
                    # Rabatt/Aufschlag berechnen
                    if btc_discount_percent != 0:
                        discount_factor = 1 - (btc_discount_percent / 100)
                        total_btc = (total_gross * discount_factor) / btc_rate
                    
                    btc_uri = f"bitcoin:{btc_address}?amount={total_btc:.8f}"
                    if lightning_address:
                        btc_uri += f"&lightning={lightning_address}"
                    btc_qr = generate_qr_base64(btc_uri)
            except Exception as e:
                print(f"BTC address generation failed: {e}")
                btc_address = None

        # GiroCode für SEPA
        account_name = settings.get("bank_account_name") or biz["name"]
        giro_data = generate_girocode_data(account_name, iban, bic, total_gross, f"Rechnung {invoice_no}")
        bank_qr = generate_qr_base64(giro_data) if iban else None

        # Logos
        logo_path = get_logo_path()
        logo_data = get_image_base64(logo_path, max_height=80) if logo_path else None
        btc_icon_data = get_image_base64(BTC_ICON_PATH, max_height=20)

        # HTML zu PDF
        template = env.get_template('invoice.html')
        html_out = template.render(
            studio_name=biz["name"],
            slogan=biz["slogan"],
            studio_address=biz["address"],
            studio_phone=biz["phone"],
            studio_email=biz["email"],
            customer_name=request.customer_name,
            customer_address=request.customer_address,
            items=request.items,
            total_gross=total_gross,
            total_btc=total_btc,
            btc_rate=btc_rate,
            btc_address=btc_address,
            btc_discount_percent=btc_discount_percent,
            lightning_address=settings.get("lightning_address"),
            iban=iban,
            bic=bic,
            bank_name=bank_name,
            bank_account_name=settings.get("bank_account_name"),
            qr_code=btc_qr,
            bank_qr=bank_qr,
            pay_qr=pay_qr,
            pay_url=pay_url,
            logo_data=logo_data,
            btc_icon_data=btc_icon_data,
            is_kleinunternehmer=is_kleinunternehmer,
            total_net=total_net,
            total_vat=total_vat,
            invoice_date=datetime.date.today().strftime("%d.%m.%Y"),
            invoice_number=invoice_no,
            tax_id=settings.get("tax_id", ""),
            business_type=business_type
        )

        pdf_buffer = io.BytesIO()
        if pisa:
            result = pisa.CreatePDF(io.BytesIO(html_out.encode("utf-8")), dest=pdf_buffer)
            if result.err:
                raise HTTPException(status_code=500, detail="PDF-Generierung fehlgeschlagen")
        else:
            raise HTTPException(status_code=500, detail="xhtml2pdf nicht installiert")

        pdf_content = pdf_buffer.getvalue()

        # ZUGFeRD XML generieren
        line_items_xml = [
            {
                "description": item.description,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.quantity * item.unit_price,
            }
            for item in request.items
        ]
        zugferd_xml = generate_zugferd_xml(
            invoice_number=invoice_no,
            issue_date=datetime.date.today(),
            seller_name=biz["name"],
            seller_address=biz["address"],
            buyer_name=request.customer_name,
            buyer_address=request.customer_address,
            line_items=line_items_xml,
            total_eur=total_gross,
            iban=request.iban,
            is_kleinunternehmer=is_kleinunternehmer,
            seller_tax_id=bk.get_settings().get("tax_id", ""),
        )

        # ZUGFeRD in PDF einbetten (inkl. XMP-Metadaten & PDF/A-3)
        if facturx:
            try:
                pdf_content = facturx.generate_facturx_from_binary(
                    pdf_content,
                    zugferd_xml,
                    facturx_level='basic',
                    check_xsd=False,
                )
            except Exception as fe:
                print(f"ZUGFeRD Fehler: {fe}")
                import traceback
                traceback.print_exc()

        # Invoice in Buchhaltung loggen
        bk.log_invoice({
            "id": invoice_no,
            "date": datetime.date.today().isoformat(),
            "customer_name": request.customer_name,
            "customer_address": request.customer_address,
            "amount": total_gross,
            "items_description": ", ".join(f"{item.description} ({item.quantity}x)" for item in request.items),
            "payment_received": False,
            "payment_date": None,
            "invoice_filename": f"Rechnung_{invoice_no}.pdf",
            "btc_rate_at_creation": btc_rate,
            "btc_amount": total_btc,
            "btc_address": btc_address,
        })

        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=Rechnung_{invoice_no}.pdf"}
        )

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
    summary = bk.get_monthly_summary(year, month)
    yearly = bk.get_yearly_summary(year)
    transactions = bk.get_recent_transactions(limit=10)
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
    for e in filtered:
        e["category_label"] = CATEGORY_LABELS.get(e["category"], e["category"])

    total = sum(e["amount"] for e in filtered)

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
    bk.create_expense(data)
    return Response(status_code=302, headers={"Location": "/expenses"})


@app.post("/expenses/{expense_id}/delete")
async def delete_expense(expense_id: str):
    bk.delete_expense(expense_id)
    return Response(status_code=302, headers={"Location": "/expenses"})


# ---------------------------------------------------------------------------
# Endpoints – Einnahmen
# ---------------------------------------------------------------------------

@app.get("/income")
async def income_page(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    year = year or datetime.date.today().year
    all_invoices = bk.get_all_invoices()

    filtered = [i for i in all_invoices if i["date"].startswith(str(year))]
    if month:
        filtered = [i for i in filtered if i["date"].startswith(f"{year}-{month:02d}")]

    total = sum(i["amount"] for i in filtered)

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
    amount: float = Form(...),
    customer_name: str = Form(...),
    items_description: str = Form(...),
    payment_received: str = Form("false"),
    payment_date: str = Form(""),
    payment_method: str = Form("bank_transfer"),
):
    invoice_no = _get_next_invoice_number()
    
    invoice_data = {
        "id": invoice_no,
        "date": date,
        "customer_name": customer_name,
        "customer_address": "",
        "amount": amount,
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


@app.post("/income/{invoice_id}/delete")
async def delete_income(invoice_id: str):
    bk.delete_invoice(invoice_id)
    return Response(status_code=302, headers={"Location": "/income"})


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
    invoices = [i for i in bk.get_all_invoices() if i["date"].startswith(str(year))]
    expenses = [e for e in bk.get_all_expenses() if e["date"].startswith(str(year))]
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
    invoices = [i for i in bk.get_all_invoices() if i["date"].startswith(str(year))]
    expenses = [e for e in bk.get_all_expenses() if e["date"].startswith(str(year))]

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
    # Einnahmen
    for inv in sorted(invoices, key=lambda x: x["date"]):
        w.writerow([
            beleg_nr,
            inv["date"],
            "1200",  # Forderungen (Soll)
            "8400",  # Erlöse (Haben)
            f"{inv['amount']:.2f}".replace(".", ","),
            f"Rechnung {inv['id']}",
            "",
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
async def settings_page(request: Request):
    settings = bk.get_settings()
    settings["has_custom_logo"] = os.path.exists(CUSTOM_LOGO_PATH)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "settings": settings,
        "message": None,
        "license_status": get_license_status(),
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
    settings["logo_hidden"] = logo_hidden == "1"

    message = "Einstellungen gespeichert."

    # Logo löschen
    if delete_logo == "1" and os.path.exists(CUSTOM_LOGO_PATH):
        os.remove(CUSTOM_LOGO_PATH)
        message = "Einstellungen gespeichert. Logo entfernt."

    # Logo hochladen
    if logo and logo.filename:
        contents = await logo.read()
        if len(contents) > 2 * 1024 * 1024:  # Max 2 MB
            message = "Logo zu groß (max. 2 MB)."
        else:
            os.makedirs(os.path.dirname(CUSTOM_LOGO_PATH), exist_ok=True)
            with open(CUSTOM_LOGO_PATH, "wb") as f:
                f.write(contents)
            message = "Einstellungen gespeichert. Logo hochgeladen."

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
            license_message = "Business-Lizenz aktiviert!"
            license_valid = True
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
    elif len(new_pw) < 4:
        error_msg = "Neues Passwort muss mindestens 4 Zeichen lang sein."
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
