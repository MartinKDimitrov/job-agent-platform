from datetime import datetime

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String,
                        Text, JSON, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    profiles: Mapped[list["Profile"]] = relationship(back_populates="user",
                                                     cascade="all, delete-orphan")


class Profile(Base):
    """A candidate search profile. A user may have several (e.g. Android + MLOps)."""
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    target_roles: Mapped[str] = mapped_column(Text, default="")   # comma-separated
    skills: Mapped[str] = mapped_column(Text, default="")         # comma-separated
    experience: Mapped[str] = mapped_column(Text, default="")     # free text
    languages: Mapped[str] = mapped_column(String(255), default="")
    english_level: Mapped[str] = mapped_column(String(16), default="B2")  # CEFR
    location_pref: Mapped[str] = mapped_column(String(255), default="")
    remote_pref: Mapped[str] = mapped_column(String(32), default="remote")  # remote/hybrid/onsite/any
    salary_expectation: Mapped[str] = mapped_column(String(64), default="")
    min_match: Mapped[int] = mapped_column(Integer, default=65)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)  # cached E5 vector
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="profiles")

    def as_text(self) -> str:
        """Concatenated text used to compute the profile embedding."""
        return " · ".join(x for x in [
            self.target_roles, self.skills, self.experience, self.languages,
        ] if x)


class Source(Base):
    """A job platform/source. user_id NULL = built-in/global; otherwise user-added."""
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32), default="manual")  # ats_api/rss/browser/manual
    url: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Posting(Base):
    __tablename__ = "postings"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    company: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    apply_url: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[list | None] = mapped_column(JSON, nullable=True)  # extracted list
    is_live: Mapped[bool] = mapped_column(Boolean, default=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("profile_id", "posting_id", name="uq_profile_posting"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    covered: Mapped[list | None] = mapped_column(JSON, nullable=True)
    missing: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserActivity(Base):
    """Per-user signals for the daily job: when we last saw them, and whether they paused
    searching because they found a job. Separate table so we don't ALTER the users table
    (no migration needed — create_all just adds this)."""
    __tablename__ = "user_activity"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    found_job: Mapped[bool] = mapped_column(Boolean, default=False)


class DigestEntry(Base):
    """Records that a (profile, posting) match was already included in a digest email, so the
    daily job never notifies the same match twice."""
    __tablename__ = "digest_entries"
    __table_args__ = (UniqueConstraint("profile_id", "posting_id", name="uq_digest_profile_posting"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CrawlRun(Base):
    """One crawl run (a daily job or a Search-now), with per-source and total metrics in `stats`
    — so we can see how each source is performing over time. New table -> no migration."""
    __tablename__ = "crawl_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), default="daily")   # daily / search_now
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), nullable=True)
    posting_id: Mapped[int | None] = mapped_column(ForeignKey("postings.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="To research")
    date_sent: Mapped[str] = mapped_column(String(32), default="")
    reply: Mapped[str] = mapped_column(Text, default="")
    reply_date: Mapped[str] = mapped_column(String(32), default="")
    next_step: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
