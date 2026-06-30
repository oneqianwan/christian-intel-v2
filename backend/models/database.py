import uuid
import shutil

from pathlib import Path
from sqlalchemy import create_engine, Column, String, DateTime, Text, JSON, Float, Boolean, Integer, ForeignKey, UniqueConstraint, inspect, text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
from config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=20,
    max_overflow=30,
    pool_timeout=60,
    pool_recycle=3600,
    pool_pre_ping=True,
)

if settings.DATABASE_URL.startswith("sqlite:///"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # The current environment cannot reliably create on-disk journal files.
        cursor.execute("PRAGMA journal_mode=MEMORY")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()

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
    official_name = Column(String, nullable=True)
    short_name = Column(String, nullable=True)
    english_name = Column(String, nullable=True)

    description = Column(Text)
    city = Column(String)
    state_province = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    mission_statement = Column(Text)
    vision_statement = Column(Text, nullable=True)
    statement_of_faith = Column(Text, nullable=True)

    official_website = Column(String)
    contact_email = Column(String)
    phone_public = Column(String)
    address = Column(Text)
    headquarters_address = Column(String, nullable=True)
    wikipedia_url = Column(String, nullable=True)
    wikidata_id = Column(String, nullable=True)
    google_maps_url = Column(String, nullable=True)
    apple_maps_url = Column(String, nullable=True)

    leader_name = Column(String)
    leader_title = Column(String)
    leader_bio_url = Column(String)
    ai_team_lead = Column(String, nullable=True)

    facebook_url = Column(String)
    youtube_url = Column(String)
    twitter_url = Column(String, nullable=True)
    telegram_username = Column(String)
    social_accounts_json = Column(Text, nullable=True)

    denomination = Column(String)
    organization_type = Column(String, nullable=True)
    denomination_category = Column(String, nullable=True)
    organization_size = Column(String, nullable=True)
    member_estimate = Column(Integer)
    founded_year = Column(Integer, nullable=True)
    member_count = Column(Integer, nullable=True)
    church_count = Column(Integer, nullable=True)
    employee_count = Column(Integer, nullable=True)
    volunteer_count = Column(Integer, nullable=True)
    languages = Column(Text, nullable=True)
    coverage_countries = Column(Text, nullable=True)
    service_countries = Column(Text, nullable=True)

    source_url = Column(String)
    source_name = Column(String)
    confidence = Column(Float, default=0.8)
    tax_status = Column(String, nullable=True)
    nonprofit_id = Column(String, nullable=True)
    registration_number = Column(String, nullable=True)
    annual_revenue = Column(String, nullable=True)
    annual_expenses = Column(String, nullable=True)
    budget_scale = Column(String, nullable=True)
    has_ai_initiative = Column(Boolean, default=False)
    has_online_giving = Column(Boolean, default=False)
    has_mobile_app = Column(Boolean, default=False)
    social_accounts = Column(JSON)
    key_activities = Column(JSON)
    ai_maturity_score = Column(Integer)
    digital_score = Column(Integer)
    about_text = Column(Text)
    tech_stack_json = Column(Text, nullable=True)
    ai_strategy = Column(Text, nullable=True)
    ai_projects = Column(Text, nullable=True)
    ai_news = Column(Text, nullable=True)
    ai_maturity_rationale = Column(Text, nullable=True)
    url_tier = Column(String, nullable=True, default="C")
    priority_tier = Column(String, nullable=True, default="T3")
    last_website_crawl = Column(DateTime)
    last_deep_crawl = Column(DateTime, nullable=True)
    deep_crawl_status = Column(String, nullable=True)
    pages_crawled = Column(Text, nullable=True)
    has_about = Column(Boolean, default=False)
    has_mission = Column(Boolean, default=False)
    has_vision = Column(Boolean, default=False)
    has_leadership_page = Column(Boolean, default=False)
    has_programs = Column(Boolean, default=False)
    has_donate = Column(Boolean, default=False)
    has_annual_report = Column(Boolean, default=False)
    has_financial_report = Column(Boolean, default=False)
    has_impact_report = Column(Boolean, default=False)
    has_partner_page = Column(Boolean, default=False)
    has_jobs = Column(Boolean, default=False)
    has_events = Column(Boolean, default=False)
    has_resources = Column(Boolean, default=False)
    has_sermons = Column(Boolean, default=False)
    has_podcast = Column(Boolean, default=False)
    has_video = Column(Boolean, default=False)
    has_blog = Column(Boolean, default=False)
    has_press = Column(Boolean, default=False)
    has_privacy = Column(Boolean, default=False)
    has_contact = Column(Boolean, default=False)
    data_sources_json = Column(Text, nullable=True)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @hybrid_property
    def deep_crawled_at(self):
        return self.last_deep_crawl

    @deep_crawled_at.expression
    def deep_crawled_at(cls):
        return cls.last_deep_crawl


class LeaderCandidate(Base):
    """People 提取候选，人工确认后才写入正式表。"""

    __tablename__ = "leader_candidates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String, ForeignKey("organization_profiles.id"), nullable=False)

    candidate_name = Column(String, nullable=False)
    candidate_title = Column(String, nullable=False)
    candidate_bio = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)

    extraction_method = Column(String, nullable=False)
    confidence = Column(Float, nullable=False, default=0.5)

    status = Column(String, nullable=False, default="pending")
    validation_notes = Column(Text, nullable=True)

    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    approved_leader_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FieldChangeHistory(Base):
    """字段变更历史记录，作为 History Layer 的最小可行实现。"""

    __tablename__ = "field_change_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String, ForeignKey("organization_profiles.id"), nullable=False, index=True)
    field_name = Column(String, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    change_source = Column(String, default="unknown")
    changed_by = Column(String, default="system")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    organization = relationship("OrganizationProfile", backref="change_history")


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


class RSSSource(Base):
    __tablename__ = "rss_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    rss_url = Column(String(500), nullable=False, unique=True)
    country = Column(String(100))
    language = Column(String(10))
    category = Column(String(50))
    scope = Column(String(20), default="global")
    last_fetched_at = Column(DateTime, nullable=True)
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


# ========== Christian Ontology 分类体系 ==========


class OrganizationType(Base):
    """机构类型分类"""

    __tablename__ = "organization_types"

    id = Column(String(50), primary_key=True)  # 如: "faithtech_ai", "foundation_grant"
    name = Column(String(100), nullable=False)  # 如: "FaithTech AI公司"
    name_en = Column(String(100))  # 英文名称
    parent_id = Column(String(50), ForeignKey("organization_types.id"), nullable=True)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class TheologicalPosition(Base):
    """神学立场/教派"""

    __tablename__ = "theological_positions"

    id = Column(String(50), primary_key=True)  # 如: "evangelical", "pentecostal"
    name = Column(String(100), nullable=False)
    name_en = Column(String(100))
    tradition = Column(String(50))  # 大类: protestant/catholic/orthodox
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScaleLevel(Base):
    """机构规模等级"""

    __tablename__ = "scale_levels"

    id = Column(String(20), primary_key=True)  # micro/small/medium/large/mega
    name = Column(String(50), nullable=False)
    min_people = Column(Integer)
    max_people = Column(Integer)
    description = Column(Text)


class AIMaturityLevel(Base):
    """AI成熟度等级"""

    __tablename__ = "ai_maturity_levels"

    id = Column(String(20), primary_key=True)  # level_0/level_1/level_2/level_3/level_4
    name = Column(String(50), nullable=False)
    description = Column(Text)
    indicators = Column(Text)  # 判断标准


class CollaborationPreference(Base):
    """合作偏好"""

    __tablename__ = "collaboration_preferences"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)


# ========== 机构与Ontology关联表 ==========


class OrganizationOntologyTag(Base):
    """机构-Ontology标签关联"""

    __tablename__ = "organization_ontology_tags"

    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(50), ForeignKey("organization_profiles.id"), nullable=False)
    tag_type = Column(String(50), nullable=False)  # type/theology/scale/ai_maturity/collaboration
    tag_id = Column(String(50), nullable=False)  # 对应各分类表的ID
    confidence = Column(String(20), default="manual")  # manual/auto/verified
    source = Column(String(200))  # 标注来源
    created_at = Column(DateTime, default=datetime.utcnow)


# ============== 投资机构数据库（阶段2） ==============


class Investor(Base):
    """投资机构/投资人"""

    __tablename__ = "investors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    name_en = Column(String(255), nullable=True)
    investor_type = Column(String(50), nullable=False)  # vc, pe, angel, corporate, foundation, impact_investor
    description = Column(Text, nullable=True)

    # 投资偏好
    focus_areas = Column(JSON, nullable=True)  # ["FaithTech", "EdTech", "Media"]
    thesis = Column(Text, nullable=True)  # 投资理念
    stage_focus = Column(JSON, nullable=True)  # ["pre_seed", "seed", "series_a"]
    check_size_min = Column(Float, nullable=True)  # 最小投资金额 USD
    check_size_max = Column(Float, nullable=True)  # 最大投资金额 USD

    # 地理覆盖
    country = Column(String(100), nullable=True)
    region_focus = Column(JSON, nullable=True)  # ["Southeast Asia", "East Africa"]

    # 联系信息
    website = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    contact_person = Column(String(255), nullable=True)

    # 元数据
    source = Column(String(100), nullable=True)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FundingRound(Base):
    """融资轮次记录"""

    __tablename__ = "funding_rounds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 当前代码库没有 entities 表，这里兼容挂到现有 knowledge_entities。
    entity_id = Column(String, ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False)
    round_type = Column(String(50), nullable=False)  # pre_seed, seed, series_a, series_b, grant, debt
    amount = Column(Float, nullable=True)  # USD
    currency = Column(String(10), default="USD")
    announced_date = Column(DateTime, nullable=True)
    valuation = Column(Float, nullable=True)

    source = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Investment(Base):
    """投资关系"""

    __tablename__ = "investments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    funding_round_id = Column(Integer, ForeignKey("funding_rounds.id", ondelete="CASCADE"), nullable=False)
    investor_id = Column(Integer, ForeignKey("investors.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=True)
    lead_investor = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 当前代码库没有 entities 表，这里兼容挂到现有 knowledge_entities。
    entity_id = Column(String, ForeignKey("knowledge_entities.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(String(20), default="medium")
    status = Column(String(20), default="pending")
    due_date = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String, ForeignKey("knowledge_entities.id", ondelete="SET NULL"), nullable=True)
    entity_name = Column(String(255), nullable=True)
    watch_type = Column(String(50), default="general")
    notes = Column(Text, nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserFeedback(Base):
    """用户反馈记录（Learning Loop核心）"""

    __tablename__ = "user_feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), nullable=False, index=True)
    feedback_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=True)
    related_entity = Column(String(255), nullable=True)
    related_investor = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserProfile(Base):
    """用户画像持久化表"""

    __tablename__ = "user_profiles"

    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(100), nullable=False, index=True)

    name = Column(String(100), nullable=True)
    org = Column(String(200), nullable=True)
    role = Column(String(200), nullable=True)

    project_description = Column(Text, nullable=True)
    focus_area = Column(String(100), nullable=True)
    project_stage = Column(String(50), nullable=True)

    focus_region = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    region = Column(String(100), nullable=True)
    preference = Column(String(50), nullable=True)
    preferred_investor_type = Column(String(50), nullable=True)

    profile_json = Column(JSON, nullable=True)

    source = Column(String(50), default="conversation")
    confidence = Column(Float, default=1.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("session_id", name="uix_session_profile"),
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    db_path = _resolve_sqlite_db_path()
    if db_path:
        print(f"[DB] SQLite path: {db_path}")
        try:
            backup_info = _backup_sqlite_db(db_path)
            if backup_info:
                latest_backup, dated_backup = backup_info
                print(f"[DB] Latest backup refreshed: {latest_backup}")
                if dated_backup:
                    print(f"[DB] Daily backup created: {dated_backup}")
        except Exception as exc:
            print(f"[DB] Backup skipped: {exc}")
    Base.metadata.create_all(bind=engine)
    _ensure_schema_compatibility()


def _resolve_sqlite_db_path() -> Path | None:
    database_url = settings.DATABASE_URL or ""
    if not database_url.startswith("sqlite:///"):
        return None

    raw_path = database_url[len("sqlite:///") :]
    if not raw_path:
        return None

    return Path(raw_path)


def _backup_sqlite_db(db_path: Path) -> tuple[Path, Path | None] | None:
    if not db_path.exists():
        return None

    backup_dir = db_path.parent / "_db_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    latest_backup = backup_dir / f"{db_path.stem}-latest{db_path.suffix}"
    shutil.copy2(db_path, latest_backup)

    today_prefix = datetime.utcnow().strftime("%Y%m%d")
    dated_backup = None
    if not any(backup_dir.glob(f"{db_path.stem}-{today_prefix}-*{db_path.suffix}")):
        dated_backup = backup_dir / f"{db_path.stem}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}{db_path.suffix}"
        shutil.copy2(db_path, dated_backup)

    dated_backups = sorted(
        path
        for path in backup_dir.glob(f"{db_path.stem}-*{db_path.suffix}")
        if path.name != latest_backup.name
    )
    for stale_backup in dated_backups[:-7]:
        stale_backup.unlink(missing_ok=True)

    return latest_backup, dated_backup


def _ensure_missing_columns(conn, inspector, table_name: str, column_definitions: list[tuple[str, str]]) -> set[str]:
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    for column_name, column_sql in column_definitions:
        if column_name not in existing_columns:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))
            existing_columns.add(column_name)
    return existing_columns


def _ensure_schema_compatibility():
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    is_sqlite = engine.dialect.name == "sqlite"

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
            if not is_sqlite:
                conn.execute(text("ALTER TABLE sources ALTER COLUMN scope SET NOT NULL"))

        if "intelligence_items" in table_names:
            item_columns = {column["name"] for column in inspector.get_columns("intelligence_items")}
            if "scope" not in item_columns:
                conn.execute(text("ALTER TABLE intelligence_items ADD COLUMN scope VARCHAR(20) DEFAULT 'country'"))
            conn.execute(text("UPDATE intelligence_items SET scope = 'country' WHERE scope IS NULL OR scope = ''"))
            if not is_sqlite:
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
                created_at_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
                conn.execute(text(f"ALTER TABLE api_configs ADD COLUMN created_at TIMESTAMP DEFAULT {created_at_default}"))
            if "updated_at" not in api_columns:
                updated_at_default = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"
                conn.execute(text(f"ALTER TABLE api_configs ADD COLUMN updated_at TIMESTAMP DEFAULT {updated_at_default}"))
            if "api_key" in api_columns:
                conn.execute(text("UPDATE api_configs SET api_key = NULL WHERE api_key IS NOT NULL"))

        if "conversations" in table_names:
            conversation_columns = {column["name"] for column in inspector.get_columns("conversations")}
            if "is_pinned" not in conversation_columns:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE NOT NULL"))
            if "pinned_at" not in conversation_columns:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN pinned_at TIMESTAMP NULL"))

        if "organization_profiles" in table_names:
            _ensure_missing_columns(
                conn,
                inspector,
                "organization_profiles",
                [
                    ("description", "TEXT"),
                    ("city", "VARCHAR(255)"),
                    ("mission_statement", "TEXT"),
                    ("has_ai_initiative", "BOOLEAN DEFAULT FALSE"),
                    ("has_online_giving", "BOOLEAN DEFAULT FALSE"),
                    ("has_mobile_app", "BOOLEAN DEFAULT FALSE"),
                    ("social_accounts", "JSON"),
                    ("key_activities", "JSON"),
                    ("ai_maturity_score", "INTEGER"),
                    ("digital_score", "INTEGER"),
                    ("about_text", "TEXT"),
                    ("last_website_crawl", "TIMESTAMP NULL"),
                    ("official_name", "VARCHAR(255)"),
                    ("short_name", "VARCHAR(255)"),
                    ("english_name", "VARCHAR(255)"),
                    ("state_province", "VARCHAR(255)"),
                    ("postal_code", "VARCHAR(64)"),
                    ("organization_type", "VARCHAR(255)"),
                    ("denomination_category", "VARCHAR(255)"),
                    ("organization_size", "VARCHAR(64)"),
                    ("headquarters_address", "VARCHAR(500)"),
                    ("tax_status", "VARCHAR(255)"),
                    ("nonprofit_id", "VARCHAR(255)"),
                    ("registration_number", "VARCHAR(255)"),
                    ("annual_revenue", "VARCHAR(255)"),
                    ("annual_expenses", "VARCHAR(255)"),
                    ("budget_scale", "VARCHAR(255)"),
                    ("member_count", "INTEGER"),
                    ("church_count", "INTEGER"),
                    ("employee_count", "INTEGER"),
                    ("volunteer_count", "INTEGER"),
                    ("languages", "TEXT"),
                    ("coverage_countries", "TEXT"),
                    ("service_countries", "TEXT"),
                    ("vision_statement", "TEXT"),
                    ("statement_of_faith", "TEXT"),
                    ("wikipedia_url", "VARCHAR(500)"),
                    ("wikidata_id", "VARCHAR(255)"),
                    ("google_maps_url", "VARCHAR(500)"),
                    ("apple_maps_url", "VARCHAR(500)"),
                    ("twitter_url", "VARCHAR(500)"),
                    ("social_accounts_json", "TEXT"),
                    ("url_tier", "VARCHAR(8) DEFAULT 'C'"),
                    ("priority_tier", "VARCHAR(8) DEFAULT 'T3'"),
                    ("last_deep_crawl", "TIMESTAMP NULL"),
                    ("deep_crawl_status", "VARCHAR(64)"),
                    ("pages_crawled", "TEXT"),
                    ("tech_stack_json", "TEXT"),
                    ("ai_strategy", "TEXT"),
                    ("ai_projects", "TEXT"),
                    ("ai_team_lead", "VARCHAR(255)"),
                    ("ai_news", "TEXT"),
                    ("ai_maturity_rationale", "TEXT"),
                    ("has_about", "BOOLEAN DEFAULT FALSE"),
                    ("has_mission", "BOOLEAN DEFAULT FALSE"),
                    ("has_vision", "BOOLEAN DEFAULT FALSE"),
                    ("has_leadership_page", "BOOLEAN DEFAULT FALSE"),
                    ("has_programs", "BOOLEAN DEFAULT FALSE"),
                    ("has_donate", "BOOLEAN DEFAULT FALSE"),
                    ("has_annual_report", "BOOLEAN DEFAULT FALSE"),
                    ("has_financial_report", "BOOLEAN DEFAULT FALSE"),
                    ("has_impact_report", "BOOLEAN DEFAULT FALSE"),
                    ("has_partner_page", "BOOLEAN DEFAULT FALSE"),
                    ("has_jobs", "BOOLEAN DEFAULT FALSE"),
                    ("has_events", "BOOLEAN DEFAULT FALSE"),
                    ("has_resources", "BOOLEAN DEFAULT FALSE"),
                    ("has_sermons", "BOOLEAN DEFAULT FALSE"),
                    ("has_podcast", "BOOLEAN DEFAULT FALSE"),
                    ("has_video", "BOOLEAN DEFAULT FALSE"),
                    ("has_blog", "BOOLEAN DEFAULT FALSE"),
                    ("has_press", "BOOLEAN DEFAULT FALSE"),
                    ("has_privacy", "BOOLEAN DEFAULT FALSE"),
                    ("has_contact", "BOOLEAN DEFAULT FALSE"),
                    ("data_sources_json", "TEXT"),
                ],
            )

            conn.execute(text("UPDATE organization_profiles SET url_tier = 'C' WHERE url_tier IS NULL OR url_tier = ''"))
            conn.execute(
                text("UPDATE organization_profiles SET priority_tier = 'T3' WHERE priority_tier IS NULL OR priority_tier = ''")
            )

        if "leader_candidates" in table_names:
            _ensure_missing_columns(
                conn,
                inspector,
                "leader_candidates",
                [
                    ("candidate_bio", "TEXT"),
                    ("source_url", "VARCHAR(500)"),
                    ("extraction_method", "VARCHAR(32)"),
                    ("confidence", "FLOAT DEFAULT 0.5"),
                    ("status", "VARCHAR(32) DEFAULT 'pending'"),
                    ("validation_notes", "TEXT"),
                    ("reviewed_by", "VARCHAR(255)"),
                    ("reviewed_at", "TIMESTAMP NULL"),
                    ("approved_leader_id", "VARCHAR(255)"),
                    ("created_at", "TIMESTAMP NULL"),
                    ("updated_at", "TIMESTAMP NULL"),
                ],
            )
