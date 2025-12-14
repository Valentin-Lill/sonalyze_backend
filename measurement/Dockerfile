FROM python:3.12-slim

WORKDIR /app

# Runtime deps for soundfile and health checks
RUN apt-get update \
  && apt-get install -y --no-install-recommends libsndfile1 curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src

ENV PYTHONPATH=/app/src \
    MEASUREMENT_DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

CMD ["python", "-m", "app.main"]
