from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    openid = Column(String(64), unique=True, nullable=False)
    campus = Column(String(20), nullable=False)
    nickname = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    identity = Column(String(20))
    raw_preference_text = Column(Text)
    interest_tags = Column(JSON)
    preferred_campuses = Column(JSON)
    available_time = Column(Text)
    activity_style_tags = Column(JSON)
    profile_summary = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Source(Base):
    __tablename__ = "sources"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    source_type = Column(String(20), nullable=False)
    base_url = Column(String(500))
    feed_url = Column(String(500))
    is_active = Column(Boolean, default=True)
    last_crawled_at = Column(DateTime(timezone=True))

class RawDocument(Base):
    __tablename__ = "raw_documents"

    id = Column(String(36), primary_key=True)
    source_id = Column(String(36), ForeignKey("sources.id"))
    url = Column(String(500))
    title = Column(String(200))
    content_text = Column(Text)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    content_hash = Column(String(64))
    status = Column(String(20), default="pending")

class Event(Base):
    __tablename__ = "events"

    id = Column(String(36), primary_key=True)
    title = Column(String(200), nullable=False)
    summary = Column(Text)
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    location = Column(String(200))
    campus = Column(String(20))
    organizer = Column(String(100))
    source_id = Column(String(36), ForeignKey("sources.id"))
    source_url = Column(String(500))
    source_name = Column(String(100))
    evidence_text = Column(Text)
    tags = Column(JSON)
    quality_score = Column(Float, default=0.5)
    verification_status = Column(String(20), default="unverified")  #verified / unverified / rejected
    is_user_visible = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True),  server_default=func.now(), onupdate=func.now())

class PlanRun(Base):
    __tablename__ = "plan_runs"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"),  nullable=False)
    status = Column(String(20), default="queued")  # queued / running  / completed / failed
    request_text = Column(Text)
    # date_scope = Column(String(20))
    started_at = Column(DateTime(timezone=True),  server_default=func.now())
    ended_at = Column(DateTime(timezone=True))
    error_message = Column(Text)    #
    debug = Column(Text)

class Plan(Base):
    __tablename__ = "plans"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("plan_runs.id"))
    user_id = Column(String(36), ForeignKey("users.id"),nullable=False)
    title = Column(String(200))
    date_scope = Column(String(20))
    summary = Column(Text)
    created_at = Column(DateTime(timezone=True),server_default=func.now())

class PlanItem(Base):
    __tablename__ = "plan_items"

    id = Column(String(36), primary_key=True)
    plan_id = Column(String(36), ForeignKey("plans.id"), nullable=False)
    event_id = Column(String(36), ForeignKey("events.id"))
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    reason_text = Column(Text)
    score = Column(Float)
    score_components = Column(JSON)
    display_order = Column(Integer)


class UserEventFeedback(Base):
    __tablename__ = "user_event_feedback"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    event_id = Column(String(36), ForeignKey("events.id"), nullable=True)
    plan_id = Column(String(36), ForeignKey("plans.id"), nullable=True)
    plan_item_id = Column(String(36), ForeignKey("plan_items.id"), nullable=True)
    run_id = Column(String(36), ForeignKey("plan_runs.id"), nullable=True)
    feedback_type = Column(Text, nullable=False)
    feedback_source = Column(Text, nullable=False)
    comment = Column(Text, nullable=True)
    weight = Column(Float, default=1.0)
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    memory_type = Column(Text, nullable=False)
    memory_scope = Column(Text, nullable=False, default="short_term")
    content = Column(Text, nullable=False)
    structured_content = Column(JSON, nullable=True)
    source_type = Column(Text, nullable=False)
    source_ref = Column(Text, nullable=True)
    confidence = Column(Float, nullable=False, default=0.5)
    priority = Column(Integer, nullable=False, default=50)
    status = Column(Text, nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    last_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class MemoryAuditLog(Base):
    __tablename__ = "memory_audit_log"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    memory_item_id = Column(String(36), ForeignKey("memory_items.id"), nullable=True)
    action = Column(Text, nullable=False)
    before_state = Column(JSON, nullable=True)
    after_state = Column(JSON, nullable=True)
    actor = Column(Text, nullable=False, default="system")
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
