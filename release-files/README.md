# BTCRechnung

Rechnungen & EÜR für Bitcoin-affine Kleinunternehmer. Self-Hosted, Open Source, Made in Germany.

## Schnellstart

### Voraussetzungen

- **Python 3.11+** – https://www.python.org/downloads/
- Beim Installieren: **"Add Python to PATH"** anhaken

### Starten

**Windows:**
Doppelklick auf `start.bat`

**macOS / Linux:**
```bash
chmod +x start.sh
./start.sh
```

Das Skript erstellt automatisch eine virtuelle Umgebung und installiert alle Abhängigkeiten. Danach öffnet sich die App im Browser unter **http://127.0.0.1:8000**.

### Erster Start

1. Beim ersten Start wirst du aufgefordert, ein **Passwort** zu setzen
2. Danach gelangst du zum **Dashboard**
3. Gehe zu **Einstellungen** und trage deine Firmendaten ein
4. Optional: Bitcoin-Wallet einrichten (siehe `docs/wallet-setup.md`)

## Features

- **Rechnungen** erstellen mit Logo, GiroCode, ZUGFeRD 2.2 E-Rechnung
- **Bitcoin-Zahlung** mit QR-Code und Live-Kurs-Berechnung
- **Dashboard** mit Monats-/Jahresübersicht
- **Ausgaben** erfassen und kategorisieren
- **EÜR** exportieren als PDF oder CSV
- **Passwort-Schutz** für die App
- **Einstellungen** für Firma, Bank, Logo, Bitcoin-Wallet

## Bitcoin-Wallet einrichten

Für die Bitcoin-Zahlung brauchst du einen Extended Public Key (zpub). Die Anleitung findest du in:

```
docs/wallet-setup.md
```

Kurzfassung:
1. Wallet erstellen (empfohlen: [Sparrow Wallet](https://sparrowwallet.com))
2. **Native SegWit** wählen
3. zpub kopieren (Settings → Script Policy → Master Public Key)
4. In BTCRechnung unter Einstellungen eintragen

## Technische Details

- **Framework:** FastAPI (Python)
- **Datenbank:** JSON-Dateien (in `data/`)
- **Rechnungsformat:** PDF mit ZUGFeRD 2.2 (factur-x)
- **Bitcoin:** Kraken API (Kurs), Blockstream API (Zahlungserkennung)
- **QR-Code:** qrcode (Python)

## Ordnerstruktur

```
btcrechnung/
├── app/                    # Anwendung
│   ├── main.py             # Haupt-App
│   ├── bookkeeping.py      # Buchhaltung
│   ├── zugferd.py          # E-Rechnung
│   ├── models.py           # Datenmodelle
│   ├── templates/          # HTML-Templates
│   └── static/             # Statische Dateien
├── data/                   # Deine Daten (wird beim Start erstellt)
│   ├── invoices.json       # Rechnungen
│   ├── expenses.json       # Ausgaben
│   └── settings.json       # Einstellungen
├── docs/                   # Dokumentation
│   └── wallet-setup.md     # Wallet-Anleitung
├── start.sh                # Start (macOS/Linux)
├── start.bat               # Start (Windows)
└── requirements.txt        # Python-Abhängigkeiten
```

## Support

- GitHub: https://github.com/papapepaya/btcrechnung
- E-Mail: btcrechnung@proton.me

## Lizenz

EUPL 1.2 – https://opensource.org/licenses/EUPL-1.2
