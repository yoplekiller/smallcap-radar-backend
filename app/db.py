"""공유 PostgreSQL 엔진.

DATABASE_URL 환경변수가 있으면 PostgreSQL 모드, 없으면 None (로컬 파일 폴백).
모든 서비스가 이 모듈의 engine / USE_DB 를 공유한다.
"""
import os

from dotenv import load_dotenv

load_dotenv()

engine = None
USE_DB = False

_db_url = os.getenv("DATABASE_URL", "")

if _db_url:
    from sqlalchemy import create_engine, text

    _url = _db_url
    if _url.startswith("postgres://"):
        _url = "postgresql+psycopg2://" + _url[len("postgres://"):]
    elif _url.startswith("postgresql://"):
        _url = "postgresql+psycopg2://" + _url[len("postgresql://"):]

    engine = create_engine(_url, pool_pre_ping=True, pool_size=3, max_overflow=5)

    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    rcept_no  TEXT PRIMARY KEY,
                    data      JSONB        NOT NULL,
                    cached_at TIMESTAMPTZ  DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                    endpoint   TEXT PRIMARY KEY,
                    sub_data   JSONB        NOT NULL,
                    created_at TIMESTAMPTZ  DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id           TEXT PRIMARY KEY,
                    rcept_no     TEXT        NOT NULL,
                    rule_id      TEXT        NOT NULL,
                    data         JSONB       NOT NULL,
                    triggered_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS alert_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """))
        USE_DB = True
        print("[db] PostgreSQL 연결 완료, 테이블 준비됨")
    except Exception as e:
        print(f"[db] 초기화 실패, 파일 모드로 동작: {e}")
        engine = None
