"""Maersk reference data: product commodity mapping and HS source, route locations, quote locations

Revision ID: 7c4d2e9f1a83
Revises: 1ebb29a98b78
Create Date: 2026-10-29 09:00:00

Additive only. Existing analysis codes get hs_source 'client' when they equal the client's own HS6,
otherwise 'classification_review'.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c4d2e9f1a83"
down_revision: Union[str, Sequence[str], None] = "1ebb29a98b78"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("hs_source", sa.String(30), server_default="classification_review", nullable=False),
    )
    op.add_column("products", sa.Column("maersk_commodity", postgresql.JSONB(), nullable=True))
    op.execute(
        "UPDATE products SET hs_source = 'client' "
        "WHERE client_hs_code <> '' AND hs_code IS NOT NULL AND left(client_hs_code, 6) = hs_code"
    )
    op.create_table(
        "route_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("carrier_geo_id", sa.String(13), nullable=False, unique=True),
        sa.Column("un_location_code", sa.String(5), nullable=False),
        sa.Column("location_name", sa.Text(), nullable=False),
        sa.Column("location_type", sa.String(40), nullable=False),
        sa.Column("city_name", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("country_iso3", sa.String(3), nullable=False),
        sa.Column("country_name", sa.Text(), nullable=False),
        sa.Column("region_name", sa.Text(), nullable=False),
        sa.Column("has_cy_service", sa.Boolean(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("saved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    for col in ("origin_location_id", "destination_location_id"):
        op.add_column(
            "logistics_quotes",
            sa.Column(col, sa.Integer(), sa.ForeignKey("route_locations.id", ondelete="SET NULL"), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("logistics_quotes", "destination_location_id")
    op.drop_column("logistics_quotes", "origin_location_id")
    op.drop_table("route_locations")
    op.drop_column("products", "maersk_commodity")
    op.drop_column("products", "hs_source")
