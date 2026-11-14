# Build: docker build -t graphite .
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    GRAPHITE_AUTH_DISABLED=true \
    BYOM_OFFLINE=true \
    GRAPHITE_DATA_DIR=/var/lib/graphite \
    GRAPHITE_DASHBOARD_DB=/var/lib/graphite/dashboard.sqlite3 \
    GRAPHITE_HISTORY_FILE=/var/lib/graphite/finding-history.json \
    GRAPHITE_PDF_ROOT=/app/regulatory_pdfs \
    COMPANIES_DIR=/app/tests/fixtures/companies

# WeasyPrint native libraries, Git for repository sources, and optional PDF OCR.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates fonts-dejavu-core fonts-liberation shared-mime-info tesseract-ocr \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 libjpeg62-turbo libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 graphite \
    && useradd --uid 10001 --gid graphite --create-home graphite \
    && mkdir -p /var/lib/graphite && chown graphite:graphite /var/lib/graphite

WORKDIR /app
COPY pyproject.toml CLAUDE.md ./
COPY src ./src
COPY assets ./assets
COPY tests ./tests
COPY synthetic_companies ./synthetic_companies
COPY sync_sources.yaml ./sync_sources.yaml
RUN mkdir -p /app/regulatory_pdfs /app/assets && pip install '.[ocr]'

USER graphite
VOLUME ["/var/lib/graphite"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()"]
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
