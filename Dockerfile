FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AEGIS_DASHBOARD_DB=/var/lib/aegis/dashboard.sqlite3 \
    AEGIS_HISTORY_FILE=/var/lib/aegis/finding-history.json \
    COMPANIES_DIR=/app/tests/fixtures/companies

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates fonts-dejavu-core fonts-liberation \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libffi8 libjpeg62-turbo libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 aegis \
    && useradd --uid 10001 --gid aegis --create-home aegis \
    && mkdir -p /var/lib/aegis && chown aegis:aegis /var/lib/aegis

WORKDIR /app
COPY pyproject.toml CLAUDE.md ./
COPY src ./src
COPY tests/fixtures/companies ./tests/fixtures/companies
COPY sample_connectors ./sample_connectors
COPY synthetic_companies ./synthetic_companies
COPY regulatory_pdfs ./regulatory_pdfs
RUN pip install .

USER aegis
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()"]
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
