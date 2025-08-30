# modules/home.py
# -----------------------------------------------------------
# Página de Inicio — Pantalla inicial con logo centrado
# -----------------------------------------------------------
# Muestra únicamente el logo de la aplicación en el centro.
# - El logo se redimensiona dinámicamente al espacio disponible.
# - Eliminados nombre de empresa y slogan.
# - Usa paleta THEME (ui.theme).
# - resource_path para rutas (compatible con PyInstaller).
# - Maneja eventos al destruirse para evitar errores Tkinter.
# -----------------------------------------------------------

from __future__ import annotations

import os
import tkinter as tk
from tkinter import TclError
from typing import Optional

# Tema centralizado y utilidades
try:
    from ui.theme import THEME
except Exception:
    THEME = {}
try:
    from ui.helpers import resource_path
except Exception:
    import sys
    def resource_path(*relative_parts: str) -> str:
        base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        return os.path.normpath(os.path.join(base_path, *relative_parts))

# Intentar usar Pillow para reescalar suavemente (opcional)
try:
    from PIL import Image, ImageTk  # type: ignore
    _PIL_OK = True
except Exception:
    _PIL_OK = False

# Colores desde THEME (con defaults oscuros)
COLOR_BG     = THEME.get("panel", "#34495E")
COLOR_BORDER = THEME.get("border", "#22313F")

# Candidatos por defecto del logo
DEFAULT_LOGO_CANDIDATES = [
    resource_path("assets", "logo.png"),
    resource_path("logo.png"),
]


class HomeFrame(tk.Frame):
    def __init__(self, master=None, logo_path: Optional[str] = None):
        super().__init__(master, bg=COLOR_BG, highlightthickness=0, bd=0)

        self._destroyed = False
        self._after_id: Optional[str] = None
        self._after_idle_id: Optional[str] = None

        # Contenedor central
        self.center = tk.Frame(self, bg=COLOR_BG, highlightthickness=1, highlightbackground=COLOR_BORDER)
        self.center.pack(expand=True, fill="both", padx=24, pady=24)

        # Imagen
        self.logo_path = self._resolver_logo_path(logo_path)
        self._pil_img = None
        self._base_photo = None
        self._img_tk = None
        self._last_wh = (0, 0)

        self.logo_label = tk.Label(self.center, bg=COLOR_BG, bd=0, highlightthickness=0)
        self.logo_label.pack(expand=True)

        # Cargar imagen base
        self._cargar_imagen_base()
        self._render_logo()

        # Binding de resize
        self.bind("<Configure>", self._on_resize)
        self.bind("<Destroy>", self._on_destroy)

    # ---------------------------
    # Imagen
    # ---------------------------
    def _resolver_logo_path(self, logo_path: Optional[str]) -> str:
        if logo_path and os.path.exists(logo_path):
            return logo_path
        for cand in DEFAULT_LOGO_CANDIDATES:
            if os.path.exists(cand):
                return cand
        return ""

    def _cargar_imagen_base(self):
        if not self.logo_path or not os.path.exists(self.logo_path):
            return
        try:
            if _PIL_OK:
                self._pil_img = Image.open(self.logo_path)
            else:
                self._base_photo = tk.PhotoImage(file=self.logo_path)
        except Exception:
            self._pil_img = None
            self._base_photo = None

    def _render_logo(self, wh: Optional[tuple[int, int]] = None):
        if self._destroyed:
            return
        if not self._pil_img and not self._base_photo:
            return

        try:
            w = self.center.winfo_width()
            h = self.center.winfo_height()
            if w < 50 or h < 50:
                return
            # Logo ocupa ~85% del ancho/alto disponible
            target_w = int(w * 1.00)
            target_h = int(h * 1.00)
            target = min(target_w, target_h)
            if self._last_wh == (target, target):
                return
            self._last_wh = (target, target)

            if _PIL_OK and self._pil_img:
                img_resized = self._pil_img.copy()
                img_resized.thumbnail((target, target), Image.LANCZOS)
                self._img_tk = ImageTk.PhotoImage(img_resized)
            else:
                self._img_tk = self._base_photo
            self.logo_label.configure(image=self._img_tk)
        except TclError:
            pass
        except Exception:
            pass

    def _on_resize(self, _e=None):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(100, self._render_logo)

    def _on_destroy(self, _e=None):
        self._destroyed = True
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        if self._after_idle_id:
            try:
                self.after_cancel(self._after_idle_id)
            except Exception:
                pass


def mostrar(frame_contenido):
    for widget in frame_contenido.winfo_children():
        widget.destroy()
    frame = HomeFrame(frame_contenido)
    try:
        frame.grid(row=0, column=0, sticky="nsew")
    except Exception:
        frame.pack(fill="both", expand=True)
