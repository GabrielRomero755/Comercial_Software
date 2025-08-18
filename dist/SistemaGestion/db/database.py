# db/database.py
# -----------------------------------------------------------
# Módulo de acceso a la base de datos (SQLite)
# - Provee get_connection() con PRAGMAs adecuados:
#     * foreign_keys = ON  → respeta claves foráneas
#     * row_factory = sqlite3.Row → acceso por nombre de columna
# - init_db() ejecuta el script SQL de inicialización (idempotente
#   si el SQL usa IF NOT EXISTS).
# - Helpers para inspeccionar tablas.
#
# CAMBIOS CLAVE
# -----------------------------------------------------------
# - La base de datos ahora se guarda en un directorio de datos de usuario
#   (escribible), NO en la carpeta del paquete:
#     * Linux:  ~/.local/share/SistemaComercio/datos_comercio.db
#     * Windows: %APPDATA%\SistemaComercio\datos_comercio.db
# - El init_db.sql se lee desde los recursos del proyecto con resource_path,
#   compatible con PyInstaller.
# -----------------------------------------------------------

import os
import sqlite3
import platform
from pathlib import Path

# Carga de recursos empaquetados (imágenes/sql/etc.)
# Requiere que ui/helpers.py tenga resource_path como acordamos.
try:
    from ui.helpers import resource_path
except Exception:
    # Fallback mínimo por si helpers no está disponible muy al principio.
    # (PyInstaller: sys._MEIPASS)
    import sys
    def resource_path(*relative_parts: str) -> str:
        base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        return os.path.normpath(os.path.join(base_path, *relative_parts))


# -----------------------------------------------------------
# Ubicación de la BD (directorio de datos del usuario)
# -----------------------------------------------------------
APP_DIR_NAME = "SistemaComercio"       # Carpeta en AppData / ~/.local/share
DB_FILENAME  = "datos_comercio.db"     # Nombre de archivo de la BD


def _user_data_dir() -> Path:
    """Devuelve la carpeta de datos del usuario para la app."""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(base) / APP_DIR_NAME
    else:
        # Linux / otros Unix
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
        return Path(base) / APP_DIR_NAME


DB_DIR = _user_data_dir()
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / DB_FILENAME


def get_connection(timeout: float = 10.0) -> sqlite3.Connection:
    """
    Devuelve una conexión activa a la base de datos con ajustes recomendados.

    - timeout: segundos a esperar antes de lanzar 'database is locked'.
    - Activa integridad referencial (foreign_keys ON).
    - row_factory: permite acceder a las columnas por nombre (row["col"]).

    Uso:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=timeout, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row

    cur = conn.cursor()
    # Claves foráneas activas
    cur.execute("PRAGMA foreign_keys = ON;")
    # (Opcionales, descomentar si lo deseas)
    # cur.execute("PRAGMA journal_mode = WAL;")     # mejor concurrencia
    # cur.execute("PRAGMA synchronous = NORMAL;")   # equilibrio durabilidad/rendimiento
    # cur.execute("PRAGMA temp_store = MEMORY;")
    # cur.execute("PRAGMA cache_size = -20000;")    # ~20 MB de caché (negativo = KB)
    cur.close()

    return conn


def init_db():
    """
    Inicializa la base de datos ejecutando el script SQL (init_db.sql).

    - Si la DB no existe, la crea y aplica el script.
    - Si ya existe, vuelve a ejecutar el SQL; como el script usa
      'IF NOT EXISTS', la operación es segura e idempotente.
    """
    # El SQL debe empaquetarse en el build (PyInstaller):
    #   --add-data "db/init_db.sql:db"
    ruta_sql = resource_path("db", "init_db.sql")
    db_nueva = not DB_PATH.exists()

    if not os.path.exists(ruta_sql):
        print(f"[ERROR] No se encontró el archivo SQL en: {ruta_sql}")
        return

    if db_nueva:
        print("[INFO] Creando nueva base de datos...")
        try:
            DB_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[ERROR] No se pudo crear el directorio de datos: {DB_DIR}\n{e}")
            return

    try:
        with get_connection() as conn:
            with open(ruta_sql, "r", encoding="utf-8") as f:
                sql_script = f.read()
            conn.executescript(sql_script)
        print("[OK] Base de datos inicializada correctamente.")
    except Exception as e:
        print(f"[ERROR] No se pudo inicializar la base de datos: {e}")


def obtener_tablas_existentes():
    """
    Devuelve una lista de nombres de tablas presentes en la base de datos.
    """
    tablas = []
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tablas = [row["name"] for row in cur.fetchall()]
    except Exception as e:
        print(f"[ERROR] No se pudieron obtener las tablas: {e}")
    return tablas


def tabla_existe(nombre_tabla: str) -> bool:
    """
    Verifica si una tabla ya existe en la base de datos.

    Ejemplo:
        if tabla_existe('productos'):
            ...
    """
    return nombre_tabla in obtener_tablas_existentes()
