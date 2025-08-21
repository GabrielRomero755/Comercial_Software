# ui/theme.py
# -----------------------------------------------------------
# Tema y paletas para la app
# - Paleta de marca (beige/rosa/café) y paleta oscura legacy.
# - apply_brand_ttk_theme(): aplica tema ttk unificado.
# - stylize_combobox_dropdown(): colorea el listbox del Combobox.
# -----------------------------------------------------------

from __future__ import annotations

from tkinter import ttk

# Paleta “marca” (beige/rosa/café)
BRAND_PALETTE = {
    "bg":        "#F5EFE6",  # beige claro (fondo)
    "panel":     "#E8D8C4",  # café muy claro
    "text":      "#3C2A21",  # café oscuro (texto)
    "primary":   "#D4A373",  # arena/caramelo (botón principal)
    "accent":    "#E5989B",  # rosa
    "success":   "#6A994E",  # verde
    "danger":    "#C8553D",  # rojo terroso
    "border":    "#B08968",  # borde tenue
    "entry_bg":  "#FFF8F0",  # fondo de entradas
    "entry_fg":  "#3C2A21",
    "sel_bg":    "#FFCAD4",  # selección
    "sel_fg":    "#3C2A21",
}

# Paleta oscura de compatibilidad
DARK_PALETTE = {
    "bg":       "#2C3E50",
    "panel":    "#34495E",
    "text":     "#ECF0F1",
    "primary":  "#3498DB",
    "accent":   "#1ABC9C",
    "success":  "#2ECC71",
    "danger":   "#E74C3C",
    "border":   "#22313F",
    "entry_bg": "#3B4A5A",
    "entry_fg": "#ECF0F1",
    "sel_bg":   "#1ABC9C",
    "sel_fg":   "#ECF0F1",
}


def apply_brand_ttk_theme(target, palette: dict = BRAND_PALETTE, treeview_style_name: str = "Brand.Treeview") -> ttk.Style:
    """
    Aplica un tema ttk consistente basado en la paleta dada.
    target: root tk.Tk / ttk.Style / widget; devuelve ttk.Style
    """
    style = target if isinstance(target, ttk.Style) else ttk.Style(target)
    try:
        style.theme_use("default")
    except Exception:
        pass

    # Base
    style.configure(".", background=palette["bg"], foreground=palette["text"])
    style.configure("TFrame", background=palette["bg"])
    style.configure("TNotebook", background=palette["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=palette["panel"], foreground=palette["text"], padding=(12, 6))
    style.map("TNotebook.Tab", background=[("selected", palette["bg"])])

    style.configure("TButton", background=palette["primary"], foreground=palette["text"], borderwidth=0, padding=(10, 6))
    style.map("TButton", background=[("active", palette["accent"])])

    style.configure("TEntry", fieldbackground=palette["entry_bg"], foreground=palette["entry_fg"])
    style.configure("TCombobox",
                    fieldbackground=palette["entry_bg"], background=palette["panel"], foreground=palette["entry_fg"])
    style.map("TCombobox",
              fieldbackground=[("readonly", palette["entry_bg"])],
              foreground=[("readonly", palette["entry_fg"])],
              background=[("readonly", palette["panel"])])

    # Treeview estilo marca
    style.configure(
        treeview_style_name,
        background=palette["panel"],
        fieldbackground=palette["panel"],
        foreground=palette["text"],
        rowheight=24,
        bordercolor=palette["border"],
        lightcolor=palette["border"],
        darkcolor=palette["border"],
    )
    style.map(
        treeview_style_name,
        background=[("selected", palette["sel_bg"])],
        foreground=[("selected", palette["sel_fg"])],
    )
    style.configure(f"{treeview_style_name}.Heading", background=palette["panel"], foreground=palette["text"], relief="flat")
    style.map(f"{treeview_style_name}.Heading", background=[("active", palette["primary"])])

    return style


def stylize_combobox_dropdown(cb, palette: dict = BRAND_PALETTE) -> None:
    """
    Aplica colores al listbox interno del Combobox (TTK popdown).
    Llamar tras crear el combobox (y cada vez que cambie el tema).
    """
    try:
        popdown = cb.tk.call("ttk::combobox::PopdownWindow", str(cb))
        win = cb.nametowidget(popdown)
        lb = win.children["f"].children["l"]  # listbox
        lb.configure(
            background=palette["panel"],
            foreground=palette["text"],
            selectbackground=palette["sel_bg"],
            selectforeground=palette["sel_fg"],
            highlightthickness=0,
            relief="flat",
            borderwidth=0,
        )
    except Exception:
        pass
