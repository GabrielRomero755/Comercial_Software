# modules/home.py
# -----------------------------------------------------------
# Página de Inicio — Pantalla inicial con logo centrado
# -----------------------------------------------------------
# Muestra el fondo del panel y el logo de la empresa en el centro,
# con slogan debajo. Todo es responsivo: el logo y el texto escalan
# con el tamaño de la ventana (si Pillow está disponible).
# Además, maneja correctamente eventos al destruirse para evitar
# TclError cuando se cambia de vista durante redimensionados.
#
# Mejoras:
# - Slogan configurable por variable de entorno APP_SLOGAN.
# - Métodos públicos set_slogan() y set_logo() para actualizar
#   el contenido en caliente sin reconstruir la vista.
# -----------------------------------------------------------

import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import TclError
from typing import Optional  # Compatibilidad Py3.8 (Optional en lugar de X | None)

# Intentar usar Pillow para reescalar suavemente (opcional)
try:
    from PIL import Image, ImageTk  # type: ignore
    _PIL_OK = True
except Exception:
    _PIL_OK = False

# Paleta coherente con el sistema
COLOR_PANEL  = "#34495E"  # fondo de panel
COLOR_TEXT   = "#ECF0F1"  # color de texto
COLOR_BORDER = "#22313F"  # borde tenue para el contenedor

# Rutas posibles del logo (ajústalas si tu estructura difiere)
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOGO_CANDIDATES = [
    os.path.normpath(os.path.join(THIS_DIR, "..", "assets", "logo.png")),
    os.path.normpath(os.path.join(os.getcwd(), "assets", "logo.png")),
]


class HomeFrame(tk.Frame):
    def __init__(self, master=None, logo_path: Optional[str] = None, slogan: Optional[str] = None):
        super().__init__(master, bg=COLOR_PANEL, highlightthickness=0, bd=0)

        # Estado para manejo seguro de eventos y temporizadores
        self._destroyed = False
        self._after_id: Optional[str] = None
        self._after_idle_id: Optional[str] = None

        # --- Tipografías (JetBrains Mono con fallbacks) ---
        familias = {f.lower(): f for f in tkfont.families()}
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
        self.slogan_font = tkfont.Font(family=mono_family, size=18, weight="bold")

        # --- Contenedor central tipo "card" ---
        self.center = tk.Frame(self, bg=COLOR_PANEL, highlightthickness=1, highlightbackground=COLOR_BORDER)
        self.center.pack(expand=True, fill="both", padx=24, pady=24)

        # Widgets / estado imagen
        self.logo_path = self._resolver_logo_path(logo_path)
        self._pil_img = None      # imagen original (Pillow) si disponible
        self._base_photo = None   # imagen base PhotoImage (fallback sin Pillow)
        self._img_tk = None       # imagen renderizada actual para Tk
        self._last_wh = (0, 0)    # último tamaño renderizado (ancho, alto)

        self.logo_label = tk.Label(self.center, bg=COLOR_PANEL, bd=0, highlightthickness=0)
        self.logo_label.pack(padx=10, pady=(10, 6))

        # Slogan configurable: parámetro > APP_SLOGAN > valor por defecto
        self._slogan_text = slogan if slogan is not None else os.getenv("APP_SLOGAN", "Intelligence in every system")
        self.slogan_label = tk.Label(
            self.center,
            text=self._slogan_text,
            bg=COLOR_PANEL,
            fg=COLOR_TEXT,
            font=self.slogan_font,
        )
        self.slogan_label.pack(padx=10, pady=(0, 10))

        self._cargar_logo()

        # Vincular eventos de tamaño (con guardas)
        self.bind("<Configure>", self._on_resize, add="+")
        self.center.bind("<Configure>", self._on_resize, add="+")
        # Asegurar primer render cuando Tk calcule geometría
        self._after_idle_id = self.after_idle(self._refresh)

        # Al destruirse, limpiar timers y marcar bandera
        self.bind("<Destroy>", self._on_destroy, add="+")

    # -------------------------------------------------------
    # API pública (mejoras)
    # -------------------------------------------------------
    def set_slogan(self, text: str):
        """
        Actualiza el slogan mostrado bajo el logo.
        """
        if self._destroyed:
            return
        self._slogan_text = text or ""
        try:
            self.slogan_label.configure(text=self._slogan_text)
        except TclError:
            pass
        self._refresh()

    def set_logo(self, path: str):
        """
        Cambia el logo en caliente. Si la ruta no existe, muestra placeholder.
        """
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
        # Cancelar temporizadores pendientes
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
        # Devolver la primera ruta por consistencia (aunque no exista) para logs/depuración.
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
                    # No configuramos aún la label; la imagen final se setea en _refresh()
                    return
                except Exception:
                    self._pil_img = None
            # Fallback sin PIL (no se reescala con suavizado)
            try:
                self._base_photo = tk.PhotoImage(file=self.logo_path)
                self.logo_label.configure(image=self._base_photo, text="")
                # Mantener referencia para evitar GC
                self.logo_label.image = self._base_photo
                return
            except Exception:
                self._base_photo = None

        # Placeholder si no hay logo
        self.logo_label.configure(
            image="",
            text="LOGO",
            fg=COLOR_TEXT,
            font=(self.slogan_font.actual("family"), 28, "bold"),
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
        """Ajusta el tamaño del logo y del texto al redimensionar."""
        if self._destroyed:
            return

        # Si había un after pendiente para _refresh, limpiarlo (ya estamos ejecutando)
        self._after_id = None

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

        # Evitar renders redundantes muy seguidos
        if abs(w - self._last_wh[0]) < 4 and abs(h - self._last_wh[1]) < 4:
            return
        self._last_wh = (w, h)

        # --- Escala del slogan (entre 14 y 36 pt según ancho del centro) ---
        try:
            size = max(14, min(36, w // 20))
            self.slogan_font.configure(size=size)
        except TclError:
            return

        # --- Reescalar el logo ---
        max_logo_w = int(w * 0.55)  # 55% del ancho
        max_logo_h = int(h * 0.65)  # 65% del alto (deja espacio para el slogan)
        max_logo_w = max(80, max_logo_w)
        max_logo_h = max(80, max_logo_h)

        try:
            if self._pil_img is not None:
                iw, ih = self._pil_img.size
                if iw > 0 and ih > 0:
                    scale = min(max_logo_w / iw, max_logo_h / ih)
                    scale = max(0.1, min(4.0, scale))
                    new_w, new_h = max(1, int(iw * scale)), max(1, int(ih * scale))
                    # Compatibilidad con Pillow moderno y antiguo
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
            # Si no hay imagen válida, ya queda el placeholder configurado en _cargar_logo()
        except TclError:
            # Puede ocurrir si el widget desaparece durante el render
            return


# -----------------------------------------------------------
# Punto de entrada para montar la vista desde main.py
# -----------------------------------------------------------
def mostrar(frame_contenido):
    for w in frame_contenido.winfo_children():
        w.destroy()
    frame = HomeFrame(frame_contenido)
    frame.pack(fill="both", expand=True)
