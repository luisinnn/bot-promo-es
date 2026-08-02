FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium-headless-shell && \
    rm -rf ~/.cache/ms-playwright/ffmpeg-*

COPY promo_bot.py .
COPY categorias.json .

CMD ["python", "promo_bot.py"]