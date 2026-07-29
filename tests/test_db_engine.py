"""The DB engine must be bounded against a dead SSH tunnel (Postgres) without breaking SQLite.

Regression for a 10h silent stall: the background ingester hung on a half-open socket when the
staging tunnel died, because the engine had no connect_timeout / TCP keepalives / statement_timeout.
"""
from app.data.db import _engine_kwargs


def test_postgres_engine_is_bounded_against_dead_tunnel():
    kw = _engine_kwargs("postgresql+psycopg2://u:p@localhost:5433/db")
    ca = kw["connect_args"]
    assert ca["connect_timeout"] == 10          # initial connect can't block forever
    assert ca["keepalives"] == 1                # detect a silently-dropped peer...
    assert ca["keepalives_idle"] <= 60          # ...in ~a minute, not the OS default ~2h
    assert "statement_timeout" in ca["options"]  # no single query blocks indefinitely
    assert kw["pool_pre_ping"] is True


def test_sqlite_engine_takes_no_libpq_connect_args():
    # libpq keepalives/connect_timeout are invalid for SQLite — tests must not get them
    kw = _engine_kwargs("sqlite:///" + "/tmp/x.db")
    assert "connect_args" not in kw
    assert kw["pool_pre_ping"] is True
