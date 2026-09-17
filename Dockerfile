# Один контейнер: собранный фронтенд + FastAPI + модели в ONNX Runtime на CPU.
# Подходит для Render (Docker), Hugging Face Spaces (порт 7860) и любого хостинга с Docker.
# Без PyTorch образ весит около 450 МБ вместо 3 ГБ, а модели поднимаются за пару секунд.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/user \
    ONNX_THREADS=2 \
    CACHE_DIR=/tmp/candid-cache \
    PORT=7860 \
    PREWARM=true
RUN useradd -m -u 1000 user
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/app backend/app
COPY scripts/download_models.py scripts/download_models.py
COPY ml/prompts ml/prompts
RUN python scripts/download_models.py

COPY backend/seed_cache backend/seed_cache
COPY ml ml
COPY --from=web /web/dist frontend/dist
RUN chown -R user:user /app
USER user

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','7860')}/api/health\", timeout=4)"
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips '*'"]
