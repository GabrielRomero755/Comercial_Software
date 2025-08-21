# modules/calendar_widget.py
# -----------------------------------------------------------
# Sistema de Comercio — Calendario simple para seleccionar fechas
#
# USO / FLUJO / FUNCIONALIDAD
# -----------------------------------------------------------
# - Dibuja un calendario mensual y permite seleccionar una fecha.
# - Se usa en popups (Toplevel) o embebido en un Frame.
# - Al hacer clic en un día activo, se envía 'YYYY-MM-DD' al callback
#   (o se inserta en un Entry si se pasa un Entry).
#
# MODOS DE ACTIVACIÓN DE DÍAS
# -----------------------------------------------------------
# - Modo filtrado (por defecto): marca como activos los días con registros en
#   las tablas indicadas en 'fuentes' (p.ej. ("ventas",) o ("gastos",)).
# - Modo libre (todas las fechas activas): si 'fuentes' contiene "all", "*"
#   o "todas" (sin distinguir mayúsculas), TODOS los días del mes son activos.
#   -> Útil para Gastos y Reportes cuando se desea seleccionar cualquier fecha.
#
# ACCESIBILIDAD / ATAJOS
# -----------------------------------------------------------
# - ESC: cierra el popup (si es Toplevel).
# - ENTER: acepta la fecha (invoca el botón del día con foco).
# - PageUp / PageDown: mes anterior / siguiente.
# - Shift+PageUp / Shift+PageDown: año anterior / siguiente.
# - El foco va a "hoy" (si está en el mes visible y es activo) o al primer día activo.
#
# DETALLES TÉCNICOS
# -----------------------------------------------------------
# - Usa la paleta centralizada de ui.theme (beige/rosa/café por defecto).
# - Carga fechas del mes visible en una sola consulta por tabla.
# - Conexión a DB con context manager.
# - Permite tablas dinámicas (solo si existen en sqlite_master).
# -----------------------------------------------------------

from __future__ import annotations

import tkinter as tk
import calendar
from datetime import datetime
from typing import Iterable, Dict, Set

from db.database import get_connection
try:
    # Paleta/tema centralizados
    from ui.theme import THEME
except Exception:
    THEME = {
        "bg": "#2C3E50",
        "panel": "#34495E",
        "text": "#ECF0F1",
        "primary": "#3498DB",
        "entry_bg": "#3B4A5A",
        "muted_text": "#95A5A6",
    }

# Colores desde el tema
COLOR_BG       = THEME.get("bg", "#2C3E50")
COLOR_PANEL    = THEME.get("panel", "#34495E")
COLOR_TEXT     = THEME.get("text", "#ECF0F1")
COLOR_PRIMARY  = THEME.get("primary", "#3498DB")
COLOR_ENTRY_BG = THEME.get("entry_bg", "#3B4A5A")
COLOR_MUTED_TX = THEME.get("muted_text", "#95A5A6")

# Meses en español
MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]


class CalendarioWidget:
    def __init__(self, master, callback, fuentes: Iterable[str] = ("ventas",)):
        """
        master   : tk.Frame o tk.Toplevel
        callback : Callable[[str], None] o tk.Entry
        fuentes  : Iterable[str] (p.ej. ('ventas',), ('gastos',), ('all',))
        """
        self.master = master

        # Compatibilidad: permitir pasar un Entry como "callback"
        if isinstance(callback, tk.Entry):
            self.callback = lambda fecha: (
                callback.delete(0, tk.END),
                callback.insert(0, fecha)
            )
        else:
            self.callback = callback

        now = datetime.now()
        self.current_year = now.year
        self.current_month = now.month

        # Normalizar fuentes
        fuentes = tuple(fuentes) if fuentes else ("ventas",)
        f_norm = tuple((f or "").strip().lower() for f in fuentes)

        # Modo libre si incluyen 'all' / '*' / 'todas'
        self._all_days_active = any(f in ("all", "*", "todas") for f in f_norm)

        # En modo filtrado, conservar nombres solicitados (se validan contra sqlite_master después)
        self.fuentes = tuple(f for f in f_norm if f not in ("all", "*", "todas")) or ("ventas",)

        # Cache: día (int) -> set de fuentes presentes ese día
        self._dias_por_fuente: Dict[int, Set[str]] = {}
        # Mapa de botones de días para manejo de foco/enter
        self._day_buttons: Dict[int, tk.Button] = {}

        # Preparar contenedor y dibujar
        for widget in self.master.winfo_children():
            widget.destroy()
        try:
            self.master.configure(bg=COLOR_BG)
        except Exception:
            pass

        # Preparar ventana (si es Toplevel) y atajos de teclado
        self._prep_toplevel_and_keys()

        self.build_calendar()
        self._center_after_render()

    # ---------- Utilidades de ventana / atajos ----------
    def _as_toplevel(self):
        top = self.master.winfo_toplevel()
        return top if isinstance(top, tk.Toplevel) else None

    def _prep_toplevel_and_keys(self):
        # Vincular atajos tanto al Toplevel (si existe) como al contenedor base
        target = self._as_toplevel() or self.master

        # Si es toplevel, apariencia mínima
        top = self._as_toplevel()
        if top:
            try:
                top.configure(bg=COLOR_BG)
            except Exception:
                pass
            top.resizable(True, True)
            top.minsize(320, 280)

        # ESC para cerrar (si hay toplevel)
        if top:
            try:
                top.bind("<Escape>", lambda e: top.destroy())
            except Exception:
                pass

        # ENTER para invocar el botón con foco
        try:
            target.bind("<Return>", lambda e: self._invoke_focused_button())
        except Exception:
            pass

        # Navegación de mes/año por teclado
        try:
            target.bind("<Prior>", lambda e: self.prev_month())         # PageUp
            target.bind("<Next>", lambda e: self.next_month())          # PageDown
            target.bind("<Shift-Prior>", lambda e: self.prev_year())    # Shift+PageUp
            target.bind("<Shift-Next>", lambda e: self.next_year())     # Shift+PageDown
        except Exception:
            pass

    def _invoke_focused_button(self):
        # Invoca si el widget con foco es un Button (día)
        top = self._as_toplevel()
        w = (top.focus_get() if top else self.master.focus_get())
        try:
            if isinstance(w, tk.Button):
                w.invoke()
        except Exception:
            pass

    def _center_after_render(self):
        """Centrar el Toplevel en pantalla después de renderizar."""
        top = self._as_toplevel()
        if not top:
            return

        def _do_center():
            try:
                top.update_idletasks()
                w = top.winfo_width() or top.winfo_reqwidth()
                h = top.winfo_height() or top.winfo_reqheight()
                sw = top.winfo_screenwidth()
                sh = top.winfo_screenheight()
                x = max(0, (sw - w) // 2)
                y = max(0, (sh - h) // 2)
                top.geometry(f"+{x}+{y}")
            except Exception:
                pass

        top.after_idle(_do_center)
        top.after(50, _do_center)

    # -------------------------------------------------------
    # Construcción del calendario (tema + responsive)
    # -------------------------------------------------------
    def build_calendar(self):
        """Redibuja el calendario para (self.current_month, self.current_year)."""
        for widget in self.master.winfo_children():
            widget.destroy()

        # Cargar días con registros si es modo filtrado
        if not self._all_days_active:
            self._cargar_dias_con_registros_mes(self.current_year, self.current_month)
        else:
            self._dias_por_fuente.clear()

        self._day_buttons.clear()

        # Contenedor principal
        root = tk.Frame(self.master, bg=COLOR_BG)
        root.pack(fill="both", expand=True, padx=8, pady=8)

        # 3 filas: header, días de la semana, grilla
        root.grid_rowconfigure(0, weight=0)  # header
        root.grid_rowconfigure(1, weight=0)  # nombres días
        root.grid_rowconfigure(2, weight=1)  # grilla
        root.grid_columnconfigure(0, weight=1)

        # Encabezado de navegación
        header = tk.Frame(root, bg=COLOR_PANEL)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for c in range(5):
            header.grid_columnconfigure(c, weight=(1 if c == 2 else 0))

        btn_style = dict(
            bg=COLOR_PRIMARY, fg=COLOR_TEXT,
            activebackground=COLOR_PRIMARY, activeforeground=COLOR_TEXT,
            relief="flat", bd=0, cursor="hand2", padx=8, pady=6
        )

        tk.Button(header, text="⏮", width=3, command=self.prev_year, **btn_style)\
            .grid(row=0, column=0, padx=4, pady=6)
        tk.Button(header, text="◀", width=3, command=self.prev_month, **btn_style)\
            .grid(row=0, column=1, padx=4, pady=6)

        titulo = tk.Label(
            header,
            text=f"{MESES_ES[self.current_month]} {self.current_year}",
            font=("Arial", 12, "bold"),
            bg=COLOR_PANEL, fg=COLOR_TEXT
        )
        titulo.grid(row=0, column=2, padx=8, sticky="ew")

        tk.Button(header, text="▶", width=3, command=self.next_month, **btn_style)\
            .grid(row=0, column=3, padx=4, pady=6)
        tk.Button(header, text="⏭", width=3, command=self.next_year,  **btn_style)\
            .grid(row=0, column=4, padx=4, pady=6)

        # Encabezado días de la semana (lunes → domingo)
        dow = tk.Frame(root, bg=COLOR_PANEL)
        dow.grid(row=1, column=0, sticky="ew")
        for i in range(7):
            dow.grid_columnconfigure(i, weight=1, uniform="dow")
        dias_semana = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        for i, dia in enumerate(dias_semana):
            tk.Label(
                dow, text=dia, padx=4, pady=6,
                font=("Arial", 10, "bold"),
                bg=COLOR_PANEL, fg=COLOR_TEXT
            ).grid(row=0, column=i, padx=3, pady=2, sticky="nsew")

        # Cuadrícula de días
        grid = tk.Frame(root, bg=COLOR_BG)
        grid.grid(row=2, column=0, sticky="nsew", pady=6)
        for c in range(7):
            grid.grid_columnconfigure(c, weight=1, uniform="days")

        cal = calendar.Calendar(firstweekday=0)  # 0 = lunes
        month_days = cal.monthdayscalendar(self.current_year, self.current_month)
        for r in range(len(month_days)):
            grid.grid_rowconfigure(r, weight=1, uniform="days")

        # Render de días
        for row_idx, week in enumerate(month_days):
            for col_idx, day in enumerate(week):
                if day == 0:
                    tk.Label(grid, text="", bg=COLOR_BG).grid(
                        row=row_idx, column=col_idx, padx=3, pady=3, sticky="nsew"
                    )
                    continue

                activo = self._all_days_active or (day in self._dias_por_fuente)
                if activo:
                    btn = tk.Button(
                        grid, text=str(day),
                        bg=COLOR_ENTRY_BG, fg=COLOR_TEXT,
                        activebackground=COLOR_PRIMARY, activeforeground=COLOR_TEXT,
                        relief="flat", bd=0, cursor="hand2",
                        command=lambda d=day: self.select_date(d),
                        takefocus=1
                    )
                    btn.grid(row=row_idx, column=col_idx, padx=3, pady=3, sticky="nsew")
                    self._day_buttons[day] = btn
                else:
                    tk.Label(
                        grid, text=str(day),
                        bg=COLOR_BG, fg=COLOR_MUTED_TX
                    ).grid(row=row_idx, column=col_idx, padx=3, pady=3, sticky="nsew")

        # Colocar el foco para que ENTER funcione sin ratón
        self._focus_default_day()

    # -------------------------------------------------------
    # Foco por defecto (hoy -> 1er día activo)
    # -------------------------------------------------------
    def _focus_default_day(self):
        try:
            today = datetime.now()
            if today.year == self.current_year and today.month == self.current_month:
                d = today.day
                if self._all_days_active or (d in self._day_buttons):
                    self._day_buttons.get(d, None).focus_set()
                    return
            # Si no es el mes actual o 'hoy' no está activo, ir al primer día activo
            if self._day_buttons:
                day = min(self._day_buttons.keys())
                self._day_buttons[day].focus_set()
        except Exception:
            pass

    # -------------------------------------------------------
    # Datos
    # -------------------------------------------------------
    def _table_exists(self, conn, name: str) -> bool:
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                (name,)
            ).fetchone()
            return row is not None
        except Exception:
            return False

    def _cargar_dias_con_registros_mes(self, year: int, month: int):
        """Llena self._dias_por_fuente con los días del mes/año con registros."""
        self._dias_por_fuente.clear()
        y = f"{year:04d}"
        m = f"{month:02d}"

        try:
            with get_connection() as conn:
                for fuente in self.fuentes:
                    # Solo consultar si la tabla existe
                    if not self._table_exists(conn, fuente):
                        continue
                    try:
                        cur = conn.execute(
                            f"""
                            SELECT DISTINCT DATE(fecha)
                            FROM {fuente}
                            WHERE strftime('%Y', fecha) = ? AND strftime('%m', fecha) = ?
                            """,
                            (y, m),
                        )
                        for (fecha_str,) in cur.fetchall():
                            if not fecha_str:
                                continue
                            try:
                                d = int(fecha_str.split("-")[2])
                                self._dias_por_fuente.setdefault(d, set()).add(fuente)
                            except Exception:
                                continue
                    except Exception:
                        # Ignorar errores por tablas con esquema distinto (sin columna fecha)
                        continue
        except Exception:
            self._dias_por_fuente = {}

    # -------------------------------------------------------
    # Acciones
    # -------------------------------------------------------
    def select_date(self, day: int):
        """Dispara el callback con 'YYYY-MM-DD' y cierra si es un Toplevel."""
        fecha = datetime(self.current_year, self.current_month, day).strftime("%Y-%m-%d")
        self.callback(fecha)

        toplevel = self._as_toplevel()
        if toplevel:
            try:
                toplevel.destroy()
            except Exception:
                pass

    # -------------------------------------------------------
    # Navegación
    # -------------------------------------------------------
    def prev_month(self):
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1
        self.build_calendar()

    def next_month(self):
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        self.build_calendar()

    def prev_year(self):
        self.current_year -= 1
        self.build_calendar()

    def next_year(self):
        self.current_year += 1
        self.build_calendar()
