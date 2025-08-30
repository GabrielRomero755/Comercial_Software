# db/__init__.py
"""
Paquete de acceso a base de datos (SQLite).

Expone utilidades principales:
- get_connection(): Context manager para obtener una conexión con PRAGMA foreign_keys=ON.
- init_db(): Inicializa la base de datos (creación de tablas/índices si no existen).

Nota:
Las implementaciones viven en db/database.py. Este paquete reexporta
símbolos clave para consumo sencillo desde el resto de la app.
"""

from .database import get_connection, init_db  # compat con el código existente

__all__ = ["get_connection", "init_db"]
