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
# - Fechas (validación, normalización, formateo; ISO local canónico)
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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, getcontext

# ===========================================================
# Configuración Decimal (evitar errores de redondeo en dinero)
# ===========================================================
getcontext().prec = 28  # suficiente para cálculos de negocio
_MONEY_QUANT = Decimal("0.01")

def _as_decimal(value) -> Decimal:
    """Convierte un valor (str/int/float/Decimal) a Decimal cuantizado 2d."""
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        q = value
    else:
        q = Decimal(str(value))
    return q.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


# ===========================================================
# Recursos (PyInstaller)
# ===========================================================
def resource_path(*paths: str) -> str:
    """
    Devuelve la ruta absoluta a un recurso (compatible con PyInstaller).
    Uso:
        resource_path("assets", "logo.png")
        resource_path("db", "schema.sql")
    """
    if not paths:
        return ""
    # Si ya viene absoluta, normaliza y retorna
    if os.path.isabs(paths[0]):
        return os.path.normpath(os.path.join(*paths))
    # _MEIPASS cuando está empaquetado; de lo contrario raíz del proyecto
    base = getattr(
        sys, "_MEIPASS",
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    )
    return os.path.normpath(os.path.join(base, *paths))


# ===========================================================
# Diálogos / mensajes
# ===========================================================
def mostrar_error(titulo: str, mensaje: str) -> None:
    messagebox.showerror(titulo, mensaje)

def mostrar_info(titulo: str, mensaje: str) -> None:
    messagebox.showinfo(titulo, mensaje)

def mostrar_confirmacion(titulo: str, mensaje: str) -> bool:
    return messagebox.askyesno(titulo, mensaje)


# ===========================================================
# Parsing y validaciones numéricas
# ===========================================================
_NUMERIC_CHARS = set("0123456789.,-+$ ")

def _normalize_number_str(s: str) -> str:
    """
    Normaliza una cadena numérica:
      - Elimina símbolos comunes ($) y espacios.
      - Acepta coma decimal.
      - Quita separadores de miles (.,) cuando aplica.
      - Mantiene signo inicial si existe.
    Casos cubiertos:
      "1.234,56" -> "1234.56"
      "1,234.56" -> "1234.56"
      ",5"       -> "0.5"
      ".5"       -> "0.5"
    """
    if s is None:
        return ""
    s = str(s).strip()
    # Filtra caracteres ajenos (evita \n, tabs, etc.) pero mantiene signo y .,,
    s = "".join(ch for ch in s if ch in _NUMERIC_CHARS)

    # Quita moneda y espacios
    s = s.replace("$", "").replace(" ", "")

    # Manejo de separadores:
    # - Solo coma: interpretarla como decimal.
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    # - Muchas comas y ningún punto: asume comas como miles -> quítalas.
    elif s.count(",") > 1 and s.count(".") == 0:
        s = s.replace(",", "")
    # - Muchos puntos y ninguna coma: asume puntos como miles -> quítalos.
    elif s.count(".") > 1 and s.count(",") == 0:
        s = s.replace(".", "")
    # - Hay ambos: decidir por la última ocurrencia (el más a la derecha suele ser decimal)
    elif s.count(",") >= 1 and s.count(".") >= 1:
        if s.rfind(",") > s.rfind("."):
            # coma es decimal, punto miles
            s = s.replace(".", "").replace(",", ".")
        else:
            # punto es decimal, coma miles
            s = s.replace(",", "")

    # Prefijo con 0 si empieza con punto (".5" -> "0.5")
    if s.startswith("."):
        s = "0" + s
    if s.startswith("-."):
        s = s.replace("-.", "-0.")
    return s


def to_float(valor, permitir_cero: bool = True) -> float:
    """Convierte a float tras normalizar. Lanza ValueError si inválido."""
    s = _normalize_number_str(valor)
    try:
        v = float(s) if s not in ("", ".", "-") else 0.0
    except Exception as e:
        raise ValueError(f"Valor numérico inválido: {valor}") from e
    if not permitir_cero and v <= 0:
        raise ValueError("El valor debe ser mayor a 0.")
    return v


def to_int(valor, permitir_cero: bool = True) -> int:
    """Convierte a int redondeando al entero más cercano."""
    v = to_float(valor, permitir_cero=permitir_cero)
    try:
        return int(round(v))
    except Exception as e:
        raise ValueError(f"No se pudo convertir a entero: {valor}") from e


def validar_numero(valor, permitir_cero: bool = False) -> bool:
    """Validación simple de número (float)."""
    try:
        _ = to_float(valor, permitir_cero=permitir_cero)
        return True
    except ValueError:
        return False


# ===== Validación de hasta 2 decimales (para Entry) =====
_DECIMAL_2_PATTERN = re.compile(r"^-?\d*(?:\.\d{0,2})?$")

def es_decimal_hasta_2(valor: str, permitir_vacio: bool = True) -> bool:
    """True si el texto representa un número con hasta 2 decimales."""
    if valor is None:
        return permitir_vacio
    s = _normalize_number_str(str(valor).strip())
    if s in ("", ".", "-"):
        return permitir_vacio
    if s.startswith("."):
        s = "0" + s
    if s.startswith("-."):
        s = s.replace("-.", "-0.")
    return bool(_DECIMAL_2_PATTERN.match(s))

def adjuntar_validador_2_decimales(entry: tk.Entry, permitir_vacio: bool = True) -> None:
    """Adjunta validador en caliente para hasta 2 decimales; soporta comas."""
    def _vcmd(nuevo_valor: str) -> bool:
        try:
            return es_decimal_hasta_2(nuevo_valor, permitir_vacio=permitir_vacio)
        except Exception:
            return False

    vcmd = (entry.register(_vcmd), "%P")
    entry.configure(validate="key", validatecommand=vcmd)

    def _replace_commas(_evt=None):
        # Convierte comas a punto respetando la posición del cursor
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

    # Reemplaza comas al tipear o pegar
    entry.bind("<KeyRelease>", _replace_commas, add="+")
    entry.bind("<<Paste>>", lambda e: entry.after_idle(_replace_commas), add="+")


# ===========================================================
# Fechas (formato canónico e interop)
# ===========================================================
# Formato canónico local: "YYYY-MM-DD HH:MM:SS"
ISO_LOCAL_FMT = "%Y-%m-%d %H:%M:%S"

def now_iso_local() -> str:
    """Fecha/hora local actual en formato canónico."""
    return datetime.now().strftime(ISO_LOCAL_FMT)

def fecha_actual() -> str:
    """Solo fecha actual 'YYYY-MM-DD' (compatibilidad)."""
    return datetime.now().strftime("%Y-%m-%d")

def es_fecha_ok(fecha_str: str) -> bool:
    """True si 'YYYY-MM-DD' es válida."""
    try:
        datetime.strptime(str(fecha_str).strip(), "%Y-%m-%d")
        return True
    except Exception:
        return False

def normalizar_fecha(fecha_str: str) -> str:
    """
    Normaliza a 'YYYY-MM-DD' si viene con hora u otros formatos parciales.
    Si no puede, retorna la cadena original.
    """
    try:
        base = str(fecha_str).strip().split(" ")[0]
        dt = datetime.strptime(base, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        # Intento extra: si viene en formato canónico con hora
        try:
            dt = datetime.strptime(str(fecha_str).strip(), ISO_LOCAL_FMT)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return fecha_str

def formatear_fecha(fecha_str, formato_salida: str = "%d/%m/%Y") -> str:
    """
    Convierte 'YYYY-MM-DD' (o canónico con hora) a formato_salida.
    Conserva original si falla.
    """
    try:
        base = normalizar_fecha(fecha_str)
        fecha = datetime.strptime(base, "%Y-%m-%d")
        return fecha.strftime(formato_salida)
    except Exception:
        return str(fecha_str)

def rango_fechas_ok(desde: str, hasta: str) -> bool:
    """Valida que desde <= hasta, con formato 'YYYY-MM-DD'."""
    if not (es_fecha_ok(desde) and es_fecha_ok(hasta)):
        return False
    di = datetime.strptime(desde, "%Y-%m-%d")
    df = datetime.strptime(hasta, "%Y-%m-%d")
    return di <= df


# ===========================================================
# Moneda y redondeo (conservando firmas legacy)
# ===========================================================
def _to_decimal(valor) -> Decimal:
    """Convierte por medio del normalizador numérico y Decimal."""
    try:
        v = to_float(valor, permitir_cero=True)
        return _as_decimal(v)
    except (InvalidOperation, ValueError) as e:
        raise InvalidOperation(f"No se pudo convertir a Decimal: {valor}") from e

def formato_moneda(valor) -> str:
    """Formatea como '$#,###.##' con dos decimales y miles."""
    try:
        d = _to_decimal(valor)
        entero, frac = f"{d:.2f}".split(".")
        # Agrupación de miles con coma (estilo en todo el proyecto)
        entero_con_miles = "{:,}".format(abs(int(entero)))
        signo = "-" if d < 0 else ""
        return f"{signo}${entero_con_miles}.{frac}"
    except Exception:
        return "$0.00"

def redondear_dos_decimales(valor):
    """Retorna float con 2 decimales (ROUND_HALF_UP)."""
    try:
        d = _to_decimal(valor)
        return float(d)
    except Exception:
        return 0.00

def calcular_total(cantidad, precio_unitario):
    """
    Multiplica cantidad * precio con Decimal y retorna float(2d).
    Se usa tanto para kilos como para unidades.
    """
    try:
        c = _to_decimal(cantidad)
        p = _to_decimal(precio_unitario)
        total = (c * p).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(total)
    except Exception:
        return 0.00


# ===========================================================
# Ventanas / UI
# ===========================================================
def centrar_ventana(ventana: tk.Tk | tk.Toplevel, ancho: int = 400, alto: int = 300) -> None:
    """Centra una ventana en pantalla (tamaño sugerido opcional)."""
    try:
        ventana.update_idletasks()
        # Si ya tiene tamaño, úsalo como base a menos que se especifique
        current_w = ventana.winfo_width() or ancho
        current_h = ventana.winfo_height() or alto
        x = (ventana.winfo_screenwidth() // 2) - (current_w // 2)
        y = (ventana.winfo_screenheight() // 2) - (current_h // 2)
        ventana.geometry(f"{current_w}x{current_h}+{x}+{y}")
    except Exception:
        # Fallback simple
        x = (ventana.winfo_screenwidth() // 2) - (ancho // 2)
        y = (ventana.winfo_screenheight() // 2) - (alto // 2)
        ventana.geometry(f"{ancho}x{alto}+{x}+{y}")

