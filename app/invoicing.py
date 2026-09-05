"""Wiederverwendbare Rechnungserstellung (HTTP-Route + Abo-Runner teilen sich die Logik)."""
import datetime
import io
import os
from typing import Callable


def validate_items(items: list):
    if not items:
        raise ValueError("Mindestens eine Position erforderlich.")
    for idx, it in enumerate(items):
        desc = it["description"] if isinstance(it, dict) else it.description
        qty = it["quantity"] if isinstance(it, dict) else it.quantity
        price = it["unit_price"] if isinstance(it, dict) else it.unit_price
        if not desc or not str(desc).strip():
            raise ValueError(f"Position {idx + 1}: Beschreibung fehlt.")
        if not (float(qty) > 0):
            raise ValueError(f"Position {idx + 1}: ungültige Menge.")
        if not (float(price) >= 0):
            raise ValueError(f"Position {idx + 1}: ungültiger Preis.")


def _val(it, key, default=0):
    if isinstance(it, dict):
        v = it.get(key, default)
    else:
        v = getattr(it, key, default)
    return v if v is not None else default


def totals(items: list, business_type: str, is_pro: bool):
    if business_type == "regulaer" and is_pro:
        total_net = sum(float(_val(i, "quantity")) * float(_val(i, "unit_price")) for i in items)
        total_vat = sum(float(_val(i, "quantity")) * float(_val(i, "unit_price")) * float(_val(i, "vat_rate"))
                        for i in items)
        return total_net, total_vat, total_net + total_vat, False
    total_net = sum(float(_val(i, "quantity")) * float(_val(i, "unit_price")) for i in items)
    return total_net, 0.0, total_net, True


def create_invoice(
    payload: dict,
    *,
    settings: dict,
    biz: dict,
    jinja_env,
    pdf_dir: str,
    logo_paths: dict,
    is_pro: bool,
    business_type: str,
    btc_rate: float,
    number_provider: Callable[[], str],
    peek_provider: Callable[[], str],
    address_provider: Callable[[], str | None],
    preview: bool = False,
) -> dict:
    """Erstellt PDF + ZUGFeRD, speichert Datei + Buchung (außer preview).
    payload: customer_name, customer_address, items[{description,quantity,unit_price,vat_rate}],
             enable_btc, btc_address, iban, bic, bank_name, doc_type, payment_days,
             discount_days, discount_percent, invoice_date (ISO oder None).
    Raises ValueError bei Validierungsfehlern, RuntimeError bei PDF-Fehlern."""
    import qrcode  # noqa - sicherstellen dass vorhanden
    from . import bitcoin as btcmod
    from .pdf_utils import generate_qr_base64, generate_girocode_data, get_image_base64
    from .zugferd import generate_zugferd_xml, validate_invoice
    from . import bookkeeping as bk

    try:
        import xhtml2pdf.pisa as pisa
    except ImportError:
        pisa = None
    try:
        import facturx
    except ImportError:
        facturx = None

    items = payload.get("items", [])
    validate_items(items)
    customer_name = (payload.get("customer_name") or "").strip()
    customer_address = payload.get("customer_address") or ""
    if not customer_name:
        raise ValueError("Kundenname fehlt.")

    total_net, total_vat, total_gross, is_kleinunternehmer = totals(items, business_type, is_pro)
    total_btc = total_gross / btc_rate if btc_rate else 0

    profile = settings.get("xrechnung_profile", "basic")
    if profile not in ("basic", "en16931"):
        profile = "basic"
    buyer_reference = (payload.get("buyer_reference") or "").strip()
    problems = validate_invoice(profile, biz.get("name", ""), biz.get("address", ""),
                                customer_name, customer_address,
                                settings.get("tax_id", ""), buyer_reference, total_gross,
                                settings.get("business_email", ""), biz.get("phone", ""),
                                payload.get("iban") or settings.get("bank_iban", ""))
    if problems:
        raise ValueError("E-Rechnung: " + " ".join(problems))

    doc_type = (payload.get("doc_type") or "rechnung").lower()
    if doc_type not in ("rechnung", "gutschrift"):
        doc_type = "rechnung"
    if preview:
        invoice_no = peek_provider()
    else:
        invoice_no = number_provider()
    if doc_type == "gutschrift":
        invoice_no = invoice_no.replace("RE-", "GS-", 1)

    try:
        if buyer_reference:
            bk.upsert_customer(customer_name, customer_address, buyer_reference)
        else:
            bk.upsert_customer(customer_name, customer_address)
    except Exception:
        pass

    iban = payload.get("iban") or settings.get("bank_iban", "")
    bic = payload.get("bic") or settings.get("bank_bic", "")
    bank_name = payload.get("bank_name") or settings.get("bank_name", "")
    if not iban and not payload.get("enable_btc"):
        raise ValueError("Keine Bankverbindung hinterlegt. Bitte IBAN und BIC in den Einstellungen eintragen.")

    pay_url = f"https://btcrechnung.de/pay/{invoice_no}"
    pay_qr = generate_qr_base64(pay_url)

    btc_address = None
    btc_qr = None
    btc_discount_percent = settings.get("btc_discount_percent", 0)
    lightning_address = settings.get("lightning_address")
    if payload.get("enable_btc"):
        try:
            btc_address = payload.get("btc_address") if preview else (address_provider() or payload.get("btc_address"))
            if btc_address:
                if btc_discount_percent != 0:
                    total_btc = (total_gross * (1 - (btc_discount_percent / 100))) / btc_rate
                btc_uri = f"bitcoin:{btc_address}?amount={total_btc:.8f}"
                if lightning_address:
                    btc_uri += f"&lightning={lightning_address}"
                btc_qr = generate_qr_base64(btc_uri)
        except Exception as e:
            print(f"BTC address generation failed: {e}")
            btc_address = None

    account_name = settings.get("bank_account_name") or biz["name"]
    giro_data = generate_girocode_data(account_name, iban, bic, total_gross, f"Rechnung {invoice_no}")
    bank_qr = generate_qr_base64(giro_data) if iban else None

    logo_path = logo_paths.get("custom") if (logo_paths.get("custom") and not settings.get("logo_hidden")) else None
    if not logo_path and not settings.get("logo_hidden"):
        logo_path = logo_paths.get("default")
    logo_data = get_image_base64(logo_path, max_height=80) if logo_path else None
    btc_icon_data = get_image_base64(logo_paths.get("btc_icon"), max_height=20)

    pay_days = max(0, int(payload.get("payment_days") or 0))
    disc_days = max(0, int(payload.get("discount_days") or 0))
    disc_pct = float(payload.get("discount_percent") or 0.0)
    try:
        inv_date = datetime.date.fromisoformat(payload.get("invoice_date")) if payload.get("invoice_date") else datetime.date.today()
    except ValueError:
        inv_date = datetime.date.today()
    due_date = inv_date + datetime.timedelta(days=pay_days)

    def plain(it, key, default=0):
        v = it[key] if isinstance(it, dict) else getattr(it, key, default)
        return v if v is not None else default

    class _Item:
        def __init__(self, d):
            self.description = plain(d, "description", "")
            self.quantity = float(plain(d, "quantity", 0))
            self.unit_price = float(plain(d, "unit_price", 0))
            self.vat_rate = float(plain(d, "vat_rate", 0))

    plain_items = [_Item(i) for i in items]
    html_out = jinja_env.get_template('invoice.html').render(
        studio_name=biz["name"], slogan=biz["slogan"], studio_address=biz["address"],
        studio_phone=biz["phone"], studio_email=biz["email"],
        customer_name=customer_name, customer_address=customer_address,
        items=plain_items, total_gross=total_gross, total_btc=total_btc, btc_rate=btc_rate,
        btc_address=btc_address, btc_discount_percent=btc_discount_percent,
        lightning_address=lightning_address, iban=iban, bic=bic, bank_name=bank_name,
        bank_account_name=settings.get("bank_account_name"),
        qr_code=btc_qr, bank_qr=bank_qr, pay_qr=pay_qr, pay_url=pay_url,
        logo_data=logo_data, btc_icon_data=btc_icon_data,
        is_kleinunternehmer=is_kleinunternehmer, total_net=total_net, total_vat=total_vat,
        invoice_date=inv_date.strftime("%d.%m.%Y"), invoice_number=invoice_no,
        tax_id=settings.get("tax_id", ""), business_type=business_type,
        doc_type=doc_type, payment_days=pay_days, due_date=due_date.strftime("%d.%m.%Y"),
        discount_days=disc_days, discount_percent=disc_pct,
        buyer_reference=buyer_reference,
    )

    pdf_buffer = io.BytesIO()
    if pisa:
        result = pisa.CreatePDF(io.BytesIO(html_out.encode("utf-8")), dest=pdf_buffer)
        if result.err:
            raise RuntimeError("PDF-Generierung fehlgeschlagen")
    else:
        raise RuntimeError("xhtml2pdf nicht installiert")
    pdf_content = pdf_buffer.getvalue()

    line_items_xml = [
        {"description": plain(i, "description", ""), "quantity": float(plain(i, "quantity", 0)),
         "unit_price": float(plain(i, "unit_price", 0)),
         "vat_rate": float(plain(i, "vat_rate", 0)),
         "line_total": float(plain(i, "quantity", 0)) * float(plain(i, "unit_price", 0))}
        for i in items
    ]
    vat_breakdown = None
    if not is_kleinunternehmer:
        by_rate: dict[float, float] = {}
        for li in line_items_xml:
            by_rate[li["vat_rate"]] = by_rate.get(li["vat_rate"], 0.0) + li["line_total"]
        vat_breakdown = [{"rate": r, "net": round(n, 2)} for r, n in sorted(by_rate.items())]
    pay_terms = f"Zahlbar bis {due_date.strftime('%d.%m.%Y')}"
    if disc_pct and disc_days:
        pay_terms += f", {disc_pct:.2f} % Skonto bei Zahlung innerhalb von {disc_days} Tagen".replace(".", ",")
    zugferd_xml = generate_zugferd_xml(
        invoice_number=invoice_no, issue_date=inv_date,
        seller_name=biz["name"], seller_address=biz["address"],
        buyer_name=customer_name, buyer_address=customer_address,
        line_items=line_items_xml, total_eur=total_gross, iban=payload.get("iban") or settings.get("bank_iban", ""),
        is_kleinunternehmer=is_kleinunternehmer,
        seller_tax_id=settings.get("tax_id", ""),
        profile=profile, buyer_reference=buyer_reference or None,
        vat_breakdown=vat_breakdown,
        type_code="381" if doc_type == "gutschrift" else "380",
        total_net=total_net,
        seller_email=settings.get("business_email", "") or None,
        seller_phone=biz.get("phone", "") or None,
        due_date=due_date, payment_terms=pay_terms,
        proprietary_id=("BTC:" + btc_address) if (btc_address and not (payload.get("iban") or settings.get("bank_iban", ""))) else None,
    )
    if facturx:
        try:
            pdf_content = facturx.generate_facturx_from_binary(
                pdf_content, zugferd_xml,
                facturx_level='en16931' if profile == 'en16931' else 'basic',
                check_xsd=False)
        except Exception as fe:
            print(f"ZUGFeRD Fehler: {fe}")

    if preview:
        return {"invoice_no": invoice_no, "pdf": pdf_content, "preview": True,
                "total_gross": total_gross, "total_btc": total_btc}

    os.makedirs(pdf_dir, exist_ok=True)
    try:
        with open(os.path.join(pdf_dir, f"{invoice_no}.pdf"), "wb") as f:
            f.write(pdf_content)
    except Exception as e:
        print(f"PDF speichern fehlgeschlagen: {e}")

    record = {
        "id": invoice_no, "date": inv_date.isoformat(),
        "customer_name": customer_name, "customer_address": customer_address,
        "amount": total_gross,
        "items_description": ", ".join(
            f"{plain(i, 'description', '')} ({plain(i, 'quantity', 0)}x)" for i in items),
        "items": [{"description": plain(i, "description", ""), "quantity": float(plain(i, "quantity", 0)),
                   "unit_price": float(plain(i, "unit_price", 0)),
                   "vat_rate": float(plain(i, "vat_rate", 0))} for i in items],
        "payment_received": False, "payment_date": None,
        "invoice_filename": f"Rechnung_{invoice_no}.pdf",
        "btc_rate_at_creation": btc_rate, "btc_amount": total_btc, "btc_address": btc_address,
        "doc_type": doc_type, "payment_days": pay_days, "due_date": due_date.isoformat(),
        "discount_days": disc_days, "discount_percent": disc_pct,
        "buyer_reference": buyer_reference, "xrechnung_profile": profile,
        "dunning_level": 0, "dunning_fees": 0.0,
    }
    bk.log_invoice(record)
    return {"invoice_no": invoice_no, "pdf": pdf_content, "record": record,
            "total_gross": total_gross, "total_btc": total_btc}
