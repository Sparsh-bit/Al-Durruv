"""Database schema.

Country-level statistics (TradeObservation) and company-level records (Company,
CompanyEvidence, Shipment) are deliberately separate tables: a national import
figure must never be presented as a company's purchase.
"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Date,
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


class HsStatus(StrEnum):
    confirmed = "confirmed"
    candidate = "candidate"  # needs verification by the client or a customs broker
    insufficient_info = "insufficient_info"
    unmapped = "unmapped"
    discrepancy = "discrepancy"  # the client's code points to a different product family; needs review


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
    language: Mapped[str] = mapped_column(String(2), default="en", server_default="en")
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
    brand: Mapped[str] = mapped_column(String(120), default="", server_default="")
    pack_size: Mapped[str] = mapped_column(String(80), default="", server_default="")
    net_quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_unit: Mapped[str] = mapped_column(String(8), default="", server_default="")  # g, kg, ml, L
    packaging: Mapped[str] = mapped_column(String(80), default="", server_default="")
    catalogue_page: Mapped[str] = mapped_column(String(40), default="", server_default="")  # e.g. "3, 5"
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    # HS6 used for trade analysis. The client's own (often national 8-10 digit) code is kept verbatim in
    # client_hs_code and never rewritten; a reviewer confirms which HS6 applies.
    hs_code: Mapped[str | None] = mapped_column(ForeignKey("hs_codes.code"), nullable=True)
    hs_status: Mapped[str] = mapped_column(String(20), default=HsStatus.candidate, server_default=HsStatus.candidate)
    hs_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    client_hs_code: Mapped[str] = mapped_column(String(14), default="", server_default="")
    client_hs_source: Mapped[str] = mapped_column(Text, default="", server_default="")
    # where the analysis HS6 came from: client (their own code), classification_review (an analyst's review),
    # maersk_reference (a Maersk Commodities API suggestion chosen by a reviewer). None is a customs ruling.
    hs_source: Mapped[str] = mapped_column(
        String(30), default="classification_review", server_default="classification_review"
    )
    # reviewer-selected Maersk commodity reference (code, name, HS codes, retrieved_at, selected_by/at)
    maersk_commodity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    hs_reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    hs_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    name_ar: Mapped[str] = mapped_column(String(255), default="", server_default="")
    ingredients: Mapped[str] = mapped_column(Text, default="", server_default="")
    processing: Mapped[str] = mapped_column(Text, default="", server_default="")
    manufacturing_country: Mapped[str] = mapped_column(String(3), default="", server_default="")
    export_entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True)
    priority_category: Mapped[str] = mapped_column(String(60), default="", server_default="", index=True)
    created_at: Mapped[datetime] = _now()
    hs: Mapped[HSCode | None] = relationship(lazy="joined")
    export_entity: Mapped["Entity | None"] = relationship(lazy="joined")


class Entity(Base):
    """A manufacturing or export entity of the client group (verified separately from client claims)."""

    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    country_iso3: Mapped[str] = mapped_column(String(3), default="")
    role: Mapped[str] = mapped_column(String(20), default="manufacturer")  # manufacturer, exporter, both
    status: Mapped[str] = mapped_column(String(24), default="pending_verification")
    notes: Mapped[str] = mapped_column(Text, default="")
    source_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _now()


class Clarification(Base):
    """An open question for the client; answers are recorded, never assumed."""

    __tablename__ = "clarifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(20), default="general", index=True)
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)  # open, answered, closed
    answer: Mapped[str] = mapped_column(Text, default="")
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _now()


class TargetMarket(Base):
    """A country in the client's market list, imported from the client's file."""

    __tablename__ = "target_markets"
    iso3: Mapped[str] = mapped_column(String(3), primary_key=True)
    segment: Mapped[str] = mapped_column(String(12), default="expansion")  # existing, expansion
    source: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = _now()


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
    # buyer | competitor | supplier: kept distinct, a competitor is not a prospect
    relationship_type: Mapped[str] = mapped_column(String(20), default="buyer", server_default="buyer", index=True)
    product_range: Mapped[str] = mapped_column(Text, default="", server_default="")
    product_fit: Mapped[str] = mapped_column(Text, default="", server_default="")
    private_label: Mapped[str] = mapped_column(String(12), default="unknown", server_default="unknown")
    private_label_evidence: Mapped[str] = mapped_column(Text, default="", server_default="")
    buying_signals: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    markets_served: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    contact: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # public business contacts only
    name_on_source: Mapped[bool | None] = mapped_column(nullable=True)
    prospect_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_components: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    pipeline_stage: Mapped[str] = mapped_column(String(20), default="identified", server_default="identified")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    brief: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    brief_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # confirmed: official identity verified from the company's own sources; needs_confirmation: named by
    # the client or a source but not yet matched to a legal entity
    identity_status: Mapped[str] = mapped_column(String(20), default="unverified", server_default="unverified")
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    normalized_name: Mapped[str] = mapped_column(Text, default="", server_default="", index=True)
    vendor_url: Mapped[str] = mapped_column(Text, default="", server_default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    next_action: Mapped[str] = mapped_column(Text, default="", server_default="")
    follow_up_on: Mapped[date | None] = mapped_column(Date, nullable=True)
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


class ImportBatch(Base):
    """One uploaded shipment file (bill-of-lading export from a licensed provider)."""

    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSONB, default=list)
    mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _now()


class Shipment(Base):
    """One bill-of-lading record from a licensed provider file. Shown only to signed-in users of this org."""

    __tablename__ = "shipments"
    __table_args__ = (UniqueConstraint("provider", "row_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    row_key: Mapped[str] = mapped_column(String(80))  # provider record id, or a hash of the row
    shipped_on: Mapped[date] = mapped_column(Date, index=True)
    shipper_company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    consignee_company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shipper_name: Mapped[str] = mapped_column(Text, default="")
    consignee_name: Mapped[str] = mapped_column(Text, default="")
    origin_iso3: Mapped[str] = mapped_column(String(3), default="")
    destination_iso3: Mapped[str] = mapped_column(String(3), default="", index=True)
    hs_code: Mapped[str] = mapped_column(String(12), default="", index=True)  # as filed (6-10 digits)
    hs6: Mapped[str] = mapped_column(String(6), default="", index=True)
    product_description: Mapped[str] = mapped_column(Text, default="")
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    port_of_lading: Mapped[str] = mapped_column(Text, default="")
    port_of_unlading: Mapped[str] = mapped_column(Text, default="")
    carrier: Mapped[str] = mapped_column(Text, default="")
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"), index=True)


class MonthlyFlow(Base):
    """Monthly trade from national/regional sources (US Census, Eurostat Comext)."""

    __tablename__ = "monthly_flows"
    __table_args__ = (
        UniqueConstraint("source", "reporter_iso3", "partner_iso3", "partner_name", "product_code", "flow", "period"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # census, comext
    reporter_iso3: Mapped[str] = mapped_column(String(3), index=True)
    partner_iso3: Mapped[str] = mapped_column(String(3))
    partner_name: Mapped[str] = mapped_column(Text, default="")
    hs6: Mapped[str] = mapped_column(String(6), index=True)
    product_code: Mapped[str] = mapped_column(String(12))  # HS10 (Census) / CN8 (Comext) / HS6
    flow: Mapped[str] = mapped_column(String(1), default="M")
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    value_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_native: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    fx_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # native -> USD, monthly average
    net_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(20), default="")
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))


class FxRate(Base):
    __tablename__ = "fx_rates"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    base: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40), default="frankfurter (ECB)")


class Tariff(Base):
    """Duty rate for an importer x HS x origin. Connector rows and admin overrides; overrides win."""

    __tablename__ = "tariffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    importer_iso3: Mapped[str] = mapped_column(String(3), index=True)  # EU members use EUN
    hs_code: Mapped[str] = mapped_column(String(10), index=True)
    origin_iso3: Mapped[str] = mapped_column(String(3), default="")  # "" = applies to any origin (MFN)
    rate_type: Mapped[str] = mapped_column(String(15))  # MFN, preferential, additional
    ad_valorem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    specific_rate: Mapped[str] = mapped_column(Text, default="")
    agreement: Mapped[str] = mapped_column(Text, default="")
    data_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(20))  # wits, usitc, override
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"), nullable=True)
    verified_at: Mapped[datetime] = _now()
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class RetailerRequirement(Base):
    """Supplier requirement for a target retailer or market; admin-maintained with its source."""

    __tablename__ = "retailer_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    market_iso3: Mapped[str] = mapped_column(String(3), default="")
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    verified_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="todo")  # todo, in_progress, met, not_applicable
    created_at: Mapped[datetime] = _now()


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    hs_code: Mapped[str] = mapped_column(String(12), default="")
    title: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = _now()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Brief(Base):
    """Every generated account brief, with the facts it was given and the model/prompt version."""

    __tablename__ = "briefs"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    language: Mapped[str] = mapped_column(String(2), default="en")
    content: Mapped[dict] = mapped_column(JSONB)
    facts_bundle: Mapped[list] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _now()


class RouteLocation(Base):
    """A location chosen from the Maersk Locations API for shipment routes. Geo ID and UN/LOCODE are kept
    separately: they are different identifier systems."""

    __tablename__ = "route_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    carrier_geo_id: Mapped[str] = mapped_column(String(13), unique=True)
    un_location_code: Mapped[str] = mapped_column(String(5), default="")
    location_name: Mapped[str] = mapped_column(Text, default="")
    location_type: Mapped[str] = mapped_column(String(40), default="")
    city_name: Mapped[str] = mapped_column(Text, default="")
    country_code: Mapped[str] = mapped_column(String(2), default="")
    country_iso3: Mapped[str] = mapped_column(String(3), default="")
    country_name: Mapped[str] = mapped_column(Text, default="")
    region_name: Mapped[str] = mapped_column(Text, default="")
    has_cy_service: Mapped[bool | None] = mapped_column(nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(40), default="maersk_locations_v4")
    retrieved_at: Mapped[datetime] = _now()
    saved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class LogisticsQuote(Base):
    """Freight quote from a connected provider or entered by the client (labelled)."""

    __tablename__ = "logistics_quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    origin: Mapped[str] = mapped_column(String(120))
    origin_iso3: Mapped[str] = mapped_column(String(3), default="", server_default="")
    payload_kg: Mapped[float | None] = mapped_column(Float, nullable=True)  # cargo per container, for $/kg
    origin_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("route_locations.id", ondelete="SET NULL"), nullable=True
    )
    destination_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("route_locations.id", ondelete="SET NULL"), nullable=True
    )
    destination: Mapped[str] = mapped_column(String(120))
    destination_iso3: Mapped[str] = mapped_column(String(3), index=True)
    mode: Mapped[str] = mapped_column(String(20))  # sea, air, road, rail
    container: Mapped[str] = mapped_column(String(40), default="")
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    transit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carrier: Mapped[str] = mapped_column(String(120), default="", server_default="")
    incoterm: Mapped[str] = mapped_column(String(10), default="", server_default="")
    assumptions: Mapped[str] = mapped_column(Text, default="", server_default="")
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
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketNews(Base):
    """AI web research on recent market developments for one HS code (sources validated)."""

    __tablename__ = "market_news"
    id: Mapped[int] = mapped_column(primary_key=True)
    hs_code: Mapped[str] = mapped_column(ForeignKey("hs_codes.code"), index=True)
    items: Mapped[list] = mapped_column(JSONB, default=list)
    retrieved_at: Mapped[datetime] = _now()


class AiUsage(Base):
    """One row per Claude call: the basis for cost reporting and the monthly budget cap."""

    __tablename__ = "ai_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = _now()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    feature: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    web_searches: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)


class AppSetting(Base):
    """Admin-editable settings (company profile, export markets, AI budget); override .env defaults."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict | list | str | float | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = _now()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = _now()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(40))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
