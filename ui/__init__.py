# modules/__init__.py
# -----------------------------------------------------------
# Paquete que contiene los módulos funcionales del sistema.
# - Exporta: home, productos, inventario, ventas, creditos, mermas, gastos, reportes
# - Carga perezosa (lazy) para evitar ciclos de importación.
# - Registro central para resolver la función `mostrar` por nombre de pestaña.
# -----------------------------------------------------------

from __future__ import annotations

from typing import Callable, Dict, Optional
import importlib

# Nombres de submódulos que exponemos públicamente
_MOD_NAMES = (
    "home",
    "productos",
    "inventario",
    "ventas",
    "creditos",
    "mermas",
    "gastos",
    "reportes",
)

__all__ = [
    # Submódulos (se resuelven perezosamente vía __getattr__)
    *(_MOD_NAMES),
    # Registro / helpers
    "REGISTRO_MODULOS",
    "get_module_loader",
    "lista_modulos",
    "modulo_existe",
]

# -----------------------------------------------------------
# Registro central (nombre de pestaña → nombre de módulo)
# No importamos los módulos aquí para evitar ciclos al arrancar.
# -----------------------------------------------------------
REGISTRO_MODULOS: Dict[str, str] = {
    "Inicio":     "home",
    "Productos":  "productos",
    "Inventario": "inventario",
    "Ventas":     "ventas",
    "Créditos":   "creditos",
    "Mermas":     "mermas",
    "Gastos":     "gastos",
    "Reportes":   "reportes",
}


def __getattr__(name: str):
    """
    Carga perezosamente un submódulo cuando se accede como atributo:
        from modules import productos  -> dispara aquí y retorna modules.productos
    """
    if name in _MOD_NAMES:
        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_module_loader(nombre: str) -> Optional[Callable]:
    """
    Devuelve la función `mostrar` del módulo asociado a la pestaña `nombre`.
    Retorna None si no existe o si el módulo no define `mostrar`.
    """
    mod_name = REGISTRO_MODULOS.get(nombre)
    if not mod_name:
        return None
    try:
        mod = importlib.import_module(f".{mod_name}", __name__)
        return getattr(mod, "mostrar", None)
    except Exception:
        return None


def lista_modulos() -> list[str]:
    """Devuelve la lista de etiquetas de módulos registrados (orden actual)."""
    return list(REGISTRO_MODULOS.keys())


def modulo_existe(nombre: str) -> bool:
    """True si `nombre` está registrado en REGISTRO_MODULOS."""
    return nombre in REGISTRO_MODULOS
