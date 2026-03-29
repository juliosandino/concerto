"""Uppercase enum values, add PASSED, and SET NULL on agent FK.

Revision ID: 4f999a0a4b66
Revises: 9f6aaac7e89a
Create Date: 2026-03-28 20:11:27.662418

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4f999a0a4b66"
down_revision: Union[str, Sequence[str], None] = "9f6aaac7e89a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Recreate agent_status with uppercase values --
    op.execute("ALTER TYPE agent_status RENAME TO agent_status_old")
    op.execute("CREATE TYPE agent_status AS ENUM ('ONLINE', 'BUSY', 'OFFLINE')")
    op.execute(
        "ALTER TABLE agents ALTER COLUMN status TYPE agent_status"
        " USING upper(status::text)::agent_status"
    )
    op.execute("DROP TYPE agent_status_old")

    # -- Recreate job_status with uppercase values + PASSED --
    op.execute("ALTER TYPE job_status RENAME TO job_status_old")
    op.execute(
        "CREATE TYPE job_status AS ENUM"
        " ('QUEUED', 'ASSIGNED', 'RUNNING', 'COMPLETED', 'PASSED', 'FAILED')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN status TYPE job_status"
        " USING upper(status::text)::job_status"
    )
    op.execute("DROP TYPE job_status_old")

    # -- Recreate product with uppercase values --
    op.execute("ALTER TYPE product RENAME TO product_old")
    op.execute(
        "CREATE TYPE product AS ENUM"
        " ('VEHICLE_GATEWAY', 'ASSET_GATEWAY',"
        " 'ENVIRONMENTAL_MONITOR', 'INDUSTRIAL_GATEWAY')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN product TYPE product"
        " USING upper(product::text)::product"
    )
    op.execute("DROP TYPE product_old")

    # -- Fix FK to SET NULL on delete --
    op.drop_constraint("jobs_assigned_agent_id_fkey", "jobs", type_="foreignkey")
    op.create_foreign_key(
        "jobs_assigned_agent_id_fkey",
        "jobs",
        "agents",
        ["assigned_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # -- Revert FK --
    op.drop_constraint("jobs_assigned_agent_id_fkey", "jobs", type_="foreignkey")
    op.create_foreign_key(
        "jobs_assigned_agent_id_fkey",
        "jobs",
        "agents",
        ["assigned_agent_id"],
        ["id"],
    )

    # -- Revert product to lowercase --
    op.execute("ALTER TYPE product RENAME TO product_old")
    op.execute(
        "CREATE TYPE product AS ENUM"
        " ('vehicle_gateway', 'asset_gateway',"
        " 'environmental_monitor', 'industrial_gateway')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN product TYPE product"
        " USING lower(product::text)::product"
    )
    op.execute("DROP TYPE product_old")

    # -- Revert job_status to lowercase (without PASSED) --
    op.execute("ALTER TYPE job_status RENAME TO job_status_old")
    op.execute(
        "CREATE TYPE job_status AS ENUM"
        " ('queued', 'assigned', 'running', 'completed', 'failed')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN status TYPE job_status"
        " USING lower(status::text)::job_status"
    )
    op.execute("DROP TYPE job_status_old")

    # -- Revert agent_status to lowercase --
    op.execute("ALTER TYPE agent_status RENAME TO agent_status_old")
    op.execute("CREATE TYPE agent_status AS ENUM ('online', 'busy', 'offline')")
    op.execute(
        "ALTER TABLE agents ALTER COLUMN status TYPE agent_status"
        " USING lower(status::text)::agent_status"
    )
    op.execute("DROP TYPE agent_status_old")
