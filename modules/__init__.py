# modules/__init__.py
# -----------------------------------------------------------
# Paquete UI
# Re-exporta utilidades de helpers y theme para importación
# conveniente: `from ui import ...`.
# IMPORTANTE: BRAND_PALETTE se obtiene desde ui.theme.
# -----------------------------------------------------------

from __future__ import annotations

# Utilidades generales (NO definen BRAND_PALETTE)
from ui.helpers import (
    centrar_ventana,
    to_float,
    formato_moneda,
    es_fecha_ok,
    normalizar_fecha,
    redondear_dos_decimales,
    adjuntar_validador_2_decimales,
)

# Tema / estilos (AQUÍ está BRAND_PALETTE)
from ui.theme import (
    apply_brand_ttk_theme,
    stylize_combobox_dropdown,
    set_treeview_stripes,
    BRAND_PALETTE,
    THEME,  # opcional, por si lo usan algunos módulos
)

__all__ = [
    # helpers
    "centrar_ventana",
    "to_float",
    "formato_moneda",
    "es_fecha_ok",
    "normalizar_fecha",
    "redondear_dos_decimales",
    "adjuntar_validador_2_decimales",
    # theme
    "apply_brand_ttk_theme",
    "stylize_combobox_dropdown",
    "set_treeview_stripes",
    "BRAND_PALETTE",
    "THEME",
]
