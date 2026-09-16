"""strona odczytana z obrazu

Revision ID: 7087f340ec8a
Revises: eaa2533b6a34
Create Date: 2026-09-16 18:09:11.823877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7087f340ec8a'
down_revision: Union[str, None] = 'eaa2533b6a34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Strony wgrane wczesniej pochodza z warstwy tekstowej - stad domyslne
    # false i server_default, zeby istniejace wiersze mialy wartosc.
    op.add_column(
        "pages",
        sa.Column("z_obrazu", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("pages", "z_obrazu")
