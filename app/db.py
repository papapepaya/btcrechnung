import json
import os
import sqlite3
import sys

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(os.path.dirname(sys.executable), 'data')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_DIR = os.path.dirname(BASE_DIR)
    DATA_DIR = os.path.join(PROJECT_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "btcrechnung.db")


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=10000;")
    return con


def init_schema(con: sqlite3.Connection | None = None):
    own = con is None
    if own:
        con = connect()
    try:
        con.execute("CREATE TABLE IF NOT EXISTS kv_settings (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS expenses (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS counters (year INTEGER PRIMARY KEY, last_number INTEGER NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, address TEXT DEFAULT '', created TEXT DEFAULT '', updated TEXT DEFAULT '')")
        con.execute("CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, updated TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS recurring (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS bank_tx (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS cashbook (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS quotes (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS timelog (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)")
    finally:
        if own:
            con.close()


def db_exists() -> bool:
    return os.path.exists(DB_PATH)


def is_empty(con: sqlite3.Connection) -> bool:
    for tbl in ("invoices", "expenses"):
        try:
            row = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            if row and row[0] > 0:
                return False
        except Exception:
            return True
    return True
