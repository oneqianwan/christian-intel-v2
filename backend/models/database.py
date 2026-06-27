from sqlalchemy import create_engine, Column, String, DateTime, Text, JSON, Float, Boolean, Integer, ForeignKey, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False, default="新会话")
    is_pinned = Column(Boolean, default=False)
    pinned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True)
    conversation_id = Column(String, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text)
    entities_mentioned = Column(JSON, default=list)
    sources = Column(JSON, default=list)
    delivery_type = Column(String, default="text")
    status = Column(String, default="completed")
    created_at = Column(DateTime, default=datetime.utcnow)

class KnowledgeEntity(Base):
    __tablename__ = "knowledge_entities"
    id = Column(String, primary_key=True)
    entity_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    country = Column(String)
    category = Column(String)
    data = Column(JSON)
    source_url = Column(String)
    source_name = Column(String)
    published_at = Column(DateTime)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    confidence = Column(Float, default=1.0)

class OrganizationProfile(Base):
    __tablename__ = "organization_profiles"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    name_local = Column(String)
    country = Column(String, nullable=False)

    official_website = Column(String)
    contact_email = Column(String)
    phone_public = Column(String)
    address = Column(Text)

    leader_name = Column(String)
    leader_title = Column(String)
    leader_bio_url = Column(String)

    facebook_url = Column(String)
    youtube_url = Column(String)
    telegram_username = Column(String)

    denomination = Column(String)
    member_estimate = Column(Integer)
    founded_year = Column(String)

    source_url = Column(String)
    source_name = Column(String)
    confidence = Column(Float, default=0.8)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class OrganizationContactHistory(Base):
    __tablename__ = "organization_contact_history"
    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organization_profiles.id"))
    event_type = Column(String)
    event_date = Column(DateTime)
    notes = Column(Text)
    created_by = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class Source(Base):
    __tablename__ = "sources"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    type = Column(String, nullable=False)  # rss, website
    country = Column(String, nullable=False)
    scope = Column(String(20), nullable=False, default="country", comment="来源范围：country/global")
    trust_level = Column(String, default="medium")  # high, medium, low
    last_scan_at = Column(DateTime)
    success_rate = Column(Float, default=1.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Page(Base):
    __tablename__ = "pages"
    id = Column(String, primary_key=True)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    url = Column(String, nullable=False)
    title = Column(String)
    content = Column(Text)
    published_at = Column(DateTime)
    extracted_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")  # pending, fetched, parsed, failed


class IntelligenceItem(Base):
    __tablename__ = "intelligence_items"
    id = Column(String, primary_key=True)
    page_id = Column(String, ForeignKey("pages.id"))
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    title = Column(String)
    content = Column(Text)
    entity_name = Column(String)
    entity_type = Column(String)
    country = Column(String)
    category = Column(String)
    source_url = Column(String)
    source_name = Column(String)
    published_at = Column(DateTime)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    confidence = Column(Float, default=0.8)
    scope = Column(String(20), nullable=False, default="country")


class ApiConfig(Base):
    __tablename__ = "api_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    api_name = Column(String(50), unique=True, nullable=False)
    encrypted_api_key = Column(Text)
    key_hint = Column(String(16))
    extra_config = Column(JSON, default=dict)
    status = Column(String(20), default="unknown")
    usage_info = Column(Text)
    last_checked = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    id = Column(String, primary_key=True)
    user_id = Column(String, default="default")
    intelligence_item_id = Column(String, ForeignKey("intelligence_items.id"))
    note = Column(Text)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class Mission(Base):
    __tablename__ = "missions"
    id = Column(String, primary_key=True)
    query = Column(String, nullable=False)
    country = Column(String, nullable=False)
    status = Column(String, default="queued")  # queued, running, done, failed, cancelled
    priority = Column(Integer, default=5, nullable=False)
    composite_task_id = Column(String(36), nullable=True)
    composite_status = Column(String(20), nullable=True)
    target_entity = Column(String(100), nullable=True, comment="该任务的目标实体名，用于来源过滤")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"
    id = Column(String, primary_key=True)
    mission_id = Column(String, ForeignKey("missions.id"), nullable=False)
    job_type = Column(String, nullable=False)  # rss_scan, page_extract
    source_id = Column(String, ForeignKey("sources.id"))
    status = Column(String, default="queued")  # queued, running, done, failed, cancelled
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    result_count = Column(Integer, default=0)
    error_message = Column(Text)


class RequestTrace(Base):
    __tablename__ = "request_traces"
    id = Column(String, primary_key=True)
    request_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    event_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_schema_compatibility()


def _ensure_schema_compatibility():
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as conn:
        if "missions" in table_names:
            mission_columns = {column["name"] for column in inspector.get_columns("missions")}
            if "priority" not in mission_columns:
                conn.execute(text("ALTER TABLE missions ADD COLUMN priority INTEGER DEFAULT 5 NOT NULL"))
            if "composite_task_id" not in mission_columns:
                conn.execute(text("ALTER TABLE missions ADD COLUMN composite_task_id VARCHAR(36) NULL"))
            if "composite_status" not in mission_columns:
                conn.execute(text("ALTER TABLE missions ADD COLUMN composite_status VARCHAR(20) NULL"))
            if "target_entity" not in mission_columns:
                conn.execute(text("ALTER TABLE missions ADD COLUMN target_entity VARCHAR(100) NULL"))

        if "sources" in table_names:
            source_columns = {column["name"] for column in inspector.get_columns("sources")}
            if "scope" not in source_columns:
                conn.execute(text("ALTER TABLE sources ADD COLUMN scope VARCHAR(20) DEFAULT 'country'"))
            conn.execute(text("UPDATE sources SET scope = 'country' WHERE scope IS NULL OR scope = ''"))
            conn.execute(text("ALTER TABLE sources ALTER COLUMN scope SET NOT NULL"))

        if "intelligence_items" in table_names:
            item_columns = {column["name"] for column in inspector.get_columns("intelligence_items")}
            if "scope" not in item_columns:
                conn.execute(text("ALTER TABLE intelligence_items ADD COLUMN scope VARCHAR(20) DEFAULT 'country'"))
            conn.execute(text("UPDATE intelligence_items SET scope = 'country' WHERE scope IS NULL OR scope = ''"))
            conn.execute(text("ALTER TABLE intelligence_items ALTER COLUMN scope SET NOT NULL"))

        if "api_configs" in table_names:
            api_columns = {column["name"] for column in inspector.get_columns("api_configs")}
            if "encrypted_api_key" not in api_columns:
                conn.execute(text("ALTER TABLE api_configs ADD COLUMN encrypted_api_key TEXT"))
            if "key_hint" not in api_columns:
                conn.execute(text("ALTER TABLE api_configs ADD COLUMN key_hint VARCHAR(16)"))
            if "extra_config" not in api_columns:
                conn.execute(text("ALTER TABLE api_configs ADD COLUMN extra_config JSON DEFAULT '{}'"))
            if "status" not in api_columns:
                conn.execute(text("ALTER TABLE api_configs ADD COLUMN status VARCHAR(20) DEFAULT 'unknown'"))
            if "usage_info" not in api_columns:
                conn.execute(text("ALTER TABLE api_configs ADD COLUMN usage_info TEXT"))
            if "last_checked" not in api_columns:
                conn.execute(text("ALTER TABLE api_configs ADD COLUMN last_checked TIMESTAMP NULL"))
            if "created_at" not in api_columns:
                conn.execute(text("ALTER TABLE api_configs ADD COLUMN created_at TIMESTAMP DEFAULT NOW()"))
            if "updated_at" not in api_columns:
                conn.execute(text("ALTER TABLE api_configs ADD COLUMN updated_at TIMESTAMP DEFAULT NOW()"))
            if "api_key" in api_columns:
                conn.execute(text("UPDATE api_configs SET api_key = NULL WHERE api_key IS NOT NULL"))

        if "conversations" in table_names:
            conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
            if "is_pinned" not in conversation_columns:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE NOT NULL"))
            if "pinned_at" not in conversation_columns:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN pinned_at TIMESTAMP NULL"))
