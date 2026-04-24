#!/usr/bin/env python3
"""Testet die PDF-Generierung via API."""
import requests

url = "http://127.0.0.1:8000/generate-pdf"
payload = {
    "customer_name": "Test Kunde",
    "customer_address": "Musterstraße 1, 12345 Berlin",
    "items": [
        {"description": "Fotoshooting", "quantity": 1, "unit_price": 250.00},
        {"description": "Bildbearbeitung", "quantity": 5, "unit_price": 50.00}
    ]
}

print("Sende Anfrage...")
resp = requests.post(url, json=payload, timeout=30)

if resp.status_code == 200:
    with open("/tmp/test_rechnung.pdf", "wb") as f:
        f.write(resp.content)
    print(f"OK: {len(resp.content)} bytes → /tmp/test_rechnung.pdf")
else:
    print(f"FEHLER {resp.status_code}: {resp.text}")
