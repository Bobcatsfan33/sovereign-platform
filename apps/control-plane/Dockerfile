FROM python:3.11-slim
WORKDIR /app

COPY libs/common /app/libs/common
COPY apps/control-plane/app /app/app

RUN pip install --no-cache-dir \
      "fastapi>=0.111" \
      "uvicorn[standard]>=0.30" \
      "pydantic>=2.7" \
      "boto3>=1.34" \
      "httpx>=0.27" \
      "PyYAML>=6.0" \
      "python-dotenv>=1.0"

ENV PYTHONPATH=/app/libs/common
ENV SERVICE_NAME=control-plane
EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8090/healthz', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
