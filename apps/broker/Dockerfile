FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY libs/common /app/libs/common
COPY apps/broker /app/apps/broker
RUN pip install --no-cache-dir -e /app -e /app/libs/common
ENV PYTHONPATH=/app/libs/common
CMD ["uvicorn", "apps.broker.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
