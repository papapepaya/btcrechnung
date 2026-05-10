# BTCRechnung

[![License: EUPL-1.2](https://img.shields.io/badge/License-EUPL--1.2-blue.svg)](https://joinup.ec.europa.eu/collection/eupl/eupl-text-eupl-12)

**Rechnungen & Buchhaltung für Kleinunternehmer mit Bitcoin-Zahlungsoption.**

## Features

- **Rechnungen als PDF** mit ZUGFeRD 2.2 E-Rechnung
- **Bitcoin + Lightning** Zahlung (optional, Live-Kurs via Kraken API)
- **EÜR-Export** als PDF oder CSV
- **Buchhaltung**: Ausgaben erfassen, Einnahmen verwalten, Dashboard
- **Dark Mode**
- **Passwort-Schutz** (Login-System)
- **Self-Hosted**: Läuft lokal oder auf dem eigenen Server
- **Portable Build**: Einzelne .exe für Windows (kein Python nötig)

## Schnellstart

### Ausführbare Version (Windows)

1. Download der neuesten Version von [btcrechnung.de](https://btcrechnung.de)
2. ZIP entpacken
3. `BTCRechnung.exe` doppelklicken
4. Browser öffnet sich automatisch unter `http://127.0.0.1:8000`
5. Passwort setzen → fertig

### Aus dem Quellcode (Linux / macOS)

Python 3.11+ wird benötigt (3.14+ ist nicht kompatibel).

```bash
git clone https://github.com/papapepaya/btcrechnung.git
cd btcrechnung
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x start.sh
./start.sh
```

Browser: http://127.0.0.1:8000

## Ersteinrichtung

1. Passwort setzen (beim ersten Start)
2. **Einstellungen** → Firmenname, Adresse, Logo, Bankverbindung
3. **Bitcoin (optional):** zpub aus deiner Wallet eintragen → [Anleitung](docs/wallet-setup.md)

## Versionen

| Feature | Basic (29 €) | Pro (69 €) |
|---------|-------------|-----------|
| Rechnungen mit ZUGFeRD | ✅ (0% MwSt) | ✅ (mit MwSt) |
| Bitcoin-Zahlung | ✅ | ✅ |
| EÜR Export | ✅ | ✅ |
| MwSt auf Rechnungen | ❌ | ✅ |
| Vorsteuer bei Ausgaben | ❌ | ✅ |
| UStVA | ❌ | ✅ |
| Audit-Log mit Prüfsummen | ❌ | ✅ |

## Bitcoin-Wallet einrichten

Für Bitcoin-Zahlungen brauchst du einen Extended Public Key (zpub):

1. Wallet erstellen ([Sparrow Wallet](https://sparrowwallet.com) empfohlen)
2. **Native SegWit** wählen
3. zpub kopieren (Settings → Script Policy → Master Public Key)
4. In BTCRechnung unter Einstellungen eintragen

Siehe [docs/wallet-setup.md](docs/wallet-setup.md) für Details.

## Tech-Stack

| Komponente | Technologie |
|-----------|-------------|
| Framework | FastAPI + Jinja2 |
| PDF | xhtml2pdf |
| ZUGFeRD | factur-x v1.10 |
| QR-Codes | qrcode + Pillow |
| Bitcoin | bip-utils, Kraken API, Blockstream API |
| Daten | JSON-Dateien (lokal) |
| Build | PyInstaller (Windows) |

## Lizenz

**European Union Public Licence (EUPL) 1.2** – siehe [LICENSE](LICENSE).

---

## Haftungsausschluss

Dieses Tool ist ein **Software-Produkt, keine Steuerberatung**. Wir übernehmen keine Verantwortung für die steuerrechtliche Konformität deiner Buchhaltung, Rechnungen oder EÜR. Für steuerliche Fragen empfehlen wir die Prüfung durch einen Steuerberater. Die Software wird ohne Gewährleistung bereitgestellt.
