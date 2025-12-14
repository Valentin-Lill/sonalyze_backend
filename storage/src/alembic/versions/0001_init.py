"""initial schema

Revision ID: 0001_init
Revises: 
Create Date: 2025-12-14

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_devices_external_id", "devices", ["external_id"], unique=True)

    op.create_table(
        "lobbies",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default=sa.text("'created'")),
        sa.Column("creator_device_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["creator_device_id"], ["devices.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_lobbies_code", "lobbies", ["code"], unique=True)

    op.create_table(
        "participants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lobby_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default=sa.text("'observer'")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'connected'")),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["lobby_id"], ["lobbies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("lobby_id", "device_id", name="uq_participant_lobby_device"),
    )
    op.create_index("ix_participants_lobby_id", "participants", ["lobby_id"], unique=False)
    op.create_index("ix_participants_device_id", "participants", ["device_id"], unique=False)

    op.create_table(
        "measurements",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lobby_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_device_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False, server_default=sa.text("'raw'")),
        sa.Column("sample_rate_hz", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("raw_blob_ref", sa.Text(), nullable=True),
        sa.Column("raw_bytes", sa.Integer(), nullable=True),
        sa.Column("raw_sha256", sa.String(length=64), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["lobby_id"], ["lobbies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_device_id"], ["devices.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_measurements_lobby_id", "measurements", ["lobby_id"], unique=False)

    op.create_table(
        "analysis_outputs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("measurement_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'created'")),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["measurement_id"], ["measurements.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_analysis_outputs_measurement_id", "analysis_outputs", ["measurement_id"], unique=False)

    op.create_table(
        "simulation_jobs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("requested_by_device_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lobby_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lobby_id"], ["lobbies.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_simulation_jobs_lobby_id", "simulation_jobs", ["lobby_id"], unique=False)

    op.create_table(
        "simulation_results",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["job_id"], ["simulation_jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", name="uq_simulation_results_job"),
    )
    op.create_index("ix_simulation_results_job_id", "simulation_results", ["job_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_simulation_results_job_id", table_name="simulation_results")
    op.drop_table("simulation_results")

    op.drop_index("ix_simulation_jobs_lobby_id", table_name="simulation_jobs")
    op.drop_table("simulation_jobs")

    op.drop_index("ix_analysis_outputs_measurement_id", table_name="analysis_outputs")
    op.drop_table("analysis_outputs")

    op.drop_index("ix_measurements_lobby_id", table_name="measurements")
    op.drop_table("measurements")

    op.drop_index("ix_participants_device_id", table_name="participants")
    op.drop_index("ix_participants_lobby_id", table_name="participants")
    op.drop_table("participants")

    op.drop_index("ix_lobbies_code", table_name="lobbies")
    op.drop_table("lobbies")

    op.drop_index("ix_devices_external_id", table_name="devices")
    op.drop_table("devices")
