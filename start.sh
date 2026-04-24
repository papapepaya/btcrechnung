#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate

LOCAL_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "=== BTCRechnung ==="
echo "Lokal:    http://127.0.0.1:8000"
echo "Netzwerk: http://$LOCAL_IP:8000"
echo ""
echo "Strg+C zum Beenden"
echo ""

# Server im Hintergrund starten
uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1 &
SERVER_PID=$!

# Warten bis Server bereit ist
sleep 3

# Pruefen ob Server noch laeuft
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo ""
    echo "FEHLER: Server konnte nicht gestartet werden!"
    echo "Moglicherweise ist Port 8000 belegt."
    echo ""
    echo "Druecke Enter zum Beenden..."
    read
    exit 1
fi

# Browser oeffnen
if command -v xdg-open &>/dev/null; then
    xdg-open "http://127.0.0.1:8000" 2>/dev/null &
elif command -v open &>/dev/null; then
    open "http://127.0.0.1:8000" 2>/dev/null &
fi

# Server in den Vordergrund holen (Terminal bleibt offen)
wait $SERVER_PID
