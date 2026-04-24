curl -X POST http://127.0.0.1:8000/generate-pdf \
  -H "Content-Type: application/json" \
  -d '{"customer_name":"Test","customer_address":"Berlin","items":[{"description":"Test","quantity":1,"unit_price":100}]}' \
  -o /tmp/test.pdf && echo "OK: $(wc -c < /tmp/test.pdf) bytes" || echo "FEHLER"
