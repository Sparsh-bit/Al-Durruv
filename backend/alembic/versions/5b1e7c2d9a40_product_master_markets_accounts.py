"""product master, entities, clarifications, target markets, account CRM fields

Revision ID: 5b1e7c2d9a40
Revises: 286627390534
Create Date: 2026-10-28 10:00:00

Additive only: existing rows are kept. Product hs_status "suggested" becomes "candidate"; the old
export_markets setting is copied into target_markets as "existing" and then removed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5b1e7c2d9a40"
down_revision: Union[str, Sequence[str], None] = "286627390534"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _text(name: str, length: int | None = None) -> sa.Column:
    kind = sa.String(length) if length else sa.Text()
    return sa.Column(name, kind, server_default="", nullable=False)


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("country_iso3", sa.String(3), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "target_markets",
        sa.Column("iso3", sa.String(3), primary_key=True),
        sa.Column("segment", sa.String(12), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.alter_column("products", "hs_code", existing_type=sa.String(6), nullable=True)
    op.alter_column("products", "hs_status", type_=sa.String(20), existing_type=sa.String(12))
    op.alter_column("products", "hs_status", server_default="candidate")
    op.execute("UPDATE products SET hs_status = 'candidate' WHERE hs_status = 'suggested'")
    for col in (
        _text("client_hs_code", 14),
        _text("client_hs_source"),
        _text("name_ar", 255),
        _text("ingredients"),
        _text("processing"),
        _text("manufacturing_country", 3),
        _text("priority_category", 60),
    ):
        op.add_column("products", col)
    op.add_column("products", sa.Column("hs_reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("products", sa.Column("hs_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "products",
        sa.Column("export_entity_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_products_priority_category", "products", ["priority_category"])

    op.create_table(
        "clarifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", sa.String(20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=True),
        sa.Column("answered_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_clarifications_topic", "clarifications", ["topic"])
    op.create_index("ix_clarifications_status", "clarifications", ["status"])

    op.add_column("companies", _text("identity_status", 20))
    op.alter_column("companies", "identity_status", server_default="unverified")
    op.execute("UPDATE companies SET identity_status = 'unverified' WHERE identity_status = ''")
    op.add_column("companies", _text("vendor_url"))
    op.add_column("companies", _text("next_action"))
    op.add_column("companies", sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
    op.add_column("companies", sa.Column("follow_up_on", sa.Date(), nullable=True))

    # carry the old flat list of export markets over as "existing" target markets
    op.execute(
        """
        INSERT INTO target_markets (iso3, segment, source, notes)
        SELECT DISTINCT upper(m.code), 'existing', 'Administration (earlier export-markets setting)', ''
        FROM app_settings s, jsonb_array_elements_text(s.value) AS m(code)
        WHERE s.key = 'export_markets' AND jsonb_typeof(s.value) = 'array'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute("DELETE FROM app_settings WHERE key = 'export_markets'")


def downgrade() -> None:
    op.drop_column("companies", "follow_up_on")
    op.drop_column("companies", "owner_id")
    op.drop_column("companies", "next_action")
    op.drop_column("companies", "vendor_url")
    op.drop_column("companies", "identity_status")
    op.drop_table("clarifications")
    op.drop_index("ix_products_priority_category", "products")
    for col in (
        "export_entity_id",
        "hs_reviewed_at",
        "hs_reviewed_by",
        "priority_category",
        "manufacturing_country",
        "processing",
        "ingredients",
        "name_ar",
        "client_hs_source",
        "client_hs_code",
    ):
        op.drop_column("products", col)
    op.execute("UPDATE products SET hs_status = 'suggested' WHERE hs_status <> 'confirmed'")
    op.alter_column("products", "hs_status", server_default="suggested")
    op.drop_table("target_markets")
    op.drop_table("entities")
