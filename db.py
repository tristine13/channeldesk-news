"""MySQL helpers for the public news site. Same database as The Channel Desk."""
import os

import pymysql
import pymysql.cursors
from flask import g


def get_db():
    if "db" not in g:
        g.db = pymysql.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3307")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "channeldesk"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            charset="utf8mb4",
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
    with get_db().cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid
