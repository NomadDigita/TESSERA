FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TESSERA_HOST=0.0.0.0 \
    TESSERA_PORT=8787 \
    TESSERA_DATABASE_PATH=/var/lib/tessera/tessera.db

WORKDIR /app
RUN groupadd --system tessera && useradd --system --gid tessera --home /app tessera \
    && mkdir -p /var/lib/tessera && chown tessera:tessera /var/lib/tessera

COPY pyproject.toml README.md ./
COPY tessera ./tessera
RUN pip install --no-cache-dir .

USER tessera
EXPOSE 8787
VOLUME ["/var/lib/tessera"]
HEALTHCHECK --interval=20s --timeout=4s --start-period=8s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/ready', timeout=3)"

ENTRYPOINT ["python", "-m", "tessera"]
