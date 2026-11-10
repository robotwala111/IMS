"""Merge 014 migration heads.

Revision ID: 015_merge_014_heads
Revises: 014_add_assigned_to_transfer, 014_add_employees_table
Create Date: 2026-05-31
"""

from typing import Sequence, Union


revision: str = "015_merge_014_heads"
down_revision: Union[str, Sequence[str], None] = (
    "014_add_assigned_to_transfer",
    "014_add_employees_table",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
