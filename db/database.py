# db/database.py
# -----------------------------------------------------------
# Acceso a base de datos (SQLite) con:
#   - get_connection(): conexión con PRAGMAs seguros.
#   - init_db(): aplica esquema base (schema.sql o init_db.sql) y migraciones.
#   - run_migrations(): ejecuta db/migrations/*.sql en orden, idempotente.
#   - Helpers de fechas: db_now(), to_iso(), parse_iso().
#   - Decimal <-> NUMERIC(10,2): adaptadores/convertidores registrados.
#   - Utilidades transaccionales: with_tx(), execute_script().
#   - Helpers: obtener_tablas_existentes(), tabla_existe(), get_db_path().
#
# CAMBIOS CLAVE
# -----------------------------------------------------------
# - Runner de migraciones tolerante a scripts con/ sin BEGIN/COMMIT.
# - Unificación de schema_migrations (columna 'filename').
# - Esquema consolidado en db/schema.sql (fallback a db/init_db.sql).
# -----------------------------------------------------------

from __future__ import annotations

import os
import sys
import sqlite3
import platform
from pathlib import Path
from typing import Iterator, List, Set
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext

# ===========================================================
# Decimal y adaptadores
# ===========================================================
getcontext().prec = 28
_MONEY_QUANT = Decimal("0.01")

def money(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    q = value if isinstance(value, Decimal) else Decimal(str(value))
    return q.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

sqlite3.register_adapter(Decimal, lambda d: str(money(d)))

def _decimal_converter(b: bytes) -> Decimal:
    s = b.decode("utf-8") if isinstance(b, (bytes, bytearray)) else str(b)
    if s == "" or s is None:
        return Decimal("0.00")
    return money(s)

sqlite3.register_converter("DECIMAL", _decimal_converter)
sqlite3.register_converter("NUMERIC", _decimal_converter)
sqlite3.register_converter("MONEY", _decimal_converter)

# ===========================================================
# Fechas y formato
# ===========================================================
ISO_LOCAL_FMT = "%Y-%m-%d %H:%M:%S"

def db_now() -> str:
    return datetime.now().strftime(ISO_LOCAL_FMT)

def to_iso(dt: datetime | None) -> str:
    if dt is None:
        dt = datetime.now()
    return dt.strftime(ISO_LOCAL_FMT)

def parse_iso(s: str | bytes | None) -> datetime | None:
    if not s:
        return None
    if isinstance(s, bytes):
        s = s.decode("utf-8", errors="ignore")
    return datetime.strptime(s.strip(), ISO_LOCAL_FMT)

# ===========================================================
# resource_path (PyInstaller)
# ===========================================================
try:
    from ui.helpers import resource_path  # preferente si existe
except Exception:
    def resource_path(*relative_parts: str) -> str:
        base_path = getattr(
            sys, "_MEIPASS",
            os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        )
        return os.path.normpath(os.path.join(base_path, *relative_parts))

# ===========================================================
# Ubicación BD
# ===========================================================
APP_DIR_NAME = "SistemaComercio"
DB_FILENAME = "datos_comercio.db"

def _user_data_dir() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(base) / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        return Path(base) / APP_DIR_NAME

DB_DIR = _user_data_dir()
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / DB_FILENAME

def get_db_path() -> Path:
    return DB_PATH

# ===========================================================
# Conexión
# ===========================================================
def get_connection(timeout: float = 10.0) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=timeout,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

# ===========================================================
# Utilidades transaccionales y scripts
# ===========================================================
from typing import Any
@contextmanager
def with_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    cur = conn.cursor()
    try:
        cur.execute("BEGIN;")
        yield cur
        cur.execute("COMMIT;")
    except Exception:
        try:
            cur.execute("ROLLBACK;")
        except Exception:
            pass
        raise
    finally:
        cur.close()

def execute_script(conn: sqlite3.Connection, script: str) -> None:
    """Ejecuta un script SQL dentro de UNA transacción controlada por Python."""
    with with_tx(conn) as _:
        conn.executescript(script)

# --- Runner tolerante a scripts con/ sin BEGIN/COMMIT ---
import re as _re

def _exec_sql_script_tolerant(conn: sqlite3.Connection, sql_text: str) -> None:
    """
    Si el script trae BEGIN explícito, le dejamos manejar la transacción (autocommit ON).
    Si NO trae BEGIN, envolvemos nosotros con BEGIN/COMMIT y además
    eliminamos COMMIT/ROLLBACK sueltos para evitar 'cannot commit - no transaction is active'.
    """
    flags = _re.I | _re.M
    has_begin = _re.search(r'^\s*BEGIN\b', sql_text, flags) is not None

    if has_begin:
        # El script maneja su propia transacción: activar autocommit temporalmente
        old_iso = conn.isolation_level
        conn.isolation_level = None
        try:
            conn.executescript(sql_text)
        finally:
            conn.isolation_level = old_iso
    else:
        # Limpia COMMIT/ROLLBACK sueltos (no habrá transacción abierta aquí)
        sql_text_clean = _re.sub(r'^\s*(COMMIT|ROLLBACK)\s*;?\s*$', '', sql_text, flags=flags)
        try:
            conn.execute("BEGIN;")
            conn.executescript(sql_text_clean)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise

# ===========================================================
# Inicialización y migraciones
# ===========================================================
def _read_text_file(path: str | Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename   TEXT UNIQUE NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
    """)

def _list_applied_migrations(conn: sqlite3.Connection) -> Set[str]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT filename FROM schema_migrations").fetchall()
    return {r["filename"] for r in rows}

def _discover_migration_files() -> List[Path]:
    mig_dir = Path(resource_path("db", "migrations"))
    if not mig_dir.exists() or not mig_dir.is_dir():
        return []
    files = [p for p in mig_dir.iterdir() if p.is_file() and p.suffix.lower() == ".sql" and not p.name.startswith(".")]
    files.sort(key=lambda p: p.name)
    return files

def _user_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
          AND name != 'schema_migrations'
    """).fetchall()
    return [r["name"] for r in rows]

def _apply_schema_if_needed(conn: sqlite3.Connection) -> None:
    """
    Si la BD está vacía (sin tablas de usuario), aplica schema.sql (o init_db.sql).
    Usa el executor tolerante para evitar choques de transacciones.
    """
    if _user_tables(conn):
        return
    schema_path = Path(resource_path("db", "schema.sql"))
    legacy_init = Path(resource_path("db", "init_db.sql"))
    if schema_path.exists():
        script = _read_text_file(schema_path)
        _exec_sql_script_tolerant(conn, script)
        print("[OK] Aplicado: schema.sql")
    elif legacy_init.exists():
        script = _read_text_file(legacy_init)
        _exec_sql_script_tolerant(conn, script)
        print("[OK] Aplicado: init_db.sql (legacy)")
    else:
        raise FileNotFoundError("No se encontró db/schema.sql ni db/init_db.sql para inicializar la base.")

def run_migrations(verbose: bool = True) -> None:
    conn = get_connection()
    try:
        _ensure_migrations_table(conn)
        applied = _list_applied_migrations(conn)
        pending = [p for p in _discover_migration_files() if p.name not in applied]

        if verbose:
            print(f"[DB] Migraciones aplicadas: {len(applied)} | Pendientes: {len(pending)}")

        for path in pending:
            script = _read_text_file(path)
            try:
                _exec_sql_script_tolerant(conn, script)

                # Registrar la migración aplicada
                conn.execute("INSERT INTO schema_migrations (filename) VALUES (?)", (path.name,))

                # Si estamos en autocommit, NO intentes commit (haría 'cannot commit...')
                if conn.isolation_level is not None:
                    conn.commit()

                if verbose:
                    print(f"[migrate] OK  {path.name}")
            except Exception as e:
                try:
                    if conn.isolation_level is not None:
                        conn.rollback()
                except Exception:
                    pass
                print(f"[migrate] ERR {path.name}: {e}")
                break

        if pending and verbose:
            print("[DB] Migraciones completadas.")
    finally:
        conn.close()


def init_db() -> None:
    """Crea carpeta, aplica schema.sql si BD vacía, y luego migraciones."""
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[ERROR] No se pudo asegurar el directorio de datos: {DB_DIR}\n{e}")
        return

    db_nueva = not DB_PATH.exists()
    if db_nueva:
        print("[DB] Creando nueva base de datos…")

    try:
        conn = get_connection()
        try:
            _apply_schema_if_needed(conn)
        finally:
            conn.close()
        run_migrations(verbose=True)
        print("[OK] Base de datos lista.")
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
    except Exception as e:
        print(f"[ERROR] Falló la inicialización de la base de datos: {e}")

# ===========================================================
# Helpers de inspección
# ===========================================================
def obtener_tablas_existentes() -> List[str]:
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
