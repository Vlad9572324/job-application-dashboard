FROM python:3.11-slim

WORKDIR /app

# tzdata нужен для ZoneInfo("Europe/Moscow") — без него _today_msk() silent-fall к UTC,
# daily reset для apply-counter сдвигается на 3h (kimi-r14-4 #8).
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY web_app.py .
COPY app/ app/
COPY static/ static/
COPY models/captcha/model.pt models/captcha/charset.txt models/captcha/

# Папка data монтируется через volume (см. docker-compose.yml)
RUN mkdir -p data

EXPOSE 8000

CMD ["python", "web_app.py"]
