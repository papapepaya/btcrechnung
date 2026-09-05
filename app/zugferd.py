"""
ZUGFeRD 2.2 / Factur-X XML Generator (EN16931 Level)
Erzeugt ein CII-konformes XML für die Einbettung in PDF.
"""

import datetime
from decimal import Decimal
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring


def generate_zugferd_xml(
    invoice_number: str,
    issue_date: datetime.date,
    seller_name: str,
    seller_address: str,
    buyer_name: str,
    buyer_address: str,
    line_items: list[dict],
    total_eur: float,
    currency: str = "EUR",
    seller_tax_id: Optional[str] = None,
    buyer_tax_id: Optional[str] = None,
    iban: Optional[str] = None,
    is_kleinunternehmer: bool = True,
    profile: str = "basic",
    buyer_reference: Optional[str] = None,
    vat_breakdown: Optional[list] = None,
    type_code: str = "380",
    total_net: Optional[float] = None,
    seller_email: Optional[str] = None,
    seller_phone: Optional[str] = None,
    buyer_email: Optional[str] = None,
    due_date: Optional[datetime.date] = None,
    payment_terms: Optional[str] = None,
    proprietary_id: Optional[str] = None,
) -> bytes:
    ns = {
        "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
        "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
        "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    for prefix, uri in ns.items():
        _register_ns(prefix, uri)

    root = Element(f"{{{ns['rsm']}}}CrossIndustryInvoice")
    root.set(
        f"{{{ns['xsi']}}}schemaLocation",
        "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100 "
        "CrossIndustryInvoice_100pD16B.xsd",
    )

    if is_kleinunternehmer:
        vat_groups = [{"rate": 0.0, "net": total_eur, "tax": 0.0,
                       "category": "E", "reason": "Steuerfreie Umsätze gemäß § 19 UStG"}]
    elif vat_breakdown:
        vat_groups = []
        for g in vat_breakdown:
            rate = float(g.get("rate", 0))
            net = float(g.get("net", 0))
            vat_groups.append({"rate": rate, "net": net,
                               "tax": round(net * rate, 2), "category": "S"})
    else:
        vat_groups = [{"rate": 0.0, "net": total_eur, "tax": 0.0, "category": "S"}]


    # --- ExchangedDocumentContext ---
    ctx = SubElement(root, f"{{{ns['rsm']}}}ExchangedDocumentContext")
    if profile == "en16931":
        proc = SubElement(ctx, f"{{{ns['ram']}}}BusinessProcessSpecifiedDocumentContextParameter")
        SubElement(proc, f"{{{ns['ram']}}}ID").text = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
    guideline = SubElement(ctx, f"{{{ns['ram']}}}GuidelineSpecifiedDocumentContextParameter")
    if profile == "en16931":
        SubElement(guideline, f"{{{ns['ram']}}}ID").text = "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_3.0"
    else:
        SubElement(guideline, f"{{{ns['ram']}}}ID").text = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic"

    # --- ExchangedDocument ---
    doc = SubElement(root, f"{{{ns['rsm']}}}ExchangedDocument")
    SubElement(doc, f"{{{ns['ram']}}}ID").text = invoice_number
    SubElement(doc, f"{{{ns['ram']}}}TypeCode").text = type_code if type_code in ("380", "381") else "380"



    issue = SubElement(doc, f"{{{ns['ram']}}}IssueDateTime")
    ts = SubElement(issue, f"{{{ns['udt']}}}DateTimeString")
    ts.set("format", "102")
    ts.text = issue_date.strftime("%Y%m%d")

    # --- SupplyChainTradeTransaction ---
    tx = SubElement(root, f"{{{ns['rsm']}}}SupplyChainTradeTransaction")

    # -- Line Items --
    for idx, item in enumerate(line_items, start=1):
        line = SubElement(tx, f"{{{ns['ram']}}}IncludedSupplyChainTradeLineItem")

        line_doc = SubElement(line, f"{{{ns['ram']}}}AssociatedDocumentLineDocument")
        SubElement(line_doc, f"{{{ns['ram']}}}LineID").text = str(idx)

        product = SubElement(line, f"{{{ns['ram']}}}SpecifiedTradeProduct")
        SubElement(product, f"{{{ns['ram']}}}Name").text = item["description"]

        line_agr = SubElement(line, f"{{{ns['ram']}}}SpecifiedLineTradeAgreement")
        price = SubElement(line_agr, f"{{{ns['ram']}}}NetPriceProductTradePrice")
        charge = SubElement(price, f"{{{ns['ram']}}}ChargeAmount")
        charge.set("currencyID", currency)
        charge.text = f"{Decimal(str(item['unit_price'])):.4f}"

        line_del = SubElement(line, f"{{{ns['ram']}}}SpecifiedLineTradeDelivery")
        qty = SubElement(line_del, f"{{{ns['ram']}}}BilledQuantity")
        qty.set("unitCode", "C62")
        qty.text = f"{Decimal(str(item['quantity'])):.2f}"

        line_settle = SubElement(line, f"{{{ns['ram']}}}SpecifiedLineTradeSettlement")
        line_tax = SubElement(line_settle, f"{{{ns['ram']}}}ApplicableTradeTax")
        SubElement(line_tax, f"{{{ns['ram']}}}TypeCode").text = "VAT"
        item_rate = float(item.get("vat_rate", 0) or 0)
        item_cat = "E" if is_kleinunternehmer else ("S" if item_rate > 0 else "E")
        SubElement(line_tax, f"{{{ns['ram']}}}CategoryCode").text = item_cat
        SubElement(line_tax, f"{{{ns['ram']}}}RateApplicablePercent").text = f"{item_rate * 100:.2f}"

        line_sum = SubElement(line_settle, f"{{{ns['ram']}}}SpecifiedTradeSettlementLineMonetarySummation")
        line_total = SubElement(line_sum, f"{{{ns['ram']}}}LineTotalAmount")
        line_total.set("currencyID", currency)
        line_total.text = f"{Decimal(str(item['line_total'])):.2f}"

    # -- TradeAgreement --
    agr = SubElement(tx, f"{{{ns['ram']}}}ApplicableHeaderTradeAgreement")
    if buyer_reference:
        SubElement(agr, f"{{{ns['ram']}}}BuyerReference").text = buyer_reference

    seller = SubElement(agr, f"{{{ns['ram']}}}SellerTradeParty")
    SubElement(seller, f"{{{ns['ram']}}}Name").text = seller_name
    _add_address(seller, seller_address, ns)
    if seller_email:
        uri = SubElement(seller, f"{{{ns['ram']}}}URIUniversalCommunication")
        uri_id = SubElement(uri, f"{{{ns['ram']}}}URIID")
        uri_id.set("schemeID", "EM")
        uri_id.text = seller_email
    if seller_phone or seller_email:
        contact = SubElement(seller, f"{{{ns['ram']}}}DefinedTradeContact")
        SubElement(contact, f"{{{ns['ram']}}}PersonName").text = seller_name
        if seller_phone:
            tel = SubElement(contact, f"{{{ns['ram']}}}TelephoneUniversalCommunication")
            SubElement(tel, f"{{{ns['ram']}}}CompleteNumber").text = seller_phone
        if seller_email:
            mail = SubElement(contact, f"{{{ns['ram']}}}EmailURIUniversalCommunication")
            SubElement(mail, f"{{{ns['ram']}}}URIID").text = seller_email
    # Seller Tax ID – immer angeben (BR-CO-26)
    if seller_tax_id:
        tax = SubElement(seller, f"{{{ns['ram']}}}SpecifiedTaxRegistration")
        tid = SubElement(tax, f"{{{ns['ram']}}}ID")
        tid.set("schemeID", "VA")
        tid.text = seller_tax_id

    buyer = SubElement(agr, f"{{{ns['ram']}}}BuyerTradeParty")
    SubElement(buyer, f"{{{ns['ram']}}}Name").text = buyer_name
    _add_address(buyer, buyer_address, ns)
    if buyer_email:
        uri = SubElement(buyer, f"{{{ns['ram']}}}URIUniversalCommunication")
        uri_id = SubElement(uri, f"{{{ns['ram']}}}URIID")
        uri_id.set("schemeID", "EM")
        uri_id.text = buyer_email
    elif buyer_reference:
        uri = SubElement(buyer, f"{{{ns['ram']}}}URIUniversalCommunication")
        uri_id = SubElement(uri, f"{{{ns['ram']}}}URIID")
        uri_id.set("schemeID", "9958")
        uri_id.text = buyer_reference
    if buyer_tax_id:
        tax = SubElement(buyer, f"{{{ns['ram']}}}SpecifiedTaxRegistration")
        tid = SubElement(tax, f"{{{ns['ram']}}}ID")
        tid.set("schemeID", "VA")
        tid.text = buyer_tax_id

    # -- TradeDelivery --
    delivery = SubElement(tx, f"{{{ns['ram']}}}ApplicableHeaderTradeDelivery")
    actual_delivery = SubElement(delivery, f"{{{ns['ram']}}}ActualDeliverySupplyChainEvent")
    occ = SubElement(actual_delivery, f"{{{ns['ram']}}}OccurrenceDateTime")
    occ_dt = SubElement(occ, f"{{{ns['udt']}}}DateTimeString")
    occ_dt.set("format", "102")
    occ_dt.text = issue_date.strftime("%Y%m%d")

    # -- TradeSettlement --
    settlement = SubElement(tx, f"{{{ns['ram']}}}ApplicableHeaderTradeSettlement")
    SubElement(settlement, f"{{{ns['ram']}}}InvoiceCurrencyCode").text = currency

    # Payment means (BR-CO-27: IBAN oder Proprietary ID Pflicht)
    pm = SubElement(settlement, f"{{{ns['ram']}}}SpecifiedTradeSettlementPaymentMeans")
    clean_iban = (iban or "").replace(" ", "")
    SubElement(pm, f"{{{ns['ram']}}}TypeCode").text = "58" if clean_iban else "30"
    payee = SubElement(pm, f"{{{ns['ram']}}}PayeePartyCreditorFinancialAccount")
    if clean_iban:
        SubElement(payee, f"{{{ns['ram']}}}IBANID").text = clean_iban
    elif proprietary_id:
        SubElement(payee, f"{{{ns['ram']}}}ProprietaryID").text = proprietary_id
    else:
        SubElement(payee, f"{{{ns['ram']}}}ProprietaryID").text = invoice_number

    # Payment terms + due date (BR-CO-25)
    if due_date is not None or payment_terms:
        terms = SubElement(settlement, f"{{{ns['ram']}}}SpecifiedTradePaymentTerms")
        if payment_terms:
            SubElement(terms, f"{{{ns['ram']}}}Description").text = payment_terms
        if due_date is not None:
            dd = SubElement(terms, f"{{{ns['ram']}}}DueDateDateTime")
            dd_ts = SubElement(dd, f"{{{ns['ram']}}}DateTimeString")
            dd_ts.set("format", "102")
            dd_ts.text = due_date.strftime("%Y%m%d")

    def _amount(parent, tag, value):
        el = SubElement(parent, f"{{{ns['ram']}}}{tag}")
        el.set("currencyID", currency)
        el.text = f"{Decimal(str(value)):.2f}"
        return el

    # Trade tax (je Steuersatz ein Block)
    tax_total = 0.0
    for g in vat_groups:
        tax_subtotal = SubElement(settlement, f"{{{ns['ram']}}}ApplicableTradeTax")
        _amount(tax_subtotal, "CalculatedAmount", round(g['tax'], 2))
        SubElement(tax_subtotal, f"{{{ns['ram']}}}TypeCode").text = "VAT"
        if g.get("reason"):
            SubElement(tax_subtotal, f"{{{ns['ram']}}}ExemptionReason").text = g["reason"]
        _amount(tax_subtotal, "BasisAmount", round(g['net'], 2))
        SubElement(tax_subtotal, f"{{{ns['ram']}}}CategoryCode").text = g["category"]
        SubElement(tax_subtotal, f"{{{ns['ram']}}}RateApplicablePercent").text = f"{g['rate'] * 100:.2f}"
        tax_total += g["tax"]
    # Monetary summation
    net_total = total_net if total_net is not None else (total_eur - tax_total)
    summation = SubElement(settlement, f"{{{ns['ram']}}}SpecifiedTradeSettlementHeaderMonetarySummation")
    _amount(summation, "LineTotalAmount", round(net_total, 2))
    _amount(summation, "ChargeTotalAmount", 0.00)
    _amount(summation, "AllowanceTotalAmount", 0.00)
    _amount(summation, "TaxBasisTotalAmount", round(net_total, 2))
    _amount(summation, "TaxTotalAmount", round(tax_total, 2))
    _amount(summation, "GrandTotalAmount", round(total_eur, 2))
    _amount(summation, "DuePayableAmount", round(total_eur, 2))

    return tostring(root, encoding="unicode", xml_declaration=True).encode("utf-8")


def _add_address(party_element, address_str: str, ns: dict):
    addr = SubElement(party_element, f"{{{ns['ram']}}}PostalTradeAddress")
    lines = [l.strip() for l in address_str.replace("\n", ",").split(",") if l.strip()]
    postcode = None
    city = None
    street = None

    if len(lines) >= 2:
        street = lines[0]
        last = lines[-1].strip()
        parts = last.split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            postcode = parts[0]
            city = parts[1]
        else:
            city = last
    else:
        street = address_str

    if postcode:
        SubElement(addr, f"{{{ns['ram']}}}PostcodeCode").text = postcode
    SubElement(addr, f"{{{ns['ram']}}}LineOne").text = street
    if city:
        SubElement(addr, f"{{{ns['ram']}}}CityName").text = city
    SubElement(addr, f"{{{ns['ram']}}}CountryID").text = "DE"


def _register_ns(prefix, uri):
    import xml.etree.ElementTree as ET
    ET.register_namespace(prefix, uri)


LEITWEG_RE = r"^[0-9]{2,12}-[0-9A-Za-z\-]{1,30}-[0-9A-Za-z]{2}$|^[0-9A-Za-z\-]{5,50}$"


def validate_invoice(profile: str, seller_name: str, seller_address: str,
                     buyer_name: str, buyer_address: str, seller_tax_id: str,
                     buyer_reference: Optional[str], total_eur: float,
                     seller_email: Optional[str] = None,
                     seller_phone: Optional[str] = None,
                     iban: Optional[str] = None) -> list:
    """Prueft Pflichtfelder je Profil. Gibt Liste von Fehlertexten zurueck (leer = ok)."""
    import re
    errors = []
    if not seller_name or not seller_name.strip():
        errors.append("Absendername fehlt (Einstellungen → Firma).")
    if not seller_address or not seller_address.strip():
        errors.append("Absenderadresse fehlt (Einstellungen → Firma).")
    if not buyer_name or not buyer_name.strip():
        errors.append("Kundenname fehlt.")
    if not buyer_address or not buyer_address.strip():
        errors.append("Kundenadresse fehlt.")
    if total_eur is None or float(total_eur) < 0:
        errors.append("Ungültiger Gesamtbetrag.")
    if profile == "en16931":
        if not seller_tax_id or not seller_tax_id.strip():
            errors.append("Steuernummer/USt-IdNr. fehlt (Pflicht für XRechnung, Einstellungen → Steuern).")
        if not buyer_reference or not buyer_reference.strip():
            errors.append("Leitweg-ID fehlt (Pflicht für XRechnung an Behörden).")
        elif not re.match(LEITWEG_RE, buyer_reference.strip()):
            errors.append("Leitweg-ID hat ungültiges Format (z.B. 991-12345-12).")
        if not (seller_phone or seller_email):
            errors.append("Ansprechpartner fehlt (Telefon oder E-Mail in Einstellungen → Firma, Pflicht für XRechnung).")
        if not seller_email:
            errors.append("E-Mail fehlt (elektronische Adresse des Verkäufers, Einstellungen → Firma).")
        for label, addr in (("Absender", seller_address), ("Kunde", buyer_address)):
            if addr and not re.search(r"\b\d{4,5}\b", addr):
                errors.append(f"{label}adresse ohne PLZ – Format „Straße, PLZ Ort“ nutzen.")
        if not iban:
            errors.append("Keine IBAN hinterlegt – für XRechnung an Behörden Bankverbindung eintragen (nur BTC reicht nicht).")
    elif buyer_reference and not re.match(LEITWEG_RE, buyer_reference.strip()):
        errors.append("Leitweg-ID hat ungewöhnliches Format – bitte prüfen.")
    return errors
