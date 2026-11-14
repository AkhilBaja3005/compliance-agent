# Aegis API image. Build: docker build -t aegis . ; run: docker run -p 8000:8000 --env-file .env -e AEGIS_API_KEYS=... aegis
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# WeasyPrint needs pango/cairo; tesseract is optional for OCR of scanned PDFs; git is needed to shallow-clone repos
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 shared-mime-info fonts-dejavu-core git tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 aegis
WORKDIR /app
COPY pyproject.toml CLAUDE.md ./
COPY src ./src
COPY regulatory_pdfs ./regulatory_pdfs
RUN pip install -e . pytesseract
USER aegis
ENV AEGIS_DATA_DIR=/data AEGIS_PDF_ROOT=/app/regulatory_pdfs
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status==200 else 1)"
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
