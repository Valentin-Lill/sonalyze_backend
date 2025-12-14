FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl ca-certificates bash \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src/ /app/src/

EXPOSE 8000

CMD ["bash", "-lc", "chmod +x /app/src/entrypoint.sh && /app/src/entrypoint.sh"]
