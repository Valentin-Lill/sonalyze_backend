# Storage Service

The Storage Service is the **persistent data layer** of the Sonalyze backend. It provides a centralized REST API for storing and retrieving all application data, including devices, lobbies, participants, measurements, analysis results, and simulation jobs.

## Summary

The Storage service handles:
- **Data Persistence**: PostgreSQL database with async SQLAlchemy ORM
- **Entity Management**: Full CRUD operations for all domain entities
- **Database Migrations**: Alembic for schema migrations
- **High Performance**: ORJSON for fast JSON serialization
- **Centralized Storage**: Single source of truth for all services

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND SERVICES                              │
│  ┌──────────┐  ┌─────────────┐  ┌────────────┐  ┌─────────────┐ │
│  │  Lobby   │  │ Measurement │  │ Simulation │  │   Gateway   │ │
│  └────┬─────┘  └──────┬──────┘  └─────┬──────┘  └──────┬──────┘ │
│       │               │               │                │        │
│       └───────────────┴───────────────┴────────────────┘        │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     STORAGE SERVICE                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    REST API (/v1/*)                        │ │
│  │                                                            │ │
│  │  /devices  /lobbies  /participants  /measurements  ...     │ │
│  └───────────────────────────┬────────────────────────────────┘ │
│                              │                                   │
│  ┌───────────────────────────┴────────────────────────────────┐ │
│  │                   SQLAlchemy ORM                           │ │
│  │                                                            │ │
│  │  Device │ Lobby │ Participant │ Measurement │ Analysis... │ │
│  └───────────────────────────┬────────────────────────────────┘ │
│                              │                                   │
│                     ┌────────┴────────┐                          │
│                     │   PostgreSQL    │                          │
│                     │   (asyncpg)     │                          │
│                     └─────────────────┘                          │
└──────────────────────────────────────────────────────────────────┘
```

## Features

### Database Features
- Async PostgreSQL with asyncpg driver
- SQLAlchemy 2.0 ORM with mapped columns
- Automatic UUID generation for primary keys
- JSON column support for flexible metadata
- Foreign key relationships with cascade deletes

### API Features
- ORJSON for fast JSON serialization
- Pagination with limit/offset
- Filtering by related entities
- Upsert operations for devices
- Soft deletes via status fields

## HTTP Endpoints

All endpoints are prefixed with `/v1`.

### Health Check

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check |

### Devices

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/devices` | Register/upsert device |
| `GET` | `/devices` | List devices (paginated) |
| `GET` | `/devices/{id}` | Get device by UUID |
| `GET` | `/devices/by-external/{external_id}` | Get by external ID |
| `PATCH` | `/devices/{id}` | Update device |
| `DELETE` | `/devices/{id}` | Delete device |

#### Device Schema
```json
{
  "external_id": "device-abc-123",
  "label": "iPhone 15 Pro",
  "platform": "ios",
  "metadata": {
    "os_version": "17.2",
    "app_version": "1.0.0"
  }
}
```

### Lobbies

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/lobbies` | Create lobby |
| `GET` | `/lobbies` | List lobbies (paginated) |
| `GET` | `/lobbies/{id}` | Get lobby by UUID |
| `GET` | `/lobbies/by-code/{code}` | Get by join code |
| `PATCH` | `/lobbies/{id}` | Update lobby |
| `DELETE` | `/lobbies/{id}` | Delete lobby |

#### Lobby Schema
```json
{
  "code": "ABC123",
  "state": "created",
  "creator_device_id": "uuid-here"
}
```

**States:** `created`, `open`, `measuring`, `closed`

### Participants

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/participants` | Add participant |
| `GET` | `/participants` | List (filter by lobby/device) |
| `GET` | `/participants/{id}` | Get participant |
| `PATCH` | `/participants/{id}` | Update role/status |
| `DELETE` | `/participants/{id}` | Remove participant |

#### Participant Schema
```json
{
  "lobby_id": "uuid-here",
  "device_id": "uuid-here",
  "role": "speaker",
  "status": "connected"
}
```

**Roles:** `observer`, `speaker`, `microphone`
**Statuses:** `connected`, `disconnected`, `left`

### Measurements

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/measurements` | Create measurement |
| `GET` | `/measurements` | List (filter by lobby/device) |
| `GET` | `/measurements/{id}` | Get measurement |
| `PATCH` | `/measurements/{id}` | Update measurement |
| `DELETE` | `/measurements/{id}` | Delete measurement |

#### Measurement Schema
```json
{
  "lobby_id": "uuid-here",
  "created_by_device_id": "uuid-here",
  "kind": "raw",
  "sample_rate_hz": 48000,
  "channels": 1,
  "raw_blob_ref": "s3://bucket/path/recording.wav",
  "raw_bytes": 1048576,
  "raw_sha256": "abc123...",
  "metadata": {
    "source_slot": "speaker_1",
    "receiver_slot": "mic_1"
  },
  "started_at": "2025-01-02T10:00:00Z",
  "stopped_at": "2025-01-02T10:00:15Z"
}
```

### Analysis Outputs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/analysis-outputs` | Store analysis result |
| `GET` | `/analysis-outputs` | List (filter by measurement) |
| `GET` | `/analysis-outputs/{id}` | Get analysis output |
| `PATCH` | `/analysis-outputs/{id}` | Update output |
| `DELETE` | `/analysis-outputs/{id}` | Delete output |

#### Analysis Output Schema
```json
{
  "measurement_id": "uuid-here",
  "type": "room_acoustics",
  "status": "completed",
  "result": {
    "rt60_s": 0.45,
    "c50_db": 2.5,
    "sti": 0.72
  }
}
```

**Types:** `room_acoustics`, `frequency_response`, `sti`, `custom`
**Statuses:** `created`, `processing`, `completed`, `failed`

### Simulation Jobs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/simulation-jobs` | Queue simulation |
| `GET` | `/simulation-jobs` | List jobs |
| `GET` | `/simulation-jobs/{id}` | Get job |
| `PATCH` | `/simulation-jobs/{id}` | Update status |
| `DELETE` | `/simulation-jobs/{id}` | Delete job |

#### Simulation Job Schema
```json
{
  "requested_by_device_id": "uuid-here",
  "lobby_id": "uuid-here",
  "status": "queued",
  "params": {
    "room": {"type": "shoebox", "dimensions_m": [5, 4, 2.5]},
    "sources": [...],
    "microphones": [...]
  }
}
```

**Statuses:** `queued`, `running`, `completed`, `failed`

### Simulation Results

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/simulation-results` | Store result |
| `GET` | `/simulation-results` | List results |
| `GET` | `/simulation-results/{id}` | Get result |
| `GET` | `/simulation-results/by-job/{job_id}` | Get by job ID |
| `PATCH` | `/simulation-results/{id}` | Update result |
| `DELETE` | `/simulation-results/{id}` | Delete result |

## Database Models

### Entity Relationship Diagram

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│   Device     │       │    Lobby     │       │ Participant  │
├──────────────┤       ├──────────────┤       ├──────────────┤
│ id (PK)      │       │ id (PK)      │◄──────│ lobby_id (FK)│
│ external_id  │◄──────│ creator_id   │       │ device_id(FK)│──────►
│ label        │       │ code         │       │ role         │
│ platform     │       │ state        │       │ status       │
│ meta (JSON)  │       │ created_at   │       │ joined_at    │
│ created_at   │       └──────────────┘       └──────────────┘
└──────────────┘              │
       │                      │
       │               ┌──────┴──────┐
       │               ▼             ▼
       │        ┌──────────────┐  ┌──────────────┐
       │        │ Measurement  │  │SimulationJob │
       │        ├──────────────┤  ├──────────────┤
       └───────►│ device_id    │  │ device_id    │◄─────┘
                │ lobby_id     │  │ lobby_id     │
                │ kind         │  │ status       │
                │ sample_rate  │  │ params (JSON)│
                │ raw_blob_ref │  │ error        │
                │ meta (JSON)  │  └──────────────┘
                └──────────────┘         │
                       │                 │
                       ▼                 ▼
               ┌──────────────┐  ┌──────────────┐
               │AnalysisOutput│  │SimulationRes │
               ├──────────────┤  ├──────────────┤
               │ measurement  │  │ job_id (FK)  │
               │ type         │  │ result (JSON)│
               │ status       │  │ created_at   │
               │ result (JSON)│  └──────────────┘
               └──────────────┘
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (required) | PostgreSQL connection string |
| `LOG_LEVEL` | `INFO` | Logging level |
| `RUN_MIGRATIONS` | `false` | Run Alembic migrations on startup |

### Database URL Format
```
postgresql+asyncpg://user:password@host:port/database
```

## Database Migrations

```bash
# Generate new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## Internal Packages

| Module | Description |
|--------|-------------|
| `app.main` | FastAPI application with router registration |
| `app.db` | Database engine and session management |
| `app.models` | SQLAlchemy ORM model definitions |
| `app.schemas` | Pydantic request/response schemas |
| `app.settings` | Configuration from environment |
| `app.http_errors` | HTTP error helpers |
| `app.utils` | Utility functions (lobby code generation) |

### Routers

| Module | Description |
|--------|-------------|
| `app.routers.devices` | Device CRUD endpoints |
| `app.routers.lobbies` | Lobby CRUD endpoints |
| `app.routers.participants` | Participant CRUD endpoints |
| `app.routers.measurements` | Measurement CRUD endpoints |
| `app.routers.analysis_outputs` | Analysis output CRUD endpoints |
| `app.routers.simulation_jobs` | Simulation job CRUD endpoints |
| `app.routers.simulation_results` | Simulation result CRUD endpoints |

## Dependencies

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.10.3
pydantic-settings==2.6.1
SQLAlchemy==2.0.36
asyncpg==0.30.0
psycopg2-binary==2.9.10
alembic==1.14.0
orjson==3.10.12
python-json-logger==2.0.7
```

## Running Locally

```bash
cd storage
pip install -r requirements.txt

# Set up PostgreSQL
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/sonalyze"

# Run migrations
cd src && alembic upgrade head

# Start the server
uvicorn app.main:app --reload --port 8004
```

## Docker

```bash
docker build -t sonalyze-storage .
docker run -p 8004:8000 \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/sonalyze \
  sonalyze-storage
```

## Usage Examples

### Register a Device
```bash
curl -X POST http://localhost:8004/v1/devices \
  -H "Content-Type: application/json" \
  -d '{
    "external_id": "device-123",
    "label": "My iPhone",
    "platform": "ios",
    "metadata": {"os_version": "17.2"}
  }'
```

### Create a Lobby
```bash
curl -X POST http://localhost:8004/v1/lobbies \
  -H "Content-Type: application/json" \
  -d '{
    "creator_device_id": "uuid-from-above",
    "state": "open"
  }'
```

### Store Analysis Results
```bash
curl -X POST http://localhost:8004/v1/analysis-outputs \
  -H "Content-Type: application/json" \
  -d '{
    "measurement_id": "measurement-uuid",
    "type": "room_acoustics",
    "status": "completed",
    "result": {
      "rt60_s": 0.45,
      "c50_db": 2.5,
      "sti": 0.72
    }
  }'
```
