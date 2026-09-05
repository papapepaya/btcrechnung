FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/btcrechnung

COPY requirements.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docs ./docs
COPY Bitcoin.svg Bitcoin.png ./

RUN mkdir -p data && touch data/.gitkeep

EXPOSE 8000
VOLUME ["/srv/btcrechnung/data"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
