# ui/helpers.py
# -----------------------------------------------------------
# Sistema de Comercio — Utilidades de interfaz y helpers generales
#
# USO / FLUJO / FUNCIONALIDAD
# -----------------------------------------------------------
# Este módulo concentra utilidades compartidas por toda la app:
# 1) Diálogos (error, info, confirmación) para feedback al usuario.
# 2) Parsing y validación numérica tolerante a formatos:
#    - Soporta coma decimal y separadores de miles.
#    - Acepta y valida valores con máximo dos decimales (p. ej. .5, 0.5, 10.50).
# 3) Herramientas de fechas (validación, normalización, formateo).
# 4) Moneda y redondeo con Decimal (precisión financiera).
# 5) Utilidad para centrar ventanas.
# 6) Validadores para Entry de Tkinter que restringen la entrada
#    a números con máximo dos decimales (en tiempo de escritura).
#
# COMPATIBILIDAD
# -----------------------------------------------------------
# Se mantienen las firmas de:
# - validar_numero, fecha_actual, formatear_fecha, formato_moneda,
#   redondear_dos_decimales, calcular_total, centrar_ventana.
#
# NUEVOS HELPERS
# -----------------------------------------------------------
# - resource_path(*rutas): resuelve rutas de recursos soportando PyInstaller (_MEIPASS).
# - to_float(valor, permitir_cero=True): float robusto (acepta coma decimal).
# - to_int(valor, permitir_cero=True): entero seguro (redondea).
# - es_fecha_ok(fecha_str): valida 'YYYY-MM-DD'.
# - normalizar_fecha(fecha_str): extrae 'YYYY-MM-DD' de cadenas con hora.
# - rango_fechas_ok(desde, hasta): valida rango.
# - es_decimal_hasta_2(valor): True si valor tiene 0–2 decimales.
# - adjuntar_validador_2_decimales(entry, permitir_vacio=True):
#       limita un Entry para aceptar hasta 2 decimales y convierte
#       coma en punto al vuelo para mantener consistencia.
# -----------------------------------------------------------

import os
import sys
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


# -----------------------
# Recursos (PyInstaller)
# -----------------------
def resource_path(*paths: str) -> str:
    """
    Devuelve la ruta absoluta a un recurso dentro del ejecutable empaquetado (PyInstaller)
    o del árbol de fuentes en desarrollo.
    Uso:
        resource_path("assets", "logo.png")
        resource_path("db", "init_db.sql")
    """
    if not paths:
        return ""
    # Si el primer argumento ya es absoluto, respétalo
    if os.path.isabs(paths[0]):
        return os.path.normpath(os.path.join(*paths))
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.normpath(os.path.join(base, *paths))


# -----------------------
# Diálogos / mensajes
# -----------------------
def mostrar_error(titulo, mensaje):
    """Muestra un cuadro de diálogo de error."""
    messagebox.showerror(titulo, mensaje)


def mostrar_info(titulo, mensaje):
    """Muestra un cuadro de diálogo informativo."""
    messagebox.showinfo(titulo, mensaje)


def mostrar_confirmacion(titulo, mensaje):
    """Muestra confirmación Sí/No y retorna True/False."""
    return messagebox.askyesno(titulo, mensaje)


# -----------------------
# Parsing y validaciones
# -----------------------
def _normalize_number_str(s: str) -> str:
    """
    Normaliza una cadena numérica:
      - Elimina símbolo '$' y espacios.
      - Acepta coma decimal (p. ej., '1,25' -> '1.25').
      - Quita separadores de miles en formatos comunes:
          '1,234.56' -> '1234.56'
          '1.234,56' -> '1234.56'
          '1.234.567' -> '1234567'
    """
    if s is None:
        return ""
    s = str(s).strip().replace("$", "")

    # 1) Solo coma -> decimal
    if s.count(",") == 1 and s.count(".") == 0:
        return s.replace(",", ".")

    # 2) Solo muchos separadores iguales -> miles (quitar)
    if s.count(",") > 1 and s.count(".") == 0:
        return s.replace(",", "")
    if s.count(".") > 1 and s.count(",") == 0:
        return s.replace(".", "")

    # 3) Coma y punto
    if s.count(",") == 1 and s.count(".") == 1:
        # '1.234,56' → quitar puntos (miles), coma → punto
        if s.rfind(",") > s.rfind("."):
            return s.replace(".", "").replace(",", ".")
        # '1,234.56' → quitar coma (miles), conservar punto decimal
        else:
            return s.replace(",", "")

    return s


def to_float(valor, permitir_cero=True) -> float:
    """
    Convierte a float tolerando coma decimal y separadores de miles.
    Lanza ValueError si el valor no es numérico o si es <= 0 y no se permite cero.

    Ejemplos válidos:
      '1,25' -> 1.25
      '1.234,56' -> 1234.56
      '$ 2,000.50' -> 2000.50
      '.5' -> 0.5
    """
    s = _normalize_number_str(valor)
    try:
        # Aceptar '.5' -> '0.5'
        if s.startswith("."):
            s = "0" + s
        v = float(s)
    except Exception as e:
        raise ValueError(f"Valor numérico inválido: {valor}") from e
    if not permitir_cero and v <= 0:
        raise ValueError("El valor debe ser mayor a 0.")
    return v


def to_int(valor, permitir_cero=True) -> int:
    """
    Convierte a entero tolerando '2.0' o '2,0'.
    Aplica las mismas reglas de validación que to_float.
    """
    v = to_float(valor, permitir_cero=permitir_cero)
    try:
        return int(round(v))
    except Exception as e:
        raise ValueError(f"No se pudo convertir a entero: {valor}") from e


def validar_numero(valor, permitir_cero=False):
    """
    Compatibilidad: True si 'valor' puede convertirse a float
    y cumple la regla de cero (>0 cuando permitir_cero=False).
    """
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
    """
    Retorna True si 'valor' representa un número con 0–2 decimales.
    Acepta entradas intermedias de edición: '', '.', '1.', '1.2', etc.
    Soporta coma decimal; se normaliza a punto antes de validar.
    """
    if valor is None:
        return permitir_vacio
    s = _normalize_number_str(str(valor).strip())
    if s == "":
        return permitir_vacio
    if s == ".":
        # estado intermedio al teclear; permitido si permitir_vacio
        return permitir_vacio
    # Aceptar '.5' -> '0.5' para el patrón
    if s.startswith("."):
        s = "0" + s
    return bool(_DECIMAL_2_PATTERN.match(s))


def adjuntar_validador_2_decimales(entry: tk.Entry, permitir_vacio: bool = True):
    """
    Restringe un Entry para aceptar solo números con hasta 2 decimales.
    Permite estados intermedios ('', '.', '1.') para no entorpecer la escritura.
    Además, convierte automáticamente comas en puntos (teclado/pegar).

    Uso:
        adjuntar_validador_2_decimales(mi_entry)
    """
    def _vcmd(nuevo_valor: str) -> bool:
        try:
            return es_decimal_hasta_2(nuevo_valor, permitir_vacio=permitir_vacio)
        except Exception:
            return False

    vcmd = (entry.register(_vcmd), "%P")
    entry.configure(validate="key", validatecommand=vcmd)

    # Reemplazar ',' por '.' al vuelo (teclado y pegado)
    def _replace_commas(_evt=None):
        txt = entry.get()
        if "," in txt:
            pos = entry.index(tk.INSERT)
            nuevo = txt.replace(",", ".")
            entry.delete(0, tk.END)
            entry.insert(0, nuevo)
            # restaurar cursor en una posición razonable
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
    """Retorna la fecha actual en formato 'YYYY-MM-DD'."""
    return datetime.now().strftime("%Y-%m-%d")


def es_fecha_ok(fecha_str: str) -> bool:
    """Valida que la fecha tenga formato 'YYYY-MM-DD'."""
    try:
        datetime.strptime(str(fecha_str).strip(), "%Y-%m-%d")
        return True
    except Exception:
        return False


def normalizar_fecha(fecha_str: str) -> str:
    """
    Acepta 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS' y devuelve 'YYYY-MM-DD'.
    Si no puede convertir, retorna la cadena original sin romper.
    """
    try:
        base = str(fecha_str).strip().split(" ")[0]
        dt = datetime.strptime(base, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return fecha_str


def formatear_fecha(fecha_str, formato_salida="%d/%m/%Y"):
    """
    Recibe una fecha 'YYYY-MM-DD' (o string con hora) y la devuelve
    en el formato deseado (por defecto 'DD/MM/YYYY').
    """
    try:
        fecha = datetime.strptime(normalizar_fecha(fecha_str), "%Y-%m-%d")
        return fecha.strftime(formato_salida)
    except Exception:
        return str(fecha_str)


def rango_fechas_ok(desde: str, hasta: str) -> bool:
    """True si ambas fechas son válidas y desde <= hasta."""
    if not (es_fecha_ok(desde) and es_fecha_ok(hasta)):
        return False
    di = datetime.strptime(desde, "%Y-%m-%d")
    df = datetime.strptime(hasta, "%Y-%m-%d")
    return di <= df


# -----------------------
# Moneda y redondeo
# -----------------------
def _to_decimal(valor) -> Decimal:
    """
    Convierte a Decimal usando to_float internamente para tolerar formatos.
    Lanza InvalidOperation si no es convertible.
    """
    v = to_float(valor, permitir_cero=True)
    try:
        return Decimal(str(v))
    except InvalidOperation as e:
        raise InvalidOperation(f"No se pudo convertir a Decimal: {valor}") from e


def formato_moneda(valor):
    """Convierte un número en formato moneda '$x,xxx.xx' con 2 decimales."""
    try:
        d = _to_decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        entero, frac = f"{d:.2f}".split(".")
        entero_con_miles = "{:,}".format(int(entero))
        return f"${entero_con_miles}.{frac}"
    except Exception:
        return "$0.00"


def redondear_dos_decimales(valor):
    """Redondea a 2 decimales con Decimal (ROUND_HALF_UP) y retorna float."""
    try:
        d = _to_decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return float(d)
    except Exception:
        return 0.00


def calcular_total(cantidad, precio_unitario):
    """
    Calcula el total de una venta = cantidad * precio_unitario,
    con redondeo financiero a 2 decimales.
    """
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
