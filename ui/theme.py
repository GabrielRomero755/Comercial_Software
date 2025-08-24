# ui/theme.py
# -----------------------------------------------------------
# Tema y paletas para la app
# - Paleta de marca (beige/rosa/café) y paleta oscura legacy.
# - apply_brand_ttk_theme(): aplica tema ttk unificado.
# - apply_dark_ttk_theme(): aplica tema oscuro (compat).
# - apply_palette_theme(): aplicación genérica por paleta.
# - set_treeview_stripes(): alterna colores de filas.
# - stylize_combobox_dropdown(): colorea el listbox del Combobox.
# - THEME: alias de compatibilidad → paleta activa.
# -----------------------------------------------------------

from __future__ import annotations

from tkinter import ttk

# Paleta “marca” (beige/rosa/café)
BRAND_PALETTE = {
    "bg":        "#F5EFE6",  # beige claro (fondo)
    "panel":     "#E8D8C4",  # café muy claro
    "text":      "#3C2A21",  # café oscuro (texto)
    "muted":     "#6F5B53",  # texto secundario
    "primary":   "#D4A373",  # arena/caramelo (botón principal)
    "accent":    "#E5989B",  # rosa (hover/active)
    "success":   "#6A994E",  # verde
    "danger":    "#C8553D",  # rojo terroso
    "warning":   "#E9C46A",  # amarillo suave
    "border":    "#B08968",  # borde tenue
    "entry_bg":  "#FFF8F0",  # fondo de entradas
    "entry_fg":  "#3C2A21",
    "sel_bg":    "#FFCAD4",  # selección
    "sel_fg":    "#3C2A21",
    "alt_row":   "#F2E9DF",  # fila alterna treeview
    "focus":     "#8D6E63",  # indicador foco
    "link":      "#7F5539",  # enlaces/botón ghost
    # Algunas vistas esperan 'muted_text'
    "muted_text": "#6F5B53",
}

# Paleta oscura de compatibilidad
DARK_PALETTE = {
    "bg":       "#2C3E50",
    "panel":    "#34495E",
    "text":     "#ECF0F1",
    "muted":    "#C0D0DA",
    "primary":  "#3498DB",
    "accent":   "#1ABC9C",
    "success":  "#2ECC71",
    "danger":   "#E74C3C",
    "warning":  "#F1C40F",
    "border":   "#22313F",
    "entry_bg": "#3B4A5A",
    "entry_fg": "#ECF0F1",
    "sel_bg":   "#1ABC9C",
    "sel_fg":   "#ECF0F1",
    "alt_row":  "#2E4053",
    "focus":    "#5DADE2",
    "link":     "#7FB3D5",
    "muted_text": "#C0D0DA",
}

# -------- Paleta activa + compatibilidad con THEME --------
_ACTIVE_PALETTE: dict = dict(BRAND_PALETTE)  # por defecto
# Alias de compatibilidad: muchos módulos importan THEME
THEME = _ACTIVE_PALETTE  # <- importante para que from ui.theme import THEME funcione


def get_active_palette() -> dict:
    """Devuelve la paleta activa actual."""
    return _ACTIVE_PALETTE


def set_active_palette(palette: dict | str) -> None:
    """
    Cambia la paleta activa.
    - dict: paleta personalizada
    - "brand" / "dark": paletas predefinidas
    """
    global _ACTIVE_PALETTE, THEME
    if isinstance(palette, str):
        p = BRAND_PALETTE if palette.lower() in ("brand", "marca") else DARK_PALETTE
    else:
        p = dict(palette or {})
    _ACTIVE_PALETTE = _ensure_palette_keys(p)
    THEME = _ACTIVE_PALETTE  # mantener alias actualizado


def _ensure_palette_keys(p: dict) -> dict:
    """Garantiza claves requeridas y sinónimos (muted_text, etc.)."""
    base = {
        "bg": "#FFFFFF", "panel": "#F2F2F2", "text": "#222222", "muted": "#777777",
        "primary": "#4C8BF5", "accent": "#9B59B6", "success": "#2ECC71", "danger": "#E74C3C",
        "warning": "#F1C40F", "border": "#DDDDDD", "entry_bg": "#FFFFFF", "entry_fg": "#222222",
        "sel_bg": "#D0E3FF", "sel_fg": "#222222", "alt_row": "#FAFAFA", "focus": "#4C8BF5",
        "link": "#4C8BF5",
    }
    base.update(p or {})
    # Compat: si no hay muted_text, deriva de muted
    base.setdefault("muted_text", base.get("muted"))
    return base


def apply_brand_ttk_theme(target) -> ttk.Style:
    """Aplica el tema de marca y fija la paleta activa."""
    set_active_palette(BRAND_PALETTE)
    return apply_palette_theme(target, _ACTIVE_PALETTE, treeview_style_name="Brand.Treeview")


def apply_dark_ttk_theme(target) -> ttk.Style:
    """Aplica el tema oscuro de compatibilidad y fija la paleta activa."""
    set_active_palette(DARK_PALETTE)
    return apply_palette_theme(target, _ACTIVE_PALETTE, treeview_style_name="Dark.Treeview")


def apply_palette_theme(target, palette: dict, treeview_style_name: str = "Brand.Treeview") -> ttk.Style:
    """
    Aplica un tema ttk consistente basado en la paleta dada.
    target: root tk.Tk / ttk.Style / widget; devuelve ttk.Style
    """
    palette = _ensure_palette_keys(palette)
    style = target if isinstance(target, ttk.Style) else ttk.Style(target)
    try:
        style.theme_use("clam")
    except Exception:
        try:
            style.theme_use("default")
        except Exception:
            pass

    # Base
    style.configure(".", background=palette["bg"], foreground=palette["text"])
    style.map(".", foreground=[("disabled", palette.get("muted", palette["text"]))])

    # Frame / Notebook
    style.configure("TFrame", background=palette["bg"], borderwidth=0)
    style.configure("TLabelframe", background=palette["bg"], bordercolor=palette["border"])
    style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette.get("muted_text", palette["text"]))
    style.configure("TNotebook", background=palette["bg"], borderwidth=0)
    style.configure("TNotebook.Tab",
                    background=palette["panel"], foreground=palette["text"],
                    padding=(12, 6), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", palette["bg"]), ("active", palette["accent"])],
              foreground=[("selected", palette["text"])])

    # Buttons
    base_btn = {"padding": (10, 6), "borderwidth": 0, "focuscolor": palette["focus"], "foreground": palette["text"]}
    style.configure("TButton", background=palette["primary"], **base_btn)
    style.map("TButton", background=[("active", palette["accent"]), ("pressed", palette["accent"])],
              focuscolor=[("focus", palette["focus"])])
    style.configure("Success.TButton", background=palette["success"], **base_btn)
    style.map("Success.TButton", background=[("active", palette["accent"]), ("pressed", palette["accent"])])
    style.configure("Danger.TButton", background=palette["danger"], **base_btn)
    style.map("Danger.TButton", background=[("active", palette["accent"]), ("pressed", palette["accent"])])
    style.configure("Warning.TButton", background=palette["warning"], **base_btn)
    style.map("Warning.TButton", background=[("active", palette["accent"]), ("pressed", palette["accent"])])
    style.configure("Ghost.TButton", background=palette["bg"], foreground=palette["link"], borderwidth=1, relief="flat")
    style.map("Ghost.TButton", background=[("active", palette["panel"])], foreground=[("active", palette["link"])])
    style.configure("Small.TButton", padding=(8, 4))

    # Entry / Combobox
    entry_kwargs = {
        "fieldbackground": palette["entry_bg"],
        "foreground": palette["entry_fg"],
        "background": palette["panel"],
        "bordercolor": palette["border"],
        "lightcolor": palette["border"],
        "darkcolor": palette["border"],
        "padding": 2,
    }
    style.configure("TEntry", **entry_kwargs)
    style.configure("TSpinbox", **entry_kwargs)
    style.configure("TCombobox", **entry_kwargs, arrowsize=16)
    style.map("TCombobox",
              fieldbackground=[("readonly", palette["entry_bg"]), ("disabled", palette["panel"])],
              foreground=[("readonly", palette["entry_fg"]), ("disabled", palette.get("muted_text", palette["text"]))],
              background=[("readonly", palette["panel"]), ("disabled", palette["panel"])])

    # Check / Radio
    style.configure("TCheckbutton", background=palette["bg"], foreground=palette["text"])
    style.map("TCheckbutton", background=[("active", palette["panel"])], foreground=[("disabled", palette.get("muted_text", palette["text"]))])
    style.configure("TRadiobutton", background=palette["bg"], foreground=palette["text"])
    style.map("TRadiobutton", background=[("active", palette["panel"])], foreground=[("disabled", palette.get("muted_text", palette["text"]))])

    # Scrollbar
    style.configure("Vertical.TScrollbar", background=palette["panel"], troughcolor=palette["bg"],
                    bordercolor=palette["border"], lightcolor=palette["border"], darkcolor=palette["border"])
    style.map("Vertical.TScrollbar", background=[("active", palette["accent"]), ("pressed", palette["accent"])])
    style.configure("Horizontal.TScrollbar", background=palette["panel"], troughcolor=palette["bg"], bordercolor=palette["border"])
    style.map("Horizontal.TScrollbar", background=[("active", palette["accent"]), ("pressed", palette["accent"])])

    # Treeview
    style.configure(
        treeview_style_name,
        background=palette["panel"],
        fieldbackground=palette["panel"],
        foreground=palette["text"],
        rowheight=24,
        bordercolor=palette["border"],
        lightcolor=palette["border"],
        darkcolor=palette["border"],
        borderwidth=1,
    )
    style.map(treeview_style_name,
              background=[("selected", palette["sel_bg"])],
              foreground=[("selected", palette["sel_fg"])])
    style.configure(f"{treeview_style_name}.Heading",
                    background=palette["panel"], foreground=palette["text"],
                    relief="flat", borderwidth=0, padding=(6, 4))
    style.map(f"{treeview_style_name}.Heading",
              background=[("active", palette["primary"]), ("pressed", palette["primary"])])

    return style


def set_treeview_stripes(tree: ttk.Treeview, even_bg: str | None = None, odd_bg: str | None = None) -> None:
    """Aplica filas alternas al Treeview. Usa tags 'evenrow' y 'oddrow'."""
    palette = get_active_palette()
    even_bg = even_bg or palette.get("alt_row", "#F2F2F2")
    odd_bg = odd_bg or palette.get("panel", "#FFFFFF")
    tree.tag_configure("evenrow", background=even_bg)
    tree.tag_configure("oddrow", background=odd_bg)
    for idx, iid in enumerate(tree.get_children("")):
        tree.item(iid, tags=("evenrow" if idx % 2 == 0 else "oddrow",))


def stylize_combobox_dropdown(cb: ttk.Combobox, palette: dict | None = None) -> None:
    """
    Aplica colores al listbox interno del Combobox (TTK popdown).
    Llamar tras crear el combobox (y cada vez que cambie el tema).
    """
    palette = _ensure_palette_keys(palette or get_active_palette())
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
