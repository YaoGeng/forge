"""engine/session 工厂：SQLite v1 载体（D-M1E.1），路径注入；WAL + busy_timeout 缓解单机并发写竞争。"""
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def make_engine(db_url: str) -> Engine:
    kwargs: dict = {}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(db_url, **kwargs)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        if not db_url.startswith("sqlite"):
            return
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine
