import base64
import io
import os
import qrcode


def get_image_base64(path, max_height=None):
    if path and os.path.exists(path):
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
