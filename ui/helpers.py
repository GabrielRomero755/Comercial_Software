# ui/helpers.py
# -----------------------------------------------------------
# Sistema de Comercio — Utilidades de interfaz y helpers generales
#
# Mantiene compat de firmas:
# - validar_numero, fecha_actual, formatear_fecha, formato_moneda,
#   redondear_dos_decimales, calcular_total, centrar_ventana.
#
# Contiene:
# - Recursos (resource_path)
# - Diálogos (error/info/confirmación)
# - Parsing/validación numérica (coma/punto, 2 decimales)
# - Fechas (validación, normalización, formateo)
# - Moneda y redondeo (Decimal, ROUND_HALF_UP)
# - Utilidad centrar_ventana
# -----------------------------------------------------------

from __future__ import annotations

import os
import sys
import re
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


# -----------------------
# Recursos (PyInstaller)
# -----------------------
def resource_path(*paths: str) -> str:
    """
    Devuelve la ruta absoluta a un recurso (compatible con PyInstaller).
    Uso:
        resource_path("assets", "logo.png")
        resource_path("db", "schema.sql")
    """
    if not paths:
        return ""
    if os.path.isabs(paths[0]):
        return os.path.normpath(os.path.join(*paths))
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.normpath(os.path.join(base, *paths))


# -----------------------
# Diálogos / mensajes
# -----------------------
def mostrar_error(titulo, mensaje):
    messagebox.showerror(titulo, mensaje)


def mostrar_info(titulo, mensaje):
    messagebox.showinfo(titulo, mensaje)


def mostrar_confirmacion(titulo, mensaje):
    return messagebox.askyesno(titulo, mensaje)


# -----------------------
# Parsing y validaciones
# -----------------------
def _normalize_number_str(s: str) -> str:
    """
    Normaliza una cadena numérica:
      - Elimina '$' y espacios.
      - Acepta coma decimal.
      - Quita separadores de miles en formatos comunes.
    """
    if s is None:
        return ""
    s = str(s).strip().replace("$", "")

    if s.count(",") == 1 and s.count(".") == 0:
        return s.replace(",", ".")

    if s.count(",") > 1 and s.count(".") == 0:
        return s.replace(",", "")
    if s.count(".") > 1 and s.count(",") == 0:
        return s.replace(".", "")

    if s.count(",") == 1 and s.count(".") == 1:
        if s.rfind(",") > s.rfind("."):
            return s.replace(".", "").replace(",", ".")
        else:
            return s.replace(",", "")

    return s


def to_float(valor, permitir_cero=True) -> float:
    s = _normalize_number_str(valor)
    try:
        if s.startswith("."):
            s = "0" + s
        v = float(s)
    except Exception as e:
        raise ValueError(f"Valor numérico inválido: {valor}") from e
    if not permitir_cero and v <= 0:
        raise ValueError("El valor debe ser mayor a 0.")
    return v


def to_int(valor, permitir_cero=True) -> int:
    v = to_float(valor, permitir_cero=permitir_cero)
    try:
        return int(round(v))
    except Exception as e:
        raise ValueError(f"No se pudo convertir a entero: {valor}") from e


def validar_numero(valor, permitir_cero=False):
    try:
        _ = to_float(valor, permitir_cero=permitir_cero)
        return True
    except ValueError:
        return False


# -----------------------
# Validación de 2 decimales
# -----------------------
_DECIMAL_2_PATTERN = re.compile(r"^\d*(?:\.\d{0,2})?$")

def es_decimal_hasta_2(valor: str, permitir_vacio: bool = True) -> bool:
    if valor is None:
        return permitir_vacio
    s = _normalize_number_str(str(valor).strip())
    if s == "":
        return permitir_vacio
    if s == ".":
        return permitir_vacio
    if s.startswith("."):
        s = "0" + s
    return bool(_DECIMAL_2_PATTERN.match(s))


def adjuntar_validador_2_decimales(entry: tk.Entry, permitir_vacio: bool = True):
    def _vcmd(nuevo_valor: str) -> bool:
        try:
            return es_decimal_hasta_2(nuevo_valor, permitir_vacio=permitir_vacio)
        except Exception:
            return False

    vcmd = (entry.register(_vcmd), "%P")
    entry.configure(validate="key", validatecommand=vcmd)

    def _replace_commas(_evt=None):
        txt = entry.get()
        if "," in txt:
            pos = entry.index(tk.INSERT)
            nuevo = txt.replace(",", ".")
            entry.delete(0, tk.END)
            entry.insert(0, nuevo)
            try:
                entry.icursor(min(pos, len(nuevo)))
            except Exception:
                pass

    entry.bind("<KeyRelease>", _replace_commas, add="+")
    entry.bind("<<Paste>>", lambda e: entry.after_idle(_replace_commas), add="+")


# -----------------------
# Fechas
# -----------------------
def fecha_actual():
    return datetime.now().strftime("%Y-%m-%d")


def es_fecha_ok(fecha_str: str) -> bool:
    try:
        datetime.strptime(str(fecha_str).strip(), "%Y-%m-%d")
        return True
    except Exception:
        return False


def normalizar_fecha(fecha_str: str) -> str:
    try:
        base = str(fecha_str).strip().split(" ")[0]
        dt = datetime.strptime(base, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return fecha_str


def formatear_fecha(fecha_str, formato_salida="%d/%m/%Y"):
    try:
        fecha = datetime.strptime(normalizar_fecha(fecha_str), "%Y-%m-%d")
        return fecha.strftime(formato_salida)
    except Exception:
        return str(fecha_str)


def rango_fechas_ok(desde: str, hasta: str) -> bool:
    if not (es_fecha_ok(desde) and es_fecha_ok(hasta)):
        return False
    di = datetime.strptime(desde, "%Y-%m-%d")
    df = datetime.strptime(hasta, "%Y-%m-%d")
    return di <= df


# -----------------------
# Moneda y redondeo
# -----------------------
def _to_decimal(valor) -> Decimal:
    v = to_float(valor, permitir_cero=True)
    try:
        return Decimal(str(v))
    except InvalidOperation as e:
        raise InvalidOperation(f"No se pudo convertir a Decimal: {valor}") from e


def formato_moneda(valor):
    try:
        d = _to_decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        entero, frac = f"{d:.2f}".split(".")
        entero_con_miles = "{:,}".format(int(entero))
        return f"${entero_con_miles}.{frac}"
    except Exception:
        return "$0.00"


def redondear_dos_decimales(valor):
    try:
        d = _to_decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(d)
    except Exception:
        return 0.00


def calcular_total(cantidad, precio_unitario):
    try:
        c = _to_decimal(cantidad)
        p = _to_decimal(precio_unitario)
        total = (c * p).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(total)
    except Exception:
        return 0.00


# -----------------------
# Ventanas / UI
# -----------------------
def centrar_ventana(ventana, ancho=400, alto=300):
    """Centra una ventana en pantalla."""
    ventana.update_idletasks()
    x = (ventana.winfo_screenwidth() // 2) - (ancho // 2)
    y = (ventana.winfo_screenheight() // 2) - (alto // 2)
    ventana.geometry(f"{ancho}x{alto}+{x}+{y}")
