"""Database schema.

Country-level statistics (TradeObservation) and company-level records (Company,
CompanyEvidence, Shipment) are deliberately separate tables: a national import
figure must never be presented as a company's purchase.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Role(StrEnum):
    admin = "admin"
    analyst = "analyst"
    viewer = "viewer"


class ReviewStatus(StrEnum):
    candidate = "candidate"
    verified = "verified"
    rejected = "rejected"


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.viewer)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = _now()


class HSCode(Base):
    __tablename__ = "hs_codes"
    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(120), default="")
    hs_code: Mapped[str] = mapped_column(ForeignKey("hs_codes.code"))
    created_at: Mapped[datetime] = _now()
    hs: Mapped[HSCode] = relationship(lazy="joined")


class Country(Base):
    __tablename__ = "countries"
    m49: Mapped[int] = mapped_column(Integer, primary_key=True)
    iso3: Mapped[str] = mapped_column(String(3), default="")
    name: Mapped[str] = mapped_column(String(120))


class SourceRecord(Base):
    """Provenance for every external fact."""

    __tablename__ = "source_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    adapter: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    reporting_period: Mapped[str] = mapped_column(String(40), default="")
    licence: Mapped[str] = mapped_column(Text, default="")
    retrieved_at: Mapped[datetime] = _now()


class TradeObservation(Base):
    """Country-level trade statistic (never company-level)."""

    __tablename__ = "trade_observations"
    __table_args__ = (UniqueConstraint("reporter_m49", "partner_m49", "hs_code", "flow", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reporter_m49: Mapped[int] = mapped_column(ForeignKey("countries.m49"), index=True)
    partner_m49: Mapped[int] = mapped_column(Integer)  # 0 = World
    hs_code: Mapped[str] = mapped_column(ForeignKey("hs_codes.code"), index=True)
    flow: Mapped[str] = mapped_column(String(1))  # M import, X export
    year: Mapped[int] = mapped_column(Integer)
    value_usd: Mapped[float] = mapped_column(Float)
    net_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty_unit: Mapped[str] = mapped_column(String(20), default="")
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))
    source: Mapped[SourceRecord] = relationship(lazy="joined")


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("name", "country_iso3"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    country_iso3: Mapped[str] = mapped_column(String(3))
    website: Mapped[str] = mapped_column(Text, default="")
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(30)), default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    hs_codes: Mapped[list[str]] = mapped_column(ARRAY(String(6)), default=list)
    review_status: Mapped[str] = mapped_column(String(20), default=ReviewStatus.candidate)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _now()
    evidence: Mapped[list["CompanyEvidence"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", lazy="selectin"
    )


class CompanyEvidence(Base):
    __tablename__ = "company_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    claim: Mapped[str] = mapped_column(Text, default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))
    company: Mapped[Company] = relationship(back_populates="evidence")
    source: Mapped[SourceRecord] = relationship(lazy="joined")


class Shipment(Base):
    """Company-level shipment record; only populated from a licensed provider."""

    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    hs_code: Mapped[str] = mapped_column(String(10))
    shipped_on: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    origin_iso3: Mapped[str] = mapped_column(String(3))
    destination_iso3: Mapped[str] = mapped_column(String(3))
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))


class LogisticsQuote(Base):
    """Freight quote from a connected provider or entered by the client (labelled)."""

    __tablename__ = "logistics_quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(120))
    destination: Mapped[str] = mapped_column(String(120))
    destination_iso3: Mapped[str] = mapped_column(String(3), index=True)
    mode: Mapped[str] = mapped_column(String(20))  # sea, air, road, rail
    container: Mapped[str] = mapped_column(String(40), default="")
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    transit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance: Mapped[str] = mapped_column(String(30), default="client_provided")
    source_note: Mapped[str] = mapped_column(Text, default="")
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _now()


class MarketOpportunity(Base):
    __tablename__ = "market_opportunities"
    id: Mapped[int] = mapped_column(primary_key=True)
    hs_code: Mapped[str] = mapped_column(ForeignKey("hs_codes.code"), index=True)
    country_m49: Mapped[int] = mapped_column(ForeignKey("countries.m49"))
    score: Mapped[float] = mapped_column(Float)
    components: Mapped[dict] = mapped_column(JSONB)
    weights: Mapped[dict] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = _now()


class ProspectList(Base):
    __tablename__ = "prospect_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    hs_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _now()


class ProspectListItem(Base):
    __tablename__ = "prospect_list_items"
    __table_args__ = (UniqueConstraint("list_id", "company_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("prospect_lists.id", ondelete="CASCADE"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    notes: Mapped[str] = mapped_column(Text, default="")


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    hs_code: Mapped[str] = mapped_column(ForeignKey("hs_codes.code"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[dict] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(60), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _now()


class ApiCache(Base):
    __tablename__ = "api_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    adapter: Mapped[str] = mapped_column(String(40))
    response: Mapped[dict | list] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RefreshRun(Base):
    __tablename__ = "refresh_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    adapter: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="running")
    rows: Mapped[int] = mapped_column(BigInteger, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    started_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
