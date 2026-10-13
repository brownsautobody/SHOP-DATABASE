"""Core tables (see docs/data-model.md). Later features only add tables; these keep their shape."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Money = Numeric(10, 2, asdecimal=False)
Hours = Numeric(8, 2, asdecimal=False)


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tracked:
    """Who made / last changed a row, and when (rule 1)."""
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class Shop(Tracked, Base):
    __tablename__ = "shops"
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(250), default="")


class User(Tracked, Base):
    __tablename__ = "users"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(120))
    login: Mapped[str] = mapped_column(String(120), unique=True)
    role: Mapped[str] = mapped_column(String(40), default="")  # admin, front office, body tech, painter, parts...
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Tracked, Base):
    __tablename__ = "customers"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str] = mapped_column(String(40), default="")
    email: Mapped[str] = mapped_column(String(200), default="")


class Vehicle(Tracked, Base):
    __tablename__ = "vehicles"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    vin: Mapped[str] = mapped_column(String(17), default="", index=True)
    year: Mapped[str] = mapped_column(String(4), default="")
    make: Mapped[str] = mapped_column(String(60), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(String(250), default="")
    mileage: Mapped[str] = mapped_column(String(20), default="")


class InsuranceCompany(Tracked, Base):
    __tablename__ = "insurance_companies"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(200), index=True)


class Job(Tracked, Base):
    """One repair order."""
    __tablename__ = "jobs"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    ro_number: Mapped[str] = mapped_column(String(20), default="", index=True)  # typed in by hand for Mitchell
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    insurance_id: Mapped[int | None] = mapped_column(ForeignKey("insurance_companies.id"))
    claim_no: Mapped[str] = mapped_column(String(60), default="", index=True)
    adjuster: Mapped[str] = mapped_column(String(200), default="")
    estimator: Mapped[str] = mapped_column(String(120), default="")
    loss_date: Mapped[str] = mapped_column(String(20), default="")
    deductible: Mapped[str] = mapped_column(String(60), default="")
    # use_alter: jobs <-> estimate_documents point at each other
    current_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimate_documents.id", use_alter=True, name="fk_jobs_current_document"))
    current_stage_id: Mapped[int | None] = mapped_column(Integer)  # unused for now (production board removed)
    dropped_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer | None] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()
    insurance: Mapped[InsuranceCompany | None] = relationship()
    documents: Mapped[list["EstimateDocument"]] = relationship(
        back_populates="job", foreign_keys="EstimateDocument.job_id", order_by="EstimateDocument.id")
    current_document: Mapped["EstimateDocument | None"] = relationship(foreign_keys=[current_document_id], post_update=True)


class File(Tracked, Base):
    """A stored file; the bytes live on disk (or cloud storage later), the row keeps where."""
    __tablename__ = "files"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # estimate_pdf, invoice, photo...
    original_name: Mapped[str] = mapped_column(String(250), default="")
    path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)


class EstimateDocument(Tracked, Base):
    """One uploaded estimate PDF = one version; never overwritten."""
    __tablename__ = "estimate_documents"
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"))
    format: Mapped[str] = mapped_column(String(20))
    title_raw: Mapped[str] = mapped_column(String(200), default="")
    display: Mapped[str] = mapped_column(String(200), default="")
    stage: Mapped[str] = mapped_column(String(20))
    supplement_no: Mapped[int] = mapped_column(Integer, default=0)
    printed_at: Mapped[str] = mapped_column(String(19), default="")  # ISO text, as the parser gives it
    supplement_amount: Mapped[float | None] = mapped_column(Money)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)
    parser_version: Mapped[str] = mapped_column(String(20))
    parse: Mapped[dict] = mapped_column(JSON)  # full parse_pdf() result, so it can be re-read later

    job: Mapped[Job] = relationship(back_populates="documents", foreign_keys=[job_id])
    file: Mapped[File | None] = relationship()
    lines: Mapped[list["EstimateLine"]] = relationship(order_by="EstimateLine.id", cascade="all, delete-orphan")
    totals: Mapped[list["EstimateTotal"]] = relationship(order_by="EstimateTotal.id", cascade="all, delete-orphan")


class EstimateLine(Base):
    """Itemized charge rows (parse_pdf()['charges']); written once with their document."""
    __tablename__ = "estimate_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("estimate_documents.id"), index=True)
    line_no: Mapped[str] = mapped_column(String(10), default="")
    section: Mapped[str] = mapped_column(String(120), default="")
    operation: Mapped[str] = mapped_column(String(40), default="")
    category: Mapped[str] = mapped_column(String(40))  # Part, Body Labor, Paint Labor, Sublet, Other Charge...
    description: Mapped[str] = mapped_column(String(300), default="")
    part_no: Mapped[str] = mapped_column(String(60), default="", index=True)
    part_type: Mapped[str] = mapped_column(String(40), default="")
    qty: Mapped[float | None] = mapped_column(Hours)
    hours: Mapped[float | None] = mapped_column(Hours)
    rate: Mapped[float | None] = mapped_column(Money)
    amount: Mapped[float | None] = mapped_column(Money)
    taxed: Mapped[bool | None] = mapped_column(Boolean)
    flags: Mapped[str] = mapped_column(String(120), default="")


class EstimateTotal(Base):
    """Totals rows printed on the estimate (parse_pdf()['totals'])."""
    __tablename__ = "estimate_totals"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("estimate_documents.id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    section: Mapped[str] = mapped_column(String(30), default="")
    hours: Mapped[float | None] = mapped_column(Hours)
    rate: Mapped[float | None] = mapped_column(Money)
    amount: Mapped[float | None] = mapped_column(Money)
    extra: Mapped[float | None] = mapped_column(Money)  # markup / discount column
    extra_kind: Mapped[str] = mapped_column(String(20), default="")


class KbSource(Tracked, Base):
    """A body of reference knowledge: CCC's help center now; shop policies and reference estimates later."""
    __tablename__ = "kb_sources"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))  # web_docs, shop_policy, estimate_reference
    base_url: Mapped[str] = mapped_column(String(300), default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KbNode(Base):
    """One category, section or article. parent_id makes the tree. Removed upstream = active False, never deleted."""
    __tablename__ = "kb_nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("kb_sources.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("kb_nodes.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # category, section, article
    external_id: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(500), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    body_html: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    source_updated_at: Mapped[str] = mapped_column(String(30), default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class KbRevision(Base):
    """The previous version of a node, kept when the source changes it (rule 2)."""
    __tablename__ = "kb_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("kb_nodes.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body_html: Mapped[str] = mapped_column(Text, default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    source_updated_at: Mapped[str] = mapped_column(String(30), default="")
    replaced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KbLink(Base):
    """A link or image inside a node's body; to_node_id is set when it points at another node in the knowledge base."""
    __tablename__ = "kb_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    from_node_id: Mapped[int] = mapped_column(ForeignKey("kb_nodes.id"), index=True)
    to_node_id: Mapped[int | None] = mapped_column(ForeignKey("kb_nodes.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # article, external, image
    text: Mapped[str] = mapped_column(String(300), default="")
    href: Mapped[str] = mapped_column(String(1000))


class AuditLog(Base):
    """Every change, for every table (rule 4). Append only."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    table_name: Mapped[str] = mapped_column(String(60))
    row_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # create, update, archive
    field: Mapped[str] = mapped_column(String(60), default="")
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True)  # quick "everything on this job"
