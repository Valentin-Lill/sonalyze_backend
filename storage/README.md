# storage/ (DB access layer)

Central Postgres-backed persistence service for Sonalyze.

## What it provides
- Owns the Postgres schema + migrations (Alembic)
- HTTP CRUD APIs that other microservices can call

## Run locally (Docker)

From repo root:

```bash
docker build -t sonalyze-storage ./storage
docker run --rm -p 8000:8000 \
  -e DATABASE_URL='postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/sonalyze' \
  sonalyze-storage
```

You can also point it at a compose Postgres container.

## Environment
- `DATABASE_URL` (required)
  - Example: `postgresql+asyncpg://postgres:postgres@postgres:5432/sonalyze`
- `RUN_MIGRATIONS` (optional, default `true`)
- `LOG_LEVEL` (optional, default `INFO`)

## API
- OpenAPI: `GET /docs`
- Health: `GET /healthz`

All endpoints are prefixed with `/v1`.
