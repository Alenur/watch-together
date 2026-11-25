"""Track organizer presence and the shared playback rate."""

from alembic import op
import sqlalchemy as sa

revision = "0002_room_lifecycle"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rooms", sa.Column("owner_deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_rooms_owner_deadline_at", "rooms", ["owner_deadline_at"])
    op.add_column("rooms", sa.Column("rate", sa.Float(), nullable=False, server_default=sa.text("1")))


def downgrade() -> None:
    op.drop_column("rooms", "rate")
    op.drop_index("ix_rooms_owner_deadline_at", table_name="rooms")
    op.drop_column("rooms", "owner_deadline_at")
