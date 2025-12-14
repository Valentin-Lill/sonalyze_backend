# gateway

WebSocket edge service for Sonalyze.

## What it does
- Accepts WebSocket connections from clients
- Validates + rate-limits inbound messages
- Routes events to internal services over HTTP
- Provides an internal broadcast endpoint for services to fan-out updates to connected clients

## WebSocket
Connect to `ws://<host>:8000/ws?device_id=<id>`.

Client -> gateway messages are JSON:

```json
{
  "event": "lobby.join",
  "request_id": "optional-correlation-id",
  "data": {"lobby_code": "ABCD"}
}
```

Gateway -> client messages are JSON:

- `type: "response"` for replies to a request
- `type: "event"` for pushed updates (fan-out)
- `type: "error"` for errors

## Routing contract (HTTP)
For an incoming websocket message, gateway POSTs to the destination service:

`POST <SERVICE_URL>/gateway/handle`

Body:

```json
{
  "client": {"device_id": "...", "connection_id": "...", "ip": "..."},
  "message": {"event": "...", "request_id": "...", "data": {}}
}
```

The service should respond `200` with JSON (any shape). The JSON is returned to the websocket client as a `response`.

## Internal broadcast
Services can push events to connected websocket clients via:

`POST /internal/broadcast` with header `x-internal-token: <INTERNAL_AUTH_TOKEN>`.

```json
{
  "event": "lobby.update",
  "data": {"...": "..."},
  "targets": {"device_ids": ["dev1", "dev2"]}
}
```

## Environment
- `LOBBY_URL` (default `http://lobby:8000`)
- `MEASUREMENT_URL` (default `http://measurement:8000`)
- `SIMULATION_URL` (default `http://simulation:8000`)
- `INTERNAL_AUTH_TOKEN` (required for `/internal/*`)
- `MAX_MESSAGE_BYTES` (default `65536`)
- `RATE_LIMIT_RPS` (default `10`)
- `RATE_LIMIT_BURST` (default `20`)

## Run locally
From repo root:

```bash
pip install -r gateway/requirements.txt
PYTHONPATH=gateway/src uvicorn gateway.main:app --reload
```
