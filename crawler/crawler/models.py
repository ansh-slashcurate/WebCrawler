"""SQLAlchemy models for the control panel's Postgres-backed config data.

Four tables:
  - users: laid down now for future role-based access. Nothing in the app
    enforces roles yet - the admin panel stays fully open to whoever can
    reach it, exactly as before. `role` exists so that switch doesn't
    require a schema change later, not because anything checks it today.
  - bank_sites / tender_tags: the Tenders page's saved-site list and tag
    list, previously flat JSON files (bank_sites.json/tender_tags.json).
    Both relate back to the user who created them (created_by_id) - the
    same readiness-for-RBAC reasoning as the users table itself.
  - app_settings: a small key/value table for user-editable crawl defaults
    (currently just "max_pages_per_crawl", the Settings page's control over
    CLOSESPIDER_PAGECOUNT) - a plain key/value shape rather than one column
    per setting, so a future setting doesn't need its own migration.

Deliberately NOT here: the tenders themselves. This project self-hosts and
some of its crawl/extraction code is reused directly by a separate RAG
project - crawl output staying disk-only (no SQLAlchemy/Postgres dependency
in that path) keeps both of those simple. Tender records + their
classification live in output/<entity>/<run_id>/tenders.jsonl
(crawler.pipelines.StoragePipeline writes it, crawler/tender_sync.py
classifies it after a crawl finishes), same as pages.jsonl/clean.jsonl.
Pipeline debugging events (every LLM call, classify start/finish, failures)
go to a log file (logs/tender_pipeline_<date>.log), not a database table
either - see crawler/tender_sync.py.
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


class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow,
    )
