# db/database.py
# -----------------------------------------------------------
# Acceso a base de datos (SQLite) con:
#   - get_connection(): conexión con PRAGMAs seguros.
#   - init_db(): aplica esquema base (schema.sql o init_db.sql) y migraciones.
#   - run_migrations(): ejecuta db/migrations/*.sql en orden, idempotente.
#   - Helpers: obtener_tablas_existentes(), tabla_existe(), get_db_path().
#
# CAMBIOS CLAVE
# -----------------------------------------------------------
# - Ruta de BD en directorio de datos del usuario (escribible):
#     * Windows: %APPDATA%\SistemaComercio\datos_comercio.db
#     * Linux:   ~/.local/share/SistemaComercio/datos_comercio.db
# - Esquema consolidado en db/schema.sql (si existe). Fallback a db/init_db.sql.
# - Sistema de migraciones (db/migrations/*.sql) con tabla schema_migrations.
# -----------------------------------------------------------

from __future__ import annotations

import os
import sys
import sqlite3
import platform
from pathlib import Path
from typing import Iterable, List, Set

# resource_path desde ui.helpers (compatible con PyInstaller)
try:
    from ui.helpers import resource_path
except Exception:
    def resource_path(*relative_parts: str) -> str:
        base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        return os.path.normpath(os.path.join(base_path, *relative_parts))


# -----------------------------------------------------------
# Ubicación de la BD (directorio de datos del usuario)
# -----------------------------------------------------------
APP_DIR_NAME = "SistemaComercio"
DB_FILENAME  = "datos_comercio.db"


def _user_data_dir() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(base) / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        return Path(base) / APP_DIR_NAME


DB_DIR  = _user_data_dir()
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / DB_FILENAME


# -----------------------------------------------------------
# Conexión
# -----------------------------------------------------------
def get_connection(timeout: float = 10.0) -> sqlite3.Connection:
    """
    Retorna una conexión SQLite con:
      - PRAGMA foreign_keys=ON
      - row_factory=sqlite3.Row
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=timeout, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")
    # Recomendables; descomenta si deseas:
    # cur.execute("PRAGMA journal_mode = WAL;")
    # cur.execute("PRAGMA synchronous = NORMAL;")
    # cur.execute("PRAGMA temp_store = MEMORY;")
    # cur.execute("PRAGMA cache_size = -20000;")  # ~20MB
    cur.close()
    return conn


def get_db_path() -> Path:
    """Devuelve la ruta absoluta al archivo de base de datos."""
    return DB_PATH


# -----------------------------------------------------------
# Inicialización y migraciones
# -----------------------------------------------------------
def _read_text_file(path: str | Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename  TEXT UNIQUE NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)


def _list_applied_migrations(conn: sqlite3.Connection) -> Set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {r["filename"] for r in rows}


def _discover_migration_files() -> List[Path]:
    """
    Devuelve la lista ordenada de archivos .sql dentro de db/migrations.
    El orden es lexicográfico; se recomienda prefijar con 0001_, 0002_, ...
    """
    mig_dir = Path(resource_path("db", "migrations"))
    if not mig_dir.exists() or not mig_dir.is_dir():
        return []
    files = [p for p in mig_dir.iterdir() if p.is_file() and p.suffix.lower() == ".sql" and not p.name.startswith(".")]
    files.sort(key=lambda p: p.name)
    return files


def _apply_schema_if_needed(conn: sqlite3.Connection) -> None:
    """
    Si la BD está vacía (sin tablas de usuario), aplica schema.sql (o init_db.sql).
    """
    user_tables = _user_tables(conn)
    if user_tables:
        return  # Ya hay tablas; no pisar.

    schema_path = Path(resource_path("db", "schema.sql"))
    legacy_init = Path(resource_path("db", "init_db.sql"))

    if schema_path.exists():
        script = _read_text_file(schema_path)
        _apply_in_tx(conn, script, label="schema.sql")
    elif legacy_init.exists():
        script = _read_text_file(legacy_init)
        _apply_in_tx(conn, script, label="init_db.sql (legacy)")
    else:
        raise FileNotFoundError("No se encontró db/schema.sql ni db/init_db.sql para inicializar la base.")


def _apply_in_tx(conn: sqlite3.Connection, script: str, label: str = "") -> None:
    """
    Ejecuta un script SQL completo dentro de una transacción.
    """
    cur = conn.cursor()
    try:
        cur.execute("BEGIN;")
        conn.executescript(script)
        cur.execute("COMMIT;")
        if label:
            print(f"[OK] Aplicado: {label}")
    except Exception:
        try:
            cur.execute("ROLLBACK;")
        except Exception:
            pass
        raise
    finally:
        cur.close()


def run_migrations(verbose: bool = True) -> None:
    """
    Aplica las migraciones incrementales en db/migrations/*.sql.
    Cada archivo se registra en schema_migrations para evitar re-aplicación.
    Transacción por archivo (BEGIN/COMMIT; ROLLBACK en error).
    """
    with get_connection() as conn:
        _ensure_migrations_table(conn)
        applied = _list_applied_migrations(conn)
        pending = [p for p in _discover_migration_files() if p.name not in applied]

        if verbose:
            print(f"[DB] Migraciones aplicadas: {len(applied)} | Pendientes: {len(pending)}")

        for path in pending:
            script = _read_text_file(path)
            cur = conn.cursor()
            try:
                cur.execute("BEGIN;")
                conn.executescript(script)
                cur.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))
                cur.execute("COMMIT;")
                if verbose:
                    print(f"[migrate] OK  {path.name}")
            except Exception as e:
                try:
                    cur.execute("ROLLBACK;")
                except Exception:
                    pass
                print(f"[migrate] ERR {path.name}: {e}")
                # Detenemos para inspección manual si algo falla
                break
            finally:
                cur.close()

        if pending and verbose:
            print("[DB] Migraciones completadas.")


def init_db() -> None:
    """
    Inicializa la base:
      1) Crea carpeta de datos si no existe.
      2) Aplica esquema base si la BD está vacía.
      3) Aplica migraciones incrementales (si hay).
    """
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[ERROR] No se pudo asegurar el directorio de datos: {DB_DIR}\n{e}")
        return

    db_nueva = not DB_PATH.exists()
    if db_nueva:
        print("[DB] Creando nueva base de datos…")

    try:
        with get_connection() as conn:
            _apply_schema_if_needed(conn)
        run_migrations(verbose=True)
        print("[OK] Base de datos lista.")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
    except Exception as e:
        print(f"[ERROR] Falló la inicialización de la base de datos: {e}")


# -----------------------------------------------------------
# Helpers de inspección
# -----------------------------------------------------------
def _user_tables(conn: sqlite3.Connection) -> List[str]:
    """
    Devuelve tablas de usuario (excluye sqlite_* y schema_migrations).
    """
    rows = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
          AND name != 'schema_migrations'
    """).fetchall()
    return [r["name"] for r in rows]


def obtener_tablas_existentes() -> List[str]:
    """
    Lista todas las tablas (incluye schema_migrations; excluye sqlite_*).
    """
    try:
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """).fetchall()
            return [r["name"] for r in rows]
    except Exception as e:
        print(f"[ERROR] No se pudieron obtener las tablas: {e}")
        return []


def tabla_existe(nombre_tabla: str) -> bool:
    try:
        with get_connection() as conn:
            row = conn.execute("""
                SELECT 1
                FROM sqlite_master
                WHERE type='table' AND name = ?
                LIMIT 1
            """, (nombre_tabla,)).fetchone()
            return row is not None
    except Exception:
        return False
