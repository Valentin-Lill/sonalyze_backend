# Lobby Service

The Lobby Service is the **state management core** of the Sonalyze backend. It handles lobby creation, participant management, role assignment (speakers/microphones), and coordinates the synchronized multi-device measurement protocol.

## Summary

The Lobby service handles:
- **Lobby Management**: Create, join, leave lobbies with unique codes
- **Participant Tracking**: Track devices and their connection status
- **Role Assignment**: Assign speaker/microphone roles with slot identifiers
- **Measurement Session Coordination**: 11-step synchronized measurement protocol
- **Real-time Broadcasts**: Push updates to all lobby participants via Gateway
- **Room Configuration Sharing**: Share room snapshots across devices

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                         GATEWAY                                  │
│                    (WebSocket Events)                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LOBBY SERVICE                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Lobby Manager   │  │ Role Manager    │  │ Measurement     │  │
│  │                 │  │                 │  │ Coordinator     │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │                    │                    │            │
│           └────────────────────┴────────────────────┘            │
│                                │                                 │
│                       ┌────────┴────────┐                        │
│                       │   PostgreSQL    │                        │
│                       │   (Async)       │                        │
│                       └─────────────────┘                        │
└──────────────────────────────────────────────────────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   Gateway   │
                    │ (Broadcast) │
                    └─────────────┘
```

## Features

### Lobby Management
- Generate unique 6-character alphanumeric lobby codes
- Track lobby state: `open`, `measurement_running`, `closed`
- Automatic participant tracking on join/leave

### Role Assignment
- Assign roles: `none`, `speaker`, `microphone`
- Support for slot IDs and labels for multi-speaker/microphone setups
- Admin-only role assignment (creator is admin)

### Measurement Session Coordination
Implements an in-memory state machine for synchronized measurements across multiple devices.

## Measurement Protocol (11 Steps)

```
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│    Admin      │     │   Speaker(s)  │     │ Microphone(s) │
└───────┬───────┘     └───────┬───────┘     └───────┬───────┘
        │                     │                     │
   1. create_session          │                     │
        │───────────────────►│◄───────────────────│
        │                     │                     │
   2. start_speaker          │                     │
        │───────────────────►│                     │
        │        start_measurement                 │
        │───────────────────►│◄────────────────────│
        │                     │                     │
   3.   │                  ready                  ready
        │◄────────────────────│─────────────────────│
        │                     │                     │
   4.   │            request_audio                 │
        │────────────────────►│                     │
        │                     │                     │
   5.   │       speaker_audio_ready                │
        │◄────────────────────│                     │
        │                     │                     │
   6.   │                     │             start_recording
        │─────────────────────│─────────────────────►│
        │                     │                     │
   7.   │                     │            recording_started
        │◄────────────────────│─────────────────────│
        │                     │                     │
   8.   │             start_playback               │
        │────────────────────►│                     │
        │                     │                     │
   9.   │          playback_complete               │
        │◄────────────────────│                     │
        │                     │                     │
  10.   │                     │             stop_recording
        │─────────────────────│─────────────────────►│
        │                     │                     │
  11.   │                     │           recording_uploaded
        │◄────────────────────│─────────────────────│
        │                     │                     │
        │        (repeat for next speaker)         │
```

## HTTP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check with database connectivity |
| `POST` | `/lobbies` | Create a new lobby |
| `POST` | `/lobbies/join` | Join an existing lobby by code |
| `POST` | `/lobbies/{lobby_id}/leave` | Leave a lobby |
| `GET` | `/lobbies/{lobby_id}` | Get lobby details and participants |
| `POST` | `/lobbies/{lobby_id}/roles` | Assign role to participant |
| `POST` | `/lobbies/{lobby_id}/start` | Start measurement session |
| `GET` | `/lobbies/{lobby_id}/events` | Get lobby events (polling fallback) |

## Gateway Events

All events are received via `POST /gateway/handle` from the Gateway service.

### Lobby Events

| Event | Description | Data |
|-------|-------------|------|
| `lobby.create` | Create a new lobby | (uses client device_id) |
| `lobby.join` | Join a lobby | `{code}` |
| `lobby.leave` | Leave a lobby | `{lobby_id}` |
| `lobby.get` | Get lobby info | `{lobby_id}` or `{code}` |
| `lobby.start` | Start measurement | `{lobby_id}` |
| `lobby.room_snapshot` | Share room config | `{lobby_id, room}` |
| `role.assign` | Assign role | `{lobby_id, target_device_id, role, role_slot_id?, role_slot_label?}` |

### Measurement Session Events

| Event | Description | Data |
|-------|-------------|------|
| `measurement.create_session` | Create session | `{job_id, lobby_id, speakers[], microphones[]}` |
| `measurement.start_speaker` | Start speaker cycle | `{session_id}` |
| `measurement.session_status` | Get session status | `{session_id}` |
| `measurement.cancel_session` | Cancel session | `{session_id, reason?}` |
| `measurement.ready` | Client ready signal | `{session_id}` |
| `measurement.speaker_audio_ready` | Speaker has audio | `{session_id, audio_hash?}` |
| `measurement.recording_started` | Mic started recording | `{session_id}` |
| `measurement.playback_complete` | Speaker finished | `{session_id}` |
| `measurement.recording_uploaded` | Mic uploaded recording | `{session_id, upload_name}` |
| `measurement.error` | Report error | `{session_id, error_message, error_code?}` |

### Outbound Broadcast Events

The Lobby service broadcasts these events to clients via Gateway:

| Event | Description |
|-------|-------------|
| `lobby.updated` | Lobby state changed (participant join/leave, role change) |
| `lobby.room_snapshot` | Room configuration shared |
| `measurement.start_measurement` | Measurement starting for speaker |
| `measurement.request_audio` | Speaker should download audio |
| `measurement.start_recording` | Microphones should start recording |
| `measurement.start_playback` | Speaker should play audio |
| `measurement.stop_recording` | Microphones should stop and upload |
| `measurement.speaker_complete` | One speaker finished |
| `measurement.session_complete` | All speakers finished |
| `measurement.session_cancelled` | Session was cancelled |
| `measurement.error` | Error occurred |

## Database Models

### Lobby
```
- id: UUID (PK)
- code: String (unique, indexed)
- creator_device_id: String
- state: Enum (open, measurement_running, closed)
- created_at: DateTime
```

### Participant
```
- id: UUID (PK)
- lobby_id: UUID (FK → Lobby)
- device_id: String
- role: Enum (none, speaker, microphone)
- role_slot_id: String (nullable)
- role_slot_label: String (nullable)
- status: Enum (joined, left)
- joined_at: DateTime
- left_at: DateTime (nullable)
```

### LobbyEvent
```
- id: Integer (PK, auto)
- lobby_id: UUID (FK → Lobby)
- type: String
- payload: JSON
- created_at: DateTime
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./lobby.db` | Database connection string |
| `GATEWAY_URL` | `http://localhost:8000` | Gateway URL for broadcasts |
| `MEASUREMENT_URL` | `http://measurement:8000` | Measurement service URL |
| `INTERNAL_AUTH_TOKEN` | `""` | Token for Gateway broadcast API |

## Internal Packages

| Module | Description |
|--------|-------------|
| `main` | FastAPI application and HTTP endpoints |
| `gateway_handler` | Gateway event handler router |
| `service` | Lobby business logic (create, join, leave, roles) |
| `measurement_coordinator` | 11-step measurement protocol state machine |
| `broadcast` | Client notification via Gateway broadcast API |
| `models` | SQLAlchemy ORM models |
| `schemas` | Pydantic request/response schemas |
| `db` | Database engine and session management |
| `settings` | Configuration from environment |

## Dependencies

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
SQLAlchemy[asyncio]==2.0.36
asyncpg==0.30.0
aiosqlite==0.20.0
pydantic-settings==2.6.1
httpx==0.27.0
```

## Running Locally

```bash
cd lobby
pip install -r requirements.txt

# With SQLite (development)
uvicorn src.main:app --reload --port 8001

# With PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/lobby \
uvicorn src.main:app --reload --port 8001
```

## Docker

```bash
docker build -t sonalyze-lobby .
docker run -p 8001:8000 \
  -e DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/lobby \
  -e GATEWAY_URL=http://gateway:8000 \
  sonalyze-lobby
```
