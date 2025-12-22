from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LobbyState(str, enum.Enum):
    OPEN = "open"
    MEASUREMENT_RUNNING = "measurement_running"
    CLOSED = "closed"


class ParticipantRole(str, enum.Enum):
    NONE = "none"
    MICROPHONE = "microphone"
    SPEAKER = "speaker"


class ParticipantStatus(str, enum.Enum):
    JOINED = "joined"
    LEFT = "left"


class Lobby(Base):
    __tablename__ = "lobbies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    creator_device_id: Mapped[str] = mapped_column(String(128), index=True)
    state: Mapped[LobbyState] = mapped_column(Enum(LobbyState), default=LobbyState.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("lobby_id", "device_id", name="uq_participant_lobby_device"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lobby_id: Mapped[str] = mapped_column(String(36), ForeignKey("lobbies.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[ParticipantRole] = mapped_column(Enum(ParticipantRole), default=ParticipantRole.NONE)
    role_slot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role_slot_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[ParticipantStatus] = mapped_column(Enum(ParticipantStatus), default=ParticipantStatus.JOINED)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LobbyEvent(Base):
    __tablename__ = "lobby_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lobby_id: Mapped[str] = mapped_column(String(36), ForeignKey("lobbies.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
