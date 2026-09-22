"""SQLAlchemy models for the control panel's Postgres-backed config data.

Three tables:
  - users: laid down now for future role-based access. Nothing in the app
    enforces roles yet - the admin panel stays fully open to whoever can
    reach it, exactly as before. `role` exists so that switch doesn't
    require a schema change later, not because anything checks it today.
  - bank_sites / tender_tags: the Tenders page's saved-site list and tag
    list, previously flat JSON files (bank_sites.json/tender_tags.json).
    Both relate back to the user who created them (created_by_id) - the
    same readiness-for-RBAC reasoning as the users table itself.

Crawl output (pages.jsonl/clean.jsonl/tenders.jsonl/summary.json under
output/<entity>/<run_id>/) is unaffected - it stays on disk, written by
crawler.pipelines.StoragePipeline exactly as before.
"""
import datetime
import enum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from crawler.db import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    viewer = "viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), default=UserRole.admin, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)

    bank_sites: Mapped[list["BankSite"]] = relationship(back_populates="created_by")
    tender_tags: Mapped[list["TenderTag"]] = relationship(back_populates="created_by")


class BankSite(Base):
    __tablename__ = "bank_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)

    created_by: Mapped[User | None] = relationship(back_populates="bank_sites")


class TenderTag(Base):
    __tablename__ = "tender_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)

    created_by: Mapped[User | None] = relationship(back_populates="tender_tags")
