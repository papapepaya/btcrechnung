import base64
import hashlib
import hmac

LEGACY_SECRET = "BTCRechnung-2026-Secret-Key"
FREE_SECRET = "BTCRechnung-Free-2026"
FREE_MONTHLY_LIMIT = 3
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


def free_key_for(email: str) -> str:
    k = hmac.new(FREE_SECRET.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:20]
    return "FREE-" + "-".join([k[i:i + 4].upper() for i in range(0, 20, 4)])


def verify_free(email: str, license_key: str) -> bool:
    if not email or not license_key:
        return False
    return hmac.compare_digest(free_key_for(email), license_key.upper().strip())


def verify_license(email: str, license_key: str, salt: str | None = None) -> bool:
    if not email or not license_key:
        return False
    lk = license_key.strip().upper()
    if lk.startswith("PRO2-"):
        return verify_ed25519(email, lk)
    if lk.startswith("FREE-"):
        return verify_free(email, lk)
    return verify_legacy(email, lk, salt)


def license_tier(email: str, license_key: str, salt: str | None = None) -> str:
    """Gibt 'pro', 'free' oder 'none' zurück."""
    if not email or not license_key:
        return "none"
    lk = license_key.strip().upper()
    if lk.startswith("FREE-"):
        return "free" if verify_free(email, lk) else "none"
    return "pro" if verify_license(email, lk, salt) else "none"


def is_pro(email: str, key: str, salt: str | None = None) -> bool:
    return verify_license(email, key, salt) and not key.strip().upper().startswith("FREE-")
