from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Lobby(Base):
    __tablename__ = "lobbies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(32), default="created")

    creator_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    participants: Mapped[list[Participant]] = relationship(
        back_populates="lobby", cascade="all, delete-orphan", passive_deletes=True
    )


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("lobby_id", "device_id", name="uq_participant_lobby_device"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lobby_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("lobbies.id", ondelete="CASCADE"))
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"))

    role: Mapped[str] = mapped_column(String(32), default="observer")
    status: Mapped[str] = mapped_column(String(32), default="connected")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    lobby: Mapped[Lobby] = relationship(back_populates="participants")


class Measurement(Base):
    __tablename__ = "measurements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    lobby_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lobbies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )

    kind: Mapped[str] = mapped_column(String(64), default="raw")
    sample_rate_hz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)

    raw_blob_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    analysis_outputs: Mapped[list[AnalysisOutput]] = relationship(
        back_populates="measurement", cascade="all, delete-orphan", passive_deletes=True
    )


class AnalysisOutput(Base):
    __tablename__ = "analysis_outputs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    measurement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("measurements.id", ondelete="CASCADE"), index=True
    )

    type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="created")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    measurement: Mapped[Measurement] = relationship(back_populates="analysis_outputs")


class SimulationJob(Base):
    __tablename__ = "simulation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    requested_by_device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    lobby_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lobbies.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(String(32), default="queued")
    params: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    result: Mapped[SimulationResult | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class SimulationResult(Base):
    __tablename__ = "simulation_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_jobs.id", ondelete="CASCADE"), unique=True, index=True
    )

    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    job: Mapped[SimulationJob] = relationship(back_populates="result")
