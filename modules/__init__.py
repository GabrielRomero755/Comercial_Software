# modules/__init__.py
# -----------------------------------------------------------
# Paquete que contiene todos los módulos funcionales del sistema.
# Expone los módulos principales y un registro central opcional
# para resolver el loader (función mostrar) por nombre.
#
# Notas:
# - Se mantienen las importaciones explícitas para compatibilidad
#   con main.py (from modules import productos, ...).
# - REGISTRO_MODULOS permite resolver el callback `mostrar`
#   por etiqueta de navegación ("Inicio", "Productos", etc.).
# - Utilitarios: get_module_loader(), lista_modulos(), modulo_existe().
# -----------------------------------------------------------

from __future__ import annotations

from typing import Callable, Dict, Optional

# Importaciones explícitas (compatibilidad con main.py)
from . import (
    home,
    productos,
    inventario,
    ventas,
    creditos,
    mermas,
    gastos,
    reportes,
)

__all__ = [
    # Submódulos
    "home",
    "productos",
    "inventario",
    "ventas",
    "creditos",
    "mermas",
    "gastos",
    "reportes",

    # Registro / helpers
    "REGISTRO_MODULOS",
    "get_module_loader",
    "lista_modulos",
    "modulo_existe",
]

# -----------------------------------------------------------
# Registro central (nombre de pestaña → módulo)
# Si más adelante agregamos nuevos módulos (p. ej. Proveedores,
# Compras, Analítica), se sumarán aquí y el main podrá usar
# get_module_loader(nombre) sin cambios.
# -----------------------------------------------------------
REGISTRO_MODULOS: Dict[str, object] = {
    "Inicio": home,
    "Productos": productos,
    "Inventario": inventario,
    "Ventas": ventas,
    "Créditos": creditos,
    "Mermas": mermas,
    "Gastos": gastos,
    "Reportes": reportes,
    # Reservados para futuras ampliaciones del roadmap:
    # "Proveedores": proveedores,
    # "Compras": compras,
    # "Analítica": analitica,
}


def get_module_loader(nombre: str) -> Optional[Callable]:
    """
    Devuelve la función `mostrar` del módulo identificado por `nombre`.
    Si no existe o el módulo no define `mostrar`, retorna None.
    """
    mod = REGISTRO_MODULOS.get(nombre)
    return getattr(mod, "mostrar", None) if mod else None


def lista_modulos() -> list[str]:
    """Devuelve la lista de etiquetas de módulos registrados (orden actual)."""
    return list(REGISTRO_MODULOS.keys())


def modulo_existe(nombre: str) -> bool:
    """True si `nombre` está registrado en REGISTRO_MODULOS."""
    return nombre in REGISTRO_MODULOS
