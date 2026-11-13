# Imagen de la API. No contiene secretos: el .env se inyecta al ejecutar (docker-compose.yml, env_file).
# Imagen base fijada por digest (python:3.12-slim del 12 nov 2026, Python 3.12.16): el mismo build da la misma base.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf

WORKDIR /app

# torch solo CPU (el VPS no tiene GPU): la imagen pesa ~1 GB menos que con la versión CUDA
RUN pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# El modelo de embeddings se descarga al construir, no en cada arranque del contenedor
ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"
# Con el modelo ya en la imagen, al arrancar no se consulta Hugging Face
ENV HF_HUB_OFFLINE=1

COPY src ./src
COPY config ./config
COPY scripts ./scripts
COPY data ./data

# Usuario sin privilegios: si alguien compromete la API no es root dentro del contenedor
RUN useradd --create-home --uid 1000 app \
    && mkdir -p logs data/vectorstore \
    && chown -R app:app /app /opt/hf
USER app

# Puerto configurable (PORT en el .env o en el entorno); 8000 si no se define
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'))"

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT}"]
