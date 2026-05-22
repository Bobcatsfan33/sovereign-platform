FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY libs/common /app/libs/common
COPY apps/control-plane /app/apps/control-plane
RUN pip install --no-cache-dir -e /app -e /app/libs/common
ENV PYTHONPATH=/app/libs/common
CMD ["uvicorn", "apps.control-plane.app.main:app", "--host", "0.0.0.0", "--port", "8090"]
