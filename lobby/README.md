# lobby service

Creates and manages measurement lobbies (sessions, participants, roles, workflow state).

## Run (Docker)

From this folder:

- `docker compose up --build`
- API: http://localhost:8001
- Docs: http://localhost:8001/docs

## Environment

- `DATABASE_URL` (required in production)

Examples:
- `postgresql+asyncpg://postgres:postgres@postgres:5432/sonalyze`
- `sqlite+aiosqlite:///./lobby.db` (dev)
