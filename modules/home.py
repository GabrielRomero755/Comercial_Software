# modules/home.py
# -----------------------------------------------------------
# Página de Inicio — Pantalla inicial con logo centrado
# -----------------------------------------------------------
# Muestra el fondo del panel y el logo de la empresa en el centro,
# con nombre de la empresa y slogan debajo. Todo es responsivo:
# el logo y los textos escalan con el tamaño de la ventana (si Pillow
# está disponible). Maneja correctamente eventos al destruirse para
# evitar TclError durante redimensionados/cambios de vista.
#
# Mejoras:
# - Integra paleta desde ui.theme (THEME).
# - Rutas de assets con resource_path (soporta PyInstaller).
# - Variables de entorno:
#       APP_COMPANY → nombre de la empresa (default: "Ajos La Misión")
#       APP_SLOGAN  → slogan (default: "Intelligence in every system")
# - API pública: set_company(), set_slogan(), set_logo() para actualizar
#   contenido en caliente sin reconstruir la vista.
# - Montaje por grid con fallback a pack (coherente con otros módulos).
# -----------------------------------------------------------

from __future__ import annotations

import os
import tkinter as tk
from tkinter import font as tkfont
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
    # Fallback mínimo si helpers aún no está disponible
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
COLOR_BG     = THEME.get("panel", "#34495E")   # fondo del panel principal
COLOR_TEXT   = THEME.get("text", "#ECF0F1")    # color de texto
COLOR_BORDER = THEME.get("border", "#22313F")  # borde tenue para el contenedor

# Candidatos por defecto del logo (resueltos con resource_path)
DEFAULT_LOGO_CANDIDATES = [
    resource_path("assets", "logo.png"),
    resource_path("logo.png"),
]


class HomeFrame(tk.Frame):
    def __init__(self, master=None, logo_path: Optional[str] = None,
                 company: Optional[str] = None, slogan: Optional[str] = None):
        super().__init__(master, bg=COLOR_BG, highlightthickness=0, bd=0)

        # Estado para manejo seguro de eventos y temporizadores
        self._destroyed = False
        self._after_id: Optional[str] = None
        self._after_idle_id: Optional[str] = None

        # --- Tipografías con fallbacks amigables ---
        familias = {f.lower(): f for f in tkfont.families()}
        # Título empresa (sans)
        if "segoe ui" in familias:
            title_family = familias["segoe ui"]
        elif "inter" in familias:
            title_family = familias["inter"]
        elif "arial" in familias:
            title_family = familias["arial"]
        else:
            title_family = "TkDefaultFont"
        self.company_font = tkfont.Font(family=title_family, size=26, weight="bold")

        # Slogan (mono/semi-mono para contraste)
        if "jetbrains mono" in familias:
            mono_family = familias["jetbrains mono"]
        elif "jetbrainsmono" in familias:
            mono_family = familias["jetbrainsmono"]
        elif "consolas" in familias:
            mono_family = familias["consolas"]
        elif "courier new" in familias:
            mono_family = familias["courier new"]
        else:
            mono_family = "TkFixedFont"
        self.slogan_font = tkfont.Font(family=mono_family, size=16, weight="bold")

        # --- Contenedor central tipo "card" ---
        self.center = tk.Frame(self, bg=COLOR_BG, highlightthickness=1, highlightbackground=COLOR_BORDER)
        self.center.pack(expand=True, fill="both", padx=24, pady=24)

        # Estado imagen
        self.logo_path = self._resolver_logo_path(logo_path)
        self._pil_img = None      # imagen original (Pillow) si disponible
        self._base_photo = None   # PhotoImage como fallback sin Pillow
        self._img_tk = None       # imagen renderizada actual para Tk
        self._last_wh = (0, 0)    # último tamaño renderizado (ancho, alto)

        # Widgets
        self.company_label = tk.Label(self.center, bg=COLOR_BG, fg=COLOR_TEXT, font=self.company_font)
        self.company_label.pack(padx=10, pady=(14, 6))

        self.logo_label = tk.Label(self.center, bg=COLOR_BG, bd=0, highlightthickness=0)
        self.logo_label.pack(padx=10, pady=(6, 6))

        # Nombre y slogan (parámetro > env > defaults)
        self._company = company if company is not None else os.getenv("APP_COMPANY", "Ajos La Misión")
        self._slogan_text = slogan if slogan is not None else os.getenv("APP_SLOGAN", "Intelligence in every system")

        self.company_label.configure(text=self._company)
        self.slogan_label = tk.Label(self.center, text=self._slogan_text, bg=COLOR_BG, fg=COLOR_TEXT, font=self.slogan_font)
        self.slogan_label.pack(padx=10, pady=(0, 12))

        # Cargar logo
        self._cargar_logo()

        # Vincular eventos de tamaño (con guardas)
        self.bind("<Configure>", self._on_resize, add="+")
        self.center.bind("<Configure>", self._on_resize, add="+")
        # Asegurar primer render cuando Tk calcule geometría
        self._after_idle_id = self.after_idle(self._refresh)

        # Al destruirse, limpiar timers y marcar bandera
        self.bind("<Destroy>", self._on_destroy, add="+")

    # -------------------------------------------------------
    # API pública
    # -------------------------------------------------------
    def set_slogan(self, text: str):
        """Actualiza el slogan mostrado bajo el logo."""
        if self._destroyed:
            return
        self._slogan_text = text or ""
        try:
            self.slogan_label.configure(text=self._slogan_text)
        except TclError:
            pass
        self._refresh()

    def set_company(self, name: str):
        """Actualiza el nombre de la empresa mostrado sobre el logo."""
        if self._destroyed:
            return
        self._company = name or ""
        try:
            self.company_label.configure(text=self._company)
        except TclError:
            pass
        self._refresh()

    def set_logo(self, path: str):
        """Cambia el logo en caliente. Si la ruta no existe, muestra placeholder."""
        if self._destroyed:
            return
        # Limpiar imágenes previas
        self._pil_img = None
        self._base_photo = None
        self._img_tk = None
        # Resolver ruta y recargar
        self.logo_path = self._resolver_logo_path(path)
        self._cargar_logo()
        self._refresh()

    # -------------------------------------------------------
    # Limpieza segura al destruir
    # -------------------------------------------------------
    def _on_destroy(self, _event=None):
        self._destroyed = True
        try:
            if self._after_id:
                self.after_cancel(self._after_id)
        except Exception:
            pass
        finally:
            self._after_id = None

        try:
            if self._after_idle_id:
                self.after_cancel(self._after_idle_id)
        except Exception:
            pass
        finally:
            self._after_idle_id = None

    # -------------------------------------------------------
    # Utilidades
    # -------------------------------------------------------
    def _resolver_logo_path(self, provided: Optional[str]) -> str:
        if provided and os.path.exists(provided):
            return os.path.normpath(provided)
        for cand in DEFAULT_LOGO_CANDIDATES:
            if os.path.exists(cand):
                return cand
        # Devolver la primera ruta por consistencia (aunque no exista)
        return DEFAULT_LOGO_CANDIDATES[0]

    # -------------------------------------------------------
    # Carga y render del logo
    # -------------------------------------------------------
    def _cargar_logo(self):
        """Carga la imagen del logo y prepara el primer render."""
        if os.path.exists(self.logo_path):
            if _PIL_OK:
                try:
                    img = Image.open(self.logo_path).convert("RGBA")
                    self._pil_img = img
                    return  # se renderiza en _refresh
                except Exception:
                    self._pil_img = None
            # Fallback sin PIL
            try:
                self._base_photo = tk.PhotoImage(file=self.logo_path)
                self.logo_label.configure(image=self._base_photo, text="")
                self.logo_label.image = self._base_photo
                return
            except Exception:
                self._base_photo = None

        # Placeholder si no hay logo
        self.logo_label.configure(
            image="",
            text="LOGO",
            fg=COLOR_TEXT,
            font=(self.company_font.actual("family"), 28, "bold"),
            padx=24,
            pady=24,
        )

    # -------------------------------------------------------
    # Redimensionado
    # -------------------------------------------------------
    def _on_resize(self, _event=None):
        if self._destroyed:
            return
        # Evitar TclError si el contenedor ya no existe
        try:
            if not (self.winfo_exists() and getattr(self, "center", None) and self.center.winfo_exists()):
                return
        except TclError:
            return
        self._refresh()

    def _refresh(self):
        """Ajusta tamaños del logo y textos al redimensionar."""
        if self._destroyed:
            return

        self._after_id = None  # ya estamos ejecutando

        # Tamaño real disponible del contenedor central
        try:
            if not self.center.winfo_exists():
                return
            w = max(self.center.winfo_width(), 1)
            h = max(self.center.winfo_height(), 1)
        except TclError:
            return

        # Si todavía no hay geometría válida, reintentar pronto
        if w <= 1 or h <= 1:
            self._after_id = self.after(30, self._refresh)
            return

        # Evitar renders redundantes
        if abs(w - self._last_wh[0]) < 4 and abs(h - self._last_wh[1]) < 4:
            return
        self._last_wh = (w, h)

        # Escala de textos (responsive)
        try:
            company_size = max(18, min(40, w // 18))
            slogan_size  = max(12, min(30, w // 26))
            self.company_font.configure(size=company_size)
            self.slogan_font.configure(size=slogan_size)
        except TclError:
            return

        # Reescalar el logo
        max_logo_w = int(w * 0.45)  # 45% del ancho
        max_logo_h = int(h * 0.55)  # 55% del alto
        max_logo_w = max(80, max_logo_w)
        max_logo_h = max(80, max_logo_h)

        try:
            if self._pil_img is not None:
                iw, ih = self._pil_img.size
                if iw > 0 and ih > 0:
                    scale = min(max_logo_w / iw, max_logo_h / ih)
                    scale = max(0.1, min(4.0, scale))
                    new_w, new_h = max(1, int(iw * scale)), max(1, int(ih * scale))
                    # Compatibilidad Pillow
                    try:
                        resample = Image.Resampling.LANCZOS  # Pillow >= 9.1
                    except Exception:
                        resample = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", Image.BICUBIC))
                    img_rs = self._pil_img.resize((new_w, new_h), resample)
                    self._img_tk = ImageTk.PhotoImage(img_rs)
                    self.logo_label.configure(image=self._img_tk, text="")
                    self.logo_label.image = self._img_tk  # referencia fuerte
            elif self._base_photo is not None:
                # Fallback sin PIL: usar zoom/subsample (enteros)
                iw = self._base_photo.width()
                ih = self._base_photo.height()
                if iw > 0 and ih > 0:
                    scale = min(max_logo_w / iw, max_logo_h / ih)
                    if scale >= 1:
                        factor = max(1, min(5, int(scale)))  # zoom entero
                        img = self._base_photo.zoom(factor, factor)
                    else:
                        factor = max(1, int(1 / max(scale, 1e-6)))  # subsample entero
                        img = self._base_photo.subsample(factor, factor)
                    self._img_tk = img
                    self.logo_label.configure(image=self._img_tk, text="")
                    self.logo_label.image = self._img_tk  # referencia fuerte
            # Si no hay imagen válida, ya queda el placeholder configurado
        except TclError:
            return


# -----------------------------------------------------------
# Punto de entrada para montar la vista desde main.py
# -----------------------------------------------------------
def mostrar(frame_contenido):
    for w in frame_contenido.winfo_children():
        w.destroy()
    frame = HomeFrame(frame_contenido)
    # Preferir grid como en el resto de módulos; fallback a pack si procede
    try:
        frame.grid(row=0, column=0, sticky="nsew")
    except Exception:
        frame.pack(fill="both", expand=True)
