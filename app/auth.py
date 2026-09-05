import hashlib
import hmac
import secrets
import time

MIN_PASSWORD_LEN = 8
MAX_FAILS = 5
BLOCK_SECONDS = 60

_fails: dict[str, dict] = {}
_sessions_cache: set[str] = set()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${h.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, hash_hex = stored.split("$", 1)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return hmac.compare_digest(h.hex(), hash_hex)


def _client_ip(request) -> str:
    try:
        if request.client:
            return request.client.host
    except Exception:
        pass
    return "unknown"


def is_blocked(request) -> bool:
    ip = _client_ip(request)
    e = _fails.get(ip)
    if not e:
        return False
    if e.get("blocked_until", 0) > time.time():
        return True
    if e.get("blocked_until", 0) and e["blocked_until"] <= time.time():
        _fails.pop(ip, None)
        return False
    return False


def record_fail(request):
    ip = _client_ip(request)
    e = _fails.get(ip, {"count": 0, "blocked_until": 0})
    e["count"] += 1
    if e["count"] >= MAX_FAILS:
        e["blocked_until"] = time.time() + BLOCK_SECONDS
    _fails[ip] = e


def record_success(request):
    _fails.pop(_client_ip(request), None)


def _get_store(bk) -> list:
    s = bk.get_settings()
    sess = s.get("sessions")
    if not isinstance(sess, list):
        sess = []
        s["sessions"] = sess
        bk.save_settings(s)
    return sess


def create_session(bk) -> str:
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    sess = _get_store(bk)
    sess.append({"digest": digest, "created": time.time()})
    bk.save_settings(bk.get_settings() | {"sessions": sess})
    _sessions_cache.add(digest)
    return token


def destroy_session(bk, token: str):
    if not token:
        return
    digest = hashlib.sha256(token.encode()).hexdigest()
    _sessions_cache.discard(digest)
    try:
        s = bk.get_settings()
        sess = [x for x in s.get("sessions", []) if x.get("digest") != digest]
        s["sessions"] = sess[-50:]
        bk.save_settings(s)
    except Exception:
        pass


def is_valid_session(bk, token: str) -> bool:
    if not token:
        return False
    if len(token) == 64 and all(c in "0123456789abcdef" for c in token.lower()):
        pass
    elif len(token) == 64:
        pass
    else:
        return _is_legacy_token(bk, token)
    digest = hashlib.sha256(token.encode()).hexdigest()
    if digest in _sessions_cache:
        return True
    try:
        for x in bk.get_settings().get("sessions", []):
            if x.get("digest") == digest:
                _sessions_cache.add(digest)
                return True
    except Exception:
        pass
    return _is_legacy_token(bk, token)


def _is_legacy_token(bk, token: str) -> bool:
    try:
        secret = bk.get_settings().get("session_secret")
        if not secret:
            return False
        expected = hmac.new(secret.encode(), b"authenticated", hashlib.sha256).hexdigest()
        return hmac.compare_digest(token, expected)
    except Exception:
        return False


def get_or_create_csrf_secret(bk) -> str:
    s = bk.get_settings()
    sec = s.get("csrf_secret")
    if not sec:
        sec = secrets.token_hex(32)
        s["csrf_secret"] = sec
        bk.save_settings(s)
    return sec


def csrf_token_for_session(bk, session_token: str) -> str:
    sec = get_or_create_csrf_secret(bk)
    return hmac.new(sec.encode(), session_token.encode(), hashlib.sha256).hexdigest()[:32]


def check_csrf(bk, session_token: str, provided: str | None) -> bool:
    if not session_token or not provided:
        return False
    expected = csrf_token_for_session(bk, session_token)
    return hmac.compare_digest(expected, provided)
