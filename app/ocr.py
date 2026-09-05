"""Beleg-OCR: Tesseract wenn vorhanden, sonst None (graceful)."""
import re
import shutil


def is_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa
        return True
    except ImportError:
        return False


def extract_text(image_bytes: bytes) -> str | None:
    if not is_available():
        return None
    try:
        import io
        from PIL import Image
        import pytesseract
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "L":
            img = img.convert("L")
        w, h = img.size
        if max(w, h) < 1500:
            scale = 1500 / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)))
        return pytesseract.image_to_string(img, lang="deu+eng") or ""
    except Exception as e:
        print(f"OCR-Fehler: {e}")
        return None


def _parse_amount_de(raw: str) -> float | None:
    s = raw.strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_receipt(text: str) -> dict:
    """Extrahiert Betrag (groesster EUR-Betrag), Datum, Haendler aus OCR-Text."""
    out = {"amount": None, "date": None, "vendor": None, "text": text}
    if not text:
        return out
    amounts = []
    for m in re.finditer(r"(\d{1,4}(?:[.,]\d{3})*[.,]\d{2})\s*(?:€|EUR|Euro)?", text):
        v = _parse_amount_de(m.group(1))
        if v is not None and 0 < v < 100000:
            amounts.append(v)
    total_hit = re.search(r"(?:summe|gesamt|total|betrag|zu zahlen)[^\d]{0,20}(\d{1,4}(?:[.,]\d{3})*[.,]\d{2})",
                          text, re.IGNORECASE)
    if total_hit:
        v = _parse_amount_de(total_hit.group(1))
        out["amount"] = v
    elif amounts:
        out["amount"] = max(amounts)
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if m:
        out["date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    else:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
        if m:
            out["date"] = m.group(0)[:10]
    for line in text.splitlines():
        s = line.strip()
        if len(s) >= 3 and not re.match(r"^[\d\s.,€\-/]+$", s):
            out["vendor"] = s[:80]
            break
    return out


def scan(image_bytes: bytes) -> dict:
    text = extract_text(image_bytes)
    if text is None:
        return {"available": False}
    res = parse_receipt(text)
    res["available"] = True
    return res
