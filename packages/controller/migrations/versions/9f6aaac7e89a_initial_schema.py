"""Initial schema.

Revision ID: 9f6aaac7e89a
Revises:
Create Date: 2026-03-23 17:43:12.278940
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9f6aaac7e89a"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create agents and jobs tables."""
    # Enum types
    agent_status = postgresql.ENUM(
        "online", "busy", "offline", name="agent_status", create_type=False
    )
    job_status = postgresql.ENUM(
        "queued",
        "assigned",
        "running",
        "completed",
        "failed",
        name="job_status",
        create_type=False,
    )
    product = postgresql.ENUM(
        "vehicle_gateway",
        "asset_gateway",
        "environmental_monitor",
        "industrial_gateway",
        name="product",
        create_type=False,
    )

    agent_status.create(op.get_bind(), checkfirst=True)
    job_status.create(op.get_bind(), checkfirst=True)
    product.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "product",
            sa.Enum(
                "vehicle_gateway",
                "asset_gateway",
                "environmental_monitor",
                "industrial_gateway",
                name="product",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "assigned",
                "running",
                "completed",
                "failed",
                name="job_status",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("assigned_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("capabilities", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "online", "busy", "offline", name="agent_status", create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["current_job_id"], ["jobs.id"], use_alter=True),
    )

    # Add FK from jobs.assigned_agent_id → agents.id
    op.create_foreign_key(None, "jobs", "agents", ["assigned_agent_id"], ["id"])


def downgrade() -> None:
    """Drop agents and jobs tables."""
    op.drop_table("agents")
    op.drop_table("jobs")
    op.execute("DROP TYPE IF EXISTS agent_status")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS product")
