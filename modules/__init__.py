# modules/__init__.py
# -----------------------------------------------------------
# Paquete que contiene todos los módulos funcionales del sistema.
# Expone los módulos principales y un registro central opcional
# para resolver el loader (función mostrar) por nombre.
# -----------------------------------------------------------

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
    "home",
    "productos",
    "inventario",
    "ventas",
    "creditos",
    "mermas",
    "gastos",
    "reportes",
    "REGISTRO_MODULOS",
    "get_module_loader",
]

# Registro central opcional (nombre → módulo)
# Útil si más adelante el main quiere resolver loaders desde aquí.
REGISTRO_MODULOS = {
    "Inicio": home,
    "Productos": productos,
    "Inventario": inventario,
    "Ventas": ventas,
    "Créditos": creditos,
    "Mermas": mermas,
    "Gastos": gastos,
    "Reportes": reportes,
}


def get_module_loader(nombre: str):
    """
    Devuelve la función `mostrar` del módulo identificado por `nombre`.
    Si no existe, devuelve None (el main puede manejar el fallback).
    """
    mod = REGISTRO_MODULOS.get(nombre)
    return getattr(mod, "mostrar", None) if mod else None
