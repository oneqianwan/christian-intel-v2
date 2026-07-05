import json
import os
import shutil
import sqlite3
import stat
import threading
import time
import traceback
import uuid

from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, Column, String, Date, DateTime, Text, JSON, Float, Boolean, Integer, ForeignKey, UniqueConstraint, Index, inspect, text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Session as SASession, relationship, sessionmaker
from sqlalchemy.pool import NullPool
from datetime import datetime
from config import settings

_IS_SQLITE = settings.DATABASE_URL.startswith("sqlite:///")
_ENGINE_KWARGS = {"pool_pre_ping": True}
if _IS_SQLITE:
    _ENGINE_KWARGS.update(
        {
            "connect_args": {"check_same_thread": False, "timeout": 5},
            "poolclass": NullPool,
        }
    )
else:
    _ENGINE_KWARGS.update(
        {
            "pool_size": 20,
            "max_overflow": 30,
            "pool_timeout": 5,
            "pool_recycle": 3600,
        }
    )

engine = create_engine(settings.DATABASE_URL, **_ENGINE_KWARGS)

_INIT_DB_ACTIVE = False
_INIT_DB_LAST_SQL = ""
_ACTIVE_SESSION_LOCK = threading.Lock()
_ACTIVE_SESSIONS: dict[int, dict] = {}
_ACTIVE_SESSION_COUNT = 0
_ENGINE_CONFIG_PRINTED = False
_SESSION_LIFETIME_MAX: dict = {}
_FIRST_POOL_UNAVAILABLE: dict = {}
_DO_CONNECT_ENTER_TS: dict[int, float] = {}


def _safe_print_line(label: str, value):
    try:
        if isinstance(value, (dict, list, tuple, set)):
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        else:
            rendered = str(value)
        print(f"{label}={rendered}")
    except Exception:
        pass


def _resolve_sqlite_db_path():
    if not settings.DATABASE_URL.startswith("sqlite:///"):
        return None
    raw_path = settings.DATABASE_URL.replace("sqlite:///", "", 1)
    return Path(raw_path)


def _read_sqlite_pragma_value(pragma_name: str):
    db_path = _resolve_sqlite_db_path()
    if db_path is None:
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=1)
        cur = conn.cursor()
        value = cur.execute(f"PRAGMA {pragma_name}").fetchone()
        cur.close()
        conn.close()
        return value[0] if value else None
    except Exception as exc:
        return f"ERROR:{exc}"


def _engine_config_payload() -> dict:
    connect_args = dict(_ENGINE_KWARGS.get("connect_args") or {})
    return {
        "DATABASE_URL": settings.DATABASE_URL,
        "POOL_CLASS": engine.pool.__class__.__name__,
        "POOL_SIZE": _ENGINE_KWARGS.get("pool_size"),
        "MAX_OVERFLOW": _ENGINE_KWARGS.get("max_overflow"),
        "POOL_TIMEOUT": _ENGINE_KWARGS.get("pool_timeout"),
        "CONNECT_ARGS": connect_args,
        "CHECK_SAME_THREAD": connect_args.get("check_same_thread"),
        "SQLITE_TIMEOUT": connect_args.get("timeout"),
        "JOURNAL_MODE": _read_sqlite_pragma_value("journal_mode") if _IS_SQLITE else None,
        "BUSY_TIMEOUT": _read_sqlite_pragma_value("busy_timeout") if _IS_SQLITE else None,
    }


def _emit_engine_config_once():
    global _ENGINE_CONFIG_PRINTED
    if _ENGINE_CONFIG_PRINTED:
        return
    _ENGINE_CONFIG_PRINTED = True
    _safe_print_line("ENGINE_CONFIG", _engine_config_payload())


def _capture_session_origin() -> dict:
    stack = traceback.extract_stack(limit=40)
    selected = None
    for frame in reversed(stack[:-2]):
        filename = str(frame.filename).replace("\\", "/")
        if filename.endswith("/backend/models/database.py") or "site-packages/sqlalchemy" in filename:
            continue
        selected = frame
        break
    if selected is None and stack:
        selected = stack[-2]
    stack_text = "".join(traceback.format_list(stack[:-1]))
    filename = str(getattr(selected, "filename", "") or "")
    return {
        "file": filename,
        "function": str(getattr(selected, "name", "") or ""),
        "line": int(getattr(selected, "lineno", 0) or 0),
        "stack": stack_text,
        "streaming_response_held": (
            "chat.py" in filename.replace("\\", "/")
            and "chat_stream" in stack_text
            and "StreamingResponse" in stack_text
        )
        or ("chat.py" in filename.replace("\\", "/") and "chat_stream" in stack_text),
    }


def _current_active_session_count() -> int:
    with _ACTIVE_SESSION_LOCK:
        return int(_ACTIVE_SESSION_COUNT)


def _oldest_active_session_snapshot() -> dict:
    with _ACTIVE_SESSION_LOCK:
        if not _ACTIVE_SESSIONS:
            return {}
        session_id, meta = min(_ACTIVE_SESSIONS.items(), key=lambda item: float(item[1].get("created_at_perf") or 0.0))
        snapshot = dict(meta)
        snapshot["session_id"] = session_id
        snapshot["age_ms"] = round((time.perf_counter() - float(meta.get("created_at_perf") or time.perf_counter())) * 1000, 2)
        return snapshot


def _update_longest_lifetime(meta: dict, *, closed_at_perf: float):
    global _SESSION_LIFETIME_MAX
    lifetime_ms = round((closed_at_perf - float(meta.get("created_at_perf") or closed_at_perf)) * 1000, 2)
    current = float(_SESSION_LIFETIME_MAX.get("lifetime_ms") or 0.0)
    if lifetime_ms >= current:
        _SESSION_LIFETIME_MAX = {
            "file": meta.get("file"),
            "function": meta.get("function"),
            "line": meta.get("line"),
            "stack": meta.get("stack"),
            "streaming_response_held": bool(meta.get("streaming_response_held")),
            "lifetime_ms": lifetime_ms,
            "session_id": meta.get("session_id"),
        }


def record_pool_unavailable(*, file: str, function: str, line: int, reason: str):
    global _FIRST_POOL_UNAVAILABLE
    if _FIRST_POOL_UNAVAILABLE:
        return
    oldest = _oldest_active_session_snapshot()
    _FIRST_POOL_UNAVAILABLE = {
        "file": file,
        "function": function,
        "line": line,
        "reason": reason,
        "oldest_active_session": oldest,
    }
    _safe_print_line("FIRST_POOL_UNAVAILABLE", _FIRST_POOL_UNAVAILABLE)


def get_db_debug_summary() -> dict:
    oldest = _oldest_active_session_snapshot()
    longest = dict(_SESSION_LIFETIME_MAX or {})
    if oldest:
        oldest_candidate_age = float(oldest.get("age_ms") or 0.0)
        if oldest_candidate_age > float(longest.get("lifetime_ms") or 0.0):
            longest = {
                "file": oldest.get("file"),
                "function": oldest.get("function"),
                "line": oldest.get("line"),
                "stack": oldest.get("stack"),
                "streaming_response_held": bool(oldest.get("streaming_response_held")),
                "lifetime_ms": oldest_candidate_age,
                "session_id": oldest.get("session_id"),
            }
    return {
        "ENGINE_CONFIG": _engine_config_payload(),
        "ACTIVE_SESSION_COUNT": _current_active_session_count(),
        "longest_unclosed_session": longest,
        "first_pool_unavailable": dict(_FIRST_POOL_UNAVAILABLE or {}),
    }


class TrackedSession(SASession):
    def __init__(self, *args, **kwargs):
        _emit_engine_config_once()
        origin = _capture_session_origin()
        started = time.perf_counter()
        _safe_print_line("SESSIONLOCAL_ENTER", {k: origin.get(k) for k in ("file", "function", "line")})
        super().__init__(*args, **kwargs)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        session_id = id(self)
        meta = {
            "session_id": session_id,
            "created_at_perf": time.perf_counter(),
            "file": origin.get("file"),
            "function": origin.get("function"),
            "line": origin.get("line"),
            "stack": origin.get("stack"),
            "streaming_response_held": bool(origin.get("streaming_response_held")),
        }
        global _ACTIVE_SESSION_COUNT
        with _ACTIVE_SESSION_LOCK:
            _ACTIVE_SESSIONS[session_id] = meta
            _ACTIVE_SESSION_COUNT += 1
            active_count = _ACTIVE_SESSION_COUNT
        self._tracked_session_meta = meta
        _safe_print_line("SESSIONLOCAL_EXIT", {"session_id": session_id, "elapsed_ms": elapsed_ms})
        _safe_print_line("ACTIVE_SESSION_COUNT", active_count)

    def close(self):
        session_id = id(self)
        meta = getattr(self, "_tracked_session_meta", {}) or {}
        already_closed = bool(meta.get("closed"))
        if not already_closed:
            meta["closed"] = True
            _update_longest_lifetime(meta, closed_at_perf=time.perf_counter())
        try:
            return super().close()
        finally:
            global _ACTIVE_SESSION_COUNT
            with _ACTIVE_SESSION_LOCK:
                removed = _ACTIVE_SESSIONS.pop(session_id, None)
                if removed is not None:
                    _ACTIVE_SESSION_COUNT = max(0, _ACTIVE_SESSION_COUNT - 1)
                active_count = _ACTIVE_SESSION_COUNT
            _safe_print_line("ACTIVE_SESSION_COUNT", active_count)


def _db_io_debug(event_name: str, **payload):
    print(
        "DB_IO_DEBUG "
        + json.dumps(
            {
                "event": event_name,
                **payload,
            },
            ensure_ascii=False,
            default=str,
        )
    )


def _startup_debug(event_name: str, **payload):
    print(
        "INIT_DB_TRACE "
        + json.dumps(
            {
                "event": event_name,
                **payload,
            },
            ensure_ascii=False,
            default=str,
        )
    )


def _start_block_timer(
    *,
    file_name: str,
    function_name: str,
    line_no: int,
    sql_getter=None,
):
    def _emit_block_here():
        sql_text = ""
        if callable(sql_getter):
            try:
                sql_text = str(sql_getter() or "")
            except Exception as exc:
                sql_text = f"<sql_getter_error {exc!r}>"
        print("BLOCK HERE")
        print(f"函数={function_name}")
        print(f"文件={file_name}")
        print(f"行号={line_no}")
        print(f"SQL={sql_text}")

    timer = threading.Timer(3.0, _emit_block_here)
    timer.daemon = True
    timer.start()
    return timer


@contextmanager
def _trace_init_db_step(step_name: str, *, file_name: str, function_name: str, line_no: int, sql_getter=None):
    started_at = time.perf_counter()
    _startup_debug(
        "ENTER_STEP",
        step=step_name,
        file=file_name,
        function=function_name,
        line_no=line_no,
    )
    timer = _start_block_timer(
        file_name=file_name,
        function_name=function_name,
        line_no=line_no,
        sql_getter=sql_getter,
    )
    try:
        yield
    finally:
        timer.cancel()
        _startup_debug(
            "EXIT_STEP",
            step=step_name,
            file=file_name,
            function=function_name,
            line_no=line_no,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )


def _sqlite_file_debug_payload() -> dict:
    db_path = _resolve_sqlite_db_path()
    if db_path is None:
        return {
            "DB_PATH": None,
            "DB_EXISTS": False,
            "DB_WRITABLE": None,
            "DB_SIZE": None,
            "DB_READONLY": None,
            "WAL_MODE_FILE": None,
            "SHM_MODE_FILE": None,
            "OPEN_PROCESSES": [],
            "journal_mode": None,
            "locking_mode": None,
        }

    wal_path = db_path.parent / f"{db_path.name}-wal"
    shm_path = db_path.parent / f"{db_path.name}-shm"
    exists = db_path.exists()
    payload = {
        "DB_PATH": str(db_path.resolve()),
        "DB_EXISTS": exists,
        "DB_WRITABLE": os.access(db_path if exists else db_path.parent, os.W_OK),
        "DB_SIZE": db_path.stat().st_size if exists else None,
        "DB_READONLY": bool(exists and not (db_path.stat().st_mode & stat.S_IWRITE)),
        "WAL_MODE_FILE": wal_path.exists(),
        "SHM_MODE_FILE": shm_path.exists(),
        "OPEN_PROCESSES": [],
        "journal_mode": None,
        "locking_mode": None,
    }
    try:
        import psutil  # type: ignore

        target = str(db_path.resolve()).lower()
        hits = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                for opened in (proc.open_files() or []):
                    if str(Path(opened.path).resolve()).lower() == target:
                        hits.append({"pid": proc.info.get("pid"), "name": proc.info.get("name"), "path": opened.path})
            except Exception:
                continue
        payload["OPEN_PROCESSES"] = hits
    except Exception as exc:
        payload["OPEN_PROCESSES"] = [f"psutil_unavailable:{exc}"]
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        payload["journal_mode"] = cursor.execute("PRAGMA journal_mode").fetchone()[0]
        payload["locking_mode"] = cursor.execute("PRAGMA locking_mode").fetchone()[0]
        cursor.close()
        conn.close()
    except Exception as exc:
        payload["PRAGMA_EXCEPTION"] = repr(exc)
    return payload


def _sqlite_file_debug_payload_lightweight() -> dict:
    db_path = _resolve_sqlite_db_path()
    if db_path is None:
        return {
            "DB_PATH": None,
            "DB_EXISTS": False,
            "DB_WRITABLE": None,
            "DB_SIZE": None,
            "DB_READONLY": None,
            "WAL_MODE_FILE": None,
            "SHM_MODE_FILE": None,
            "OPEN_PROCESSES": "SKIPPED_DURING_INIT_DB",
            "journal_mode": "SKIPPED_DURING_INIT_DB",
            "locking_mode": "SKIPPED_DURING_INIT_DB",
        }
    exists = db_path.exists()
    wal_path = db_path.parent / f"{db_path.name}-wal"
    shm_path = db_path.parent / f"{db_path.name}-shm"
    return {
        "DB_PATH": str(db_path.resolve()),
        "DB_EXISTS": exists,
        "DB_WRITABLE": os.access(db_path if exists else db_path.parent, os.W_OK),
        "DB_SIZE": db_path.stat().st_size if exists else None,
        "DB_READONLY": bool(exists and not (db_path.stat().st_mode & stat.S_IWRITE)),
        "WAL_MODE_FILE": wal_path.exists(),
        "SHM_MODE_FILE": shm_path.exists(),
        "OPEN_PROCESSES": "SKIPPED_DURING_INIT_DB",
        "journal_mode": "SKIPPED_DURING_INIT_DB",
        "locking_mode": "SKIPPED_DURING_INIT_DB",
    }


def emit_db_runtime_debug(event_name: str, *, lightweight: bool | None = None, **payload):
    use_lightweight = _INIT_DB_ACTIVE if lightweight is None else lightweight
    debug_payload = _sqlite_file_debug_payload_lightweight() if use_lightweight else _sqlite_file_debug_payload()
    _db_io_debug(event_name, **debug_payload, **payload)


def _execute_sqlite_pragma_once(cursor, pragma_sql: str, *, source: str, skip_threshold_ms: float | None = None) -> bool:
    started = time.perf_counter()
    try:
        emit_db_runtime_debug("PRAGMA", lightweight=True, SQL=pragma_sql, source=source)
        cursor.execute(pragma_sql)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if skip_threshold_ms is not None and elapsed_ms > skip_threshold_ms:
            _safe_print_line(
                "PRAGMA_SKIPPED",
                {"source": source, "sql": pragma_sql, "elapsed_ms": elapsed_ms, "reason": "elapsed_over_threshold"},
            )
        return True
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        _safe_print_line(
            "PRAGMA_SKIPPED",
            {"source": source, "sql": pragma_sql, "elapsed_ms": elapsed_ms, "reason": repr(exc)},
        )
        return False


def _apply_startup_sqlite_pragmas() -> None:
    db_path = _resolve_sqlite_db_path()
    if db_path is None:
        return
    with _trace_init_db_step(
        "_apply_startup_sqlite_pragmas",
        file_name=__file__,
        function_name="init_db",
        line_no=1230,
        sql_getter=lambda: "PRAGMA synchronous=NORMAL / PRAGMA temp_store=MEMORY",
    ):
        conn = sqlite3.connect(str(db_path), timeout=1)
        try:
            cursor = conn.cursor()
            try:
                for pragma_sql in (
                    "PRAGMA synchronous=NORMAL",
                    "PRAGMA temp_store=MEMORY",
                ):
                    _execute_sqlite_pragma_once(cursor, pragma_sql, source="init_db", skip_threshold_ms=None)
            finally:
                cursor.close()
            conn.commit()
        finally:
            conn.close()

if settings.DATABASE_URL.startswith("sqlite:///"):
    @event.listens_for(engine, "do_connect", retval=True)
    def _sqlite_do_connect(dialect, conn_rec, cargs, cparams):
        connection_record_id = id(conn_rec)
        started = time.perf_counter()
        _DO_CONNECT_ENTER_TS[connection_record_id] = started
        _safe_print_line("DB_CONNECT_ENTER", {"connection_record_id": connection_record_id, "cargs": cargs, "cparams": cparams})
        try:
            dbapi_connection = dialect.loaded_dbapi.connect(*cargs, **cparams)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            _safe_print_line(
                "DB_CONNECT_EXIT",
                {"connection_record_id": connection_record_id, "connection_id": id(dbapi_connection), "elapsed_ms": elapsed_ms},
            )
            return dbapi_connection
        finally:
            _DO_CONNECT_ENTER_TS.pop(connection_record_id, None)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        connect_started = time.perf_counter()
        _safe_print_line(
            "DB_CONNECT_EVENT_ENTER",
            {"connection_id": id(dbapi_connection), "connection_record_id": id(connection_record)},
        )
        cursor = dbapi_connection.cursor()
        emit_db_runtime_debug(
            "connect()",
            lightweight=True,
            DB_CONNECTION=repr(dbapi_connection),
            connection_record_id=id(connection_record),
        )
        try:
            pragma_timer = _start_block_timer(
                file_name=__file__,
                function_name="_set_sqlite_pragmas",
                line_no=112,
                sql_getter=lambda: "PRAGMA busy_timeout=1000",
            )
            try:
                _execute_sqlite_pragma_once(
                    cursor,
                    "PRAGMA busy_timeout=1000",
                    source="_set_sqlite_pragmas",
                    skip_threshold_ms=500.0,
                )
            finally:
                pragma_timer.cancel()
        finally:
            cursor.close()
        _safe_print_line(
            "DB_CONNECT_EVENT_EXIT",
            {
                "connection_id": id(dbapi_connection),
                "connection_record_id": id(connection_record),
                "elapsed_ms": round((time.perf_counter() - connect_started) * 1000, 2),
            },
        )


    @event.listens_for(engine, "begin")
    def _sqlite_begin(conn):
        emit_db_runtime_debug("BEGIN", lightweight=True, DB_CONNECTION=repr(conn))

    @event.listens_for(engine, "commit")
    def _sqlite_commit(conn):
        emit_db_runtime_debug("COMMIT", lightweight=True, DB_CONNECTION=repr(conn))

    @event.listens_for(engine, "rollback")
    def _sqlite_rollback(conn):
        emit_db_runtime_debug("ROLLBACK", lightweight=True, DB_CONNECTION=repr(conn))

    @event.listens_for(engine.pool, "close")
    def _sqlite_close(dbapi_connection, connection_record):
        emit_db_runtime_debug(
            "close()",
            lightweight=True,
            DB_CONNECTION=repr(dbapi_connection),
            connection_record_id=id(connection_record),
        )

    @event.listens_for(engine.pool, "checkout")
    def _sqlite_checkout(dbapi_connection, connection_record, connection_proxy):
        _safe_print_line(
            "POOL_CHECKOUT",
            {
                "connection_id": id(dbapi_connection),
                "connection_record_id": id(connection_record),
                "ACTIVE_SESSION_COUNT": _current_active_session_count(),
            },
        )

    @event.listens_for(engine.pool, "checkin")
    def _sqlite_checkin(dbapi_connection, connection_record):
        _safe_print_line(
            "POOL_CHECKIN",
            {
                "connection_id": id(dbapi_connection) if dbapi_connection is not None else None,
                "connection_record_id": id(connection_record) if connection_record is not None else None,
                "ACTIVE_SESSION_COUNT": _current_active_session_count(),
            },
        )

    @event.listens_for(engine.pool, "invalidate")
    def _sqlite_invalidate(dbapi_connection, connection_record, exception):
        _safe_print_line(
            "POOL_INVALIDATE",
            {
                "connection_id": id(dbapi_connection) if dbapi_connection is not None else None,
                "connection_record_id": id(connection_record) if connection_record is not None else None,
                "exception": repr(exception),
                "ACTIVE_SESSION_COUNT": _current_active_session_count(),
            },
        )

    @event.listens_for(engine, "before_cursor_execute")
    def _sqlite_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        global _INIT_DB_LAST_SQL
        if not _INIT_DB_ACTIVE:
            return
        sql_text = " ".join(str(statement or "").split())
        _INIT_DB_LAST_SQL = sql_text
        context._init_db_sql_timer = _start_block_timer(
            file_name=__file__,
            function_name="before_cursor_execute",
            line_no=151,
            sql_getter=lambda: sql_text,
        )
        emit_db_runtime_debug(
            "SQL",
            SQL=sql_text,
            parameters=repr(parameters)[:1000],
            executemany=executemany,
        )

    @event.listens_for(engine, "after_cursor_execute")
    def _sqlite_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        timer = getattr(context, "_init_db_sql_timer", None)
        if timer is not None:
            timer.cancel()
        if _INIT_DB_ACTIVE:
            emit_db_runtime_debug(
                "SQL_DONE",
                SQL=" ".join(str(statement or "").split()),
                rowcount=getattr(cursor, "rowcount", None),
            )

_SessionLocalFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=TrackedSession)


def SessionLocal(*args, **kwargs):
    return _SessionLocalFactory(*args, **kwargs)
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
    digital_score_grade = Column(String(2), default="F")
    digital_score_dimensions = Column(Text, nullable=True)
    digital_score_calculated_at = Column(DateTime, nullable=True)
    intel_score = Column(Integer, default=0)
    intel_score_grade = Column(String(2), default="F")
    intel_score_dimensions = Column(Text, nullable=True)
    intel_score_calculated_at = Column(DateTime, nullable=True)
    people_score = Column(Integer, default=0)
    people_score_grade = Column(String(2), default="F")
    people_score_dimensions = Column(Text, nullable=True)
    people_score_calculated_at = Column(DateTime, nullable=True)
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
    __table_args__ = (
        Index("ix_missions_query_country_target_entity_status", "query", "country", "target_entity", "status"),
        Index("ix_missions_composite_task_id_status", "composite_task_id", "status"),
        Index("ix_missions_country_created_at", "country", "created_at"),
    )
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
    __table_args__ = (
        Index("ix_job_runs_mission_source_job_type_status", "mission_id", "source_id", "job_type", "status"),
        Index("ix_job_runs_mission_id", "mission_id"),
    )
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


class RelationEdge(Base):
    """统一存储机构、实体、投资方之间的关系边。"""

    __tablename__ = "relation_edges"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    source_id = Column(String, nullable=False, index=True)
    source_type = Column(String, default="organization")

    target_id = Column(String, nullable=False, index=True)
    target_type = Column(String, default="organization")

    relation_type = Column(String, nullable=False, index=True)
    confidence = Column(Float, default=0.8)

    source_item = Column(String, nullable=True)
    source_type_detail = Column(String, nullable=True)

    properties_json = Column(Text, nullable=True)

    # L7 Evidence Layer
    investment_amount = Column(String(50), nullable=True)
    investment_currency = Column(String(10), default="USD")
    investment_round = Column(String(30), nullable=True)
    evidence_url = Column(String(500), nullable=True)
    evidence_date = Column(Date, nullable=True)
    evidence_source = Column(String(255), nullable=True)
    is_verified = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "target_id",
            "relation_type",
            "source_item",
            name="uix_relation_edge_source_target_type_item",
        ),
    )


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 当前代码库没有 entities 表，这里兼容挂到现有 knowledge_entities。
    entity_id = Column(String, ForeignKey("knowledge_entities.id", ondelete="SET NULL"), nullable=True)
    mission_id = Column(String, ForeignKey("missions.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    priority = Column(String(20), nullable=True, default="medium")
    status = Column(String(20), nullable=True, default="pending")
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


from models.watch_alert import Alert, AlertRule, Signal, WatchRun, WatchTarget  # noqa: E402,F401


def get_db():
    db = SessionLocal()
    emit_db_runtime_debug(
        "get_db()",
        lightweight=True,
        DB_CONNECTION=repr(getattr(db, "bind", None)),
        session_id=id(db),
    )
    print("DB Connected=True")
    try:
        yield db
    finally:
        emit_db_runtime_debug(
            "get_db().close()",
            lightweight=True,
            DB_CONNECTION=repr(getattr(db, "bind", None)),
            session_id=id(db),
        )
        db.close()


def get_db_session():
    return SessionLocal()

def init_db():
    global _INIT_DB_ACTIVE, _INIT_DB_LAST_SQL
    _INIT_DB_ACTIVE = True
    _INIT_DB_LAST_SQL = ""
    _startup_debug("ENTER init_db", file=__file__, function="init_db", line_no=778)
    try:
        with _trace_init_db_step(
            "_resolve_sqlite_db_path",
            file_name=__file__,
            function_name="init_db",
            line_no=779,
        ):
            db_path = _resolve_sqlite_db_path()
        if db_path:
            print(f"[DB] SQLite path: {db_path}")
            with _trace_init_db_step(
                "_backup_sqlite_db",
                file_name=__file__,
                function_name="init_db",
                line_no=783,
            ):
                try:
                    backup_info = _backup_sqlite_db(db_path)
                    if backup_info:
                        latest_backup, dated_backup = backup_info
                        print(f"[DB] Latest backup refreshed: {latest_backup}")
                        if dated_backup:
                            print(f"[DB] Daily backup created: {dated_backup}")
                except Exception as exc:
                    print(f"[DB] Backup skipped: {exc}")
            _apply_startup_sqlite_pragmas()
        with _trace_init_db_step(
            "Base.metadata.create_all",
            file_name=__file__,
            function_name="init_db",
            line_no=791,
            sql_getter=lambda: _INIT_DB_LAST_SQL,
        ):
            Base.metadata.create_all(bind=engine)
        with _trace_init_db_step(
            "_ensure_schema_compatibility",
            file_name=__file__,
            function_name="init_db",
            line_no=792,
            sql_getter=lambda: _INIT_DB_LAST_SQL,
        ):
            _ensure_schema_compatibility()
    finally:
        _INIT_DB_ACTIVE = False
        _startup_debug("EXIT init_db", file=__file__, function="init_db", line_no=792)


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


def _ensure_indexes(conn, inspector, table_name: str, indexes: list[tuple[str, tuple[str, ...]]]) -> None:
    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    for index_name, columns in indexes:
        if index_name in existing_indexes:
            continue
        column_sql = ", ".join(columns)
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_sql})"))
        existing_indexes.add(index_name)


def _ensure_schema_compatibility():
    is_sqlite = engine.dialect.name == "sqlite"

    with _trace_init_db_step(
        "engine.begin",
        file_name=__file__,
        function_name="_ensure_schema_compatibility",
        line_no=856,
        sql_getter=lambda: _INIT_DB_LAST_SQL,
    ):
        conn_ctx = engine.begin()
        conn = conn_ctx.__enter__()
    try:
        with _trace_init_db_step(
            "inspect(conn)",
            file_name=__file__,
            function_name="_ensure_schema_compatibility",
            line_no=857,
            sql_getter=lambda: _INIT_DB_LAST_SQL,
        ):
            inspector = inspect(conn)
        with _trace_init_db_step(
            "inspector.get_table_names",
            file_name=__file__,
            function_name="_ensure_schema_compatibility",
            line_no=858,
            sql_getter=lambda: _INIT_DB_LAST_SQL,
        ):
            table_names = set(inspector.get_table_names())
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
            _ensure_indexes(
                conn,
                inspector,
                "missions",
                [
                    ("ix_missions_query_country_target_entity_status", ("query", "country", "target_entity", "status")),
                    ("ix_missions_composite_task_id_status", ("composite_task_id", "status")),
                    ("ix_missions_country_created_at", ("country", "created_at")),
                ],
            )

        if "job_runs" in table_names:
            _ensure_indexes(
                conn,
                inspector,
                "job_runs",
                [
                    ("ix_job_runs_mission_source_job_type_status", ("mission_id", "source_id", "job_type", "status")),
                    ("ix_job_runs_mission_id", ("mission_id",)),
                ],
            )

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

        if "tasks" in table_names:
            task_columns = {column["name"] for column in inspector.get_columns("tasks")}
            if "mission_id" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN mission_id VARCHAR NULL"))

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
                    ("digital_score_grade", "VARCHAR(2) DEFAULT 'F'"),
                    ("digital_score_dimensions", "TEXT"),
                    ("digital_score_calculated_at", "TIMESTAMP NULL"),
                    ("intel_score", "INTEGER DEFAULT 0"),
                    ("intel_score_grade", "VARCHAR(2) DEFAULT 'F'"),
                    ("intel_score_dimensions", "TEXT"),
                    ("intel_score_calculated_at", "TIMESTAMP NULL"),
                    ("people_score", "INTEGER DEFAULT 0"),
                    ("people_score_grade", "VARCHAR(2) DEFAULT 'F'"),
                    ("people_score_dimensions", "TEXT"),
                    ("people_score_calculated_at", "TIMESTAMP NULL"),
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

        if "relation_edges" in table_names:
            _ensure_missing_columns(
                conn,
                inspector,
                "relation_edges",
                [
                    ("investment_amount", "VARCHAR(50)"),
                    ("investment_currency", "VARCHAR(10) DEFAULT 'USD'"),
                    ("investment_round", "VARCHAR(30)"),
                    ("evidence_url", "VARCHAR(500)"),
                    ("evidence_date", "DATE"),
                    ("evidence_source", "VARCHAR(255)"),
                    ("is_verified", "BOOLEAN DEFAULT FALSE"),
                ],
            )
    finally:
        with _trace_init_db_step(
            "engine.begin.__exit__",
            file_name=__file__,
            function_name="_ensure_schema_compatibility",
            line_no=1286,
            sql_getter=lambda: _INIT_DB_LAST_SQL,
        ):
            conn_ctx.__exit__(None, None, None)
