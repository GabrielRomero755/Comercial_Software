# ui/__init__.py
# Paquete que contiene componentes visuales y funciones auxiliares

from .helpers import (
    # Recursos / sistema
    resource_path, centrar_ventana,

    # Tema / estilos
    BRAND_PALETTE, DARK_PALETTE, apply_brand_ttk_theme, stylize_combobox_dropdown,

    # Diálogos
    mostrar_error, mostrar_info, mostrar_confirmacion,

    # Números y validaciones
    validar_numero, to_float, to_int,
    redondear_dos_decimales, calcular_total, formato_moneda,
    es_decimal_hasta_2, adjuntar_validador_2_decimales,

    # Fechas
    fecha_actual, es_fecha_ok, normalizar_fecha, formatear_fecha, rango_fechas_ok,

    # Tickets
    REPORTLAB_OK, generate_ticket, generate_ticket_pdf, generate_ticket_txt,
)

__all__ = [
    # Recursos / sistema
    "resource_path", "centrar_ventana",

    # Tema / estilos
    "BRAND_PALETTE", "DARK_PALETTE", "apply_brand_ttk_theme", "stylize_combobox_dropdown",

    # Diálogos
    "mostrar_error", "mostrar_info", "mostrar_confirmacion",

    # Números y validaciones
    "validar_numero", "to_float", "to_int",
    "redondear_dos_decimales", "calcular_total", "formato_moneda",
    "es_decimal_hasta_2", "adjuntar_validador_2_decimales",

    # Fechas
    "fecha_actual", "es_fecha_ok", "normalizar_fecha", "formatear_fecha", "rango_fechas_ok",

    # Tickets
    "REPORTLAB_OK", "generate_ticket", "generate_ticket_pdf", "generate_ticket_txt",
]
