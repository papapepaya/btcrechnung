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

    vat_cat = "S"  # Standard rated (0% = kein USt-Ausweis für Kleinunternehmer)

    # --- ExchangedDocumentContext ---
    ctx = SubElement(root, f"{{{ns['rsm']}}}ExchangedDocumentContext")
    guideline = SubElement(ctx, f"{{{ns['ram']}}}GuidelineSpecifiedDocumentContextParameter")
    SubElement(guideline, f"{{{ns['ram']}}}ID").text = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic"

    # --- ExchangedDocument ---
    doc = SubElement(root, f"{{{ns['rsm']}}}ExchangedDocument")
    SubElement(doc, f"{{{ns['ram']}}}ID").text = invoice_number
    SubElement(doc, f"{{{ns['ram']}}}TypeCode").text = "380"

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
        SubElement(price, f"{{{ns['ram']}}}ChargeAmount").text = f"{Decimal(str(item['unit_price'])):.4f}"

        line_del = SubElement(line, f"{{{ns['ram']}}}SpecifiedLineTradeDelivery")
        qty = SubElement(line_del, f"{{{ns['ram']}}}BilledQuantity")
        qty.set("unitCode", "C62")
        qty.text = f"{Decimal(str(item['quantity'])):.2f}"

        line_settle = SubElement(line, f"{{{ns['ram']}}}SpecifiedLineTradeSettlement")
        line_tax = SubElement(line_settle, f"{{{ns['ram']}}}ApplicableTradeTax")
        SubElement(line_tax, f"{{{ns['ram']}}}TypeCode").text = "VAT"
        SubElement(line_tax, f"{{{ns['ram']}}}CategoryCode").text = vat_cat
        SubElement(line_tax, f"{{{ns['ram']}}}RateApplicablePercent").text = "0.00"

        line_sum = SubElement(line_settle, f"{{{ns['ram']}}}SpecifiedTradeSettlementLineMonetarySummation")
        SubElement(line_sum, f"{{{ns['ram']}}}LineTotalAmount").text = f"{Decimal(str(item['line_total'])):.2f}"

    # -- TradeAgreement --
    agr = SubElement(tx, f"{{{ns['ram']}}}ApplicableHeaderTradeAgreement")

    seller = SubElement(agr, f"{{{ns['ram']}}}SellerTradeParty")
    SubElement(seller, f"{{{ns['ram']}}}Name").text = seller_name
    _add_address(seller, seller_address, ns)
    # Seller Tax ID – immer angeben (BR-CO-26)
    if seller_tax_id:
        tax = SubElement(seller, f"{{{ns['ram']}}}SpecifiedTaxRegistration")
        tid = SubElement(tax, f"{{{ns['ram']}}}ID")
        tid.set("schemeID", "VA")
        tid.text = seller_tax_id

    buyer = SubElement(agr, f"{{{ns['ram']}}}BuyerTradeParty")
    SubElement(buyer, f"{{{ns['ram']}}}Name").text = buyer_name
    _add_address(buyer, buyer_address, ns)
    if buyer_tax_id:
        tax = SubElement(buyer, f"{{{ns['ram']}}}SpecifiedTaxRegistration")
        tid = SubElement(tax, f"{{{ns['ram']}}}ID")
        tid.set("schemeID", "VA")
        tid.text = buyer_tax_id

    # -- TradeDelivery --
    delivery = SubElement(tx, f"{{{ns['ram']}}}ApplicableHeaderTradeDelivery")
    ship = SubElement(delivery, f"{{{ns['ram']}}}ShipToTradeParty")
    ship_addr = SubElement(ship, f"{{{ns['ram']}}}PostalTradeAddress")
    SubElement(ship_addr, f"{{{ns['ram']}}}CountryID").text = "DE"
    actual_delivery = SubElement(delivery, f"{{{ns['ram']}}}ActualDeliverySupplyChainEvent")
    occ = SubElement(actual_delivery, f"{{{ns['ram']}}}OccurrenceDateTime")
    occ_dt = SubElement(occ, f"{{{ns['udt']}}}DateTimeString")
    occ_dt.set("format", "102")
    occ_dt.text = issue_date.strftime("%Y%m%d")

    # -- TradeSettlement --
    settlement = SubElement(tx, f"{{{ns['ram']}}}ApplicableHeaderTradeSettlement")
    SubElement(settlement, f"{{{ns['ram']}}}InvoiceCurrencyCode").text = currency

    # Payment means
    pm = SubElement(settlement, f"{{{ns['ram']}}}SpecifiedTradeSettlementPaymentMeans")
    SubElement(pm, f"{{{ns['ram']}}}TypeCode").text = "30"
    if iban:
        payee = SubElement(pm, f"{{{ns['ram']}}}PayeePartyCreditorFinancialAccount")
        SubElement(payee, f"{{{ns['ram']}}}IBANID").text = iban.replace(" ", "")

    # Trade tax
    tax_subtotal = SubElement(settlement, f"{{{ns['ram']}}}ApplicableTradeTax")
    SubElement(tax_subtotal, f"{{{ns['ram']}}}CalculatedAmount").text = f"{Decimal('0.00'):.2f}"
    SubElement(tax_subtotal, f"{{{ns['ram']}}}TypeCode").text = "VAT"
    SubElement(tax_subtotal, f"{{{ns['ram']}}}BasisAmount").text = f"{Decimal(str(total_eur)):.2f}"
    SubElement(tax_subtotal, f"{{{ns['ram']}}}CategoryCode").text = vat_cat
    SubElement(tax_subtotal, f"{{{ns['ram']}}}RateApplicablePercent").text = "0.00"
    # Monetary summation
    summation = SubElement(settlement, f"{{{ns['ram']}}}SpecifiedTradeSettlementHeaderMonetarySummation")
    SubElement(summation, f"{{{ns['ram']}}}LineTotalAmount").text = f"{Decimal(str(total_eur)):.2f}"
    SubElement(summation, f"{{{ns['ram']}}}ChargeTotalAmount").text = "0.00"
    SubElement(summation, f"{{{ns['ram']}}}AllowanceTotalAmount").text = "0.00"
    SubElement(summation, f"{{{ns['ram']}}}TaxBasisTotalAmount").text = f"{Decimal(str(total_eur)):.2f}"
    SubElement(summation, f"{{{ns['ram']}}}TaxTotalAmount").text = f"{Decimal('0.00'):.2f}"
    SubElement(summation, f"{{{ns['ram']}}}GrandTotalAmount").text = f"{Decimal(str(total_eur)):.2f}"
    SubElement(summation, f"{{{ns['ram']}}}DuePayableAmount").text = f"{Decimal(str(total_eur)):.2f}"

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
