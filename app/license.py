import base64
import hashlib
import hmac

LEGACY_SECRET = "BTCRechnung-2026-Secret-Key"
VENDOR_ED25519_PUB_HEX = "38fe65c525f9f6f3f02a0e140a9583a7198d5918a595da2e75702613276bc99b"


def _email_hash(email: str) -> bytes:
    return hashlib.sha256(("btcrechnung:" + email.lower()).encode()).digest()


def generate_ed25519_key(priv_hex: str, email: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    sig = priv.sign(_email_hash(email))
    b32 = base64.b32encode(sig).decode().rstrip("=")
    groups = [b32[i:i + 4] for i in range(0, len(b32), 4)]
    return "PRO2-" + "-".join(groups)


def verify_ed25519(email: str, license_key: str) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        k = license_key.strip().upper().replace(" ", "")
        if not k.startswith("PRO2-"):
            return False
        k = k[5:].replace("-", "")
        pad = "=" * (-len(k) % 8)
        sig = base64.b32decode(k + pad)
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(VENDOR_ED25519_PUB_HEX))
        pub.verify(sig, _email_hash(email))
        return True
    except Exception:
        return False


def legacy_key_for(email: str, secret: str) -> str:
    k = hmac.new(secret.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:20]
    return "PRO-" + "-".join([k[i:i + 4].upper() for i in range(0, 20, 4)])


def verify_legacy(email: str, license_key: str, salt: str | None = None) -> bool:
    if not email or not license_key:
        return False
    given = license_key.upper().strip()
    if legacy_key_for(email, LEGACY_SECRET) == given:
        return True
    if salt and legacy_key_for(email, salt) == given:
        return True
    return hmac.compare_digest(legacy_key_for(email, LEGACY_SECRET), given)


def verify_license(email: str, license_key: str, salt: str | None = None) -> bool:
    if not email or not license_key:
        return False
    lk = license_key.strip().upper()
    if lk.startswith("PRO2-"):
        return verify_ed25519(email, lk)
    return verify_legacy(email, lk, salt)


def is_pro(email: str, key: str, salt: str | None = None) -> bool:
    return verify_license(email, key, salt)
