FROM python:3.11-slim
WORKDIR /app

COPY libs/common /app/libs/common
COPY apps/audit-service/app /app/app

RUN pip install --no-cache-dir \
      "fastapi>=0.111" \
      "uvicorn[standard]>=0.30" \
      "pydantic>=2.7" \
      "httpx>=0.27" \
      "clickhouse-connect>=0.7" \
      "python-dotenv>=1.0"

ENV PYTHONPATH=/app/libs/common
ENV SERVICE_NAME=audit-service
EXPOSE 8086

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8086/healthz', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8086"]
