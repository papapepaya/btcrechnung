#!/bin/bash
cd "$(dirname "$0")"

# Virtuelle Umgebung erstellen falls nicht vorhanden
if [ ! -d ".venv" ]; then
    echo "Erstelle virtuelle Umgebung..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "FEHLER: Virtuelle Umgebung konnte nicht erstellt werden."
        echo "Bitte Python 3.11+ installieren: https://www.python.org/downloads/"
        read -p "Enter zum Beenden..."
        exit 1
    fi
fi

source .venv/bin/activate

# Abhängigkeiten installieren falls nötig
if ! python -c "import uvicorn" 2>/dev/null; then
    echo "Installiere Abhängigkeiten (kann 1-2 Minuten dauern)..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    if [ $? -ne 0 ]; then
        echo "FEHLER: Abhängigkeiten konnten nicht installiert werden."
        read -p "Enter zum Beenden..."
        exit 1
    fi
fi

LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

echo ""
echo "=== BTCRechnung ==="
echo "Lokal:    http://127.0.0.1:8000"
echo "Netzwerk: http://${LOCAL_IP}:8000"
echo ""
echo "Strg+C zum Beenden"
echo ""

# Browser öffnen
if command -v xdg-open &>/dev/null; then
    sleep 2 && xdg-open "http://127.0.0.1:8000" 2>/dev/null &
elif command -v open &>/dev/null; then
    sleep 2 && open "http://127.0.0.1:8000" 2>/dev/null &
fi

# Server starten
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

read -p "Enter zum Beenden..."
