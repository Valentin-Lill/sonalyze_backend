# Gateway Service

The Gateway is the **single entry point** for all client connections to the Sonalyze backend. It provides WebSocket-based real-time communication and HTTP proxy capabilities, acting as a reverse proxy and message router for all downstream microservices.

## Summary

The Gateway service handles:
- **WebSocket connections** for real-time bidirectional communication
- **HTTP proxying** for REST API requests to internal services
- **Event routing** to appropriate backend services (lobby, measurement, simulation)
- **Rate limiting** to protect against abuse
- **Device identification** and connection management
- **Internal broadcast API** for pushing events to connected clients

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENTS                                  │
│              (Mobile Apps, Web Browsers)                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GATEWAY SERVICE                               │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────────┐   │
│  │  WebSocket  │  │ HTTP Proxy  │  │ Internal Broadcast API │   │
│  │  /ws        │  │ /v1/*       │  │ /internal/broadcast    │   │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬────────────┘   │
│         │                │                      │                │
│         └────────────────┴──────────────────────┘                │
│                          │                                       │
│                    Event Router                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   ┌──────────┐     ┌─────────────┐   ┌────────────┐
   │  Lobby   │     │ Measurement │   │ Simulation │
   └──────────┘     └─────────────┘   └────────────┘
```

## Features

### WebSocket Communication
- Real-time bidirectional messaging
- Device identification via `?device_id=` query param or `identify` event
- JSON message protocol with request/response correlation
- Automatic connection tracking by device ID

### Event Routing
Routes events to appropriate backend services:
- `lobby.*` and `role.*` → Lobby Service
- `measurement.*` session events → Lobby Service (stateful coordination)
- `measurement.*` job events → Measurement Service (stateless computation)
- `analysis.*` → Measurement Service
- `simulation.*` → Simulation Service

### HTTP Proxy
Proxies REST API requests to internal services:
- `/v1/measurement/*` → Measurement Service
- `/v1/jobs/*` → Measurement Service
- `/v1/simulation/*` → Simulation Service

### Rate Limiting
Token bucket algorithm with configurable:
- Requests per second (RPS)
- Burst capacity

## Event Routing Details

### Lobby Service Events
*Target: `http://lobby:8000/gateway/handle`*

| Event | Description |
|-------|-------------|
| `lobby.create` | Create a new lobby |
| `lobby.join` | Join an existing lobby |
| `lobby.leave` | Leave a lobby |
| `lobby.get` | Get lobby information |
| `lobby.start` | Start measurement |
| `lobby.room_snapshot` | Share room configuration |
| `role.assign` | Assign speaker/microphone roles |

**Measurement Session Events (Stateful):**
| Event | Description |
|-------|-------------|
| `measurement.create_session` | Create measurement session |
| `measurement.start_speaker` | Start measurement for current speaker |
| `measurement.session_status` | Get session status |
| `measurement.cancel_session` | Cancel ongoing session |
| `measurement.ready` | Client ready signal |
| `measurement.speaker_audio_ready` | Speaker has downloaded audio |
| `measurement.recording_started` | Microphone started recording |
| `measurement.playback_complete` | Speaker finished playback |
| `measurement.recording_uploaded` | Microphone uploaded recording |
| `measurement.error` | Report measurement error |

### Measurement Service Events
*Target: `http://measurement:8000/gateway/handle`*

| Event | Description |
|-------|-------------|
| `measurement.create_job` | Create a new measurement job |
| `measurement.get_job` | Get job data and results |
| `measurement.get_audio_info` | Get measurement audio timing info |
| `analysis.run` | Run acoustic analysis on recordings |

### Simulation Service Events
*Target: `http://simulation:8000/gateway/handle`*

| Event | Description |
|-------|-------------|
| `simulation.run` | Run room acoustics simulation |
| `simulation.health` | Check simulation service health |

## Endpoints

### HTTP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check endpoint |
| `*` | `/v1/measurement/{path}` | Proxy to measurement service |
| `*` | `/v1/jobs/{path}` | Proxy to measurement service (file uploads) |
| `*` | `/v1/simulation/{path}` | Proxy to simulation service |
| `POST` | `/internal/broadcast` | Internal API to broadcast events to clients |

### WebSocket Endpoint

| Path | Description |
|------|-------------|
| `WS /ws?device_id={id}` | WebSocket connection with optional device ID |

## WebSocket Protocol

### Client → Server Messages

```json
{
  "event": "lobby.create",
  "request_id": "uuid-123",
  "data": {}
}
```

### Server → Client Messages

**Response:**
```json
{
  "type": "response",
  "event": "lobby.create",
  "request_id": "uuid-123",
  "data": { "lobby_id": "...", "code": "ABC123" }
}
```

**Event (push):**
```json
{
  "type": "event",
  "event": "lobby.updated",
  "data": { "type": "participant_joined", "device_id": "..." }
}
```

**Error:**
```json
{
  "type": "error",
  "event": "lobby.create",
  "request_id": "uuid-123",
  "error": {
    "code": "bad_request",
    "message": "Missing 'code' in data"
  }
}
```

### Device Identification

Clients must identify before sending other events:

1. **Query parameter:** Connect with `?device_id=your-device-id`
2. **Identify event:** Send `{"event": "identify", "data": {"device_id": "your-device-id"}}`

## Internal Broadcast API

Used by backend services to push events to connected clients:

```http
POST /internal/broadcast
X-Internal-Token: <token>
Content-Type: application/json

{
  "event": "lobby.updated",
  "data": { "type": "participant_joined", "device_id": "..." },
  "targets": { "device_ids": ["device1", "device2"] }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOBBY_URL` | `http://lobby:8000` | URL of the lobby service |
| `MEASUREMENT_URL` | `http://measurement:8000` | URL of the measurement service |
| `SIMULATION_URL` | `http://simulation:8000` | URL of the simulation service |
| `INTERNAL_AUTH_TOKEN` | `""` | Token for internal broadcast API |
| `MAX_MESSAGE_BYTES` | `65536` | Maximum WebSocket message size |
| `RATE_LIMIT_RPS` | `10.0` | Rate limit requests per second |
| `RATE_LIMIT_BURST` | `20` | Rate limit burst capacity |
| `HTTP_TIMEOUT_SECONDS` | `10.0` | Timeout for upstream HTTP requests |

## Internal Packages

| Module | Description |
|--------|-------------|
| `gateway.main` | FastAPI application, WebSocket handler, HTTP proxy routes |
| `gateway.router` | Event router that forwards messages to appropriate services |
| `gateway.connection_manager` | WebSocket connection tracking and management |
| `gateway.models` | Pydantic models for messages and requests |
| `gateway.config` | Configuration settings from environment variables |
| `gateway.http_client` | Async HTTP client for upstream requests |
| `gateway.rate_limit` | Token bucket rate limiter implementation |

## Dependencies

```
fastapi>=0.110
uvicorn[standard]>=0.27
httpx>=0.27
pydantic>=2.6
```

## Running Locally

```bash
cd gateway
pip install -r requirements.txt
uvicorn gateway.main:app --reload --port 8000
```

## Docker

```bash
docker build -t sonalyze-gateway .
docker run -p 8000:8000 \
  -e LOBBY_URL=http://lobby:8000 \
  -e MEASUREMENT_URL=http://measurement:8000 \
  -e SIMULATION_URL=http://simulation:8000 \
  sonalyze-gateway
```
