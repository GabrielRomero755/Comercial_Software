# db/migrator.py
# -----------------------------------------------------------
# Runner de migraciones SQLite (CLI opcional)
# - Aplica .sql en db/migrations/ en orden.
# - Registra en schema_migrations.filename.
# - Tolerante a scripts con/ sin BEGIN/COMMIT.
# -----------------------------------------------------------

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Set, List

MIGRATION_FILE_RE = re.compile(r"^\d+_.+\.sql$", re.IGNORECASE)

def _ensure_schema_migrations_table(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            filename     TEXT    UNIQUE NOT NULL,
            applied_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

def _get_applied_migrations(conn) -> Set[str]:
    try:
        cur = conn.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}
    except Exception:
        return set()

def _list_migration_files(migrations_dir: Path) -> List[Path]:
    if not migrations_dir.exists() or not migrations_dir.is_dir():
        return []
    files = [p for p in migrations_dir.iterdir() if p.is_file() and MIGRATION_FILE_RE.match(p.name)]
    files.sort(key=lambda p: p.name.lower())
    return files

def _read_sql(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

import re as _re

def _exec_sql_script_tolerant(conn, sql_text: str) -> None:
    has_begin = _re.search(r'^\s*BEGIN\b', sql_text, _re.I | _re.M) is not None
    if has_begin:
        old_iso = conn.isolation_level
        conn.isolation_level = None
        try:
            conn.executescript(sql_text)
        finally:
            conn.isolation_level = old_iso
    else:
        sql_text_clean = _re.sub(r'^\s*(COMMIT|ROLLBACK)\s*;?\s*$', '', sql_text, flags=_re.I | _re.M)
        conn.execute("BEGIN;")
        try:
            conn.executescript(sql_text_clean)
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise

def apply_all_migrations(conn, migrations_dir: str | os.PathLike) -> int:
    migrations_path = Path(migrations_dir)
    _ensure_schema_migrations_table(conn)
    applied = _get_applied_migrations(conn)
    pending_files = [p for p in _list_migration_files(migrations_path) if p.name not in applied]

    applied_count = 0
    for path in pending_files:
        sql = _read_sql(path)
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            _exec_sql_script_tolerant(conn, sql)
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))
            if conn.isolation_level is not None:
                conn.commit()
            applied_count += 1
            print(f"[migrator] OK  {path.name}")
        except Exception as e:
            try:
                if conn.isolation_level is not None:
                    conn.rollback()
            except Exception:
                pass
            print(f"[migrator] ERR {path.name}: {e}")
            break
    return applied_count

if __name__ == "__main__":
    from db.database import get_connection  # import tardío

    try:
        from ui.helpers import resource_path
        migrations_dir = resource_path("db", "migrations")
    except Exception:
        migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")

    with get_connection() as _conn:
        n = apply_all_migrations(_conn, migrations_dir)
        print(f"[migrator] Migraciones aplicadas: {n}")
        if n == 0:
            print("[migrator] No hay migraciones pendientes.")
