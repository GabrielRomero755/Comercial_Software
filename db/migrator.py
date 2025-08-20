# -----------------------------------------------------------
# Runner de migraciones SQLite
# - Aplica archivos .sql en db/migrations/ en orden ascendente.
# - Registra cada archivo aplicado en schema_migrations.
# - Transaccional por archivo (BEGIN/COMMIT/ROLLBACK).
# - Seguro para re-ejecución (idempotente por registro).
# -----------------------------------------------------------

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Set, List, Optional

# Nota: NO importamos db.database a nivel módulo para evitar ciclos.
#       database.py importará este módulo dentro de init_db().

MIGRATION_FILE_RE = re.compile(r"^\d+_.+\.sql$", re.IGNORECASE)


def _ensure_schema_migrations_table(conn) -> None:
    """Crea la tabla de registro de migraciones, si no existe."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_id TEXT    UNIQUE NOT NULL,
            applied_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()


def _get_applied_migrations(conn) -> Set[str]:
    try:
        cur = conn.execute("SELECT migration_id FROM schema_migrations")
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


def apply_all_migrations(conn, migrations_dir: str | os.PathLike) -> int:
    """
    Aplica todas las migraciones pendientes encontradas en 'migrations_dir'.
    Retorna el número de migraciones aplicadas en esta ejecución.
    """
    migrations_path = Path(migrations_dir)
    _ensure_schema_migrations_table(conn)

    applied = _get_applied_migrations(conn)
    pending_files = [p for p in _list_migration_files(migrations_path) if p.name not in applied]

    applied_count = 0
    for path in pending_files:
        sql = _read_sql(path)
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("BEGIN;")
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (migration_id) VALUES (?)", (path.name,))
            conn.execute("COMMIT;")
            applied_count += 1
            print(f"[migrator] OK  {path.name}")
        except Exception as e:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            print(f"[migrator] ERR {path.name}: {e}")
            # Rompemos para que el operador pueda revisar el error
            break

    return applied_count


if __name__ == "__main__":
    # Uso CLI opcional: ejecuta migraciones contra la BD por defecto del proyecto
    from db.database import get_connection  # import tardío para evitar ciclo

    # Intentamos localizar la carpeta de migraciones relativa al paquete
    try:
        from ui.helpers import resource_path  # para builds con PyInstaller
        migrations_dir = resource_path("db", "migrations")
    except Exception:
        migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")

    with get_connection() as _conn:
        n = apply_all_migrations(_conn, migrations_dir)
        print(f"[migrator] Migraciones aplicadas: {n}")
        if n == 0:
            print("[migrator] No hay migraciones pendientes.")