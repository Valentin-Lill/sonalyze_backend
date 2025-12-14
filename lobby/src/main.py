from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db import engine, get_session
from models import Base
from schemas import (
    AssignRoleRequest,
    EventsResponse,
    HealthResponse,
    LobbyCreateRequest,
    LobbyCreateResponse,
    LobbyJoinRequest,
    LobbyLeaveRequest,
    LobbyOut,
    ParticipantOut,
    StartMeasurementRequest,
)
from service import (
    assign_role,
    create_lobby,
    get_events,
    get_lobby_by_code,
    get_lobby_by_id,
    join_lobby,
    leave_lobby,
    list_participants,
    start_measurement,
)
from settings import settings

app = FastAPI(title="Sonalyze Lobby Service", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
        return HealthResponse(service=settings.service_name, ok=True)
    except Exception:
        return HealthResponse(service=settings.service_name, ok=False)


@app.post("/lobbies", response_model=LobbyCreateResponse)
async def create(req: LobbyCreateRequest, session: AsyncSession = Depends(get_session)) -> LobbyCreateResponse:
    try:
        lobby = await create_lobby(session, creator_device_id=req.creator_device_id)
        await session.commit()
        return LobbyCreateResponse(
            lobby_id=lobby.id,
            code=lobby.code,
            admin_device_id=lobby.creator_device_id,
            state=lobby.state,
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/lobbies/join", response_model=LobbyOut)
async def join(req: LobbyJoinRequest, session: AsyncSession = Depends(get_session)) -> LobbyOut:
    lobby = await get_lobby_by_code(session, req.code)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")

    try:
        await join_lobby(session, lobby=lobby, device_id=req.device_id)
        participants = await list_participants(session, lobby.id)
        await session.commit()
        return LobbyOut(
            lobby_id=lobby.id,
            code=lobby.code,
            admin_device_id=lobby.creator_device_id,
            state=lobby.state,
            participants=[
                ParticipantOut(
                    device_id=p.device_id,
                    role=p.role,
                    status=p.status,
                    joined_at=p.joined_at,
                    left_at=p.left_at,
                )
                for p in participants
            ],
        )
    except ValueError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/lobbies/{lobby_id}/leave")
async def leave(lobby_id: str, req: LobbyLeaveRequest, session: AsyncSession = Depends(get_session)) -> dict:
    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")

    await leave_lobby(session, lobby=lobby, device_id=req.device_id)
    await session.commit()
    return {"ok": True}


@app.get("/lobbies/{lobby_id}", response_model=LobbyOut)
async def get_lobby(lobby_id: str, session: AsyncSession = Depends(get_session)) -> LobbyOut:
    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")

    participants = await list_participants(session, lobby.id)
    return LobbyOut(
        lobby_id=lobby.id,
        code=lobby.code,
        admin_device_id=lobby.creator_device_id,
        state=lobby.state,
        participants=[
            ParticipantOut(
                device_id=p.device_id,
                role=p.role,
                status=p.status,
                joined_at=p.joined_at,
                left_at=p.left_at,
            )
            for p in participants
        ],
    )


@app.post("/lobbies/{lobby_id}/roles")
async def roles(lobby_id: str, req: AssignRoleRequest, session: AsyncSession = Depends(get_session)) -> dict:
    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")

    try:
        await assign_role(
            session,
            lobby=lobby,
            admin_device_id=req.admin_device_id,
            target_device_id=req.target_device_id,
            role=req.role,
        )
        await session.commit()
        return {"ok": True}
    except PermissionError as e:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(e))
    except LookupError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/lobbies/{lobby_id}/start")
async def start(lobby_id: str, req: StartMeasurementRequest, session: AsyncSession = Depends(get_session)) -> dict:
    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")

    try:
        await start_measurement(session, lobby=lobby, admin_device_id=req.admin_device_id)
        await session.commit()
        return {"ok": True, "state": lobby.state}
    except PermissionError as e:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/lobbies/{lobby_id}/events", response_model=EventsResponse)
async def events(lobby_id: str, after_id: int | None = None, session: AsyncSession = Depends(get_session)) -> EventsResponse:
    lobby = await get_lobby_by_id(session, lobby_id)
    if lobby is None:
        raise HTTPException(status_code=404, detail="Lobby not found")

    items = await get_events(session, lobby_id=lobby_id, after_id=after_id)
    return EventsResponse(
        lobby_id=lobby_id,
        events=[
            {
                "id": e.id,
                "type": e.type,
                "payload": e.payload,
                "created_at": e.created_at,
            }
            for e in items
        ],
    )
