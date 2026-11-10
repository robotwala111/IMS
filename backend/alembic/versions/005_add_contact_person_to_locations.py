"""Add contact_person field to locations table

Revision ID: 005
Revises: b8df5501e558
Create Date: 2026-02-27 12:00:00.000000

"""
from typing import Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "b8df5501e558"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Add contact_person column to locations table
    op.add_column('locations', sa.Column('contact_person', sa.String(255), nullable=True))


def downgrade() -> None:
    # Remove contact_person column from locations table
    op.drop_column('locations', 'contact_person')
