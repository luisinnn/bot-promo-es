#STREAMING_CHUNK: Atualizando as dependências do Docker para async

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Em vez de requests e beautifulsoup, instalamos aiohttp para conexões assíncronas

RUN pip install --no-cache-dir beautifulsoup4 curl_cffi

COPY promo_bot.py /app/

CMD ["python", "promo_bot.py"]
