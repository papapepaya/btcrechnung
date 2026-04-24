# Bitcoin-Wallet einrichten für BTCRechnung

Damit BTCRechnung automatisch eine **eindeutige Bitcoin-Adresse pro Rechnung** vergeben und **Zahlungseingänge erkennen** kann, benötigst du einen Extended Public Key (xpub/zpub) aus deiner Bitcoin-Wallet.

---

## Was ist ein xpub/zpub?

- **xpub/zpub** = Öfflicher Schlüssel, aus dem unendlich viele Bitcoin-Adressen abgeleitet werden können
- **zpub** = Version für Native SegWit (bc1q... Adressen) – empfohlen
- Mit dem zpub kann BTCRechnung für jede Rechnung eine eigene Adresse generieren
- Dein **Private Key** bleibt in deiner Wallet – BTCRechnung kann nur Adressen erstellen, **nicht** BTC ausgeben
- Zahlungen gehen direkt in **deine Wallet**, nicht auf einen Server

---

## Wallet empfohlen: Sparrow Wallet

[Sparrow](https://sparrowwallet.com) ist eine kostenlose Desktop-Wallet (Windows/Mac/Linux), die den Export von zpub unterstützt und sehr benutzerfreundlich ist.

### Schritt 1: Sparrow installieren

1. Lade Sparrow herunter: https://sparrowwallet.com/download/
2. Installiere und starte Sparrow

### Schritt 2: Neue Wallet erstellen

1. Klicke auf **"New Wallet"**
2. Gib einen Namen ein, z.B. `BTCRechnung`
3. Wähle **"New or Imported Software Wallet"**
4. Wähle **"Mnemonic Words"** (12 oder 24 Wörter)
5. Notiere die Wörter **sicher auf Papier** (nicht digital!)
6. Wähle **"Native Segwit (P2WPKH)"** als Script Type
7. Klicke **"Apply"**

### Schritt 3: zpub exportieren

1. Gehe zu **"Settings"** (Zahnrad-Symbol)
2. Klicke auf **"Script Policy"**
3. Dort siehst du unter **"Master Public Key"** deinen zpub
4. Kopiere den gesamten zpub-Wert (beginnt mit `zpub...`)

![Sparrow zpub Export](https://sparrowwallet.com/docs/images/settingspolicy.png)

### Schritt 4: zpub in BTCRechnung eintragen

1. Öffne die Datei `data/settings.json` im Projektordner
2. Trage deinen zpub ein:

```json
{
  "btc_xpub": "zpub6rF...",
  "btc_address_index": 0
}
```

3. Speichere die Datei
4. Starte BTCRechnung neu

---

## Alternative: Electrum Wallet

[Electrum](https://electrum.org) ist eine etablierte, kostenlose Bitcoin-Wallet.

### Schritt 1: Wallet erstellen

1. Electrum herunterladen und installieren: https://electrum.org/#download
2. **File → New/Restore** → Name eingeben
3. **Standard Wallet** → **Create a new seed**
4. **Segwit** wählen
5. Seed-Wörter **sicher aufschreiben**

### Schritt 2: xpub exportieren

1. **Wallet → Information**
2. Dort steht **"Master Public Key"** (beginnt mit `zpub` oder `ypub`)
3. Kopieren und in `data/settings.json` eintragen

---

## Alternative: BlueWallet (Mobile)

Für Smartphones (iOS/Android):

1. BlueWallet installieren: https://bluewallet.io
2. Neue Wallet erstellen → **Bitcoin** wählen
3. Seed-Wörter aufschreiben
4. Auf die Wallet tippen → **⋮ (Menü) → Export xpub**
5. QR-Code scannen oder Text kopieren

---

## Alternative: Hardware Wallet (empfohlen für größere Beträge)

Hardware-Wallets sind die sicherste Option. Alle unterstützen zpub-Export:

| Wallet | Preis | zpub Export |
|--------|-------|-------------|
| **BitBox02** | ~140 CHF | BitBoxApp → Settings → Export |
| **Coldcard** | ~150 USD | Advanced → View xpub |
| **Trezor** | ~70 USD | Trezor Suite → Account → Export |
| **Ledger** | ~80 USD | Ledger Live → Account → Extended Public Key |

---

## Was passiert nach dem Eintragen?

1. Bei jeder neuen Rechnung vergibt BTCRechnung eine **eigene BTC-Adresse**
2. Der Kunde scannt den QR-Code und wird auf die Zahlungsseite weitergeleitet
3. Dort sieht er den aktuellen BTC-Betrag und die Adresse
4. Er zahlt – das Geld geht **direkt in deine Wallet**
5. BTCRechnung erkennt den Zahlungseingang automatisch (via Blockstream API)
6. Die Rechnung wird als "Bezahlt" markiert mit exakten BTC/EUR-Werten

---

## Sicherheit

### Was BTCRechnung KANN:
- ✅ Unendlich viele Adressen aus deinem zpub ableiten
- ✅ Zahlungseingänge auf diesen Adressen erkennen
- ✅ BTC-Beträge in EUR umrechnen

### Was BTCRechnung NICHT kann:
- ❌ BTC von deinen Adressen ausgeben (dafür braucht man den Private Key)
- ❌ Auf dein Wallet zugreifen
- ❌ Deine Transaktionen stehlen

### Wichtig:
- Dein **zpub ist öffentlich** – aber jemand der ihn kennt, kann alle deine Adressen und Einnahmen einsehen
- Dein **Seed (12/24 Wörter) ist geheim** – niemals eingeben, fotografieren oder digital speichern
- Bewahre den Seed **auf Papier** an einem sicheren Ort auf
- Für größere Beträge empfehlen wir eine **Hardware-Wallet**

---

## Ohne zpub (manuelle Adresse)

Falls du keinen zpub verwenden möchtest:

1. Erstelle eine Bitcoin-Wallet (z.B. Electrum)
2. Kopiere eine Adresse aus deiner Wallet
3. Trage sie im Rechnungsformular im Feld "Bitcoin-Adresse" ein
4. **Nachteil:** Alle Rechnungen verwenden dieselbe Adresse – du musst Zuordnungen manuell machen

---

## FAQ

**F: Brauche ich einen eigenen Bitcoin-Node?**
A: Nein. BTCRechnung nutzt die öffentliche Blockstream API zur Zahlungserkennung. Dein Node ist optional (für mehr Privatsphäre).

**F: Was kostet mich das?**
A: Nichts. Der zpub-Export ist kostenlos. BTCRechnung nutzt kostenlose APIs. Nur der Kunde zahlt die Bitcoin-Transaktionsgebühr.

**F: Muss ich Bitcoin verstehen?**
A: Grundlegend: Du erstellst eine Wallet, kopierst den zpub, und BTCRechnung erledigt den Rest. Zahlungen gehen automatisch in deine Wallet.

**F: Was wenn der Kurs zwischen Rechnung und Zahlung schwankt?**
A: BTCRechnung zeigt den BTC-Betrag basierend auf dem **Live-Kurs** zum Zeitpunkt des Seitenaufrufs. Bei Zahlungseingang wird der exakte EUR-Wert zum Zahlungszeitpunkt berechnet und angezeigt.

**F: Kann ich BTCRechnung auch ohne Bitcoin nutzen?**
A: Ja. Lasse das Bitcoin-Adress-Feld einfach leer. Die Rechnung enthält dann nur die Bankverbindung (SEPA/GiroCode).
