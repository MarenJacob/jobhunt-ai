from datetime import datetime
from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(300))
    location: Mapped[str] = mapped_column(String(300), default="")
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    source: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    match_score: Mapped[float] = mapped_column(Float, default=0)
    qualification: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="discovered")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expired: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    tailored_cv: Mapped[str] = mapped_column(Text, default="")
    cover_letter: Mapped[str] = mapped_column(Text, default="")
    answers: Mapped[str] = mapped_column(Text, default="{}")
    notes: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Profile(Base):
    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    headline: Mapped[str] = mapped_column(String(300), default="")
    email: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(300), default="Nigeria")
    skills: Mapped[str] = mapped_column(Text, default="")
    projects: Mapped[str] = mapped_column(Text, default="")
    experience: Mapped[str] = mapped_column(Text, default="")
    education: Mapped[str] = mapped_column(Text, default="")
    preferences: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    linkedin: Mapped[str] = mapped_column(String(500), default="")
    github: Mapped[str] = mapped_column(String(500), default="")
    website: Mapped[str] = mapped_column(String(500), default="")
    work_authorization: Mapped[str] = mapped_column(String(300), default="")
    sponsorship: Mapped[str] = mapped_column(String(300), default="")
    salary: Mapped[str] = mapped_column(String(200), default="")
    resume_filename: Mapped[str] = mapped_column(String(300), default="")
    resume_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

class ATSRun(Base):
    __tablename__ = "ats_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(50), default="generic")
    field_map: Mapped[str] = mapped_column(Text, default="{}")
    unresolved: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(50), default="mapped")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TailoringRun(Base):
    __tablename__ = "tailoring_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(Integer)
    ats_score: Mapped[float] = mapped_column(Float, default=0)
    matched_keywords: Mapped[str] = mapped_column(Text, default="[]")
    missing_keywords: Mapped[str] = mapped_column(Text, default="[]")
    bullet_alignment: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TelemetryReport(Base):
    __tablename__ = "telemetry_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(300))
    report: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer)
    session: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class NegotiationRun(Base):
    __tablename__ = "negotiation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(Integer)
    analysis: Mapped[str] = mapped_column(Text, default="{}")
    script: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class BrowserRun(Base):
    __tablename__ = "browser_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(50), default="generic")
    action: Mapped[str] = mapped_column(String(50), default="inspect")
    status: Mapped[str] = mapped_column(String(50), default="started")
    mapping: Mapped[str] = mapped_column(Text, default="{}")
    unresolved: Mapped[str] = mapped_column(Text, default="[]")
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
