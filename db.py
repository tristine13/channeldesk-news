"""PostgreSQL (Supabase) helpers for the public news site. Same database as The Channel Desk.

Connection string comes from POSTGRES_URL (set automatically by the Supabase integration on
Vercel; use the pooled/transaction URL there) or DATABASE_URL for local work.
"""
import os

import psycopg
from flask import g
from psycopg.rows import dict_row


def _dsn():
    url = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Set POSTGRES_URL (or DATABASE_URL) to your Supabase connection string.")
    # psycopg does not understand the pgbouncer/supa query flags the integration may append
    return url.split("?")[0] if "supa=" in url else url


def get_db():
    if "db" not in g:
        g.db = psycopg.connect(
            _dsn(),
            row_factory=dict_row,
            autocommit=True,
            prepare_threshold=None,      # required behind Supabase's transaction pooler
            sslmode="require",
        )
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    with get_db().cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    """Run a write. If the statement ends with RETURNING id, that id is returned."""
    with get_db().cursor() as cur:
        cur.execute(sql, args)
        if cur.description:
            row = cur.fetchone()
            return next(iter(row.values())) if row else None
        return None
