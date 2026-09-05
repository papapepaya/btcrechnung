"""Bank-Import: CSV (Standard) + CAMT.053 XML. Nur Lesen, 0 EUR Kosten."""
import csv
import io
import re


def _parse_amount_de(raw: str) -> float:
    s = (raw or "").strip().replace("\u00a0", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def _parse_date(raw: str) -> str:
    s = (raw or "").strip()[:10]
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return s


def parse_csv(contents: bytes) -> list:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = contents.decode(enc)
            break
        except Exception:
            continue
    else:
        text = contents.decode("utf-8", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
        delim = dialect.delimiter
    except Exception:
        delim = ";" if ";" in sample else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        raise ValueError("CSV ohne Kopfzeile.")
    cols = {c.lower().strip(): c for c in reader.fieldnames}
    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None
    c_date = col("buchungstag", "valuta", "datum", "buchungsdatum", "date")
    c_purpose = col("verwendungszweck", "buchungstext", "beschreibung", "zweck", "purpose", "description", "auftraggeber")
    c_amount = col("betrag", "amount", "wert", "umsatz")
    c_iban = col("iban", "kontonummer", "auftraggeberkonto")
    if not c_date or not c_amount:
        raise ValueError("Spalten Datum/Betrag nicht gefunden.")
    rows = []
    for line in reader:
        try:
            amt = _parse_amount_de(line.get(c_amount, "0"))
        except ValueError:
            continue
        rows.append({
            "date": _parse_date(line.get(c_date, "")),
            "purpose": (line.get(c_purpose, "") or "").strip()[:500],
            "amount": round(amt, 2),
            "counter_iban": (line.get(c_iban, "") or "").strip() if c_iban else "",
            "source": "csv",
        })
    return rows


def parse_camt053(contents: bytes) -> list:
    from lxml import etree
    root = etree.fromstring(contents)
    ns = {"c": root.nsmap.get(None, "")} if None in root.nsmap else {}
    def xp(el, path):
        if ns.get("c"):
            return el.xpath(path, namespaces={"d": ns["c"]})
        return el.xpath(path.replace("d:", ""))
    rows = []
    for ntry in xp(root, "//d:Ntry"):
        def txt(path):
            els = xp(ntry, path)
            return els[0].text.strip() if els and els[0].text else ""
        amt_raw = txt("d:Amt")
        try:
            amt = float(amt_raw.replace(",", "."))
        except ValueError:
            continue
        cdt = txt("d:CdtDbtInd")
        if cdt == "DBIT":
            amt = -abs(amt)
        else:
            amt = abs(amt)
        purpose = " ".join([
            txt("d:RmtInf/d:Ustrd"),
            txt("d:NtryDtls/d:TxDtls/d:RmtInf/d:Ustrd"),
            txt("d:AddtlNtryInf"),
        ]).strip()[:500]
        rows.append({
            "date": txt("d:BookgDt/d:Dt")[:10] or txt("d:ValDt/d:Dt")[:10],
            "purpose": purpose,
            "amount": round(amt, 2),
            "counter_iban": txt("d:NtryDtls/d:TxDtls/d:RltdPties/d:DbtrAcct/d:Id/d:IBAN"),
            "source": "camt053",
        })
    return rows
