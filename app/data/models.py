from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON as _JSON

# pgvector on Postgres (binary, SQL cosine, HNSW-indexable — installed on staging);
# plain JSON on SQLite so the hermetic test suite keeps working unchanged.
EmbeddingType = Vector(384).with_variant(_JSON(), "sqlite")

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
    country: Mapped[str] = mapped_column(String(64), default="Bulgaria")   # where the user lives
    relocate: Mapped[bool] = mapped_column(Boolean, default=False)         # willing to move?
    remote_pref: Mapped[str] = mapped_column(String(32), default="remote")  # remote/hybrid/onsite/any
    salary_expectation: Mapped[str] = mapped_column(String(64), default="")
    min_match: Mapped[int] = mapped_column(Integer, default=65)
    embedding: Mapped[list | None] = mapped_column(EmbeddingType, nullable=True)  # E5 query vec
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="profiles")

    def as_text(self) -> str:
        """Full profile text — used for requirement COVERAGE matching (languages/CEFR are
        needed there: 'Fluent in English' is covered by the declared level)."""
        english = f"English {self.english_level}" if self.english_level else ""
        return " · ".join(x for x in [
            self.target_roles, self.skills, self.experience, self.languages, english,
        ] if x)

    def embed_text(self) -> str:
        """The EMBEDDING input — role + skills + experience only, mirroring the posting's
        title+requirements structure (languages/CEFR are filter data, not semantics)."""
        return " · ".join(x for x in [self.target_roles, self.skills, self.experience] if x)


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
    annotation_version: Mapped[str] = mapped_column(String(16), default="")  # annotate-vN
    annotation_fp: Mapped[str] = mapped_column(String(64), default="")       # reqs fingerprint
    embedding: Mapped[list | None] = mapped_column(EmbeddingType, nullable=True)  # passage vec
    embedding_version: Mapped[str] = mapped_column(String(32), default="")  # input+mode stamp
    is_live: Mapped[bool] = mapped_column(Boolean, default=True)
    # Phase 7: salary parsed from the RAW text at ingest (domain/salary.py). NULL = not
    # stated; a stated value shows on the card and acts as a SOFT score signal when the
    # profile states an expectation too.
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String(8), nullable=True)  # month/year
    salary_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)    # as written
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    # UNIQUE so concurrent writers (parallel Adzuna/Careerjet/Jooble) can't both insert the same
    # posting — the DB rejects the racing INSERT and ingest() catches it and touches instead.
    content_hash: Mapped[str] = mapped_column(String(64), default="", unique=True, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # source date
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # by a fetch
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # URL probe


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("profile_id", "posting_id", name="uq_profile_posting"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    llm_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # coverage LLM-checked
    first_shown_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)        # user said 'not this'
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
    lang: Mapped[str] = mapped_column(String(8), default="en")  # digest email language


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


class Document(Base):
    """A generated CV or cover letter, tied to a user and a posting. Content is the LLM output
    (the user reviews/edits before use — human in the loop). prompt_version records which
    prompt template produced it, so prompt changes are traceable."""
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    posting_id: Mapped[int | None] = mapped_column(
        ForeignKey("postings.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="cv")       # cv / cover_letter
    lang: Mapped[str] = mapped_column(String(8), default="en")        # en / bg
    content: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserLLMConfig(Base):
    """Per-user BYOK settings: which LLM provider to use and their API key, encrypted at rest
    (Fernet — see data/keystore.py). One config per user; deletable any time. The plaintext key
    is decrypted only at generation time and never logged or rendered back."""
    __tablename__ = "user_llm_configs"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))            # gemini / groq / ollama / ...
    encrypted_key: Mapped[str] = mapped_column(Text, default="")  # empty for keyless (ollama)
    model: Mapped[str] = mapped_column(String(128), default="")   # empty -> provider default
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FeedbackEvent(Base):
    """High-signal user actions on matches (Phase 6): the substrate for the applications
    dashboard and the Phase-5 learning loop. 'shown' is tracked cheaply as
    Match.first_shown_at; rows here are only the deliberate acts (applied / hidden).
    New table -> no migration."""
    __tablename__ = "feedback_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(16))            # applied / hidden
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Company(Base):
    """The company registry (ROADMAP 16б): employers whose career pages we crawl through an
    ATS adapter. Filled by the ATS auto-detection tool; one adapter covers every company on
    the same platform. New table -> no migration."""
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    country: Mapped[str] = mapped_column(String(8), default="BG")     # BG / EU / ...
    industry: Mapped[str] = mapped_column(String(64), default="")
    website: Mapped[str] = mapped_column(Text, default="")
    careers_url: Mapped[str] = mapped_column(Text, default="")
    ats: Mapped[str] = mapped_column(String(32), default="")          # greenhouse/lever/ashby
    ats_slug: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)       # crawled when True
    detected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class AdzunaPull(Base):
    """Resumable cursor for the category×country bulk pull of Adzuna (all professions). One row
    per (country, category) slice — the nightly job advances next_page and updates counts, so
    progress is checkable/board-able any time and the pull resumes exactly where it stopped."""
    __tablename__ = "adzuna_pull"
    id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(String(4), index=True)
    category: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(128), default="")
    next_page: Mapped[int] = mapped_column(Integer, default=1)      # page to fetch next
    pulled: Mapped[int] = mapped_column(Integer, default=0)         # postings persisted from slice
    total: Mapped[int] = mapped_column(Integer, default=0)          # Adzuna's count for the slice
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("country", "category", name="uq_adzuna_slice"),)


class AggregatorPull(Base):
    """Per-profession collection tally for the keyword aggregators (Jooble / Careerjet). They
    have no catalogue cursor like Adzuna, so the fallback sweep records one row per (source,
    term): unique postings persisted, total fetched, run count — enough to board what each
    source has collected per profession."""
    __tablename__ = "aggregator_pull"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), index=True)     # jooble | careerjet
    term: Mapped[str] = mapped_column(String(64))
    pulled: Mapped[int] = mapped_column(Integer, default=0)         # postings persisted (added)
    seen: Mapped[int] = mapped_column(Integer, default=0)           # postings fetched (incl. dupes)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("source", "term", name="uq_agg_pull"),)


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
