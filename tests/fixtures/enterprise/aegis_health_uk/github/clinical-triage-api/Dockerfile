FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV GRAPHITE_NHS_VPC_ENDPOINT="https://eu-west-2.clinical-ai.nhs.uk/v1"
ENV DATA_RESIDENCY_REGION="eu-west-2"
EXPOSE 8000
CMD ["uvicorn", "src.routes.triage_router:router", "--host", "0.0.0.0", "--port", "8000"]
