# modules/reportes.py
# -----------------------------------------------------------
# Sistema de Comercio — Reportes (Ventas, Gastos, Créditos,
# Deudas a Proveedores, Deudas de Clientes y Análisis)
#
# Cambios clave en esta versión:
# - Tema unificado con ui/theme.py (paleta BRAND por defecto).
# - Reemplazo de botones/entradas tk.* por ttk.* (estilos del tema).
# - Corrección de Matplotlib (set_xticks antes de set_xticklabels).
# - Totales en PDFs con formato_moneda para consistencia.
# - Carpeta por defecto: expansión segura de XDG_DOCUMENTS_DIR.
# - Combobox popdown estilizado y Treeview con “zebra stripes”.
# - Robustez extra al cargar combos vacíos y al parsear fechas vacías.
# - CSV con delimitador explícito y lineterminator consistente.
# - Botones PDF deshabilitados si ReportLab no está presente.
# -----------------------------------------------------------

from __future__ import annotations

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
from ui.theme import (
    apply_brand_ttk_theme,
    apply_dark_ttk_theme,
    BRAND_PALETTE,
    DARK_PALETTE,
    set_treeview_stripes,
    stylize_combobox_dropdown,
)

# --- Shim hashlib.md5 (Windows/ReportLab 'usedforsecurity') ---
try:
    import hashlib as _hashlib
    _orig_md5 = _hashlib.md5
    try:
        _orig_md5(b"", usedforsecurity=False)  # type: ignore[arg-type]
    except TypeError:
        def _md5_compat(*args, **kwargs):
            kwargs.pop("usedforsecurity", None)
            return _orig_md5(*args, **kwargs)
        _hashlib.md5 = _md5_compat  # type: ignore[assignment]
except Exception:
    pass

# PDF opcional
try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False

# Gráficas opcionales (Tk + matplotlib)
try:
    import matplotlib
    matplotlib.use("Agg")  # backend no-interactivo para generar PNG
    import matplotlib.pyplot as plt
    MATPLOTLIB_OK = True
except Exception:
    MATPLOTLIB_OK = False


class ReportesFrame(tk.Frame):
    def __init__(self, master=None, use_dark: bool = False):
        # Paleta + estilo ttk del tema
        self.palette = DARK_PALETTE if use_dark else BRAND_PALETTE
        super().__init__(master, bg=self.palette["bg"], highlightthickness=0, bd=0)

        # Estilo TTK
        try:
            self._style = apply_dark_ttk_theme(self) if use_dark else apply_brand_ttk_theme(self)
        except Exception:
            # Fallback
            self._style = ttk.Style(self)
        # Nombre de estilo para Treeviews
        self._tree_style_name = "Dark.Treeview" if use_dark else "Brand.Treeview"
        # Ajuste de altura de filas (evitar texto cortado)
        try:
            self._style.configure(self._tree_style_name, rowheight=26)
        except Exception:
            pass

        # Única ventana de calendario
        self._calendar_win = None

        # Carpeta de exportación (Windows/Linux-friendly)
        self.output_dir = tk.StringVar(value=self._default_output_dir())

        # Buffers para exportación (ventas/gastos/créditos)
        self.ventas_rows = []   # [(producto, kilos, precio, total, fecha_iso)]
        self.gastos_rows = []   # [(tipo, monto, descripcion, fecha_iso)]
        self.creditos_rows = [] # [(cliente, telefono, compras, pagos, deuda, estatus)]

        # Buffers nuevos
        self.deudas_prov_comp_rows = []   # compras crédito por proveedor
        self.deudas_prov_pagos_rows = []  # pagos a proveedor
        self.cliente_credito_rows = []    # ventas a crédito del cliente (detalle)
        self.cliente_pagos_rows = []      # pagos del cliente

        # Buffers análisis
        self.rank_producto_rows = []      # ranking por producto
        self.general_series_rows = []     # serie por fecha (general)

        # Totales existentes
        self.total_kilos_ventas = 0.0
        self.total_importe_ventas = 0.0
        self.total_gastos = 0.0
        self.total_compras_credito = 0.0
        self.total_pagos_realizados = 0.0
        self.total_deuda_actual = 0.0

        # Totales nuevos
        self.total_saldo_proveedor = 0.0
        self.total_importe_cliente = 0.0
        self.total_pagos_cliente = 0.0
        self.saldo_cliente = 0.0

        # Referencias a botones PDF para (des)habilitar
        self._btn_pdf_ventas = None
        self._btn_pdf_gastos = None
        self._btn_pdf_creditos = None
        self._btn_pdf_deudas_prov = None
        self._btn_pdf_deudas_cli = None
        self._btn_pdf_rank = None
        self._btn_pdf_general = None

        # Flags de esquema/tables opcionales
        self._has_deudas_prov = False
        self._has_pagos_prov = False
        self._has_pagos_cli = False
        self._clientes_has_direccion = False
        self._productos_cost_cols = {"costo_kg": False, "costo": False, "costo_unitario": False}

        self._detect_schema_flags()
        self.init_ui()

    # -------------------- Helpers DB/esquema -----------------
    def _table_exists(self, name: str) -> bool:
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (name,))
                return cur.fetchone() is not None
        except Exception:
            return False

    def _columns_in(self, table: str) -> set[str]:
        cols = set()
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(f"PRAGMA table_info({table})")
                for r in cur.fetchall():
                    cols.add(str(r[1]).lower())
        except Exception:
            pass
        return cols
    def _table_exists(self, name: str) -> bool:
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,))
                return cur.fetchone() is not None
        except Exception:
            return False


    def _detect_schema_flags(self):
        """Refresca flags de esquema y detecta tabla de pagos de clientes (singular/plural)."""
        # Proveedores / productos (existentes)
        self._has_deudas_prov = self._table_exists("deudas_proveedores")
        self._has_pagos_prov  = self._table_exists("pagos_proveedores")

        # Pagos de clientes: acepta plural o singular
        if self._table_exists("pagos_clientes"):
            self._pagos_cli_table = "pagos_clientes"
        elif self._table_exists("pagos_cliente"):
            self._pagos_cli_table = "pagos_cliente"
        else:
            self._pagos_cli_table = None
        self._has_pagos_cli = self._pagos_cli_table is not None  # flag único para la UI

        # Campos opcionales
        ccols = self._columns_in("clientes")
        self._clientes_has_direccion = ("direccion" in ccols)
        pcols = self._columns_in("productos")
        self._productos_cost_cols = {
            "costo_kg":       ("costo_kg" in pcols),
            "costo":          ("costo" in pcols),
            "costo_unitario": ("costo_unitario" in pcols),
        }


    # -------------------- Helpers visuales -------------------
    def _panel(self, parent, **pack):
        f = tk.Frame(parent, bg=self.palette["bg"], bd=0, highlightthickness=0)
        if pack:
            f.pack(**pack)
        return f

    def _lbl(self, parent, text, **grid):
        w = tk.Label(parent, text=text, bg=parent["bg"], fg=self.palette["text"])
        if grid:
            w.grid(**grid)
        return w

    def _entry(self, parent, width=12, textvariable=None, **grid):
        e = ttk.Entry(parent, width=width, textvariable=textvariable)
        if grid:
            e.grid(**grid)
        return e

    def _btn(self, parent, text, style, cmd, **grid):
        """
        style: "TButton" | "Success.TButton" | "Danger.TButton" | "Warning.TButton" | "Ghost.TButton" | "Small.TButton"
        """
        b = ttk.Button(parent, text=text, command=cmd, style=style)
        if grid:
            b.grid(**grid)
        return b

    def _tree_with_scrolls(self, parent, columnas):
        """Treeview con scrollbars usando GRID (evita mezclar pack/place)."""
        # Asegurar que el contenedor permita expandir la celda principal
        try:
            parent.grid_rowconfigure(0, weight=1)
            parent.grid_columnconfigure(0, weight=1)
        except Exception:
            pass

        scroll_y = ttk.Scrollbar(parent, orient="vertical", style="Vertical.TScrollbar")
        scroll_x = ttk.Scrollbar(parent, orient="horizontal", style="Horizontal.TScrollbar")

        tree = ttk.Treeview(
            parent,
            columns=columnas,
            show="headings",
            style=self._tree_style_name,
            yscrollcommand=scroll_y.set,
            xscrollcommand=scroll_x.set,
            height=14,
        )

        scroll_y.config(command=tree.yview)
        scroll_x.config(command=tree.xview)

        # Colocar con GRID (nunca pack/place aquí)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

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
                raw = os.environ.get("XDG_DOCUMENTS_DIR")
                docs = os.path.expandvars(raw) if raw else os.path.join(os.path.expanduser("~"), "Documents")
                docs = os.path.expanduser(docs)
            ruta = os.path.join(docs, "SistemaComercio", "Reportes")
            os.makedirs(ruta, exist_ok=True)
            return ruta
        except Exception:
            return os.getcwd()

    # ---------------------- UI general -----------------------
    def init_ui(self):
        # Carpeta de exportación
        salida = self._panel(self, padx=8, pady=(8, 0), fill="x")
        salida.grid_columnconfigure(1, weight=1)
        self._lbl(salida, "Ubicación de guardado de reportes (PDF/CSV)", row=0, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 8))
        self._lbl(salida, "Carpeta:", row=1, column=0, padx=6, pady=6, sticky="e")
        self.entry_output = self._entry(salida, width=50, textvariable=self.output_dir, row=1, column=1, padx=6, pady=6, sticky="we")
        self._btn(salida, "Examinar…", "TButton", self._seleccionar_carpeta, row=1, column=2, padx=6, pady=6)

        # Pestañas
        tabs_container = self._panel(self, padx=6, pady=6, fill="both", expand=True)
        tabs = ttk.Notebook(tabs_container)
        tabs.pack(fill="both", expand=True)

        # Pestañas existentes
        self.tab_ventas = tk.Frame(tabs, bg=self.palette["bg"])
        self.tab_gastos = tk.Frame(tabs, bg=self.palette["bg"])
        self.tab_creditos = tk.Frame(tabs, bg=self.palette["bg"])
        tabs.add(self.tab_ventas, text="Reporte de Ventas")
        tabs.add(self.tab_gastos, text="Gestión de Gastos")
        tabs.add(self.tab_creditos, text="Reporte de Créditos")

        # NUEVAS pestañas
        self.tab_deudas_prov = tk.Frame(tabs, bg=self.palette["bg"])
        self.tab_deudas_cli = tk.Frame(tabs, bg=self.palette["bg"])
        self.tab_analisis = tk.Frame(tabs, bg=self.palette["bg"])

        tabs.add(self.tab_deudas_prov, text="Deudas a Proveedores")
        tabs.add(self.tab_deudas_cli, text="Deudas de Clientes")
        tabs.add(self.tab_analisis, text="Análisis de Ventas")

        # Construcción de cada pestaña
        self.init_tab_ventas()
        self.init_tab_gastos()
        self.init_tab_creditos()

        self.init_tab_deudas_proveedores()
        self.init_tab_deudas_clientes()
        self.init_tab_analisis()

        # Si no hay reportlab, deshabilitar botones PDF
        for b in (
            self._btn_pdf_ventas, self._btn_pdf_gastos, self._btn_pdf_creditos,
            self._btn_pdf_deudas_prov, self._btn_pdf_deudas_cli,
            self._btn_pdf_rank, self._btn_pdf_general
        ):
            if (not REPORTLAB_OK) and b:
                try:
                    b.config(state="disabled", text=f"{b.cget('text')} (no disp.)")
                except Exception:
                    pass

    # ================== Pestaña: Ventas =====================
    def init_tab_ventas(self):
        filtros = self._panel(self.tab_ventas, pady=10, padx=8, fill="x")
        filtros.grid_columnconfigure(1, weight=1)
        filtros.grid_columnconfigure(4, weight=1)

        self._lbl(filtros, "Desde:", row=0, column=0, sticky="e")
        self.fecha_inicio = self._entry(filtros, width=12, row=0, column=1, padx=5, sticky="we")
        ttk.Button(filtros, text="📅",
                   command=lambda: self.abrir_calendario(self.fecha_inicio, fuentes=("all",)),
                   style="TButton").grid(row=0, column=2)

        self._lbl(filtros, "Hasta:", row=0, column=3, sticky="e")
        self.fecha_fin = self._entry(filtros, width=12, row=0, column=4, padx=5, sticky="we")
        ttk.Button(filtros, text="📅",
                   command=lambda: self.abrir_calendario(self.fecha_fin, fuentes=("all",)),
                   style="TButton").grid(row=0, column=5)

        self._btn(filtros, "Generar", "TButton", self.generar_reporte_ventas, row=0, column=6, padx=5)
        self._btn_pdf_ventas = self._btn(filtros, "Exportar PDF", "Success.TButton", self.exportar_pdf_ventas, row=0, column=7, padx=5)
        self._btn(filtros, "Exportar CSV", "Success.TButton", self.exportar_csv_ventas, row=0, column=8, padx=5)

        # Rango rápido
        quick = self._panel(self.tab_ventas, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", "TButton", self.generar_reporte_dia).pack(side="left", padx=4)
        self._btn(quick, "Semana", "TButton", self.generar_reporte_semana).pack(side="left", padx=4)
        self._btn(quick, "Mes", "TButton", self.generar_reporte_mes).pack(side="left", padx=4)

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

        self.lbl_resumen_ventas = tk.Label(self.tab_ventas,
                                           text="Total kilos: 0.00 | Total importe: $0.00",
                                           bg=self.palette["bg"], fg=self.palette["text"])
        self.lbl_resumen_ventas.pack(pady=(0, 10))

    def _leer_rango(self, e_ini: ttk.Entry, e_fin: ttk.Entry):
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

            # zebra stripes
            set_treeview_stripes(self.tree_ventas, even_bg=self.palette.get("alt_row", "#F2F2F2"), odd_bg=self.palette.get("panel", "#FFFFFF"))

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
                f"Total importe: {formato_moneda(self.total_importe_ventas)}",
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
                w = csv.writer(f, delimiter=",", lineterminator="\n")
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
        inicio = h - timedelta(days=6)
        fin = h
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

    # ================== Pestaña: Gastos =====================
    def init_tab_gastos(self):
        filtros = self._panel(self.tab_gastos, pady=10, padx=8, fill="x")
        filtros.grid_columnconfigure(1, weight=1)
        filtros.grid_columnconfigure(4, weight=1)

        self._lbl(filtros, "Desde:", row=0, column=0, sticky="e")
        self.gasto_fecha_ini = self._entry(filtros, width=12, row=0, column=1, padx=5, sticky="we")
        ttk.Button(filtros, text="📅",
                   command=lambda: self.abrir_calendario(self.gasto_fecha_ini, fuentes=("all",)),
                   style="TButton").grid(row=0, column=2)

        self._lbl(filtros, "Hasta:", row=0, column=3, sticky="e")
        self.gasto_fecha_fin = self._entry(filtros, width=12, row=0, column=4, padx=5, sticky="we")
        ttk.Button(filtros, text="📅",
                   command=lambda: self.abrir_calendario(self.gasto_fecha_fin, fuentes=("all",)),
                   style="TButton").grid(row=0, column=5)

        self._btn(filtros, "Generar", "TButton", self.generar_reporte_gastos, row=0, column=6, padx=5)
        self._btn_pdf_gastos = self._btn(filtros, "Exportar PDF", "Success.TButton", self.exportar_pdf_gastos, row=0, column=7, padx=5)
        self._btn(filtros, "Exportar CSV", "Success.TButton", self.exportar_csv_gastos, row=0, column=8, padx=5)

        # Rango rápido
        quick = self._panel(self.tab_gastos, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", "TButton", self.generar_reporte_gastos_hoy).pack(side="left", padx=4)
        self._btn(quick, "Semana", "TButton", self.generar_reporte_gastos_semana).pack(side="left", padx=4)
        self._btn(quick, "Mes", "TButton", self.generar_reporte_gastos_mes).pack(side="left", padx=4)

        # Bind Enter
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

        self.lbl_resumen_gastos = tk.Label(self.tab_gastos, text="Total gastos: $0.00",
                                           bg=self.palette["bg"], fg=self.palette["text"])
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

            set_treeview_stripes(self.tree_gastos, even_bg=self.palette.get("alt_row", "#F2F2F2"), odd_bg=self.palette.get("panel", "#FFFFFF"))

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
            elementos.append(Paragraph(f"Total gastos: {formato_moneda(self.total_gastos)}", estilo['Normal']))
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
                w = csv.writer(f, delimiter=",", lineterminator="\n")
                w.writerow(["Tipo", "Monto", "Descripción", "Fecha"])
                for row in self.gastos_rows:
                    w.writerow(row)
                w.writerow([])
                w.writerow(["TOTAL GASTOS", f"{self.total_gastos:.2f}"])
            messagebox.showinfo("Éxito", f"CSV exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a CSV.\n{e}")

    # ================== Pestaña: Créditos ===================
    def init_tab_creditos(self):
        filtros = self._panel(self.tab_creditos, pady=10, padx=8, fill="x")
        filtros.grid_columnconfigure(1, weight=1)
        filtros.grid_columnconfigure(4, weight=1)

        self._lbl(filtros, "Desde:", row=0, column=0, sticky="e")
        self.cred_fecha_ini = self._entry(filtros, width=12, row=0, column=1, padx=5, sticky="we")
        ttk.Button(filtros, text="📅",
                   command=lambda: self.abrir_calendario(self.cred_fecha_ini, fuentes=("all",)),
                   style="TButton").grid(row=0, column=2)

        self._lbl(filtros, "Hasta:", row=0, column=3, sticky="e")
        self.cred_fecha_fin = self._entry(filtros, width=12, row=0, column=4, padx=5, sticky="we")
        ttk.Button(filtros, text="📅",
                   command=lambda: self.abrir_calendario(self.cred_fecha_fin, fuentes=("all",)),
                   style="TButton").grid(row=0, column=5)

        self._btn(filtros, "Generar", "TButton", self.generar_reporte_creditos, row=0, column=6, padx=5)
        self._btn_pdf_creditos = self._btn(filtros, "Exportar PDF", "Success.TButton", self.exportar_pdf_creditos, row=0, column=7, padx=5)
        self._btn(filtros, "Exportar CSV", "Success.TButton", self.exportar_csv_creditos, row=0, column=8, padx=5)

        # Rango rápido
        quick = self._panel(self.tab_creditos, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", "TButton", self.generar_reporte_creditos_hoy).pack(side="left", padx=4)
        self._btn(quick, "Semana", "TButton", self.generar_reporte_creditos_semana).pack(side="left", padx=4)
        self._btn(quick, "Mes", "TButton", self.generar_reporte_creditos_mes).pack(side="left", padx=4)

        # Bind Enter
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
            bg=self.palette["bg"], fg=self.palette["text"]
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

            set_treeview_stripes(self.tree_creditos, even_bg=self.palette.get("alt_row", "#F2F2F2"), odd_bg=self.palette.get("panel", "#FFFFFF"))

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el reporte de créditos.\n{e}")

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
                f"Compras: {formato_moneda(self.total_compras_credito)} &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; "
                f"Pagos: {formato_moneda(self.total_pagos_realizados)} &nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; "
                f"Deuda: {formato_moneda(self.total_deuda_actual)}",
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
                w = csv.writer(f, delimiter=",", lineterminator="\n")
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

    # =========== NUEVA Pestaña: Deudas a Proveedores =========
    def init_tab_deudas_proveedores(self):
        top = self._panel(self.tab_deudas_prov, pady=10, padx=8, fill="x")
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(4, weight=1)

        self._lbl(top, "Proveedor:", row=0, column=0, sticky="e")
        self.combo_prov = ttk.Combobox(top, state="readonly", width=28)
        self.combo_prov.grid(row=0, column=1, padx=6, sticky="w")
        stylize_combobox_dropdown(self.combo_prov, self.palette)
        self._btn(top, "Recargar", "TButton", self._cargar_proveedores, row=0, column=2, padx=4)

        self._lbl(top, "Desde:", row=0, column=3, sticky="e")
        self.prov_fecha_ini = self._entry(top, width=12, row=0, column=4, padx=5, sticky="we")
        ttk.Button(top, text="📅",
                   command=lambda: self.abrir_calendario(self.prov_fecha_ini, fuentes=("all",)),
                   style="TButton").grid(row=0, column=5)

        self._lbl(top, "Hasta:", row=0, column=6, sticky="e")
        self.prov_fecha_fin = self._entry(top, width=12, row=0, column=7, padx=5, sticky="we")
        ttk.Button(top, text="📅",
                   command=lambda: self.abrir_calendario(self.prov_fecha_fin, fuentes=("all",)),
                   style="TButton").grid(row=0, column=8)

        self._btn(top, "Generar", "TButton", self.generar_deudas_proveedor, row=0, column=9, padx=6)
        self._btn_pdf_deudas_prov = self._btn(top, "Exportar PDF", "Success.TButton", self.exportar_pdf_deudas_prov, row=0, column=10, padx=4)
        self._btn(top, "Exportar CSV", "Success.TButton", self.exportar_csv_deudas_prov, row=0, column=11, padx=4)
        
        
        self._btn(top, "Gestionar Proveedores", "TButton", self._abrir_crud_proveedores, row=0, column=12, padx=4)


        # Rápidos
        quick = self._panel(self.tab_deudas_prov, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", "TButton", lambda: self._set_rango_and(self.prov_fecha_ini, self.prov_fecha_fin, *self._rango_hoy(), self.generar_deudas_proveedor)).pack(side="left", padx=4)
        self._btn(quick, "Semana", "TButton", lambda: self._set_rango_and(self.prov_fecha_ini, self.prov_fecha_fin, *self._rango_semana_actual(), self.generar_deudas_proveedor)).pack(side="left", padx=4)
        self._btn(quick, "Mes", "TButton", lambda: self._set_rango_and(self.prov_fecha_ini, self.prov_fecha_fin, *self._rango_mes_actual(), self.generar_deudas_proveedor)).pack(side="left", padx=4)

        # Layout de tablas
        middle = self._panel(self.tab_deudas_prov, padx=8, pady=6, fill="both", expand=True)
        middle.grid_columnconfigure(0, weight=1)
        middle.grid_columnconfigure(1, weight=1)
        left = tk.Frame(middle, bg=self.palette["panel"])
        right = tk.Frame(middle, bg=self.palette["panel"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        # Compras a crédito
        self._lbl(left, "Compras a crédito (detalle)", row=0, column=0, sticky="w", padx=6, pady=(2, 0))
        cols_comp = ("Fecha", "Producto", "Monto compra", "Saldo compra", "Descripción")
        self.tree_prov_comp, _, _ = self._tree_with_scrolls(left, cols_comp)
        for col, w, a in (
            ("Fecha", 140, "center"),
            ("Producto", 180, "w"),
            ("Monto compra", 120, "e"),
            ("Saldo compra", 120, "e"),
            ("Descripción", 240, "w"),
        ):
            self.tree_prov_comp.heading(col, text=col)
            self.tree_prov_comp.column(col, width=w, anchor=a, stretch=(col in ("Producto", "Descripción")))
        _setup_sorting(self.tree_prov_comp, cols_comp, {"Fecha":"date","Producto":"str","Monto compra":"money","Saldo compra":"money","Descripción":"str"})

        # Pagos al proveedor
        self._lbl(right, "Pagos realizados (detalle)", row=0, column=0, sticky="w", padx=6, pady=(2, 0))
        cols_pag = ("Fecha", "Descripción", "Monto pago")
        self.tree_prov_pagos, _, _ = self._tree_with_scrolls(right, cols_pag)
        for col, w, a in (("Fecha", 140, "center"), ("Descripción", 280, "w"), ("Monto pago", 120, "e")):
            self.tree_prov_pagos.heading(col, text=col)
            self.tree_prov_pagos.column(col, width=w, anchor=a, stretch=(col == "Descripción"))
        _setup_sorting(self.tree_prov_pagos, cols_pag, {"Fecha":"date","Descripción":"str","Monto pago":"money"})

        # Resumen
        self.lbl_resumen_prov = tk.Label(self.tab_deudas_prov, text="Saldo total: $0.00",
                                         bg=self.palette["bg"], fg=self.palette["text"])
        self.lbl_resumen_prov.pack(pady=(4, 10))

        # Inicial
        self._cargar_proveedores()

        # Enter en fechas
        self.prov_fecha_ini.bind("<Return>", lambda e: self.generar_deudas_proveedor())
        self.prov_fecha_fin.bind("<Return>", lambda e: self.generar_deudas_proveedor())

        # Advertencias si no hay tablas opcionales
        if not self._has_deudas_prov:
            tk.Label(self.tab_deudas_prov,
                     text="Aviso: No existe la tabla 'deudas_proveedores'. Se mostrarán 0 resultados.",
                     bg=self.palette["bg"], fg=self.palette["warning"]).pack(pady=(0, 8))

    def _cargar_proveedores(self):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, nombre FROM proveedores ORDER BY nombre COLLATE NOCASE")
                rows = cur.fetchall()
            self._prov_map = {nombre: pid for pid, nombre in rows}
            self.combo_prov["values"] = list(self._prov_map.keys())
            if rows:
                if not self.combo_prov.get():
                    self.combo_prov.current(0)
            else:
                messagebox.showinfo("Proveedores", "No hay proveedores cargados.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar proveedores.\n{e}")

    def generar_deudas_proveedor(self):
        self.tree_prov_comp.delete(*self.tree_prov_comp.get_children())
        self.tree_prov_pagos.delete(*self.tree_prov_pagos.get_children())
        self.deudas_prov_comp_rows.clear()
        self.deudas_prov_pagos_rows.clear()
        self.total_saldo_proveedor = 0.0

        prov_nom = (self.combo_prov.get() or "").strip()
        if not prov_nom:
            messagebox.showwarning("Proveedor", "Selecciona un proveedor.")
            return
        prov_id = self._prov_map.get(prov_nom)

        rango = self._leer_rango(self.prov_fecha_ini, self.prov_fecha_fin)
        if not rango:
            return
        f1, f2 = rango

        if not self._has_deudas_prov:
            messagebox.showinfo("Sin datos", "La tabla 'deudas_proveedores' no existe en la base de datos.")
            self.lbl_resumen_prov.config(text="Saldo total: $0.00")
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                # Compras a crédito (deudas)
                cur.execute("""
                    SELECT dp.fecha, IFNULL(prod.nombre,''), dp.monto, dp.saldo, IFNULL(dp.descripcion,'')
                    FROM deudas_proveedores dp
                    LEFT JOIN productos prod ON prod.id = dp.producto_id
                    WHERE dp.proveedor_id = ? AND DATE(dp.fecha) BETWEEN ? AND ?
                    ORDER BY dp.fecha DESC
                """, (prov_id, f1, f2))
                comp = cur.fetchall()

                # Pagos a proveedor (opcional)
                pagos = []
                if self._has_pagos_prov:
                    cols = self._columns_in("pagos_proveedores")
                    # Estrategias de join según esquema disponible
                    if "proveedor_id" in cols:
                        cur.execute("""
                            SELECT fecha, IFNULL(descripcion,''), monto
                            FROM pagos_proveedores
                            WHERE proveedor_id = ? AND DATE(fecha) BETWEEN ? AND ?
                            ORDER BY fecha DESC
                        """, (prov_id, f1, f2))
                        pagos = cur.fetchall()
                    elif "deuda_proveedor_id" in cols:
                        cur.execute("""
                            SELECT pp.fecha, IFNULL(pp.descripcion,''), pp.monto
                            FROM pagos_proveedores pp
                            WHERE DATE(pp.fecha) BETWEEN ? AND ?
                              AND pp.deuda_proveedor_id IN (
                                  SELECT id FROM deudas_proveedores
                                  WHERE proveedor_id = ?
                              )
                            ORDER BY pp.fecha DESC
                        """, (f1, f2, prov_id))
                        pagos = cur.fetchall()

            # Cargar tablas
            saldo_total = 0.0
            for fecha, prod, monto, saldo, desc in comp:
                m = redondear_dos_decimales(monto or 0.0)
                s = redondear_dos_decimales(saldo or 0.0)
                self.tree_prov_comp.insert("", "end", values=(formatear_fecha(fecha), prod, formato_moneda(m), formato_moneda(s), desc))
                self.deudas_prov_comp_rows.append((str(fecha), prod, float(m), float(s), desc))
                saldo_total += s

            for fecha, desc, monto in pagos:
                mo = redondear_dos_decimales(monto or 0.0)
                self.tree_prov_pagos.insert("", "end", values=(formatear_fecha(fecha), desc, formato_moneda(mo)))
                self.deudas_prov_pagos_rows.append((str(fecha), desc, float(mo)))

            self.total_saldo_proveedor = redondear_dos_decimales(saldo_total)

            if not comp and not pagos:
                messagebox.showinfo("Sin datos", "No hay movimientos en el rango seleccionado.")

            self.lbl_resumen_prov.config(text=f"Saldo total: {formato_moneda(self.total_saldo_proveedor)}")

            set_treeview_stripes(self.tree_prov_comp, even_bg=self.palette.get("alt_row", "#F2F2F2"), odd_bg=self.palette.get("panel", "#FFFFFF"))
            set_treeview_stripes(self.tree_prov_pagos, even_bg=self.palette.get("alt_row", "#F2F2F2"), odd_bg=self.palette.get("panel", "#FFFFFF"))

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el reporte de proveedor.\n{e}")

    def exportar_csv_deudas_prov(self):
        if not (self.deudas_prov_comp_rows or self.deudas_prov_pagos_rows):
            messagebox.showwarning("Sin datos", "Primero genera el reporte.")
            return
        nombre = f"deudas_proveedor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=",", lineterminator="\n")
                w.writerow(["== COMPRAS A CRÉDITO =="])
                w.writerow(["Fecha", "Producto", "Monto", "Saldo", "Descripción"])
                for r in self.deudas_prov_comp_rows:
                    w.writerow(r)
                w.writerow([])
                w.writerow(["== PAGOS REALIZADOS =="])
                w.writerow(["Fecha", "Descripción", "Monto"])
                for r in self.deudas_prov_pagos_rows:
                    w.writerow(r)
                w.writerow([])
                w.writerow(["SALDO TOTAL", f"{self.total_saldo_proveedor:.2f}"])
            messagebox.showinfo("Éxito", f"CSV exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a CSV.\n{e}")
    

    def exportar_pdf_deudas_prov(self):
        if not REPORTLAB_OK:
            messagebox.showerror("PDF no disponible", "No se encontró reportlab.")
            return
        if not (self.deudas_prov_comp_rows or self.deudas_prov_pagos_rows):
            messagebox.showwarning("Sin datos", "Primero genera el reporte.")
            return

        nombre = f"deudas_proveedor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return

        try:
            doc = SimpleDocTemplate(ruta, pagesize=A4)
            elementos = []
            estilo = getSampleStyleSheet()
            prov = self.combo_prov.get() or "Proveedor"
            elementos.append(Paragraph(f"Deudas a Proveedores — {prov}", estilo['Title']))

            # Compras
            datos1 = [["Fecha", "Producto", "Monto", "Saldo", "Descripción"]]
            for f, prod, monto, saldo, desc in self.deudas_prov_comp_rows:
                datos1.append([f, prod, f"{redondear_dos_decimales(monto):.2f}", f"{redondear_dos_decimales(saldo):.2f}", desc])
            tabla1 = Table(datos1)
            tabla1.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
            ]))
            elementos.append(tabla1)
            elementos.append(Spacer(1, 8))

            # Pagos
            datos2 = [["Fecha", "Descripción", "Monto"]]
            for f, desc, monto in self.deudas_prov_pagos_rows:
                datos2.append([f, desc, f"{redondear_dos_decimales(monto):.2f}"])
            tabla2 = Table(datos2)
            tabla2.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
            ]))
            elementos.append(tabla2)
            elementos.append(Spacer(1, 8))
            elementos.append(Paragraph(
                f"Saldo total: {formato_moneda(self.total_saldo_proveedor)}",
                estilo['Normal']
            ))
            doc.build(elementos)
            messagebox.showinfo("Éxito", f"Reporte exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a PDF.\n{e}")

    def _abrir_crud_proveedores(self):
        top = tk.Toplevel(self)
        top.title("Proveedores")
        try:
            top.configure(bg=self.palette["bg"])
        except Exception:
            pass
        top.transient(self.winfo_toplevel())
        top.grab_set()
        top.bind("<Escape>", lambda _: top.destroy())

        for c in range(3):
            top.grid_columnconfigure(c, weight=(1 if c == 1 else 0))

        tk.Label(top, text="Nombre:", bg=self.palette["bg"], fg=self.palette["text"]).grid(row=0, column=0, padx=8, pady=6, sticky="e")
        ent_nombre = ttk.Entry(top, width=26, style="TEntry"); ent_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we")

        tk.Label(top, text="Teléfono:", bg=self.palette["bg"], fg=self.palette["text"]).grid(row=1, column=0, padx=8, pady=6, sticky="e")
        ent_tel = ttk.Entry(top, width=20, style="TEntry"); ent_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we")

        def cargar_lista():
            tree.delete(*tree.get_children())
            try:
                with get_connection() as conn:
                    rows = conn.execute("SELECT id, nombre, IFNULL(telefono,'') FROM proveedores ORDER BY nombre COLLATE NOCASE").fetchall()
                for r in rows:
                    # r puede ser tuple o sqlite Row; cubrir ambos
                    pid = r[0] if isinstance(r, tuple) else r["id"]
                    nom = r[1] if isinstance(r, tuple) else r["nombre"]
                    tel = r[2] if isinstance(r, tuple) else r["telefono"]
                    tree.insert("", "end", values=(pid, nom, tel))
                set_treeview_stripes(tree, even_bg=self.palette.get("alt_row"), odd_bg=self.palette.get("panel"))
            except Exception:
                pass

        def add_prov(_=None):
            nombre = (ent_nombre.get() or "").strip()
            tel = (ent_tel.get() or "").strip()
            if not nombre:
                messagebox.showerror("Error", "El nombre es obligatorio.", parent=top)
                return
            try:
                with get_connection() as conn:
                    conn.execute("INSERT INTO proveedores (nombre, telefono) VALUES (?, ?)", (nombre, tel))
                ent_nombre.delete(0, tk.END); ent_tel.delete(0, tk.END)
                cargar_lista(); self._cargar_proveedores()
                messagebox.showinfo("Éxito", "Proveedor agregado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo agregar el proveedor.\n{e}", parent=top)

        ttk.Button(top, text="Agregar", command=add_prov, style="Success.TButton").grid(row=2, column=0, columnspan=2, padx=8, pady=(4, 8))
        top.bind("<Return>", add_prov)

        cols = ("ID", "Nombre", "Teléfono")
        tree = ttk.Treeview(top, columns=cols, show="headings", style=self._tree_style_name, height=10)
        for c, w in (("ID", 70), ("Nombre", 220), ("Teléfono", 160)):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor=("center" if c == "ID" else "w"))
        tree.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=(6, 6))
        top.grid_rowconfigure(3, weight=1)

        def editar():
            item = tree.focus()
            if not item:
                messagebox.showerror("Error", "Selecciona un proveedor.", parent=top)
                return
            vals = tree.item(item, "values")
            pid = int(vals[0]); nombre = vals[1]; tel = vals[2]

            w = tk.Toplevel(top)
            w.title("Editar proveedor")
            try:
                w.configure(bg=self.palette["bg"])
            except Exception:
                pass
            w.transient(top); w.grab_set()
            w.bind("<Escape>", lambda _: w.destroy())

            tk.Label(w, text="Nombre:", bg=self.palette["bg"], fg=self.palette["text"]).grid(row=0, column=0, padx=8, pady=6, sticky="e")
            e_nombre = ttk.Entry(w, width=26, style="TEntry"); e_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we"); e_nombre.insert(0, nombre)

            tk.Label(w, text="Teléfono:", bg=self.palette["bg"], fg=self.palette["text"]).grid(row=1, column=0, padx=8, pady=6, sticky="e")
            e_tel = ttk.Entry(w, width=20, style="TEntry"); e_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we"); e_tel.insert(0, tel)

            w.grid_columnconfigure(1, weight=1)

            def save(_=None):
                n = (e_nombre.get() or "").strip()
                t = (e_tel.get() or "").strip()
                if not n:
                    messagebox.showerror("Error", "El nombre es obligatorio.", parent=w)
                    return
                try:
                    with get_connection() as conn:
                        conn.execute("UPDATE proveedores SET nombre = ?, telefono = ? WHERE id = ?", (n, t, pid))
                    cargar_lista(); self._cargar_proveedores()
                    messagebox.showinfo("Éxito", "Proveedor actualizado.", parent=w)
                    w.destroy()
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo actualizar el proveedor.\n{e}", parent=w)

            ttk.Button(w, text="Guardar", command=save, style="Success.TButton").grid(row=2, column=0, columnspan=2, pady=8)
            w.bind("<Return>", save)

        def eliminar():
            item = tree.focus()
            if not item:
                messagebox.showerror("Error", "Selecciona un proveedor.", parent=top)
                return
            vals = tree.item(item, "values")
            pid = int(vals[0]); nombre = vals[1]
            if not messagebox.askyesno("Confirmar", f"¿Eliminar proveedor '{nombre}'?", parent=top):
                return
            try:
                with get_connection() as conn:
                    # Evitar borrar si tiene registros referenciados en deudas/pagos
                    refs = 0
                    try:
                        refs += conn.execute("SELECT COUNT(*) FROM deudas_proveedores WHERE proveedor_id = ?", (pid,)).fetchone()[0]
                    except Exception:
                        pass
                    try:
                        refs += conn.execute("SELECT COUNT(*) FROM pagos_proveedores WHERE proveedor_id = ?", (pid,)).fetchone()[0]
                    except Exception:
                        pass
                    if refs > 0:
                        messagebox.showwarning("No permitido", "No se puede eliminar: tiene movimientos asociados.", parent=top)
                        return
                    conn.execute("DELETE FROM proveedores WHERE id = ?", (pid,))
                cargar_lista(); self._cargar_proveedores()
                messagebox.showinfo("Éxito", "Proveedor eliminado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el proveedor.\n{e}", parent=top)

        ttk.Button(top, text="Editar", command=editar, style="TButton").grid(row=4, column=0, padx=8, pady=(0, 8), sticky="ew")
        ttk.Button(top, text="Eliminar", command=eliminar, style="Danger.TButton").grid(row=4, column=1, padx=8, pady=(0, 8), sticky="ew")
        ttk.Button(top, text="Cerrar", command=top.destroy, style="TButton").grid(row=4, column=2, padx=8, pady=(0, 8), sticky="ew")

        cargar_lista()

    # ========= NUEVA Pestaña: Deudas de Clientes ============
    def init_tab_deudas_clientes(self):
        top = self._panel(self.tab_deudas_cli, pady=10, padx=8, fill="x")
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(4, weight=1)

        self._lbl(top, "Cliente:", row=0, column=0, sticky="e")
        self.combo_cli = ttk.Combobox(top, state="readonly", width=28)
        self.combo_cli.grid(row=0, column=1, padx=6, sticky="w")
        stylize_combobox_dropdown(self.combo_cli, self.palette)
        self._btn(top, "Recargar", "TButton", self._cargar_clientes, row=0, column=2, padx=4)

        self._lbl(top, "Desde:", row=0, column=3, sticky="e")
        self.cli_fecha_ini = self._entry(top, width=12, row=0, column=4, padx=5, sticky="we")
        ttk.Button(top, text="📅",
                   command=lambda: self.abrir_calendario(self.cli_fecha_ini, fuentes=("all",)),
                   style="TButton").grid(row=0, column=5)

        self._lbl(top, "Hasta:", row=0, column=6, sticky="e")
        self.cli_fecha_fin = self._entry(top, width=12, row=0, column=7, padx=5, sticky="we")
        ttk.Button(top, text="📅",
                   command=lambda: self.abrir_calendario(self.cli_fecha_fin, fuentes=("all",)),
                   style="TButton").grid(row=0, column=8)

        self._btn(top, "Generar", "TButton", self.generar_deudas_cliente, row=0, column=9, padx=6)
        self._btn_pdf_deudas_cli = self._btn(top, "Exportar PDF", "Success.TButton", self.exportar_pdf_deudas_cli, row=0, column=10, padx=4)
        self._btn(top, "Exportar CSV", "Success.TButton", self.exportar_csv_deudas_cli, row=0, column=11, padx=4)

        # Info del cliente
        info = self._panel(self.tab_deudas_cli, pady=4, padx=8, fill="x")
        self.lbl_info_cliente = tk.Label(info, text="Tel.: s/d | Dirección: s/d",
                                         bg=self.palette["bg"], fg=self.palette["text"], anchor="w")
        self.lbl_info_cliente.pack(fill="x")

        # Rápidos
        quick = self._panel(self.tab_deudas_cli, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", "TButton", lambda: self._set_rango_and(self.cli_fecha_ini, self.cli_fecha_fin, *self._rango_hoy(), self.generar_deudas_cliente)).pack(side="left", padx=4)
        self._btn(quick, "Semana", "TButton", lambda: self._set_rango_and(self.cli_fecha_ini, self.cli_fecha_fin, *self._rango_semana_actual(), self.generar_deudas_cliente)).pack(side="left", padx=4)
        self._btn(quick, "Mes", "TButton", lambda: self._set_rango_and(self.cli_fecha_ini, self.cli_fecha_fin, *self._rango_mes_actual(), self.generar_deudas_cliente)).pack(side="left", padx=4)

        # Layout tablas
        middle = self._panel(self.tab_deudas_cli, padx=8, pady=6, fill="both", expand=True)
        middle.grid_columnconfigure(0, weight=1)
        middle.grid_columnconfigure(1, weight=1)
        left = tk.Frame(middle, bg=self.palette["panel"])
        right = tk.Frame(middle, bg=self.palette["panel"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        # Ventas a crédito (detalle por producto)
        self._lbl(left, "Ventas a crédito (detalle por producto)", row=0, column=0, sticky="w", padx=6, pady=(2, 0))
        cols_cli_v = ("Fecha", "Producto", "Unidades", "Kilos", "Precio", "Total")
        self.tree_cli_vtas, _, _ = self._tree_with_scrolls(left, cols_cli_v)
        for col, w, a in (
            ("Fecha", 140, "center"),
            ("Producto", 220, "w"),
            ("Unidades", 90, "e"),
            ("Kilos", 90, "e"),
            ("Precio", 110, "e"),
            ("Total", 120, "e"),
        ):
            self.tree_cli_vtas.heading(col, text=col)
            self.tree_cli_vtas.column(col, width=w, anchor=a, stretch=(col == "Producto"))
        _setup_sorting(self.tree_cli_vtas, cols_cli_v, {"Fecha":"date","Producto":"str","Unidades":"float","Kilos":"float","Precio":"money","Total":"money"})

        # Pagos individuales del cliente
        self._lbl(right, "Pagos del cliente (individuales)", row=0, column=0, sticky="w", padx=6, pady=(2, 0))
        cols_cli_p = ("Fecha", "Descripción", "Monto")
        self.tree_cli_pagos, _, _ = self._tree_with_scrolls(right, cols_cli_p)
        for col, w, a in (("Fecha", 140, "center"), ("Descripción", 280, "w"), ("Monto", 120, "e")):
            self.tree_cli_pagos.heading(col, text=col)
            self.tree_cli_pagos.column(col, width=w, anchor=a, stretch=(col == "Descripción"))
        _setup_sorting(self.tree_cli_pagos, cols_cli_p, {"Fecha":"date","Descripción":"str","Monto":"money"})

        # Resumen
        self.lbl_resumen_cli = tk.Label(self.tab_deudas_cli, text="Compras: $0.00 | Pagos: $0.00 | Saldo: $0.00",
                                        bg=self.palette["bg"], fg=self.palette["text"])
        self.lbl_resumen_cli.pack(pady=(4, 10))

        # Inicial
        self._cargar_clientes()

        # Enter fechas
        self.cli_fecha_ini.bind("<Return>", lambda e: self.generar_deudas_cliente())
        self.cli_fecha_fin.bind("<Return>", lambda e: self.generar_deudas_cliente())

        # Aviso si no hay tabla de pagos de clientes (singular o plural)
        if not self._has_pagos_cli:
            tk.Label(
                self.tab_deudas_cli,
                text="Aviso: No existe la tabla de pagos de clientes ('pagos_clientes' o 'pagos_cliente'). Se mostrarán 0 pagos.",
                bg=self.palette["bg"],
                fg=self.palette["warning"]
            ).pack(pady=(0, 8))




    def _cargar_clientes(self):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre COLLATE NOCASE")
                rows = cur.fetchall()
            self._cli_map = {nombre: cid for cid, nombre in rows}
            self.combo_cli["values"] = list(self._cli_map.keys())
            if rows:
                if not self.combo_cli.get():
                    self.combo_cli.current(0)
            else:
                messagebox.showinfo("Clientes", "No hay clientes cargados.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar clientes.\n{e}")

    def _set_info_cliente(self, cid: int):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cols = self._columns_in("clientes")
                if "direccion" in cols:
                    cur.execute("SELECT IFNULL(telefono,''), IFNULL(direccion,'s/d') FROM clientes WHERE id = ?", (cid,))
                    row = cur.fetchone()
                    tel, dirx = (row or ("s/d", "s/d"))
                else:
                    cur.execute("SELECT IFNULL(telefono,'') FROM clientes WHERE id = ?", (cid,))
                    row = cur.fetchone()
                    tel, dirx = ((row[0] if row else "s/d"), "s/d")
            self.lbl_info_cliente.config(text=f"Tel.: {tel or 's/d'} | Dirección: {dirx or 's/d'}")
        except Exception:
            self.lbl_info_cliente.config(text="Tel.: s/d | Dirección: s/d")

    def generar_deudas_cliente(self):
        self.tree_cli_vtas.delete(*self.tree_cli_vtas.get_children())
        self.tree_cli_pagos.delete(*self.tree_cli_pagos.get_children())
        self.cliente_credito_rows.clear()
        self.cliente_pagos_rows.clear()

        # Refrescar flags por si cambió el esquema en caliente
        self._detect_schema_flags()

        cli_nom = (self.combo_cli.get() or "").strip()
        if not cli_nom:
            messagebox.showwarning("Cliente", "Selecciona un cliente.")
            return
        cid = self._cli_map.get(cli_nom)

        rango = self._leer_rango(self.cli_fecha_ini, self.cli_fecha_fin)
        if not rango:
            return
        f1, f2 = rango

        self._set_info_cliente(cid)

        try:
            # 1) Ventas a crédito en el rango
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT v.fecha, p.nombre, COALESCE(v.unidades,0), COALESCE(v.kilos,0),
                        COALESCE(v.precio,0), COALESCE(v.total, v.kilos * v.precio)
                    FROM ventas v
                    JOIN productos p ON p.id = v.producto_id
                    WHERE v.tipo_venta = 'credito'
                    AND v.cliente_id = ?
                    AND DATE(v.fecha) BETWEEN ? AND ?
                    ORDER BY v.fecha DESC
                """, (cid, f1, f2))
                vtas = cur.fetchall()

            # 2) Pagos del cliente (usa tabla singular/plural si existe) + saldo actual
            pagos = []
            saldo_actual = 0.0
            with get_connection() as conn:
                cur = conn.cursor()

                if self._pagos_cli_table:
                    cols = self._columns_in(self._pagos_cli_table)

                    if "cliente_id" in cols:
                        # Detectar columna de descripción (si no existe, usar cadena vacía)
                        desc_candidates = ["descripcion", "detalle", "concepto", "nota", "observacion", "observaciones"]
                        monto_candidates = ["monto", "importe", "pago", "cantidad", "valor"]

                        desc_col = next((c for c in desc_candidates if c in cols), None)
                        monto_col = next((c for c in monto_candidates if c in cols), None)

                        desc_expr = f"IFNULL({desc_col},'')" if desc_col else "''"
                        monto_expr = monto_col if monto_col else "0"

                        cur.execute(
                            f"""
                            SELECT fecha, {desc_expr} AS descripcion, {monto_expr} AS monto
                            FROM {self._pagos_cli_table}
                            WHERE cliente_id = ? AND DATE(fecha) BETWEEN ? AND ?
                            ORDER BY fecha DESC
                            """,
                            (cid, f1, f2)
                        )
                        pagos = cur.fetchall()

                # Siempre lee el saldo "live" del cliente
                cur.execute("SELECT COALESCE(deuda_total,0) FROM clientes WHERE id = ?", (cid,))
                saldo_actual = float((cur.fetchone() or (0.0,))[0])


            # 3) Pintar ventas
            total_imp = 0.0
            for fecha, prod, un, kg, precio, total in vtas:
                un = float(un or 0); kg = float(kg or 0)
                pr = redondear_dos_decimales(precio or 0)
                tt = redondear_dos_decimales(total or (kg * pr))
                total_imp += tt
                self.tree_cli_vtas.insert("", "end", values=(
                    formatear_fecha(fecha), prod, f"{redondear_dos_decimales(un):.2f}",
                    f"{redondear_dos_decimales(kg):.2f}", formato_moneda(pr), formato_moneda(tt)
                ))
                self.cliente_credito_rows.append((str(fecha), prod, float(un), float(kg), float(pr), float(tt)))

            # 4) Pintar pagos
            total_pagos = 0.0
            for fecha, desc, monto in pagos:
                mo = redondear_dos_decimales(monto or 0.0)
                total_pagos += mo
                self.tree_cli_pagos.insert("", "end", values=(formatear_fecha(fecha), desc, formato_moneda(mo)))
                self.cliente_pagos_rows.append((str(fecha), desc, float(mo)))

            # 5) Totales
            self.total_importe_cliente = redondear_dos_decimales(total_imp)
            self.total_pagos_cliente = redondear_dos_decimales(total_pagos)
            self.saldo_cliente = redondear_dos_decimales(saldo_actual)

            if not vtas and not pagos:
                messagebox.showinfo("Sin datos", "No hay movimientos en el rango seleccionado.")

            self.lbl_resumen_cli.config(text=f"Compras: {formato_moneda(self.total_importe_cliente)} | "
                                            f"Pagos: {formato_moneda(self.total_pagos_cliente)} | "
                                            f"Saldo: {formato_moneda(self.saldo_cliente)}")

            set_treeview_stripes(self.tree_cli_vtas,
                                even_bg=self.palette.get("alt_row", "#F2F2F2"),
                                odd_bg=self.palette.get("panel", "#FFFFFF"))
            set_treeview_stripes(self.tree_cli_pagos,
                                even_bg=self.palette.get("alt_row", "#F2F2F2"),
                                odd_bg=self.palette.get("panel", "#FFFFFF"))

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar la vista de deudas del cliente.\n{e}")
   

    def exportar_csv_deudas_cli(self):
        if not (self.cliente_credito_rows or self.cliente_pagos_rows):
            messagebox.showwarning("Sin datos", "Primero genera el reporte.")
            return
        nombre = f"deudas_cliente_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=",", lineterminator="\n")
                w.writerow(["== VENTAS A CRÉDITO =="])
                w.writerow(["Fecha", "Producto", "Unidades", "Kilos", "Precio", "Total"])
                for r in self.cliente_credito_rows:
                    w.writerow(r)
                w.writerow([])
                w.writerow(["== PAGOS DEL CLIENTE =="])
                w.writerow(["Fecha", "Descripción", "Monto"])
                for r in self.cliente_pagos_rows:
                    w.writerow(r)
                w.writerow([])
                w.writerow(["TOTAL COMPRAS", f"{self.total_importe_cliente:.2f}"])
                w.writerow(["TOTAL PAGOS", f"{self.total_pagos_cliente:.2f}"])
                w.writerow(["SALDO ACTUAL", f"{self.saldo_cliente:.2f}"])
            messagebox.showinfo("Éxito", f"CSV exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a CSV.\n{e}")

    def exportar_pdf_deudas_cli(self):
        if not REPORTLAB_OK:
            messagebox.showerror("PDF no disponible", "No se encontró reportlab.")
            return
        if not (self.cliente_credito_rows or self.cliente_pagos_rows):
            messagebox.showwarning("Sin datos", "Primero genera el reporte.")
            return

        nombre = f"deudas_cliente_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return

        try:
            doc = SimpleDocTemplate(ruta, pagesize=A4)
            elementos = []
            estilo = getSampleStyleSheet()
            cli = self.combo_cli.get() or "Cliente"
            elementos.append(Paragraph(f"Deudas de Cliente — {cli}", estilo['Title']))

            # Ventas
            datos1 = [["Fecha", "Producto", "Unidades", "Kilos", "Precio", "Total"]]
            for f, prod, un, kg, pr, tt in self.cliente_credito_rows:
                datos1.append([f, prod, f"{redondear_dos_decimales(un):.2f}", f"{redondear_dos_decimales(kg):.2f}",
                               f"{redondear_dos_decimales(pr):.2f}", f"{redondear_dos_decimales(tt):.2f}"])
            tabla1 = Table(datos1)
            tabla1.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
            ]))
            elementos.append(tabla1)
            elementos.append(Spacer(1, 8))

            # Pagos
            datos2 = [["Fecha", "Descripción", "Monto"]]
            for f, desc, mo in self.cliente_pagos_rows:
                datos2.append([f, desc, f"{redondear_dos_decimales(mo):.2f}"])
            tabla2 = Table(datos2)
            tabla2.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
            ]))
            elementos.append(tabla2)
            elementos.append(Spacer(1, 8))
            elementos.append(Paragraph(
                f"Compras: {formato_moneda(self.total_importe_cliente)} &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Pagos: {formato_moneda(self.total_pagos_cliente)} &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"Saldo: {formato_moneda(self.saldo_cliente)}",
                estilo['Normal']
            ))
            doc.build(elementos)
            messagebox.showinfo("Éxito", f"Reporte exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a PDF.\n{e}")

    def _set_rango_and(self, e1, e2, ini, fin, fn):
        e1.delete(0, tk.END); e1.insert(0, ini)
        e2.delete(0, tk.END); e2.insert(0, fin)
        fn()

    # ============= NUEVA Pestaña: Análisis de Ventas =========
    def init_tab_analisis(self):
        # Subpestañas
        nb = ttk.Notebook(self.tab_analisis)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.tab_rank = tk.Frame(nb, bg=self.palette["bg"])
        self.tab_general = tk.Frame(nb, bg=self.palette["bg"])
        nb.add(self.tab_rank, text="Por producto (ranking)")
        nb.add(self.tab_general, text="General")

        # ---- Por producto ----
        fr = self._panel(self.tab_rank, pady=10, padx=8, fill="x")
        fr.grid_columnconfigure(1, weight=1)
        fr.grid_columnconfigure(4, weight=1)

        self._lbl(fr, "Desde:", row=0, column=0, sticky="e")
        self.rank_ini = self._entry(fr, width=12, row=0, column=1, padx=5, sticky="we")
        ttk.Button(fr, text="📅", command=lambda: self.abrir_calendario(self.rank_ini, fuentes=("all",)),
                   style="TButton").grid(row=0, column=2)

        self._lbl(fr, "Hasta:", row=0, column=3, sticky="e")
        self.rank_fin = self._entry(fr, width=12, row=0, column=4, padx=5, sticky="we")
        ttk.Button(fr, text="📅", command=lambda: self.abrir_calendario(self.rank_fin, fuentes=("all",)),
                   style="TButton").grid(row=0, column=5)

        self._btn(fr, "Generar", "TButton", self.generar_ranking_producto, row=0, column=6, padx=6)
        self._btn_pdf_rank = self._btn(fr, "Exportar PDF", "Success.TButton", self.exportar_pdf_rank, row=0, column=7, padx=4)
        self._btn(fr, "Exportar CSV", "Success.TButton", self.exportar_csv_rank, row=0, column=8, padx=4)
        if MATPLOTLIB_OK:
            self._btn(fr, "Gráfica Top 10 (importe)", "TButton", lambda: self._grafica_top_productos(metric="importe")).grid(row=0, column=9, padx=4)
            self._btn(fr, "Gráfica Top 10 (kilos)", "TButton", lambda: self._grafica_top_productos(metric="kilos")).grid(row=0, column=10, padx=4)
        else:
            tk.Label(fr, text="(matplotlib no disponible para gráficas)", bg=self.palette["bg"], fg=self.palette["warning"]).grid(row=0, column=9, columnspan=2, padx=4)

        quick = self._panel(self.tab_rank, pady=(0, 6), padx=8, fill="x")
        self._btn(quick, "Hoy", "TButton", lambda: self._set_rango_and(self.rank_ini, self.rank_fin, *self._rango_hoy(), self.generar_ranking_producto)).pack(side="left", padx=4)
        self._btn(quick, "Semana", "TButton", lambda: self._set_rango_and(self.rank_ini, self.rank_fin, *self._rango_semana_actual(), self.generar_ranking_producto)).pack(side="left", padx=4)
        self._btn(quick, "Mes", "TButton", lambda: self._set_rango_and(self.rank_ini, self.rank_fin, *self._rango_mes_actual(), self.generar_ranking_producto)).pack(side="left", padx=4)

        tabla = self._panel(self.tab_rank, padx=6, pady=6, fill="both", expand=True)
        cols_r = ("#", "Producto", "Kilos", "Unidades", "Importe", "% Part.", "Tickets", "Ticket prom.", "Rotación vtas/día", "Δ Importe % (ant.)", "Margen (opt.)")
        self.tree_rank, _, _ = self._tree_with_scrolls(tabla, cols_r)
        for col, w, a in (
            ("#", 50, "center"),
            ("Producto", 200, "w"),
            ("Kilos", 100, "e"),
            ("Unidades", 100, "e"),
            ("Importe", 120, "e"),
            ("% Part.", 90, "e"),
            ("Tickets", 90, "e"),
            ("Ticket prom.", 120, "e"),
            ("Rotación vtas/día", 140, "e"),
            ("Δ Importe % (ant.)", 140, "e"),
            ("Margen (opt.)", 120, "e"),
        ):
            self.tree_rank.heading(col, text=col)
            self.tree_rank.column(col, width=w, anchor=a, stretch=(col == "Producto"))
        _setup_sorting(self.tree_rank, cols_r, {
            "#":"int","Producto":"str","Kilos":"float","Unidades":"float","Importe":"money","% Part.":"float",
            "Tickets":"int","Ticket prom.":"money","Rotación vtas/día":"float","Δ Importe % (ant.)":"float","Margen (opt.)":"money"
        })

        self.lbl_resumen_rank = tk.Label(self.tab_rank, text="Total importe: $0.00 | Total kilos: 0.00 | Tickets: 0",
                                         bg=self.palette["bg"], fg=self.palette["text"])
        self.lbl_resumen_rank.pack(pady=(0, 10))

        self.rank_ini.bind("<Return>", lambda e: self.generar_ranking_producto())
        self.rank_fin.bind("<Return>", lambda e: self.generar_ranking_producto())

        # ---- General ----
        fg = self._panel(self.tab_general, pady=10, padx=8, fill="x")
        fg.grid_columnconfigure(1, weight=1)
        fg.grid_columnconfigure(4, weight=1)
        self._lbl(fg, "Desde:", row=0, column=0, sticky="e")
        self.gen_ini = self._entry(fg, width=12, row=0, column=1, padx=5, sticky="we")
        ttk.Button(fg, text="📅", command=lambda: self.abrir_calendario(self.gen_ini, fuentes=("all",)),
                   style="TButton").grid(row=0, column=2)
        self._lbl(fg, "Hasta:", row=0, column=3, sticky="e")
        self.gen_fin = self._entry(fg, width=12, row=0, column=4, padx=5, sticky="we")
        ttk.Button(fg, text="📅", command=lambda: self.abrir_calendario(self.gen_fin, fuentes=("all",)),
                   style="TButton").grid(row=0, column=5)
        self._btn(fg, "Generar", "TButton", self.generar_general, row=0, column=6, padx=6)
        self._btn_pdf_general = self._btn(fg, "Exportar PDF", "Success.TButton", self.exportar_pdf_general, row=0, column=7, padx=4)
        self._btn(fg, "Exportar CSV", "Success.TButton", self.exportar_csv_general, row=0, column=8, padx=4)
        if MATPLOTLIB_OK:
            self._btn(fg, "Gráfica Importe", "TButton", lambda: self._grafica_series(metric="importe")).grid(row=0, column=9, padx=4)
            self._btn(fg, "Gráfica Kilos", "TButton", lambda: self._grafica_series(metric="kilos")).grid(row=0, column=10, padx=4)
            self._btn(fg, "Gráfica Tickets", "TButton", lambda: self._grafica_series(metric="tickets")).grid(row=0, column=11, padx=4)
        else:
            tk.Label(fg, text="(matplotlib no disponible para gráficas)", bg=self.palette["bg"], fg=self.palette["warning"]).grid(row=0, column=9, columnspan=3, padx=4)

        quickg = self._panel(self.tab_general, pady=(0, 6), padx=8, fill="x")
        self._btn(quickg, "Hoy", "TButton", lambda: self._set_rango_and(self.gen_ini, self.gen_fin, *self._rango_hoy(), self.generar_general)).pack(side="left", padx=4)
        self._btn(quickg, "Semana", "TButton", lambda: self._set_rango_and(self.gen_ini, self.gen_fin, *self._rango_semana_actual(), self.generar_general)).pack(side="left", padx=4)
        self._btn(quickg, "Mes", "TButton", lambda: self._set_rango_and(self.gen_ini, self.gen_fin, *self._rango_mes_actual(), self.generar_general)).pack(side="left", padx=4)

        tabg = self._panel(self.tab_general, padx=6, pady=6, fill="both", expand=True)
        cols_g2 = ("Fecha", "Importe", "Kilos", "Tickets", "Ticket prom.", "Clientes atendidos")
        self.tree_general, _, _ = self._tree_with_scrolls(tabg, cols_g2)
        for col, w, a in (
            ("Fecha", 140, "center"),
            ("Importe", 120, "e"),
            ("Kilos", 100, "e"),
            ("Tickets", 90, "e"),
            ("Ticket prom.", 120, "e"),
            ("Clientes atendidos", 160, "e"),
        ):
            self.tree_general.heading(col, text=col)
            self.tree_general.column(col, width=w, anchor=a, stretch=False)
        _setup_sorting(self.tree_general, cols_g2, {"Fecha":"date","Importe":"money","Kilos":"float","Tickets":"int","Ticket prom.":"money","Clientes atendidos":"int"})

        self.lbl_resumen_general = tk.Label(self.tab_general,
                                            text="Importe: $0.00 | Kilos: 0.00 | Tickets: 0 | Ticket prom.: $0.00 | Clientes: 0 | Δ vs. ant.: 0%",
                                            bg=self.palette["bg"], fg=self.palette["text"])
        self.lbl_resumen_general.pack(pady=(0, 10))

        self.gen_ini.bind("<Return>", lambda e: self.generar_general())
        self.gen_fin.bind("<Return>", lambda e: self.generar_general())

    # --------- Lógica por producto (ranking) ----------
    def generar_ranking_producto(self):
        self.tree_rank.delete(*self.tree_rank.get_children())
        self.rank_producto_rows.clear()
        rango = self._leer_rango(self.rank_ini, self.rank_fin)
        if not rango:
            return
        f1, f2 = rango

        # periodo anterior (misma longitud)
        fi = datetime.strptime(f1, "%Y-%m-%d").date()
        ff = datetime.strptime(f2, "%Y-%m-%d").date()
        dias = (ff - fi).days + 1
        prev_ff = fi - timedelta(days=1)
        prev_fi = prev_ff - timedelta(days=dias - 1)
        pf1, pf2 = str(prev_fi), str(prev_ff)

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                # Totales del periodo actual
                cur.execute("""
                    SELECT p.id, p.nombre,
                           SUM(COALESCE(v.kilos,0)) AS kilos,
                           SUM(COALESCE(v.unidades,0)) AS unidades,
                           SUM(COALESCE(v.total, v.kilos*v.precio)) AS importe,
                           COUNT(*) AS tickets
                    FROM ventas v
                    JOIN productos p ON p.id = v.producto_id
                    WHERE DATE(v.fecha) BETWEEN ? AND ?
                    GROUP BY p.id, p.nombre
                """, (f1, f2))
                rows = cur.fetchall()

                # Totales periodo anterior (para tendencia)
                cur.execute("""
                    SELECT p.id,
                           SUM(COALESCE(v.total, v.kilos*v.precio)) AS importe_ant
                    FROM ventas v
                    JOIN productos p ON p.id = v.producto_id
                    WHERE DATE(v.fecha) BETWEEN ? AND ?
                    GROUP BY p.id
                """, (pf1, pf2))
                prev = {pid: float(imp or 0.0) for (pid, imp) in cur.fetchall()}

                # Costos opcionales (para margen)
                pcols = self._productos_cost_cols
                cost_by_id = {}
                if any(pcols.values()):
                    sel = ["id"]
                    if pcols["costo_kg"]: sel.append("COALESCE(costo_kg,0)")
                    elif pcols["costo"]: sel.append("COALESCE(costo,0)")
                    else: sel.append("0")
                    if pcols["costo_unitario"]: sel.append("COALESCE(costo_unitario,0)")
                    else: sel.append("0")
                    cur.execute(f"SELECT {', '.join(sel)} FROM productos")
                    for r in cur.fetchall():
                        pid = int(r[0]); ckg = float(r[1]); cu = float(r[2])
                        cost_by_id[pid] = (ckg, cu)

            total_importe = sum(float(r[4] or 0.0) for r in rows) or 1.0
            total_kilos = sum(float(r[2] or 0.0) for r in rows)
            total_tickets = sum(int(r[5] or 0) for r in rows)
            dias_periodo = max(dias, 1)

            # Armar ranking
            tmp = []
            for pid, nombre, kilos, unidades, importe, tickets in rows:
                kilos = float(kilos or 0.0)
                unidades = float(unidades or 0.0)
                importe = float(importe or 0.0)
                tickets = int(tickets or 0)

                part = (importe / total_importe) * 100.0
                ticket_prom = (importe / tickets) if tickets > 0 else 0.0
                rotacion = tickets / dias_periodo
                imp_ant = float(prev.get(pid, 0.0))
                delta_pct = ((importe - imp_ant) / imp_ant * 100.0) if imp_ant > 0 else (100.0 if importe > 0 else 0.0)

                margen = ""
                if cost_by_id:
                    ckg, cu = cost_by_id.get(pid, (0.0, 0.0))
                    margen_val = (importe - (ckg * kilos) - (cu * unidades))
                    margen = redondear_dos_decimales(margen_val)

                tmp.append({
                    "pid": pid,
                    "nombre": nombre,
                    "kilos": redondear_dos_decimales(kilos),
                    "unidades": redondear_dos_decimales(unidades),
                    "importe": redondear_dos_decimales(importe),
                    "part": redondear_dos_decimales(part),
                    "tickets": tickets,
                    "ticket_prom": redondear_dos_decimales(ticket_prom),
                    "rotacion": redondear_dos_decimales(rotacion),
                    "delta": redondear_dos_decimales(delta_pct),
                    "margen": (margen if margen != "" else None)
                })

            # Orden por importe desc
            tmp.sort(key=lambda x: x["importe"], reverse=True)

            # Pintar
            for i, r in enumerate(tmp, start=1):
                margen_str = (formato_moneda(r["margen"]) if r["margen"] is not None else "")
                self.tree_rank.insert("", "end", values=(
                    i, r["nombre"], f"{r['kilos']:.2f}", f"{r['unidades']:.2f}", formato_moneda(r["importe"]),                     i, r["nombre"], f"{r['kilos']:.2f}", f"{r['unidades']:.2f}", formato_moneda(r["importe"]),
                    f"{r['part']:.2f}", r["tickets"], formato_moneda(r["ticket_prom"]),
                    f"{r['rotacion']:.2f}", f"{r['delta']:.2f}", margen_str
                ))
                self.rank_producto_rows.append((
                    i, r["nombre"], float(r["kilos"]), float(r["unidades"]), float(r["importe"]),
                    float(r["part"]), int(r["tickets"]), float(r["ticket_prom"]),
                    float(r["rotacion"]), float(r["delta"]), (float(r["margen"]) if r["margen"] is not None else "")
                ))

            # Resumen
            self.lbl_resumen_rank.config(
                text=f"Total importe: {formato_moneda(redondear_dos_decimales(total_importe))} | "
                     f"Total kilos: {redondear_dos_decimales(total_kilos):.2f} | "
                     f"Tickets: {total_tickets}"
            )

            set_treeview_stripes(self.tree_rank, even_bg=self.palette.get("alt_row", "#F2F2F2"),
                                 odd_bg=self.palette.get("panel", "#FFFFFF"))

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar el ranking por producto.\n{e}")

    def exportar_csv_rank(self):
        if not self.rank_producto_rows:
            messagebox.showwarning("Sin datos", "Primero genera el ranking.")
            return
        nombre = f"ranking_productos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=",", lineterminator="\n")
                w.writerow(["#", "Producto", "Kilos", "Unidades", "Importe", "% Part.",
                            "Tickets", "Ticket prom.", "Rotación vtas/día", "Δ Importe % (ant.)", "Margen (opt.)"])
                for row in self.rank_producto_rows:
                    w.writerow(row)
            messagebox.showinfo("Éxito", f"CSV exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a CSV.\n{e}")

    def exportar_pdf_rank(self):
        if not REPORTLAB_OK:
            messagebox.showerror("PDF no disponible", "No se encontró reportlab.")
            return
        if not self.rank_producto_rows:
            messagebox.showwarning("Sin datos", "Primero genera el ranking.")
            return

        nombre = f"ranking_productos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return

        try:
            doc = SimpleDocTemplate(ruta, pagesize=A4)
            elementos = []
            estilo = getSampleStyleSheet()
            elementos.append(Paragraph("Ranking de Productos", estilo['Title']))

            encabezado = ["#", "Producto", "Kilos", "Unidades", "Importe", "% Part.",
                          "Tickets", "Ticket prom.", "Rotación vtas/día", "Δ Importe % (ant.)", "Margen (opt.)"]
            datos = [encabezado]
            for r in self.rank_producto_rows:
                i, prod, kilos, unidades, imp, part, tks, tkp, rota, delta, margen = r
                datos.append([
                    i, prod, f"{redondear_dos_decimales(kilos):.2f}", f"{redondear_dos_decimales(unidades):.2f}",
                    f"{redondear_dos_decimales(imp):.2f}", f"{redondear_dos_decimales(part):.2f}",
                    tks, f"{redondear_dos_decimales(tkp):.2f}", f"{redondear_dos_decimales(rota):.2f}",
                    f"{redondear_dos_decimales(delta):.2f}", (f"{redondear_dos_decimales(margen):.2f}" if margen != "" else "")
                ])

            tabla = Table(datos)
            tabla.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ]))
            elementos.append(tabla)
            doc.build(elementos)
            messagebox.showinfo("Éxito", f"Reporte exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a PDF.\n{e}")

    def _grafica_top_productos(self, metric: str = "importe"):
        if not MATPLOTLIB_OK:
            messagebox.showerror("Gráficas", "matplotlib no está disponible.")
            return
        if not self.rank_producto_rows:
            messagebox.showwarning("Sin datos", "Primero genera el ranking.")
            return

        try:
            # Selección de métrica
            idx = {"importe": 4, "kilos": 2}.get(metric, 4)
            # Top 10
            datos = sorted(self.rank_producto_rows, key=lambda r: float(r[idx] or 0), reverse=True)[:10]
            labels = [d[1] for d in datos]
            valores = [float(d[idx]) for d in datos]

            fig, ax = plt.subplots(figsize=(9, 5))
            ax.bar(range(len(valores)), valores)
            ax.set_title(f"Top 10 por {metric}")
            ax.set_ylabel(metric.capitalize())
            ax.set_xlabel("Producto")
            # Corrección: set_xticks antes de set_xticklabels
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=45, ha="right")
            fig.tight_layout()

            nombre = f"grafica_top10_{metric}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            ruta = self._ruta_export(nombre)
            if not ruta:
                plt.close(fig)
                return
            fig.savefig(ruta, dpi=120)
            plt.close(fig)
            messagebox.showinfo("Éxito", f"Gráfica guardada en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar la gráfica.\n{e}")

    # --------- Lógica general (serie por día) ----------
    def generar_general(self):
        self.tree_general.delete(*self.tree_general.get_children())
        self.general_series_rows.clear()

        rango = self._leer_rango(self.gen_ini, self.gen_fin)
        if not rango:
            return
        f1, f2 = rango

        # periodo anterior (misma longitud)
        fi = datetime.strptime(f1, "%Y-%m-%d").date()
        ff = datetime.strptime(f2, "%Y-%m-%d").date()
        dias = (ff - fi).days + 1
        prev_ff = fi - timedelta(days=1)
        prev_fi = prev_ff - timedelta(days=dias - 1)
        pf1, pf2 = str(prev_fi), str(prev_ff)

        try:
            with get_connection() as conn:
                cur = conn.cursor()

                # ¿Existe cliente_id para contar clientes atendidos?
                vcols = self._columns_in("ventas")
                has_cliente = ("cliente_id" in vcols)

                # Serie por día
                if has_cliente:
                    cur.execute("""
                        SELECT DATE(v.fecha) AS dia,
                               SUM(COALESCE(v.total, v.kilos*v.precio)) AS importe,
                               SUM(COALESCE(v.kilos,0)) AS kilos,
                               COUNT(*) AS tickets,
                               COUNT(DISTINCT v.cliente_id) AS clientes
                        FROM ventas v
                        WHERE DATE(v.fecha) BETWEEN ? AND ?
                        GROUP BY DATE(v.fecha)
                        ORDER BY DATE(v.fecha) ASC
                    """, (f1, f2))
                else:
                    cur.execute("""
                        SELECT DATE(v.fecha) AS dia,
                               SUM(COALESCE(v.total, v.kilos*v.precio)) AS importe,
                               SUM(COALESCE(v.kilos,0)) AS kilos,
                               COUNT(*) AS tickets
                        FROM ventas v
                        WHERE DATE(v.fecha) BETWEEN ? AND ?
                        GROUP BY DATE(v.fecha)
                        ORDER BY DATE(v.fecha) ASC
                    """, (f1, f2))

                rows = cur.fetchall()

                # Totales periodo anterior (importe)
                cur.execute("""
                    SELECT SUM(COALESCE(v.total, v.kilos*v.precio)) AS importe_ant
                    FROM ventas v
                    WHERE DATE(v.fecha) BETWEEN ? AND ?
                """, (pf1, pf2))
                prev_total = float((cur.fetchone() or (0.0,))[0] or 0.0)

            total_importe = 0.0
            total_kilos = 0.0
            total_tickets = 0
            total_clientes = 0

            for r in rows:
                if len(r) == 5:
                    dia, imp, kg, tks, clis = r
                else:
                    dia, imp, kg, tks = r
                    clis = 0
                imp = redondear_dos_decimales(float(imp or 0.0))
                kg = redondear_dos_decimales(float(kg or 0.0))
                tks = int(tks or 0)
                clis = int(clis or 0)
                tk_prom = redondear_dos_decimales((imp / tks) if tks > 0 else 0.0)

                self.tree_general.insert("", "end", values=(
                    formatear_fecha(dia), formato_moneda(imp), f"{kg:.2f}", tks, formato_moneda(tk_prom), clis
                ))
                self.general_series_rows.append((str(dia), float(imp), float(kg), int(tks), float(tk_prom), int(clis)))

                total_importe += imp
                total_kilos += kg
                total_tickets += tks
                total_clientes += clis

            total_importe = redondear_dos_decimales(total_importe)
            total_kilos = redondear_dos_decimales(total_kilos)
            tk_prom_global = redondear_dos_decimales((total_importe / total_tickets) if total_tickets > 0 else 0.0)
            delta_pct = redondear_dos_decimales(((total_importe - prev_total) / prev_total * 100.0) if prev_total > 0 else (100.0 if total_importe > 0 else 0.0))

            if not self.general_series_rows:
                messagebox.showinfo("Sin datos", "No hay ventas en el rango seleccionado.")

            self.lbl_resumen_general.config(
                text=f"Importe: {formato_moneda(total_importe)} | Kilos: {total_kilos:.2f} | "
                     f"Tickets: {total_tickets} | Ticket prom.: {formato_moneda(tk_prom_global)} | "
                     f"Clientes: {total_clientes} | Δ vs. ant.: {delta_pct:.2f}%"
            )

            set_treeview_stripes(self.tree_general, even_bg=self.palette.get("alt_row", "#F2F2F2"),
                                 odd_bg=self.palette.get("panel", "#FFFFFF"))

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar la serie general.\n{e}")

    def exportar_csv_general(self):
        if not self.general_series_rows:
            messagebox.showwarning("Sin datos", "Primero genera la serie general.")
            return
        nombre = f"serie_general_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return
        try:
            with open(ruta, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=",", lineterminator="\n")
                w.writerow(["Fecha", "Importe", "Kilos", "Tickets", "Ticket prom.", "Clientes atendidos"])
                for r in self.general_series_rows:
                    w.writerow(r)
                # Totales al final (mismos cálculos que en UI)
                tot_imp = sum(float(r[1]) for r in self.general_series_rows)
                tot_kg = sum(float(r[2]) for r in self.general_series_rows)
                tot_tk = sum(int(r[3]) for r in self.general_series_rows)
                tot_cli = sum(int(r[5]) for r in self.general_series_rows)
                tk_prom = (tot_imp / tot_tk) if tot_tk > 0 else 0.0
                w.writerow([])
                w.writerow(["TOTAL IMPORTE", f"{redondear_dos_decimales(tot_imp):.2f}"])
                w.writerow(["TOTAL KILOS", f"{redondear_dos_decimales(tot_kg):.2f}"])
                w.writerow(["TOTAL TICKETS", tot_tk])
                w.writerow(["TICKET PROM.", f"{redondear_dos_decimales(tk_prom):.2f}"])
                w.writerow(["CLIENTES ATENDIDOS", tot_cli])
            messagebox.showinfo("Éxito", f"CSV exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a CSV.\n{e}")

    def exportar_pdf_general(self):
        if not REPORTLAB_OK:
            messagebox.showerror("PDF no disponible", "No se encontró reportlab.")
            return
        if not self.general_series_rows:
            messagebox.showwarning("Sin datos", "Primero genera la serie general.")
            return

        nombre = f"serie_general_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ruta = self._ruta_export(nombre)
        if not ruta:
            return

        try:
            doc = SimpleDocTemplate(ruta, pagesize=A4)
            elementos = []
            estilo = getSampleStyleSheet()
            elementos.append(Paragraph("Serie General (por día)", estilo['Title']))

            datos = [["Fecha", "Importe", "Kilos", "Tickets", "Ticket prom.", "Clientes"]]
            for fch, imp, kg, tks, tkp, cli in self.general_series_rows:
                datos.append([
                    fch, f"{redondear_dos_decimales(imp):.2f}", f"{redondear_dos_decimales(kg):.2f}",
                    tks, f"{redondear_dos_decimales(tkp):.2f}", cli
                ])

            tabla = Table(datos)
            tabla.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ]))
            elementos.append(tabla)
            doc.build(elementos)
            messagebox.showinfo("Éxito", f"Reporte exportado en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo exportar a PDF.\n{e}")

    def _grafica_series(self, metric: str = "importe"):
        if not MATPLOTLIB_OK:
            messagebox.showerror("Gráficas", "matplotlib no está disponible.")
            return
        if not self.general_series_rows:
            messagebox.showwarning("Sin datos", "Primero genera la serie general.")
            return

        try:
            fechas = [r[0] for r in self.general_series_rows]
            if metric == "importe":
                valores = [float(r[1]) for r in self.general_series_rows]
                ylabel = "Importe"
            elif metric == "kilos":
                valores = [float(r[2]) for r in self.general_series_rows]
                ylabel = "Kilos"
            else:
                valores = [int(r[3]) for r in self.general_series_rows]
                ylabel = "Tickets"

            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(range(len(valores)), valores, marker="o")
            ax.set_title(f"Serie general - {ylabel}")
            ax.set_ylabel(ylabel)
            ax.set_xlabel("Fecha")
            # set_xticks antes de set_xticklabels
            ax.set_xticks(range(len(fechas)))
            ax.set_xticklabels(fechas, rotation=45, ha="right")
            fig.tight_layout()

            nombre = f"grafica_serie_{metric}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            ruta = self._ruta_export(nombre)
            if not ruta:
                plt.close(fig)
                return
            fig.savefig(ruta, dpi=120)
            plt.close(fig)
            messagebox.showinfo("Éxito", f"Gráfica guardada en:\n{ruta}")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo generar la gráfica.\n{e}")

    # ================= Calendario (forzar popup) ===================
    def abrir_calendario(self, entry_target: ttk.Entry, fuentes=("all",)):
        """
        Abre el CalendarioWidget en una ventana emergente (Toplevel)
        y coloca la fecha seleccionada en entry_target.
        Mantiene una única ventana de calendario abierta.
        """
        # Cerrar calendario previo si sigue abierto
        try:
            if self._calendar_win and self._calendar_win.winfo_exists():
                self._calendar_win.destroy()
        except Exception:
            pass

        # Crear popup
        top = tk.Toplevel(self)
        top.title("Seleccionar fecha")
        try:
            top.configure(bg=self.palette["bg"])
        except Exception:
            pass
        top.transient(self.winfo_toplevel())
        top.grab_set()
        top.bind("<Escape>", lambda _: top.destroy())
        self._calendar_win = top  # mantener referencia

        # Callback de selección (si el widget usa on_select)
        def _on_select(fecha_str: str):
            try:
                entry_target.delete(0, tk.END)
                entry_target.insert(0, fecha_str)
            except Exception:
                pass
            try:
                if self._calendar_win and self._calendar_win.winfo_exists():
                    self._calendar_win.destroy()
            except Exception:
                pass

        # Intentar firma (parent, entry_target, fuentes=...)
        try:
            CalendarioWidget(top, entry_target, fuentes=fuentes)
            return
        except TypeError:
            # Intentar firma (parent, on_select=..., fuentes=...)
            try:
                CalendarioWidget(top, on_select=_on_select, fuentes=fuentes)
                return
            except Exception:
                pass
        except Exception:
            pass

        # Fallback
        try:
            top.destroy()
        except Exception:
            pass
        messagebox.showinfo("Calendario", "No se pudo abrir el calendario. Ingresa la fecha como YYYY-MM-DD.")
    

# ================= Utilidades: ordenamiento Treeview =================

def _setup_sorting(tree: ttk.Treeview, columnas: tuple[str, ...], tipos: dict[str, str]):
    """
    Habilita ordenamiento por columna con tipos: 'str' | 'int' | 'float' | 'money' | 'date'
    """
    directions = {}

    def parse_value(val: str, tipo: str):
        try:
            if tipo == "int":
                return int(float(_clean_money(val)))
            if tipo == "float":
                return float(val.replace(",", "."))
            if tipo == "money":
                return float(_clean_money(val))
            if tipo == "date":
                # Soporta 'YYYY-MM-DD' o 'DD/MM/YYYY'
                v = val.strip()
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                    try:
                        return datetime.strptime(v, fmt)
                    except Exception:
                        continue
                # Intento final: ya formateada por formatear_fecha (debería ser YYYY-MM-DD)
                return datetime.fromisoformat(v)
        except Exception:
            pass
        return str(val).lower()

    def sort_by(col: str):
        # Alternar dirección
        direc = directions.get(col, False)
        directions[col] = not direc

        tipo = tipos.get(col, "str")
        items = [(tree.set(k, col), k) for k in tree.get_children("")]

        try:
            items.sort(key=lambda x: parse_value(x[0], tipo), reverse=direc)
        except Exception:
            items.sort(key=lambda x: str(x[0]).lower(), reverse=direc)

        for index, (_, k) in enumerate(items):
            tree.move(k, "", index)

    # Configurar encabezados
    for c in columnas:
        tree.heading(c, text=c, command=lambda col=c: sort_by(col))


def _clean_money(s: str) -> str:
    """
    Limpia cadenas de moneda tipo "$1,234.56" o "$ 1.234,56" -> "1234.56"
    """
    if s is None:
        return "0"
    s = str(s)
    # quitar símbolos y espacios
    chars = []
    for ch in s:
        if ch.isdigit() or ch in (".", ",", "-", "+"):
            chars.append(ch)
    raw = "".join(chars)
    # Normalizar: si hay más de un separador, asumir coma como miles y punto como decimal
    if raw.count(",") > 0 and raw.count(".") > 0:
        raw = raw.replace(",", "")
    else:
        # Si sólo hay comas, interpretarlas como decimales (formato europeo)
        if raw.count(",") == 1 and raw.count(".") == 0:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    try:
        float(raw)  # validar
        return raw
    except Exception:
        return "0"

                   
# -----------------------------------------------------------
# Punto de entrada desde main.py
# -----------------------------------------------------------
def mostrar(frame_contenido, use_dark: bool = False):
    """Monta el frame de Reportes en el contenedor principal."""
    # Limpiar el contenedor destino
    for widget in frame_contenido.winfo_children():
        widget.destroy()

    # Crear el frame de Reportes
    frame = ReportesFrame(frame_contenido, use_dark=use_dark)

    # Compatibilidad: si el contenedor principal usa grid o pack
    try:
        frame.grid(row=0, column=0, sticky="nsew")
    except Exception:
        frame.pack(fill="both", expand=True)
