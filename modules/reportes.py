# modules/reportes.py
# -----------------------------------------------------------
# Sistema de Comercio — Reportes (Ventas, Gastos y Créditos)
#
# Mejoras:
# - Validación de fechas con helpers (es_fecha_ok, rango_fechas_ok).
# - Uso de formato_moneda en tablas y totales.
# - Ventas/Créditos: respeta 'total' guardado con COALESCE(v.total, v.kilos*v.precio).
# - Rango rápido (Hoy / Semana / Mes) en ventas, gastos y créditos.
# - Exportar a PDF y CSV en las 3 pestañas (PDF opcional: reportlab).
# - Una sola ventana de calendario activa para toda la vista.
# - Calendarios con TODAS las fechas activas (fuentes=("all",)).
# - ENTER en los campos de fecha ejecuta Generar; ESC cierra el calendario.
# - Mensaje de “Sin datos” cuando el rango no arroja registros.
#
# NUEVO (Windows-friendly):
# - Carpeta por defecto de exportación en Documentos\SistemaComercio\Reportes (escribible).
# - Botones Exportar PDF deshabilitados si reportlab no está disponible.
# - Exportar PDF bajo try/except con mensajes claros.
# - Compatibilidad MD5 para ReportLab en Windows: shim para 'usedforsecurity'.
# -----------------------------------------------------------

import os
import csv
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta, date
from calendar import monthrange

from db.database import get_connection
from modules.calendar_widget import CalendarioWidget
from ui.helpers import (
    redondear_dos_decimales,
    formatear_fecha,
    es_fecha_ok,
    rango_fechas_ok,
    formato_moneda,
)

# --- Shim de compatibilidad hashlib.md5 (Windows / OpenSSL sin 'usedforsecurity') ---
# Algunos builds de Python/Windows no aceptan el kwarg 'usedforsecurity' que usa ReportLab.
# Este shim lo elimina si no está soportado para evitar TypeError.
try:
    import hashlib as _hashlib
    _orig_md5 = _hashlib.md5
    try:
        # Si esto falla, es que el kwarg no está soportado y aplicamos el shim.
        _orig_md5(b"", usedforsecurity=False)  # type: ignore[arg-type]
    except TypeError:
        def _md5_compat(*args, **kwargs):
            kwargs.pop("usedforsecurity", None)
            return _orig_md5(*args, **kwargs)
        _hashlib.md5 = _md5_compat  # type: ignore[assignment]
except Exception:
    # No impedir que la app arranque si algo falla aquí.
    pass

# PDF opcional (tras el shim para que ReportLab lo herede)
try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

# Paleta oscura consistente
COLOR_BG        = "#2C3E50"
COLOR_PANEL     = "#34495E"
COLOR_TEXT      = "#ECF0F1"
COLOR_PRIMARY   = "#3498DB"
COLOR_SUCCESS   = "#2ECC71"
COLOR_DANGER    = "#E74C3C"
COLOR_ENTRY_BG  = "#3B4A5A"
COLOR_ENTRY_FG  = COLOR_TEXT
COLOR_BORDER    = "#22313F"
COLOR_SEL_BG    = "#1ABC9C"


class ReportesFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master, bg=COLOR_BG, highlightthickness=0, bd=0)

        # Estilos ttk
        self._style = ttk.Style()
        try:
            self._style.theme_use("default")
        except Exception:
            pass
        self._style.configure(
            "Dark.Treeview",
            background=COLOR_PANEL,
            fieldbackground=COLOR_PANEL,
            foreground=COLOR_TEXT,
            rowheight=24,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            darkcolor=COLOR_BORDER,
        )
        self._style.map(
            "Dark.Treeview",
            background=[("selected", COLOR_SEL_BG)],
            foreground=[("selected", COLOR_TEXT)],
        )
        self._style.configure("Dark.Treeview.Heading", background=COLOR_PANEL, foreground=COLOR_TEXT, relief="flat")
        self._style.map("Dark.Treeview.Heading", background=[("active", COLOR_PRIMARY)])

        # Única ventana de calendario
        self._calendar_win = None

        # Carpeta de exportación (Windows-friendly)
        self.output_dir = tk.StringVar(value=self._default_output_dir())

        # Buffers para exportación
        self.ventas_rows = []   # [(producto, kilos, precio, total, fecha_iso)]
        self.gastos_rows = []   # [(tipo, monto, descripcion, fecha_iso)]
        self.creditos_rows = [] # [(cliente, telefono, compras, pagos, deuda, estatus)]

        # Totales
        self.total_kilos_ventas = 0.0
        self.total_importe_ventas = 0.0
        self.total_gastos = 0.0
        self.total_compras_credito = 0.0
        self.total_pagos_realizados = 0.0
        self.total_deuda_actual = 0.0

        # Referencias a botones PDF para (des)habilitar
        self._btn_pdf_ventas = None
        self._btn_pdf_gastos = None
        self._btn_pdf_creditos = None

        self.init_ui()

    # -------------------- Helpers visuales --------------------
    def _panel(self, parent, **pack):
        f = tk.Frame(parent, bg=COLOR_PANEL, bd=0, highlightthickness=0)
        if pack:
            f.pack(**pack)
        return f

    def _lbl(self, parent, text, **grid):
        w = tk.Label(parent, text=text, bg=parent["bg"], fg=COLOR_TEXT)
        if grid:
            w.grid(**grid)
        return w

    def _entry(self, parent, width=12, textvariable=None, **grid):
        e = tk.Entry(
            parent, width=width, textvariable=textvariable,
            bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG, insertbackground=COLOR_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY
        )
        if grid:
            e.grid(**grid)
        return e

    def _btn(self, parent, text, bgc, cmd, **grid):
        b = tk.Button(
            parent, text=text, command=cmd,
            bg=bgc, fg=COLOR_TEXT, activebackground=bgc, activeforeground=COLOR_TEXT,
            relief="flat", padx=10, pady=6, cursor="hand2"
        )
        if grid:
            b.grid(**grid)
        return b

    def _tree_with_scrolls(self, parent, columnas):
        scroll_y = ttk.Scrollbar(parent, orient="vertical")
        scroll_x = ttk.Scrollbar(parent, orient="horizontal")
        tree = ttk.Treeview(
            parent, columns=columnas, show="headings", style="Dark.Treeview",
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set, height=14
        )
        scroll_y.config(command=tree.yview)
        scroll_x.config(command=tree.xview)
        tree.pack(fill="both", expand=True)
        scroll_x.pack(fill="x")
        scroll_y.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")
        return tree, scroll_x, scroll_y

    def _seleccionar_carpeta(self):
        carpeta = filedialog.askdirectory(initialdir=self.output_dir.get() or self._default_output_dir())
        if carpeta:
            try:
                os.makedirs(carpeta, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo crear la carpeta seleccionada.\n{e}")
                return
            self.output_dir.set(carpeta)

    def _ruta_export(self, nombre_archivo):
        carpeta = (self.output_dir.get() or "").strip()
        if not carpeta:
            messagebox.showerror("Carpeta no válida", "Selecciona una carpeta de destino para exportar.")
            return None
        try:
            os.makedirs(carpeta, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo acceder/crear la carpeta seleccionada.\n{e}")
            return None
        return os.path.join(carpeta, nombre_archivo)

    def _default_output_dir(self) -> str:
        """Carpeta de reportes por defecto (Documentos/SistemaComercio/Reportes)."""
        try:
            if os.name == "nt":
                base = os.environ.get("USERPROFILE", os.path.expanduser("~"))
                docs = os.path.join(base, "Documents")
            else:
                base = os.path.expanduser("~")
                docs = os.environ.get("XDG_DOCUMENTS_DIR") or os.path.join(base, "Documents")
            ruta = os.path.join(docs, "SistemaComercio", "Reportes")
            os.makedirs(ruta, exist_ok=True)
            return ruta
        except Exception:
            # Fallback: cwd
            return os.getcwd()

    # ---------------------- UI general -----------------------
    def init_ui(self):
        # Carpeta de exportación
        salida = self._panel(self, padx=8, pady=(8, 0), fill="x")
        salida.grid_columnconfigure(1, weight=1)
        self._lbl(salida, "Ubicación de guardado de reportes (PDF/CSV)", row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 8))
        self._lbl(salida, "Carpeta:", row=1, column=0, padx=6, pady=6, sticky="e")
        self.entry_output = self._entry(salida, width=50, textvariable=self.output_dir, row=1, column=1, padx=6, pady=6, sticky="we")
        self._btn(salida, "Examinar…", COLOR_PRIMARY, self._seleccionar_carpeta, row=1, column=2, padx=6, pady=6)

        # Pestañas
        tabs_container = self._panel(self, padx=6, pady=6, fill="both", expand=True)
        tabs = ttk.Notebook(tabs_container)
        tabs.pack(fill="both", expand=True)

        self.tab_ventas = tk.Frame(tabs, bg=COLOR_BG)
        self.tab_gastos = tk.Frame(tabs, bg=COLOR_BG)
        self.tab_creditos = tk.Frame(tabs, bg=COLOR_BG)

        tabs.add(self.tab_ventas, text="Reporte de Ventas")
        tabs.add(self.tab_gastos, text="Gestión de Gastos")
        tabs.add(self.tab_creditos, text="Reporte de Créditos")

        self.init_tab_ventas()
        self.init_tab_gastos()
        self.init_tab_creditos()

        # Si no hay reportlab, deshabilitar botones PDF
        if not REPORTLAB_OK:
            for b in (self._btn_pdf_ventas, self._btn_pdf_gastos, self._btn_pdf_creditos):
                if b:
                    try:
                        b.config(state="disabled", text=f"{b.cget('text')} (no disp.)")
                    except Exception:
                        pass

    # ------------------ Pestaña: Ventas ---------------------
    def init_tab_ventas(self):
        filtros = self._panel(self.tab_ventas, pady=10, padx=8, fill="x")
        filtros.grid_columnconfigure(1, weight=1)
        filtros.grid_columnconfigure(4, weight=1)

        self._lbl(filtros, "Desde:", row=0, column=0, sticky="e")
        self.fecha_inicio = self._entry(filtros, width=12, row=0, column=1, padx=5, sticky="we")
        tk.Button(
            filtros, text="📅",
            command=lambda: self.abrir_calendario(self.fecha_inicio, fuentes=("all",)),
            bg=COLOR_PRIMARY, fg=COLOR_TEXT, relief="flat", padx=6
        ).grid(row=0, column=2)

        self._lbl(filtros, "Hasta:", row=0, column=3, sticky="e")
        self.fecha_fin = self._entry(filtros, width=12, row=0, column=4, padx=5, sticky="we")
        tk.Button(
            filtros, text="📅",
            command=lambda: self.abrir_calendario(self.fecha_fin, fuentes=("all",)),
            bg=COLOR_PRIMARY, fg=COLOR_TEXT, relief="flat", padx=6
        ).grid(row=0, column=5)

        self._btn(filtros, "Generar", COLOR_PRIMARY, self.generar_reporte_ventas, row=0, column=6, padx=5)
        self._btn_pdf_ventas = self._btn(filtros, "Exportar PDF", COLOR_SUCCESS, self.exportar_pdf_ventas, row=0, column=7, padx=5)
        self._btn(filtros, "Exportar CSV", COLOR_SUCCESS, self.exportar_csv_ventas, row=0, column=8, padx=5)

        # Rango rápido
        quick = self._panel(self.tab_ventas, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", COLOR_PRIMARY, self.generar_reporte_dia).pack(side="left", padx=4)
        self._btn(quick, "Semana", COLOR_PRIMARY, self.generar_reporte_semana).pack(side="left", padx=4)
        self._btn(quick, "Mes", COLOR_PRIMARY, self.generar_reporte_mes).pack(side="left", padx=4)

        # Bind Enter en entradas
        self.fecha_inicio.bind("<Return>", lambda e: self.generar_reporte_ventas())
        self.fecha_fin.bind("<Return>", lambda e: self.generar_reporte_ventas())

        # Tabla
        tabla_panel = self._panel(self.tab_ventas, padx=6, pady=6, fill="both", expand=True)
        cols_v = ("Producto", "Kilos", "Precio", "Total", "Fecha")
        self.tree_ventas, _, _ = self._tree_with_scrolls(tabla_panel, cols_v)

        for col, width, anchor in (
            ("Producto", 180, "w"),
            ("Kilos", 90, "e"),
            ("Precio", 110, "e"),
            ("Total", 120, "e"),
            ("Fecha", 140, "center"),
        ):
            self.tree_ventas.heading(col, text=col)
            self.tree_ventas.column(col, width=width, anchor=anchor, stretch=(col == "Producto"))

        _setup_sorting(
            tree=self.tree_ventas,
            columnas=cols_v,
            tipos={"Producto": "str", "Kilos": "float", "Precio": "money", "Total": "money", "Fecha": "date"},
        )

        self.lbl_resumen_ventas = tk.Label(self.tab_ventas, text="Total kilos: 0.00 | Total importe: $0.00",
                                           bg=COLOR_BG, fg=COLOR_TEXT)
        self.lbl_resumen_ventas.pack(pady=(0, 10))

    def _leer_rango(self, e_ini: tk.Entry, e_fin: tk.Entry):
        f1 = (e_ini.get() or "").strip()
        f2 = (e_fin.get() or "").strip()
        if not (f1 and f2):
            messagebox.showwarning("Fechas faltantes", "Debes ingresar ambas fechas.")
            return None
        if not (es_fecha_ok(f1) and es_fecha_ok(f2)):
            messagebox.showerror("Formato inválido", "Usa el formato YYYY-MM-DD.")
            return None
        if not rango_fechas_ok(f1, f2):
            messagebox.showerror("Rango inválido", "La fecha 'Desde' no puede ser mayor que 'Hasta'.")
            return None
        return f1, f2

    def generar_reporte_ventas(self):
        self.tree_ventas.delete(*self.tree_ventas.get_children())
        rango = self._leer_rango(self.fecha_inicio, self.fecha_fin)
        if not rango:
            return
        fecha_ini, fecha_fin = rango

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT p.nombre,
                           COALESCE(v.kilos, 0) as kilos,
                           COALESCE(v.precio, 0) as precio,
                           COALESCE(v.total, v.kilos * v.precio) as total,
                           v.fecha
                    FROM ventas v
                    JOIN productos p ON v.producto_id = p.id
                    WHERE DATE(v.fecha) BETWEEN ? AND ?
                    ORDER BY v.fecha DESC
                """, (fecha_ini, fecha_fin))
                rows = cur.fetchall()

            self.ventas_rows = []
            tot_kilos = 0.0
            tot_importe = 0.0

            for nombre, kilos, precio, total, fecha in rows:
                k = redondear_dos_decimales(kilos)
                p = redondear_dos_decimales(precio)
                t = redondear_dos_decimales(total)
                tot_kilos += k
                tot_importe += t

                self.tree_ventas.insert("", "end", values=(
                    nombre,
                    f"{k:.2f}",
                    formato_moneda(p),
                    formato_moneda(t),
                    formatear_fecha(fecha)
                ))
                self.ventas_rows.append((nombre, float(k), float(p), float(t), str(fecha)))

            self.total_kilos_ventas = redondear_dos_decimales(tot_kilos)
            self.total_importe_ventas = redondear_dos_decimales(tot_importe)

            if not self.ventas_rows:
                messagebox.showinfo("Sin datos", "No hay ventas en el rango seleccionado.")

            self.lbl_resumen_ventas.config(
                text=f"Total kilos: {self.total_kilos_ventas:.2f} | Total importe: {formato_moneda(self.total_importe_ventas)}"
            )

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el reporte de ventas.\n{e}")

    def exportar_pdf_ventas(self):
        if not self.ventas_rows:
            messagebox.showwarning("Sin datos", "Primero genera un reporte de ventas.")
            return
        if not REPORTLAB_OK:
            messagebox.showerror("PDF no disponible", "No se encontró reportlab. Puedes exportar a CSV.")
            return

        nombre = f"reporte_ventas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return

        try:
            doc = SimpleDocTemplate(ruta, pagesize=A4)
            elementos = []
            estilo = getSampleStyleSheet()
            elementos.append(Paragraph("Reporte de Ventas", estilo['Title']))

            encabezado = ["Producto", "Kilos", "Precio Unitario", "Total", "Fecha"]
            datos = [encabezado]
            for nombre, kilos, precio, total, fecha in self.ventas_rows:
                datos.append([
                    str(nombre),
                    f"{redondear_dos_decimales(kilos):.2f}",
                    f"{redondear_dos_decimales(precio):.2f}",
                    f"{redondear_dos_decimales(total):.2f}",
                    str(fecha)
                ])

            tabla = Table(datos)
            tabla.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ]))
            elementos.append(tabla)
            elementos.append(Spacer(1, 8))
            elementos.append(Paragraph(
                f"Total kilos: {self.total_kilos_ventas:.2f} &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; "
                f"Total importe: {self.total_importe_ventas:.2f}",
                estilo['Normal']
            ))
            doc.build(elementos)
            messagebox.showinfo("Éxito", f"Reporte exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a PDF.\n{e}")

    def exportar_csv_ventas(self):
        if not self.ventas_rows:
            messagebox.showwarning("Sin datos", "Primero genera un reporte de ventas.")
            return
        nombre = f"reporte_ventas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Producto", "Kilos", "Precio Unitario", "Total", "Fecha"])
                for row in self.ventas_rows:
                    w.writerow(row)
                w.writerow([])
                w.writerow(["TOTAL KILOS", f"{self.total_kilos_ventas:.2f}"])
                w.writerow(["TOTAL IMPORTE", f"{self.total_importe_ventas:.2f}"])
            messagebox.showinfo("Éxito", f"CSV exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a CSV.\n{e}")

    # Rápidos (Ventas)
    @staticmethod
    def _rango_hoy():
        h = date.today()
        return str(h), str(h)

    @staticmethod
    def _rango_semana_actual():
        h = date.today()
        inicio = h - timedelta(days=h.weekday())
        fin = inicio + timedelta(days=6)
        return str(inicio), str(fin)

    @staticmethod
    def _rango_mes_actual():
        h = date.today()
        inicio = date(h.year, h.month, 1)
        fin = date(h.year, h.month, monthrange(h.year, h.month)[1])
        return str(inicio), str(fin)

    def generar_reporte_dia(self):
        ini, fin = self._rango_hoy()
        self.fecha_inicio.delete(0, tk.END); self.fecha_inicio.insert(0, ini)
        self.fecha_fin.delete(0, tk.END);    self.fecha_fin.insert(0, fin)
        self.generar_reporte_ventas()

    def generar_reporte_semana(self):
        ini, fin = self._rango_semana_actual()
        self.fecha_inicio.delete(0, tk.END); self.fecha_inicio.insert(0, ini)
        self.fecha_fin.delete(0, tk.END);    self.fecha_fin.insert(0, fin)
        self.generar_reporte_ventas()

    def generar_reporte_mes(self):
        ini, fin = self._rango_mes_actual()
        self.fecha_inicio.delete(0, tk.END); self.fecha_inicio.insert(0, ini)
        self.fecha_fin.delete(0, tk.END);    self.fecha_fin.insert(0, fin)
        self.generar_reporte_ventas()

    # ------------------ Pestaña: Gastos ---------------------
    def init_tab_gastos(self):
        filtros = self._panel(self.tab_gastos, pady=10, padx=8, fill="x")
        filtros.grid_columnconfigure(1, weight=1)
        filtros.grid_columnconfigure(4, weight=1)

        self._lbl(filtros, "Desde:", row=0, column=0, sticky="e")
        self.gasto_fecha_ini = self._entry(filtros, width=12, row=0, column=1, padx=5, sticky="we")
        tk.Button(
            filtros, text="📅",
            command=lambda: self.abrir_calendario(self.gasto_fecha_ini, fuentes=("all",)),
            bg=COLOR_PRIMARY, fg=COLOR_TEXT, relief="flat", padx=6
        ).grid(row=0, column=2)

        self._lbl(filtros, "Hasta:", row=0, column=3, sticky="e")
        self.gasto_fecha_fin = self._entry(filtros, width=12, row=0, column=4, padx=5, sticky="we")
        tk.Button(
            filtros, text="📅",
            command=lambda: self.abrir_calendario(self.gasto_fecha_fin, fuentes=("all",)),
            bg=COLOR_PRIMARY, fg=COLOR_TEXT, relief="flat", padx=6
        ).grid(row=0, column=5)

        self._btn(filtros, "Generar", COLOR_PRIMARY, self.generar_reporte_gastos, row=0, column=6, padx=5)
        self._btn_pdf_gastos = self._btn(filtros, "Exportar PDF", COLOR_SUCCESS, self.exportar_pdf_gastos, row=0, column=7, padx=5)
        self._btn(filtros, "Exportar CSV", COLOR_SUCCESS, self.exportar_csv_gastos, row=0, column=8, padx=5)

        # Rango rápido (nuevo)
        quick = self._panel(self.tab_gastos, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", COLOR_PRIMARY, self.generar_reporte_gastos_hoy).pack(side="left", padx=4)
        self._btn(quick, "Semana", COLOR_PRIMARY, self.generar_reporte_gastos_semana).pack(side="left", padx=4)
        self._btn(quick, "Mes", COLOR_PRIMARY, self.generar_reporte_gastos_mes).pack(side="left", padx=4)

        # Bind Enter en entradas
        self.gasto_fecha_ini.bind("<Return>", lambda e: self.generar_reporte_gastos())
        self.gasto_fecha_fin.bind("<Return>", lambda e: self.generar_reporte_gastos())

        tabla_panel = self._panel(self.tab_gastos, padx=6, pady=6, fill="both", expand=True)
        cols_g = ("Tipo", "Monto", "Descripción", "Fecha")
        self.tree_gastos, _, _ = self._tree_with_scrolls(tabla_panel, cols_g)

        for col, width, anchor in (
            ("Tipo", 160, "w"),
            ("Monto", 110, "e"),
            ("Descripción", 300, "w"),
            ("Fecha", 140, "center"),
        ):
            self.tree_gastos.heading(col, text=col)
            self.tree_gastos.column(col, width=width, anchor=anchor, stretch=(col == "Descripción"))

        _setup_sorting(
            tree=self.tree_gastos,
            columnas=cols_g,
            tipos={"Tipo": "str", "Monto": "money", "Descripción": "str", "Fecha": "date"},
        )

        self.lbl_resumen_gastos = tk.Label(self.tab_gastos, text="Total gastos: $0.00", bg=COLOR_BG, fg=COLOR_TEXT)
        self.lbl_resumen_gastos.pack(pady=(0, 10))

    def generar_reporte_gastos(self):
        self.tree_gastos.delete(*self.tree_gastos.get_children())
        rango = self._leer_rango(self.gasto_fecha_ini, self.gasto_fecha_fin)
        if not rango:
            return
        fecha_ini, fecha_fin = rango

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT tipo, monto, descripcion, fecha
                    FROM gastos
                    WHERE DATE(fecha) BETWEEN ? AND ?
                    ORDER BY fecha DESC
                """, (fecha_ini, fecha_fin))
                rows = cur.fetchall()

            self.gastos_rows = []
            total = 0.0
            for tipo, monto, descripcion, fecha in rows:
                m = redondear_dos_decimales(monto)
                total += m
                self.tree_gastos.insert("", "end", values=(tipo, formato_moneda(m), descripcion or "", formatear_fecha(fecha)))
                self.gastos_rows.append((tipo, float(m), descripcion or "", str(fecha)))

            self.total_gastos = redondear_dos_decimales(total)
            if not self.gastos_rows:
                messagebox.showinfo("Sin datos", "No hay gastos en el rango seleccionado.")
            self.lbl_resumen_gastos.config(text=f"Total gastos: {formato_moneda(self.total_gastos)}")

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el reporte de gastos.\n{e}")

    # Rápidos (Gastos)
    def generar_reporte_gastos_hoy(self):
        ini, fin = self._rango_hoy()
        self.gasto_fecha_ini.delete(0, tk.END); self.gasto_fecha_ini.insert(0, ini)
        self.gasto_fecha_fin.delete(0, tk.END); self.gasto_fecha_fin.insert(0, fin)
        self.generar_reporte_gastos()

    def generar_reporte_gastos_semana(self):
        ini, fin = self._rango_semana_actual()
        self.gasto_fecha_ini.delete(0, tk.END); self.gasto_fecha_ini.insert(0, ini)
        self.gasto_fecha_fin.delete(0, tk.END); self.gasto_fecha_fin.insert(0, fin)
        self.generar_reporte_gastos()

    def generar_reporte_gastos_mes(self):
        ini, fin = self._rango_mes_actual()
        self.gasto_fecha_ini.delete(0, tk.END); self.gasto_fecha_ini.insert(0, ini)
        self.gasto_fecha_fin.delete(0, tk.END); self.gasto_fecha_fin.insert(0, fin)
        self.generar_reporte_gastos()

    def exportar_pdf_gastos(self):
        if not self.gastos_rows:
            messagebox.showwarning("Sin datos", "Primero genera un reporte de gastos.")
            return
        if not REPORTLAB_OK:
            messagebox.showerror("PDF no disponible", "No se encontró reportlab. Puedes exportar a CSV.")
            return

        nombre = f"reporte_gastos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return
        try:
            doc = SimpleDocTemplate(ruta, pagesize=A4)
            elementos = []
            estilo = getSampleStyleSheet()
            elementos.append(Paragraph("Reporte de Gastos", estilo['Title']))

            encabezado = ["Tipo", "Monto", "Descripción", "Fecha"]
            datos = [encabezado] + [[
                str(tipo),
                f"{redondear_dos_decimales(monto):.2f}",
                str(descripcion or ""),
                str(fecha),
            ] for (tipo, monto, descripcion, fecha) in self.gastos_rows]

            tabla = Table(datos)
            tabla.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ]))
            elementos.append(tabla)
            elementos.append(Spacer(1, 8))
            elementos.append(Paragraph(f"Total gastos: {self.total_gastos:.2f}", estilo['Normal']))
            doc.build(elementos)
            messagebox.showinfo("Éxito", f"Reporte exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a PDF.\n{e}")

    def exportar_csv_gastos(self):
        if not self.gastos_rows:
            messagebox.showwarning("Sin datos", "Primero genera un reporte de gastos.")
            return
        nombre = f"reporte_gastos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Tipo", "Monto", "Descripción", "Fecha"])
                for row in self.gastos_rows:
                    w.writerow(row)
                w.writerow([])
                w.writerow(["TOTAL GASTOS", f"{self.total_gastos:.2f}"])
            messagebox.showinfo("Éxito", f"CSV exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a CSV.\n{e}")

    # ---------------- Pestaña: Créditos ---------------------
    def init_tab_creditos(self):
        filtros = self._panel(self.tab_creditos, pady=10, padx=8, fill="x")
        filtros.grid_columnconfigure(1, weight=1)
        filtros.grid_columnconfigure(4, weight=1)

        self._lbl(filtros, "Desde:", row=0, column=0, sticky="e")
        self.cred_fecha_ini = self._entry(filtros, width=12, row=0, column=1, padx=5, sticky="we")
        tk.Button(
            filtros, text="📅",
            command=lambda: self.abrir_calendario(self.cred_fecha_ini, fuentes=("all",)),
            bg=COLOR_PRIMARY, fg=COLOR_TEXT, relief="flat", padx=6
        ).grid(row=0, column=2)

        self._lbl(filtros, "Hasta:", row=0, column=3, sticky="e")
        self.cred_fecha_fin = self._entry(filtros, width=12, row=0, column=4, padx=5, sticky="we")
        tk.Button(
            filtros, text="📅",
            command=lambda: self.abrir_calendario(self.cred_fecha_fin, fuentes=("all",)),
            bg=COLOR_PRIMARY, fg=COLOR_TEXT, relief="flat", padx=6
        ).grid(row=0, column=5)

        self._btn(filtros, "Generar", COLOR_PRIMARY, self.generar_reporte_creditos, row=0, column=6, padx=5)
        self._btn_pdf_creditos = self._btn(filtros, "Exportar PDF", COLOR_SUCCESS, self.exportar_pdf_creditos, row=0, column=7, padx=5)
        self._btn(filtros, "Exportar CSV", COLOR_SUCCESS, self.exportar_csv_creditos, row=0, column=8, padx=5)

        # Rango rápido (nuevo)
        quick = self._panel(self.tab_creditos, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", COLOR_PRIMARY, self.generar_reporte_creditos_hoy).pack(side="left", padx=4)
        self._btn(quick, "Semana", COLOR_PRIMARY, self.generar_reporte_creditos_semana).pack(side="left", padx=4)
        self._btn(quick, "Mes", COLOR_PRIMARY, self.generar_reporte_creditos_mes).pack(side="left", padx=4)

        # Bind Enter en entradas
        self.cred_fecha_ini.bind("<Return>", lambda e: self.generar_reporte_creditos())
        self.cred_fecha_fin.bind("<Return>", lambda e: self.generar_reporte_creditos())

        tabla_panel = self._panel(self.tab_creditos, padx=6, pady=6, fill="both", expand=True)
        cols_c = ("Cliente", "Teléfono", "Compras a crédito", "Pagos realizados", "Deuda actual", "Estatus")
        self.tree_creditos, _, _ = self._tree_with_scrolls(tabla_panel, cols_c)

        for col, width, anchor in (
            ("Cliente", 200, "w"),
            ("Teléfono", 120, "center"),
            ("Compras a crédito", 140, "e"),
            ("Pagos realizados", 140, "e"),
            ("Deuda actual", 130, "e"),
            ("Estatus", 90, "center"),
        ):
            self.tree_creditos.heading(col, text=col)
            self.tree_creditos.column(col, width=width, anchor=anchor, stretch=(col == "Cliente"))

        _setup_sorting(
            tree=self.tree_creditos,
            columnas=cols_c,
            tipos={
                "Cliente": "str",
                "Teléfono": "str",
                "Compras a crédito": "money",
                "Pagos realizados": "money",
                "Deuda actual": "money",
                "Estatus": "str",
            },
        )

        self.lbl_resumen_creditos = tk.Label(
            self.tab_creditos,
            text="Compras: $0.00 | Pagos: $0.00 | Deuda: $0.00",
            bg=COLOR_BG, fg=COLOR_TEXT
        )
        self.lbl_resumen_creditos.pack(pady=(0, 10))

    def generar_reporte_creditos(self):
        self.tree_creditos.delete(*self.tree_creditos.get_children())
        rango = self._leer_rango(self.cred_fecha_ini, self.cred_fecha_fin)
        if not rango:
            return
        fecha_ini, fecha_fin = rango

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT
                        c.id,
                        c.nombre,
                        c.telefono,
                        COALESCE(SUM(COALESCE(v.total, v.kilos * v.precio)), 0) AS total_credito,
                        c.deuda_total
                    FROM clientes c
                    LEFT JOIN ventas v
                      ON v.cliente_id = c.id
                     AND v.tipo_venta = 'credito'
                     AND DATE(v.fecha) BETWEEN ? AND ?
                    GROUP BY c.id, c.nombre, c.telefono, c.deuda_total
                    ORDER BY c.nombre COLLATE NOCASE
                """, (fecha_ini, fecha_fin))
                rows = cur.fetchall()

            visibles = []
            tot_comp = tot_pagos = tot_deuda = 0.0
            self.creditos_rows = []
            for cid, nombre, tel, total_credito, deuda_actual in rows:
                total_credito = redondear_dos_decimales(total_credito)
                deuda_actual = redondear_dos_decimales(deuda_actual or 0.0)
                pagos = redondear_dos_decimales(max(total_credito - deuda_actual, 0.0))
                estatus = "Al día" if deuda_actual <= 0 else "Adeuda"

                if total_credito > 0 or deuda_actual > 0:
                    visibles.append((nombre, tel or "", total_credito, pagos, deuda_actual, estatus))
                    tot_comp += total_credito
                    tot_pagos += pagos
                    tot_deuda += deuda_actual

            for (cliente, tel, comp, pag, deu, est) in visibles:
                self.tree_creditos.insert("", "end", values=(
                    cliente, tel, formato_moneda(comp), formato_moneda(pag), formato_moneda(deu), est
                ))
                self.creditos_rows.append((cliente, tel, float(comp), float(pag), float(deu), est))

            self.total_compras_credito = redondear_dos_decimales(tot_comp)
            self.total_pagos_realizados = redondear_dos_decimales(tot_pagos)
            self.total_deuda_actual = redondear_dos_decimales(tot_deuda)

            if not self.creditos_rows:
                messagebox.showinfo("Sin datos", "No hay créditos en el rango seleccionado.")

            self.lbl_resumen_creditos.config(
                text=f"Compras: {formato_moneda(self.total_compras_credito)} | "
                     f"Pagos: {formato_moneda(self.total_pagos_realizados)} | "
                     f"Deuda: {formato_moneda(self.total_deuda_actual)}"
            )

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el reporte de créditos.\n{e}")

    # Rápidos (Créditos)
    def generar_reporte_creditos_hoy(self):
        ini, fin = self._rango_hoy()
        self.cred_fecha_ini.delete(0, tk.END); self.cred_fecha_ini.insert(0, ini)
        self.cred_fecha_fin.delete(0, tk.END); self.cred_fecha_fin.insert(0, fin)
        self.generar_reporte_creditos()

    def generar_reporte_creditos_semana(self):
        ini, fin = self._rango_semana_actual()
        self.cred_fecha_ini.delete(0, tk.END); self.cred_fecha_ini.insert(0, ini)
        self.cred_fecha_fin.delete(0, tk.END); self.cred_fecha_fin.insert(0, fin)
        self.generar_reporte_creditos()

    def generar_reporte_creditos_mes(self):
        ini, fin = self._rango_mes_actual()
        self.cred_fecha_ini.delete(0, tk.END); self.cred_fecha_ini.insert(0, ini)
        self.cred_fecha_fin.delete(0, tk.END); self.cred_fecha_fin.insert(0, fin)
        self.generar_reporte_creditos()

    def exportar_pdf_creditos(self):
        if not self.creditos_rows:
            messagebox.showwarning("Sin datos", "Primero genera un reporte de créditos.")
            return
        if not REPORTLAB_OK:
            messagebox.showerror("PDF no disponible", "No se encontró reportlab. Puedes exportar a CSV.")
            return

        nombre = f"reporte_creditos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return

        try:
            doc = SimpleDocTemplate(ruta, pagesize=A4)
            elementos = []
            estilo = getSampleStyleSheet()
            elementos.append(Paragraph("Reporte de Créditos", estilo['Title']))

            encabezado = ["Cliente", "Teléfono", "Compras a crédito", "Pagos realizados", "Deuda actual", "Estatus"]
            datos = [encabezado] + [[
                str(cliente),
                str(telefono),
                f"{redondear_dos_decimales(compras):.2f}",
                f"{redondear_dos_decimales(pagos):.2f}",
                f"{redondear_dos_decimales(deuda):.2f}",
                str(estatus),
            ] for (cliente, telefono, compras, pagos, deuda, estatus) in self.creditos_rows]

            tabla = Table(datos)
            tabla.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ]))
            elementos.append(tabla)
            elementos.append(Spacer(1, 8))
            elementos.append(Paragraph(
                f"Compras: {self.total_compras_credito:.2f} &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; "
                f"Pagos: {self.total_pagos_realizados:.2f} &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; "
                f"Deuda: {self.total_deuda_actual:.2f}",
                estilo['Normal']
            ))
            doc.build(elementos)
            messagebox.showinfo("Éxito", f"Reporte exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a PDF.\n{e}")

    def exportar_csv_creditos(self):
        if not self.creditos_rows:
            messagebox.showwarning("Sin datos", "Primero genera un reporte de créditos.")
            return
        nombre = f"reporte_creditos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Cliente", "Teléfono", "Compras a crédito", "Pagos realizados", "Deuda actual", "Estatus"])
                for row in self.creditos_rows:
                    w.writerow(row)
                w.writerow([])
                w.writerow(["TOTAL COMPRAS", f"{self.total_compras_credito:.2f}"])
                w.writerow(["TOTAL PAGOS", f"{self.total_pagos_realizados:.2f}"])
                w.writerow(["TOTAL DEUDA", f"{self.total_deuda_actual:.2f}"])
            messagebox.showinfo("Éxito", f"CSV exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a CSV.\n{e}")

    # ---------------- Calendario (único) --------------------
    def abrir_calendario(self, entry_widget: tk.Entry, fuentes=("all",)):
        # Cierra uno previo si está abierto
        if self._calendar_win is not None and self._calendar_win.winfo_exists():
            try:
                self._calendar_win.destroy()
            except Exception:
                pass
            self._calendar_win = None

        top = tk.Toplevel(self)
        top.title("Seleccionar fecha")
        top.resizable(False, False)
        try:
            top.configure(bg=COLOR_BG)
        except Exception:
            pass

        def _on_close():
            try:
                top.destroy()
            finally:
                self._calendar_win = None

        top.protocol("WM_DELETE_WINDOW", _on_close)
        top.bind("<Escape>", lambda e: _on_close())

        # Calendario en modo "libre" (todas fechas activas)
        CalendarioWidget(top, entry_widget, fuentes=("all",))
        self._calendar_win = top


# ---------- Ordenamiento por encabezados ----------
def _setup_sorting(tree: ttk.Treeview, columnas, tipos):
    tree._sort_state = {}
    col_index = {c: i for i, c in enumerate(columnas)}

    def parse_value(col, val):
        from datetime import datetime as _dt
        t = tipos.get(col, "str")
        s = "" if val is None else str(val).strip()
        if t == "int":
            try:
                return int(float(s.replace(",", "")))
            except Exception:
                return 0
        if t in ("float", "money"):
            try:
                s2 = s.replace("$", "").replace(",", "")
                return float(s2)
            except Exception:
                return 0.0
        if t == "date":
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    return _dt.strptime(s, fmt)
                except Exception:
                    pass
            return s
        return s.lower()

    def sort_by(col):
        reverse = not tree._sort_state.get(col, False)
        data = []
        idx = col_index[col]
        for iid in tree.get_children(""):
            vals = tree.item(iid, "values")
            v = vals[idx] if idx < len(vals) else ""
            data.append((parse_value(col, v), iid))
        data.sort(key=lambda x: x[0], reverse=reverse)
        for n, (_, iid) in enumerate(data):
            tree.move(iid, "", n)
        tree._sort_state[col] = reverse

    for c in columnas:
        tree.heading(c, text=c, command=lambda cc=c: sort_by(cc))


def mostrar(frame_contenido):
    for widget in frame_contenido.winfo_children():
        widget.destroy()
    frame = ReportesFrame(frame_contenido)
    frame.pack(fill="both", expand=True)
