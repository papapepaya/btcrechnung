from typing import Optional
import requests

try:
    from bip_utils import Bip84, Bip84Coins, Bip44Changes
except ImportError:
    Bip84 = None


def derive_btc_address(xpub: str, index: int) -> str:
    if not Bip84:
        raise RuntimeError("bip-utils nicht installiert (pip install bip-utils)")
    bip84_ctx = Bip84.FromExtendedKey(xpub, Bip84Coins.BITCOIN)
    addr_ctx = bip84_ctx.Change(Bip44Changes.CHAIN_EXT).AddressIndex(index)
    return addr_ctx.PublicKey().ToAddress()


def get_next_btc_address(bk) -> Optional[str]:
    settings = bk.get_settings()
    xpub = settings.get("btc_xpub")
    if not xpub:
        return None
    index = settings.get("btc_address_index", 0)
    address = derive_btc_address(xpub, index)
    settings["btc_address_index"] = index + 1
    bk.save_settings(settings)
    return address


_price_cache: dict = {"ts": 0.0, "value": 62500.0}
PRICE_TTL = 60


def get_btc_price_eur(use_cache: bool = True) -> float:
    import time
    if use_cache and time.time() - _price_cache["ts"] < PRICE_TTL:
        return _price_cache["value"]
    for url, parse in (
        ("https://api.kraken.com/0/public/Ticker?pair=XBTEUR",
         lambda d: float(d["result"]["XXBTZEUR"]["c"][0])),
        ("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=eur",
         lambda d: float(d["bitcoin"]["eur"])),
    ):
        try:
            response = requests.get(url, timeout=5)
            price = parse(response.json())
            _price_cache.update(ts=time.time(), value=price)
            return price
        except Exception as e:
            print(f"Kurs-Fehler ({url}): {e}")
    return _price_cache["value"]


def check_btc_payment(address: str) -> dict:
    try:
        url = f"https://blockstream.info/api/address/{address}/utxo"
        response = requests.get(url, timeout=10)
        utxos = response.json()
        total_sats = sum(u.get("value", 0) for u in utxos)
        total_btc = total_sats / 100_000_000
        txid = utxos[0].get("txid") if utxos else None
        return {"received": total_btc > 0, "btc_amount": total_btc, "txid": txid, "sats": total_sats}
    except Exception as e:
        for base in ("https://mempool.space/api/address/",):
            try:
                r = requests.get(base + address + "/utxo", timeout=10)
                utxos = r.json()
                total_sats = sum(u.get("value", 0) for u in utxos)
                return {"received": total_sats > 0, "btc_amount": total_sats / 100_000_000,
                        "txid": utxos[0].get("txid") if utxos else None, "sats": total_sats}
            except Exception:
                pass
        print(f"Blockstream API Fehler: {e}")
        return {"received": False, "btc_amount": 0, "txid": None, "sats": 0}
