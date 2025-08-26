# modules/inventario.py
# -----------------------------------------------------------
# Sistema de Comercio — Módulo de Inventario
#
# Funcionalidad:
# - ENTRADAS (compra/ajuste/devolución/otro):
#   * Producto, kilos(+), cajas(+), peso/caja, unidades(+), tipo, motivo,
#     proveedor (opcional), pago (Contado/Crédito), monto (compra $).
#   * Stock: actualiza productos (kilos, num_cajas, unidades, peso_caja).
#   * Compra CONTADO: crea gasto y enlaza por FK (inventario.gasto_id).
#   * Compra CRÉDITO: crea deuda en deudas_proveedores y enlaza por FK
#     (inventario.deuda_proveedor_id).
#
# - MERMAS:
#   * Producto, kilos(-), cajas(-), unidades(-), motivo.
#   * Valida stock suficiente y descuenta.
#
# - PAGOS A PROVEEDOR (CXP):
#   * Registrar pago (proveedor, monto, nota). Inserta en pagos_proveedores.
#   * Si existen deudas abiertas del proveedor, aplica el pago FIFO
#     reduciendo el saldo de cada deuda (deudas_proveedores.saldo).
#
# - PROVEEDORES (CRUD):
#   * Alta/edición/eliminación y listado (ID, Nombre, Teléfono).
#   * El combobox de Proveedor se alimenta de este catálogo.
#
# - LISTADO:
#   * Entradas (con monto si hubo gasto) + Mermas.
#   * Búsqueda dinámica y ordenamiento por columnas.
#   * Estilo visual unificado (ttk) con zebra stripes.
#
# Dependencias:
# - ui/theme.py: apply_brand_ttk_theme, stylize_combobox_dropdown, set_treeview_stripes
# - ui/helpers.py: formatear_fecha, redondear_dos_decimales, formato_moneda,
#                  to_float, to_int, adjuntar_validador_2_decimales
# - db/database.get_connection: conexión SQLite con PRAGMA FK activas
# -----------------------------------------------------------

from __future__ import annotations

from logging import root
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from db.database import get_connection
from modules.calendar_widget import CalendarioWidget
from ui.helpers import (
    formatear_fecha,
    redondear_dos_decimales,
    formato_moneda,
    to_float,
    to_int,
    adjuntar_validador_2_decimales,
)
from ui.theme import (
    apply_brand_ttk_theme,
    stylize_combobox_dropdown,
    set_treeview_stripes,
    BRAND_PALETTE,
)

PALETTE = BRAND_PALETTE


class InventarioFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=PALETTE["bg"])
        self.productos: dict[str, int] = {}     # nombre -> id
        self.proveedores: dict[str, int] = {}   # nombre -> id

        # Flags de esquema (columnas / tablas opcionales)
        self._inv_has_gasto_fk = False            # inventario.gasto_id
        self._inv_has_deuda_fk = False            # inventario.deuda_proveedor_id
        self._pagos_has_proveedor_id = False      # pagos_proveedores.proveedor_id
        self._pagos_has_deuda_fk = False          # pagos_proveedores.deuda_proveedor_id
        self._has_deudas_prov = False             # tabla deudas_proveedores
        self._prov_has_direccion = False  # proveedores.direccion


        # Estilo TTK unificado
        self._style = apply_brand_ttk_theme(self)
        self._tree_style_name = "Brand.Treeview"

        self._build_ui()
        self._after_mount()

    # ---------------------------
    # Helpers UI (ttk preferente)
    # ---------------------------
    def _panel(self, parent, **pack):
        f = tk.Frame(parent, bg=PALETTE["panel"], bd=0, highlightthickness=0)
        if pack:
            f.pack(**pack)
        return f

    def _title(self, parent, text):
        tk.Label(parent, text=text, bg=PALETTE["panel"], fg=PALETTE["text"],
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 4))

    def _lbl(self, parent, text, **grid):
        w = tk.Label(parent, text=text, bg=parent["bg"], fg=PALETTE["text"])
        if grid:
            w.grid(**grid)
        return w

    def _entry(self, parent, width=14, textvariable=None, **grid):
        e = ttk.Entry(parent, width=width, textvariable=textvariable, style="TEntry")
        if grid:
            e.grid(**grid)
        return e

    def _btn(self, parent, text, style, cmd, **grid):
        b = ttk.Button(parent, text=text, command=cmd, style=style)
        if grid:
            b.grid(**grid)
        else:
            b.pack()
        return b

    def _combobox(self, parent, width=20, **grid):
        cb = ttk.Combobox(parent, state="readonly", width=width, style="TCombobox")
        if grid:
            cb.grid(**grid)
        # colorear dropdown cuando exista
        stylize_combobox_dropdown(cb, PALETTE)
        cb.bind("<Map>", lambda e, c=cb: stylize_combobox_dropdown(c, PALETTE), add="+")
        return cb

    def _tree_with_scrolls(self, parent, columnas, height=12):
        scroll_y = ttk.Scrollbar(parent, orient="vertical", style="Vertical.TScrollbar")
        scroll_x = ttk.Scrollbar(parent, orient="horizontal", style="Horizontal.TScrollbar")
        tree = ttk.Treeview(
            parent, columns=columnas, show="headings", height=height,
            style=self._tree_style_name,
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set
        )
        scroll_y.config(command=tree.yview)
        scroll_x.config(command=tree.xview)
        tree.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        scroll_x.pack(fill="x", padx=8, pady=(0, 6))
        scroll_y.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")
        return tree, scroll_x, scroll_y
    
        # --- Contenedor desplazable (scroll vertical) ---
    def _build_scroll_container(self):
        """
        Crea un canvas con scroll vertical y un frame interno self._scroll_body
        donde se construye el resto de la UI.
        Devuelve self._scroll_body como parent para los paneles.
        """
        container = tk.Frame(self, bg=PALETTE["bg"], bd=0, highlightthickness=0)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, bg=PALETTE["bg"], bd=0, highlightthickness=0)
        vbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar")
        canvas.configure(yscrollcommand=vbar.set)

        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=PALETTE["bg"], bd=0, highlightthickness=0)
        # guardamos el item del window para poder ajustar su ancho al redimensionar
        self._scroll_window_item = canvas.create_window(0, 0, window=body, anchor="nw")

        # Ajustar scrollregion cuando cambie el contenido
        def _on_body_config(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        body.bind("<Configure>", _on_body_config)

        # Hacer que el body ocupe todo el ancho visible del canvas
        def _on_canvas_config(e):
            canvas.itemconfigure(self._scroll_window_item, width=e.width)
        canvas.bind("<Configure>", _on_canvas_config)

        # Bind de rueda del mouse/touchpad
        self._bind_scroll_wheel(canvas)

        self._scroll_canvas = canvas
        self._scroll_body = body
        return body

    def _bind_scroll_wheel(self, canvas: tk.Canvas):
    # Windows / Mac
        def _on_mousewheel(event):
            if not canvas.winfo_exists():
                return
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        # Linux (rueda)
        def _on_button4(_e):
            if canvas.winfo_exists():
                canvas.yview_scroll(-3, "units")
        def _on_button5(_e):
            if canvas.winfo_exists():
                canvas.yview_scroll(+3, "units")
        canvas.bind("<Button-4>", _on_button4)
        canvas.bind("<Button-5>", _on_button5)
    # ---------------------------
    # Construcción de la UI
    # ---------------------------
    def _build_ui(self):
        # Contenedor desplazable
        root = self._build_scroll_container()

        # === ENTRADAS ===
        entrada_panel = self._panel(root, pady=8, padx=8, fill="x")
        self._title(entrada_panel, "Entradas de Inventario (Compra/Ajuste)")

        grid = tk.Frame(entrada_panel, bg=PALETTE["panel"])
        grid.pack(fill="x", padx=8, pady=(0, 4))

        # Fila 0
        self._lbl(grid, "Producto:", row=0, column=0, padx=4, pady=4, sticky="e")
        self.combo_producto = self._combobox(grid, width=26, row=0, column=1, padx=4, pady=4, sticky="we")
        grid.grid_columnconfigure(1, weight=1)
        self.combo_producto.bind("<<ComboboxSelected>>", self._on_producto_change)
        self.combo_producto.bind("<Return>", lambda e: self.registrar_entrada())

        self._lbl(grid, "Kilos (+):", row=0, column=2, padx=4, pady=4, sticky="e")
        self.kilos_entry = self._entry(grid, width=12, row=0, column=3, padx=4, pady=4)

        self._lbl(grid, "Núm. Cajas (+):", row=0, column=4, padx=4, pady=4, sticky="e")
        self.cajas_entry = self._entry(grid, width=12, row=0, column=5, padx=4, pady=4)

        self._lbl(grid, "Peso/Caja (kg):", row=0, column=6, padx=4, pady=4, sticky="e")
        self.peso_entry = self._entry(grid, width=12, row=0, column=7, padx=4, pady=4)

        # Fila 1
        self._lbl(grid, "Unidades (+):", row=1, column=0, padx=4, pady=4, sticky="e")
        self.unidades_entry = self._entry(grid, width=12, row=1, column=1, padx=4, pady=4, sticky="w")

        self._lbl(grid, "Tipo:", row=1, column=2, padx=4, pady=4, sticky="e")
        self.tipo_combo = self._combobox(grid, width=18, row=1, column=3, padx=4, pady=4, sticky="w")
        self.tipo_combo["values"] = ["Compra", "Ajuste", "Devolución", "Otro"]
        if self.tipo_combo["values"]:
            self.tipo_combo.current(0)
        self.tipo_combo.bind("<Return>", lambda e: self.registrar_entrada())

        self._lbl(grid, "Motivo:", row=1, column=4, padx=4, pady=4, sticky="e")
        self.motivo_entry = self._entry(grid, width=40, row=1, column=5, columnspan=3, padx=4, pady=4, sticky="we")
        grid.grid_columnconfigure(5, weight=1)

        # Fila 2
        self._lbl(grid, "Proveedor:", row=2, column=0, padx=4, pady=4, sticky="e")
        self.combo_proveedor = self._combobox(grid, width=26, row=2, column=1, padx=4, pady=4, sticky="we")
        grid.grid_columnconfigure(1, weight=1)

        self._lbl(grid, "Pago:", row=2, column=2, padx=4, pady=4, sticky="e")
        self.pago_combo = self._combobox(grid, width=14, row=2, column=3, padx=4, pady=4, sticky="w")
        self.pago_combo["values"] = ["Contado", "Crédito"]
        if self.pago_combo["values"]:
            self.pago_combo.current(0)
        self.pago_combo.bind("<Return>", lambda e: self.registrar_entrada())

        self._lbl(grid, "Monto (Compra $):", row=2, column=4, padx=4, pady=4, sticky="e")
        self.monto_compra_entry = self._entry(grid, width=14, row=2, column=5, padx=4, pady=4)

        self._btn(grid, "Registrar Entrada", "Success.TButton", self.registrar_entrada,
                  row=2, column=6, columnspan=2, padx=4, pady=6, sticky="w")

        # Info producto
        self.info_label = tk.Label(
            entrada_panel,
            text="Kilos: 0.00 | Cajas: 0.00 | Unidades: 0 | Peso/caja: 0.00 kg",
            bg=PALETTE["panel"], fg=PALETTE["text"], anchor="w"
        )
        self.info_label.pack(fill="x", padx=16, pady=(0, 8))

        # Validadores decimales (hasta 2 decimales)
        for e in (self.kilos_entry, self.cajas_entry, self.peso_entry, self.monto_compra_entry):
            adjuntar_validador_2_decimales(e, permitir_vacio=True)
        for w in (
            self.kilos_entry, self.cajas_entry, self.peso_entry, self.unidades_entry,
            self.monto_compra_entry, self.motivo_entry, self.combo_proveedor
        ):
            w.bind("<Return>", lambda e: self.registrar_entrada())

        # === MERMAS ===
        merma_panel = self._panel(root, pady=8, padx=8, fill="x")
        self._title(merma_panel, "Registro de Mermas")

        grid_m = tk.Frame(merma_panel, bg=PALETTE["panel"])
        grid_m.pack(fill="x", padx=8, pady=(0, 8))

        self._lbl(grid_m, "Producto:", row=0, column=0, padx=4, pady=4, sticky="e")
        self.combo_producto_merma = self._combobox(grid_m, width=26, row=0, column=1, padx=4, pady=4, sticky="we")
        grid_m.grid_columnconfigure(1, weight=1)
        self.combo_producto_merma.bind("<<ComboboxSelected>>", self._on_producto_change_merma)
        self.combo_producto_merma.bind("<Return>", lambda e: self.registrar_merma())

        self._lbl(grid_m, "Kilos (-):", row=0, column=2, padx=4, pady=4, sticky="e")
        self.merma_kilos_entry = self._entry(grid_m, width=12, row=0, column=3, padx=4, pady=4)

        self._lbl(grid_m, "Núm. Cajas (-):", row=0, column=4, padx=4, pady=4, sticky="e")
        self.merma_cajas_entry = self._entry(grid_m, width=12, row=0, column=5, padx=4, pady=4)

        self._lbl(grid_m, "Unidades (-):", row=0, column=6, padx=4, pady=4, sticky="e")
        self.merma_unidades_entry = self._entry(grid_m, width=12, row=0, column=7, padx=4, pady=4)

        self._lbl(grid_m, "Motivo:", row=1, column=0, padx=4, pady=4, sticky="e")
        self.motivo_merma_entry = self._entry(grid_m, width=52, row=1, column=1, columnspan=7, padx=4, pady=4, sticky="we")
        grid_m.grid_columnconfigure(1, weight=1)

        self._btn(grid_m, "Registrar Merma", "TButton", self.registrar_merma,
                  row=2, column=0, columnspan=8, padx=4, pady=6)

        for e in (self.merma_kilos_entry, self.merma_cajas_entry):
            adjuntar_validador_2_decimales(e, permitir_vacio=True)
        for w in (self.merma_kilos_entry, self.merma_cajas_entry, self.merma_unidades_entry, self.motivo_merma_entry):
            w.bind("<Return>", lambda e: self.registrar_merma())

        # === Buscador dinámico ===
        busc_panel = self._panel(root, pady=(2, 0), padx=8, fill="x")
        tk.Label(busc_panel, text="Buscar en inventario/mermas:", bg=PALETTE["panel"], fg=PALETTE["text"])\
            .pack(side=tk.LEFT, padx=8, pady=8)
        self.entry_busqueda = ttk.Entry(busc_panel, width=50, style="TEntry")
        self.entry_busqueda.pack(side=tk.LEFT, padx=8, pady=6, fill="x", expand=True)
        self.entry_busqueda.bind("<KeyRelease>", lambda e: self.cargar_movimientos(self.entry_busqueda.get().strip()))
        self.entry_busqueda.bind("<Return>", lambda e: self.cargar_movimientos(self.entry_busqueda.get().strip()))
        self.entry_busqueda.bind("<Escape>", self._limpiar_filtro_busqueda)

        # === Tabla de movimientos ===
        tabla_panel = self._panel(root, pady=8, padx=8, fill="both", expand=True)
        columnas = ("Movimiento", "Producto", "Kilos", "Cajas", "Unidades", "Monto", "Tipo", "Motivo", "Fecha")
        self.tree, _, _ = self._tree_with_scrolls(tabla_panel, columnas, height=12)
        for col, width, anchor in (
            ("Movimiento", 100, "center"),
            ("Producto",   200, "w"),
            ("Kilos",       90, "e"),
            ("Cajas",       90, "e"),
            ("Unidades",    90, "e"),
            ("Monto",      110, "e"),
            ("Tipo",       140, "center"),
            ("Motivo",     320, "w"),
            ("Fecha",      150, "center"),
        ):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("Producto", "Motivo")))
        self._setup_sorting(self.tree, columnas, {
            "Movimiento": "str",
            "Producto":   "str",
            "Kilos":      "float",
            "Cajas":      "float",
            "Unidades":   "int",
            "Monto":      "money",
            "Tipo":       "str",
            "Motivo":     "str",
            "Fecha":      "date",
        })
    # === CxP por compra (deudas <-> pagos) ===
        cxp_panel = self._panel(root, pady=8, padx=8, fill="both", expand=True)
        self._title(cxp_panel, "Gestión de Cuentas por Pagar por Compra")

        # Filtros
        filtros = tk.Frame(cxp_panel, bg=PALETTE["panel"]); filtros.pack(fill="x", padx=8, pady=(0,6))
        tk.Label(filtros, text="Proveedor:", bg=PALETTE["panel"], fg=PALETTE["text"]).pack(side="left", padx=(0,6))
        self.cxp_prov_filtro = self._combobox(filtros, width=26); self.cxp_prov_filtro.pack(side="left", padx=(0,12))
        self.cxp_prov_filtro.bind("<<ComboboxSelected>>", lambda _e: self._cargar_cxp_creditos())

        tk.Label(filtros, text="Desde:", bg=PALETTE["panel"], fg=PALETTE["text"]).pack(side="left")
        self.cxp_desde = ttk.Entry(filtros, width=12); self.cxp_desde.pack(side="left", padx=(6,4))
        ttk.Button(filtros, text="📅", width=3, command=lambda: self._pick_date(self.cxp_desde)).pack(side="left", padx=(0,12))

        tk.Label(filtros, text="Hasta:", bg=PALETTE["panel"], fg=PALETTE["text"]).pack(side="left")
        self.cxp_hasta = ttk.Entry(filtros, width=12); self.cxp_hasta.pack(side="left", padx=(6,4))
        ttk.Button(filtros, text="📅", width=3, command=lambda: self._pick_date(self.cxp_hasta)).pack(side="left", padx=(0,12))

        ttk.Button(filtros, text="Recargar", command=self._cargar_cxp_creditos).pack(side="left", padx=(6,0))

        # Paneles lado a lado
        dual = tk.Frame(cxp_panel, bg=PALETTE["panel"]); dual.pack(fill="both", expand=True, padx=8, pady=(6,0))
        dual.grid_columnconfigure(0, weight=1); dual.grid_columnconfigure(1, weight=1); dual.grid_rowconfigure(0, weight=1)

        # Izquierda: deudas (abiertas y cerradas)
        left_box = tk.LabelFrame(dual, text="Compras a crédito (deudas abiertas y cerradas)",
                                bg=PALETTE["panel"], fg=PALETTE["text"])
        left_box.grid(row=0, column=0, sticky="nsew", padx=(0,6))
        cols_deuda = ("Fecha","Proveedor","Producto","Monto","Saldo","DeudaID")
        self.tree_cxp_deudas, _, _ = self._tree_with_scrolls(left_box, cols_deuda, height=8)
        for col, w, a in (("Fecha",120,"center"),("Proveedor",180,"w"),("Producto",180,"w"),
                        ("Monto",110,"e"),("Saldo",110,"e"),("DeudaID",70,"center")):
            self.tree_cxp_deudas.heading(col, text=col)
            self.tree_cxp_deudas.column(col, width=w, anchor=a, stretch=(col in ("Proveedor","Producto")))
        self.tree_cxp_deudas.bind("<<TreeviewSelect>>", lambda _e: self._cargar_pagos_por_deuda())

        # Derecha: pagos de la deuda seleccionada
        right_box = tk.LabelFrame(dual, text="Pagos / Abonos", bg=PALETTE["panel"], fg=PALETTE["text"])
        right_box.grid(row=0, column=1, sticky="nsew", padx=(6,0))
        cols_pago = ("Fecha","DeudaID","Descripción","Monto")
        self.tree_cxp_pagos, _, _ = self._tree_with_scrolls(right_box, cols_pago, height=8)
        for col, w, a in (("Fecha",120,"center"),("DeudaID",80,"center"),("Descripción",260,"w"),("Monto",110,"e")):
            self.tree_cxp_pagos.heading(col, text=col)
            self.tree_cxp_pagos.column(col, width=w, anchor=a, stretch=(col == "Descripción"))

        # Barra de acciones
        barra = tk.Frame(cxp_panel, bg=PALETTE["panel"]); barra.pack(fill="x", padx=8, pady=(6,8))
        ttk.Button(barra, text="Abonar a compra seleccionada…", style="Success.TButton",
                command=self._abonar_compra_seleccionada).pack(side="left", padx=(0,8))
        ttk.Button(barra, text="Ver pagos de la compra", command=self._cargar_pagos_por_deuda).pack(side="left")
        ttk.Button(barra, text="Editar Abonos", command=self._abrir_crud_abonos)\
            .pack(side="left", padx=(8,0))

        
        # === PROVEEDORES (CRUD) ===
        prov_panel = self._panel(root, pady=8, padx=8, fill="both", expand=False)
        self._title(prov_panel, "Proveedores")

        top = tk.Frame(prov_panel, bg=PALETTE["panel"])
        top.pack(fill="x", padx=8, pady=(0, 6))

        tk.Label(top, text="Nombre:", bg=PALETTE["panel"], fg=PALETTE["text"])\
        .grid(row=0, column=0, padx=4, pady=4, sticky="e")
        self.prov_nombre_entry = self._entry(top, width=24, row=0, column=1, padx=4, pady=4, sticky="w")

        tk.Label(top, text="Teléfono:", bg=PALETTE["panel"], fg=PALETTE["text"])\
        .grid(row=0, column=2, padx=4, pady=4, sticky="e")
        self.prov_tel_entry = self._entry(top, width=18, row=0, column=3, padx=4, pady=4, sticky="w")

        tk.Label(top, text="Dirección:", bg=PALETTE["panel"], fg=PALETTE["text"])\
        .grid(row=0, column=4, padx=4, pady=4, sticky="e")
        self.prov_dir_entry = self._entry(top, width=36, row=0, column=5, padx=4, pady=4, sticky="we")
        top.grid_columnconfigure(5, weight=1)

        self._btn(top, "Agregar", "Success.TButton", self.agregar_proveedor,
                row=0, column=6, padx=6, pady=4, sticky="w")
        self._btn(top, "Editar seleccionado", "TButton", self.editar_proveedor,
                row=0, column=7, padx=6, pady=4, sticky="w")
        self._btn(top, "Eliminar seleccionado", "Danger.TButton", self.eliminar_proveedor,
                row=0, column=8, padx=6, pady=4, sticky="w")

        tabla_prov = tk.Frame(prov_panel, bg=PALETTE["panel"])
        tabla_prov.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tabla_prov.grid_rowconfigure(0, weight=1)
        tabla_prov.grid_columnconfigure(0, weight=1)

        self.tree_prov, _, _ = self._tree_with_scrolls(
            tabla_prov, ("ID", "Nombre", "Teléfono", "Dirección", "Deuda"), height=6
        )
        for col, w, a in (
            ("ID", 70, "center"),
            ("Nombre", 220, "w"),
            ("Teléfono", 140, "center"),
            ("Dirección", 320, "w"),
            ("Deuda", 120, "e"),
        ):
            self.tree_prov.heading(col, text=col)
            self.tree_prov.column(col, width=w, anchor=a, stretch=(col in ("Nombre", "Dirección")))
        self.tree_prov.bind("<Double-1>", lambda e: self.editar_proveedor())    
    # ====== CxP por compra (deudas <-> pagos) ======
    def _pick_date(self, entry_widget):
        """Abre el calendario; al elegir fecha llena el Entry y recarga la grilla."""
        top = tk.Toplevel(self)
        top.title("Seleccionar fecha")
        # Modo libre: todas las fechas activas
        CalendarioWidget(top, lambda fecha: (
            entry_widget.delete(0, tk.END),
            entry_widget.insert(0, fecha),
            self._cargar_cxp_creditos()
        ), fuentes=("all",))

    def _deuda_seleccionada(self):
        sel = self.tree_cxp_deudas.selection()
        if not sel:
            return None
        vals = self.tree_cxp_deudas.item(sel[0], "values")
        if not vals or len(vals) < 6:
            return None
        return int(vals[5])  # DeudaID

    def _cargar_cxp_creditos(self):
        """Llena la tabla izquierda con deudas (compras a crédito, abiertas y cerradas)."""
        if not getattr(self, "_has_deudas_prov", False):
            # Si aún no existe la tabla, intenta crearla (por si vienes de una DB vieja)
            try:
                with get_connection() as conn:
                    self._ensure_deudas_proveedores(conn.cursor())
            except Exception:
                pass

        # Limpiar grillas
        if hasattr(self, "tree_cxp_deudas"):
            self.tree_cxp_deudas.delete(*self.tree_cxp_deudas.get_children())
        if hasattr(self, "tree_cxp_pagos"):
            self.tree_cxp_pagos.delete(*self.tree_cxp_pagos.get_children())

        prov_filtro = (self.cxp_prov_filtro.get() or "").strip()
        prov_id = self.proveedores.get(prov_filtro) if prov_filtro and prov_filtro != "(todos)" else None
        desde = (self.cxp_desde.get() or "").strip()
        hasta = (self.cxp_hasta.get() or "").strip()

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                sql = """
                    SELECT d.id, d.fecha, pr.nombre AS proveedor, p.nombre AS producto,
                           d.monto, d.saldo
                    FROM deudas_proveedores d
                    JOIN proveedores pr ON pr.id = d.proveedor_id
                    LEFT JOIN productos   p ON p.id = d.producto_id
                    WHERE 1=1
                """
                params = []
                if prov_id:
                    sql += " AND d.proveedor_id = ?"
                    params.append(int(prov_id))
                if desde:
                    sql += " AND DATE(d.fecha) >= DATE(?)"
                    params.append(desde)
                if hasta:
                    sql += " AND DATE(d.fecha) <= DATE(?)"
                    params.append(hasta)
                sql += " ORDER BY d.fecha DESC, d.id DESC"
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

            for deuda_id, fecha, proveedor, producto, monto, saldo in rows:
                self.tree_cxp_deudas.insert("", "end", values=(
                    (fecha.split(" ")[0] if fecha else ""),
                    proveedor or "",
                    producto or "",
                    formato_moneda(float(monto or 0.0)),
                    formato_moneda(float(saldo or 0.0)),
                    int(deuda_id),
                ))
        except Exception as e:
            messagebox.showerror("CxP", f"No se pudieron cargar las deudas.\n{e}")

    def _cargar_pagos_por_deuda(self):
        """Llena la tabla derecha con los pagos de la deuda seleccionada."""
        if not hasattr(self, "tree_cxp_pagos"):
            return
        self.tree_cxp_pagos.delete(*self.tree_cxp_pagos.get_children())
        deuda_id = self._deuda_seleccionada()
        if not deuda_id:
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT fecha, descripcion, monto
                    FROM pagos_proveedores
                    WHERE deuda_proveedor_id = ?
                    ORDER BY fecha DESC, id DESC
                """, (int(deuda_id),))
                for fecha, desc, monto in cur.fetchall():
                    self.tree_cxp_pagos.insert("", "end", values=(
                        (fecha.split(" ")[0] if fecha else ""),
                        int(deuda_id),
                        (desc or ""),
                        formato_moneda(float(monto or 0.0)),
                    ))
        except Exception:
            # Silencioso: si la tabla aún no tiene FK deuda_proveedor_id
            pass

    def _abonar_compra_seleccionada(self):
        """Abre un diálogo y registra un pago exactamente sobre la deuda seleccionada."""
        deuda_id = self._deuda_seleccionada()
        if not deuda_id:
            messagebox.showinfo("Abonar", "Selecciona primero una compra en la lista de deudas.")
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT d.proveedor_id, pr.nombre, d.saldo
                    FROM deudas_proveedores d
                    JOIN proveedores pr ON pr.id = d.proveedor_id
                    WHERE d.id = ?
                """, (int(deuda_id),))
                row = cur.fetchone()
                if not row:
                    messagebox.showerror("Abonar", "Deuda no encontrada.")
                    return
                prov_id, prov_nombre, saldo = int(row[0]), (row[1] or ""), float(row[2] or 0.0)
        except Exception as e:
            messagebox.showerror("Abonar", f"No se pudo leer la deuda.\n{e}")
            return

        if saldo <= 0:
            messagebox.showinfo("Abonar", "Esta deuda ya está saldada.")
            return

        # Diálogo simple
        win = tk.Toplevel(self)
        win.title("Abonar a compra")
        try: win.configure(bg=PALETTE["bg"])
        except Exception: pass

        tk.Label(win, text=f"Proveedor: {prov_nombre}", bg=PALETTE["bg"], fg=PALETTE["text"])\
            .grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 4), sticky="w")
        tk.Label(win, text=f"Saldo pendiente: {formato_moneda(saldo)}", bg=PALETTE["bg"], fg=PALETTE["text"])\
            .grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")

        tk.Label(win, text="Monto $:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=2, column=0, padx=10, pady=6, sticky="e")
        ent_monto = ttk.Entry(win, width=16); ent_monto.grid(row=2, column=1, padx=10, pady=6, sticky="w")
        adjuntar_validador_2_decimales(ent_monto, permitir_vacio=False)

        tk.Label(win, text="Descripción:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=3, column=0, padx=10, pady=6, sticky="e")
        ent_desc = ttk.Entry(win, width=36); ent_desc.grid(row=3, column=1, padx=10, pady=6, sticky="we")
        win.grid_columnconfigure(1, weight=1)

        def guardar():
            from ui.helpers import to_float, redondear_dos_decimales
            try:
                monto = to_float(ent_monto.get(), permitir_cero=False)
            except Exception:
                messagebox.showerror("Monto", "Monto inválido.", parent=win); return
            if monto <= 0:
                messagebox.showerror("Monto", "El monto debe ser mayor a 0.", parent=win); return
            if monto > saldo:
                if not messagebox.askyesno("Confirmar", "El monto excede el saldo. ¿Registrar de todos modos (se recorta al saldo)?", parent=win):
                    return
            desc = (ent_desc.get() or "Abono a compra").strip()
            fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    aplica = min(monto, saldo)

                    # 1) Registrar pago CxP
                    cur.execute("""
                        INSERT INTO pagos_proveedores (proveedor_id, deuda_proveedor_id, monto, fecha, descripcion)
                        VALUES (?, ?, ?, ?, ?)
                    """, (int(prov_id), int(deuda_id), float(aplica), fecha_str, desc))

                    # 2) Actualizar saldo de la deuda
                    nuevo_saldo = redondear_dos_decimales(saldo - aplica)
                    cur.execute("UPDATE deudas_proveedores SET saldo = ? WHERE id = ?", (float(nuevo_saldo), int(deuda_id)))

                    # 3) Crear el GASTO correspondiente (enlazar proveedor si la columna existe)
                    g_cols = {r[1] for r in conn.execute("PRAGMA table_info(gastos)").fetchall()}
                    cols_g = ["tipo", "monto", "descripcion", "fecha"]
                    vals_g = ["Abono compra", float(aplica), f"{desc} — Deuda #{deuda_id} — Proveedor {prov_nombre}", fecha_str]
                    if "proveedor_id" in g_cols:
                        cols_g.append("proveedor_id"); vals_g.append(int(prov_id))
                    cur.execute(
                        f"INSERT INTO gastos ({', '.join(cols_g)}) VALUES ({', '.join('?' for _ in cols_g)})",
                        tuple(vals_g)
                    )

                messagebox.showinfo("Éxito", "Abono registrado.")
                win.destroy()
                self._cargar_cxp_creditos()
                self._cargar_pagos_por_deuda()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo registrar el abono.\n{e}", parent=win)
        
        # --- Botón + atajos + modal seguro ---
        ttk.Button(win, text="Registrar abono", command=guardar, style="Success.TButton")\
            .grid(row=4, column=0, columnspan=2, padx=10, pady=(6, 10), sticky="ew")

        # atajos
        win.bind("<Return>", lambda _e: guardar())
        win.bind("<Escape>", lambda _e: win.destroy())

        # modal seguro
        win.update_idletasks()
        try: win.grab_set()
        except Exception: pass
        try: win.focus_force()
        except Exception: pass
    def _abrir_crud_abonos(self):
        """Ventana CRUD para pagos_proveedores con ajuste automático del saldo de la deuda vinculada."""
        win = tk.Toplevel(self)
        win.title("Pagos / Abonos a Proveedores (CRUD)")
        try: win.configure(bg=PALETTE["bg"])
        except Exception: pass
        win.geometry("900x420")
        win.transient(self.winfo_toplevel())

        # --- Tabla ---
        cols = ("ID","Fecha","Proveedor","DeudaID","Descripción","Monto")
        tree, _, _ = self._tree_with_scrolls(win, cols, height=12)
        for c,w,a in (("ID",70,"center"),("Fecha",130,"center"),("Proveedor",220,"w"),
                      ("DeudaID",90,"center"),("Descripción",300,"w"),("Monto",110,"e")):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor=a, stretch=(c in ("Proveedor","Descripción")))

        # detectar columnas reales
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                pp_cols = {r[1] for r in cur.execute("PRAGMA table_info(pagos_proveedores)").fetchall()}
                has_prov = "proveedor_id" in pp_cols
                has_deuda_fk = "deuda_proveedor_id" in pp_cols
                # cargar
                if has_prov:
                    cur.execute("""
                        SELECT pp.id, pp.fecha, IFNULL(pr.nombre,'(s/d)') AS proveedor,
                               {did} AS deuda_id, IFNULL(pp.descripcion,''), COALESCE(pp.monto,0)
                        FROM pagos_proveedores pp
                        LEFT JOIN proveedores pr ON pr.id = pp.proveedor_id
                        ORDER BY datetime(pp.fecha) DESC, pp.id DESC
                    """.format(did=("pp.deuda_proveedor_id" if has_deuda_fk else "NULL")))
                else:
                    cur.execute("""
                        SELECT pp.id, pp.fecha, '(s/d)' AS proveedor,
                               {did} AS deuda_id, IFNULL(pp.descripcion,''), COALESCE(pp.monto,0)
                        FROM pagos_proveedores pp
                        ORDER BY datetime(pp.fecha) DESC, pp.id DESC
                    """.format(did=("pp.deuda_proveedor_id" if has_deuda_fk else "NULL")))
                rows = cur.fetchall()
        except Exception as e:
            messagebox.showerror("Pagos", f"No se pudieron leer los abonos.\n{e}", parent=win)
            win.destroy()
            return

        for pid, fecha, prov, deuda_id, desc, monto in rows:
            tree.insert("", "end", values=(
                int(pid),
                (fecha.split(" ")[0] if fecha else ""),
                prov or "(s/d)",
                (int(deuda_id) if deuda_id else ""),
                (desc or ""),
                formato_moneda(float(monto or 0.0))
            ))

        def _sel_id():
            it = tree.focus()
            if not it: return None
            vals = tree.item(it, "values")
            if not vals: return None
            return int(vals[0])

        # --- Edición ---
        def editar():
            pid = _sel_id()
            if not pid:
                messagebox.showinfo("Editar", "Selecciona un abono en la tabla.", parent=win); return
            # leer registro actual
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, proveedor_id, deuda_proveedor_id, fecha, descripcion, monto FROM pagos_proveedores WHERE id = ?", (pid,))
                    row = cur.fetchone()
                    if not row:
                        messagebox.showerror("Editar", "No se encontró el abono.", parent=win); return
                    _id, prov_id, deuda_id, fecha, desc, monto = row
                    prov_id = int(prov_id) if prov_id is not None else None
                    deuda_id = int(deuda_id) if deuda_id is not None else None
                    monto = float(monto or 0.0)
            except Exception as e:
                messagebox.showerror("Editar", f"No se pudo leer el abono.\n{e}", parent=win); return

            w = tk.Toplevel(win); w.title(f"Editar abono #{pid}")
            try: w.configure(bg=PALETTE["bg"])
            except Exception: pass
            tk.Label(w, text=f"ID: {pid}", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=8, pady=(8,2), sticky="w")
            tk.Label(w, text=f"Deuda vinculada: {deuda_id if deuda_id else '(ninguna)'}", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=8, pady=2, sticky="w")

            tk.Label(w, text="Fecha (YYYY-MM-DD HH:MM:SS):", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=2, column=0, padx=8, pady=6, sticky="e")
            e_fecha = ttk.Entry(w, width=22); e_fecha.grid(row=2, column=1, padx=8, pady=6, sticky="w")
            e_fecha.insert(0, fecha or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            tk.Label(w, text="Descripción:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=3, column=0, padx=8, pady=6, sticky="e")
            e_desc = ttk.Entry(w, width=36); e_desc.grid(row=3, column=1, padx=8, pady=6, sticky="we")
            e_desc.insert(0, desc or "")
            w.grid_columnconfigure(1, weight=1)

            tk.Label(w, text="Monto $:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=4, column=0, padx=8, pady=6, sticky="e")
            e_monto = ttk.Entry(w, width=16); e_monto.grid(row=4, column=1, padx=8, pady=6, sticky="w")
            adjuntar_validador_2_decimales(e_monto, permitir_vacio=False)
            e_monto.insert(0, f"{monto:.2f}")

            def guardar():
                from ui.helpers import to_float, redondear_dos_decimales
                try:
                    nuevo_monto = to_float(e_monto.get(), permitir_cero=False)
                except Exception:
                    messagebox.showerror("Monto", "Monto inválido.", parent=w); return
                if nuevo_monto <= 0:
                    messagebox.showerror("Monto", "Debe ser mayor a 0.", parent=w); return
                nueva_fecha = (e_fecha.get() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")).strip()
                nueva_desc  = (e_desc.get() or "").strip()

                try:
                    with get_connection() as conn:
                        cur = conn.cursor()
                        # ajustar saldo si hay deuda vinculada
                        if deuda_id:
                            cur.execute("SELECT saldo FROM deudas_proveedores WHERE id = ?", (int(deuda_id),))
                            r = cur.fetchone()
                            if r:
                                saldo = float(r[0] or 0.0)
                                delta = float(nuevo_monto) - float(monto)
                                nuevo_saldo = redondear_dos_decimales(max(0.0, saldo - delta))
                                cur.execute("UPDATE deudas_proveedores SET saldo = ? WHERE id = ?", (float(nuevo_saldo), int(deuda_id)))
                        # actualizar abono
                        cur.execute("""
                            UPDATE pagos_proveedores
                            SET fecha = ?, descripcion = ?, monto = ?
                            WHERE id = ?
                        """, (nueva_fecha, nueva_desc, float(nuevo_monto), int(pid)))
                    messagebox.showinfo("Éxito", "Abono actualizado.", parent=w)
                    w.destroy()
                    self._cargar_cxp_creditos()
                    self._cargar_pagos_por_deuda()
                    # refrescar tabla local
                    for iid in tree.get_children(""):
                        if int(tree.item(iid, "values")[0]) == pid:
                            tree.item(iid, values=(
                                pid,
                                (nueva_fecha.split(" ")[0] if nueva_fecha else ""),
                                tree.item(iid, "values")[2],
                                (deuda_id if deuda_id else ""),
                                nueva_desc,
                                formato_moneda(nuevo_monto)
                            ))
                            break
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo guardar.\n{e}", parent=w)

            ttk.Button(w, text="Guardar", command=guardar, style="Success.TButton")\
                .grid(row=5, column=0, columnspan=2, pady=8, padx=8, sticky="ew")
            w.bind("<Return>", lambda _e: guardar())
            w.bind("<Escape>", lambda _e: w.destroy())
            try: w.grab_set()
            except Exception: pass

        # --- Eliminación ---
        def eliminar():
            pid = _sel_id()
            if not pid:
                messagebox.showinfo("Eliminar", "Selecciona un abono.", parent=win); return
            if not messagebox.askyesno("Confirmar", f"¿Eliminar abono #{pid}?", parent=win):
                return
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT deuda_proveedor_id, monto FROM pagos_proveedores WHERE id = ?", (int(pid),))
                    r = cur.fetchone()
                    deuda_id = int(r[0]) if r and r[0] is not None else None
                    monto = float(r[1] or 0.0)

                    # reponer saldo si corresponde
                    if deuda_id:
                        cur.execute("UPDATE deudas_proveedores SET saldo = saldo + ? WHERE id = ?", (float(monto), int(deuda_id)))

                    # eliminar pago
                    cur.execute("DELETE FROM pagos_proveedores WHERE id = ?", (int(pid),))
                messagebox.showinfo("Éxito", "Abono eliminado.", parent=win)
                # quitar de la tabla
                it = tree.focus()
                if it: tree.delete(it)
                self._cargar_cxp_creditos()
                self._cargar_pagos_por_deuda()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar.\n{e}", parent=win)

        # --- Barra inferior ---
        bar = tk.Frame(win, bg=PALETTE["panel"]); bar.pack(fill="x", padx=8, pady=8)
        ttk.Button(bar, text="Editar", command=editar).pack(side="left", padx=(0,8))
        ttk.Button(bar, text="Eliminar", command=eliminar, style="Danger.TButton").pack(side="left")
        ttk.Button(bar, text="Cerrar", command=win.destroy).pack(side="right")
        try: win.grab_set()
        except Exception: pass


    # ---------------------------
    # Post-construcción
    # ---------------------------
    def _after_mount(self):
        """Tareas posteriores a construir la UI."""
        try:
            self._style.configure(self._tree_style_name, rowheight=26)
        except Exception:
            pass

        self._detectar_esquema()
        self.cargar_productos()
        self.cargar_proveedores()
        self.cargar_movimientos()

        # Filtros CxP por compra: proveedor + rango por defecto (día de hoy)
        try:
            self.cxp_prov_filtro["values"] = ["(todos)"] + list(self.proveedores.keys())
            if not self.cxp_prov_filtro.get():
                self.cxp_prov_filtro.current(0)
        except Exception:
            pass

        hoy = datetime.now().strftime("%Y-%m-%d")
        try:
            if not self.cxp_desde.get().strip():
                self.cxp_desde.insert(0, hoy)
            if not self.cxp_hasta.get().strip():
                self.cxp_hasta.insert(0, hoy)
        except Exception:
            pass

        self._cargar_cxp_creditos()




    # ---------------------------
    # Esquema / detección
    # ---------------------------
    def _detectar_esquema(self):
        try:
            with get_connection() as conn:
                cur = conn.cursor()

                # inventario
                cur.execute("PRAGMA table_info(inventario)")
                inv_cols = {str(r[1]).lower() for r in cur.fetchall()}
                self._inv_has_gasto_fk = ("gasto_id" in inv_cols)
                self._inv_has_deuda_fk = ("deuda_proveedor_id" in inv_cols)

                # deudas_proveedores
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deudas_proveedores'")
                self._has_deudas_prov = (cur.fetchone() is not None)

                # pagos_proveedores columnas
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pagos_proveedores'")
                if cur.fetchone() is not None:
                    cur.execute("PRAGMA table_info(pagos_proveedores)")
                    pagos_cols = {str(r[1]).lower() for r in cur.fetchall()}
                    self._pagos_has_proveedor_id = ("proveedor_id" in pagos_cols)
                    self._pagos_has_deuda_fk = ("deuda_proveedor_id" in pagos_cols)
                else:
                    self._pagos_has_proveedor_id = False
                    self._pagos_has_deuda_fk = False

                # proveedores.direccion ?
                cur.execute("PRAGMA table_info(proveedores)")
                prov_cols = {str(r[1]).lower() for r in cur.fetchall()}
                self._prov_has_direccion = ("direccion" in prov_cols)

        except Exception:
            self._inv_has_gasto_fk = False
            self._inv_has_deuda_fk = False
            self._has_deudas_prov = False
            self._pagos_has_proveedor_id = False
            self._pagos_has_deuda_fk = False
            self._prov_has_direccion = False


            
    def _ensure_deudas_proveedores(self, cur):
        """
        Crea en caliente las tablas necesarias para compras a crédito si no existen.
        Actualiza los flags de esquema para que el resto del módulo lo detecte.
        """
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS deudas_proveedores (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    proveedor_id  INTEGER NOT NULL,
                    producto_id   INTEGER,
                    monto         REAL    NOT NULL CHECK (monto  >= 0),
                    saldo         REAL    NOT NULL DEFAULT 0.0 CHECK (saldo >= 0),
                    descripcion   TEXT,
                    fecha         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
                    FOREIGN KEY (producto_id)  REFERENCES productos(id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_deudas_prov_proveedor ON deudas_proveedores(proveedor_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_deudas_prov_fecha     ON deudas_proveedores(fecha)")
            self._has_deudas_prov = True

            # Opcional pero útil: asegurar pagos_proveedores (plural) que usa el reporte/pagos
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pagos_proveedores (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    proveedor_id        INTEGER,
                    monto               REAL    NOT NULL CHECK (monto > 0),
                    fecha               TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    descripcion         TEXT,
                    deuda_proveedor_id  INTEGER,
                    FOREIGN KEY (proveedor_id)       REFERENCES proveedores(id),
                    FOREIGN KEY (deuda_proveedor_id) REFERENCES deudas_proveedores(id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pagos_proveedores_prov  ON pagos_proveedores(proveedor_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pagos_proveedores_fecha ON pagos_proveedores(fecha)")

            # Refrescar flags de pagos
            cur.execute("PRAGMA table_info(pagos_proveedores)")
            pagos_cols = {str(r[1]).lower() for r in cur.fetchall()}
            self._pagos_has_proveedor_id = ("proveedor_id" in pagos_cols)
            self._pagos_has_deuda_fk     = ("deuda_proveedor_id" in pagos_cols)
        except Exception:
            # Si algo falla, dejamos flags como estaban; el insert fallará y lo capturará el except del caller.
            pass
        
        
    # ---------------------------
    # Carga de catálogos
    # ---------------------------
    def cargar_productos(self):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, nombre FROM productos ORDER BY nombre COLLATE NOCASE")
                rows = cur.fetchall()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los productos.\n{e}")
            return
        self.productos = {nombre: pid for (pid, nombre) in rows}
        nombres = list(self.productos.keys())
        self.combo_producto["values"] = nombres
        self.combo_producto_merma["values"] = nombres
        if nombres:
            if not self.combo_producto.get():
                self.combo_producto.current(0)
            if not self.combo_producto_merma.get():
                self.combo_producto_merma.current(0)
            self._actualizar_info_producto(self.combo_producto.get())

    def cargar_proveedores(self):
        try:
            with get_connection() as conn:
                cur = conn.cursor()

                # ¿Tenemos columna direccion?
                has_dir = getattr(self, "_prov_has_direccion", False)
                # ¿Existe tabla de deudas?
                has_deudas = getattr(self, "_has_deudas_prov", False)

                if has_dir and has_deudas:
                    cur.execute("""
                        SELECT pr.id,
                            pr.nombre,
                            IFNULL(pr.telefono,'') AS tel,
                            IFNULL(pr.direccion,'') AS dir,
                            COALESCE(SUM(dp.saldo), 0.0) AS deuda
                        FROM proveedores pr
                        LEFT JOIN deudas_proveedores dp
                            ON dp.proveedor_id = pr.id AND dp.saldo > 0
                        GROUP BY pr.id, pr.nombre, pr.telefono, pr.direccion
                        ORDER BY pr.nombre COLLATE NOCASE
                    """)
                    rows = cur.fetchall()
                elif has_dir and not has_deudas:
                    cur.execute("""
                        SELECT pr.id,
                            pr.nombre,
                            IFNULL(pr.telefono,'') AS tel,
                            IFNULL(pr.direccion,'') AS dir,
                            0.0 AS deuda
                        FROM proveedores pr
                        ORDER BY pr.nombre COLLATE NOCASE
                    """)
                    rows = cur.fetchall()
                elif not has_dir and has_deudas:
                    cur.execute("""
                        SELECT pr.id,
                            pr.nombre,
                            IFNULL(pr.telefono,'') AS tel,
                            '' AS dir,
                            COALESCE(SUM(dp.saldo), 0.0) AS deuda
                        FROM proveedores pr
                        LEFT JOIN deudas_proveedores dp
                            ON dp.proveedor_id = pr.id AND dp.saldo > 0
                        GROUP BY pr.id, pr.nombre, pr.telefono
                        ORDER BY pr.nombre COLLATE NOCASE
                    """)
                    rows = cur.fetchall()
                else:
                    cur.execute("""
                        SELECT pr.id,
                            pr.nombre,
                            IFNULL(pr.telefono,'') AS tel,
                            '' AS dir,
                            0.0 AS deuda
                        FROM proveedores pr
                        ORDER BY pr.nombre COLLATE NOCASE
                    """)
                    rows = cur.fetchall()

        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los proveedores.\n{e}")
            return

        # diccionario para combos
        self.proveedores = {nombre: pid for (pid, nombre, _tel, _dir, _deuda) in rows}
        nombres = list(self.proveedores.keys())

        # Combos
        self.combo_proveedor["values"] = ["(sin proveedor)"] + nombres
        if not self.combo_proveedor.get():
            self.combo_proveedor.current(0)

        # Tabla
        self.tree_prov.delete(*self.tree_prov.get_children())
        for pid, nombre, tel, dire, deuda in rows:
            deuda_txt = formato_moneda(float(deuda)) if deuda is not None else "$0.00"
            self.tree_prov.insert("", "end", values=(pid, nombre, tel or "", dire or "", deuda_txt))

        set_treeview_stripes(self.tree_prov, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))
        
        try:
            self.cxp_prov_filtro["values"] = ["(todos)"] + list(self.proveedores.keys())
            if not self.cxp_prov_filtro.get():
                self.cxp_prov_filtro.current(0)
        except Exception:
            pass

        
    def _actualizar_deuda_proveedor_pago(self):
        """Llena la tabla de deudas abiertas según el proveedor seleccionado en el combo de pagos."""
        if not getattr(self, "_has_deudas_prov", False):
            if hasattr(self, "tree_deudas"):
                self.tree_deudas.delete(*self.tree_deudas.get_children())
            return

        prov_nombre = (self.combo_prov_pago.get() or "").strip()
        prov_id = self.proveedores.get(prov_nombre)
        if not prov_id or not hasattr(self, "tree_deudas"):
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT d.id,
                           d.fecha,
                           IFNULL(p.nombre,'(s/n)') AS producto,
                           d.monto,
                           d.saldo,
                           IFNULL(d.descripcion,'')
                    FROM deudas_proveedores d
                    LEFT JOIN productos p ON p.id = d.producto_id
                    WHERE d.proveedor_id = ? AND d.saldo > 0
                    ORDER BY d.fecha ASC, d.id ASC
                """, (int(prov_id),))
                rows = cur.fetchall()
        except Exception as e:
            messagebox.showerror("CxP", f"No se pudo cargar deudas del proveedor.\n{e}")
            return

        self.tree_deudas.delete(*self.tree_deudas.get_children())
        for did, fecha, prod, monto, saldo, desc in rows:
            self.tree_deudas.insert("", "end", values=(
                int(did),
                formatear_fecha(fecha),
                prod or "",
                formato_moneda(float(monto or 0)),
                formato_moneda(float(saldo or 0)),
                desc or ""
            ))



    # ---------------------------
    # Cambios de selección
    # ---------------------------
    def _on_producto_change(self, _e=None):
        self._actualizar_info_producto(self.combo_producto.get())

    def _actualizar_info_producto(self, nombre: str):
        if not nombre:
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT kilos, num_cajas, unidades, peso_caja FROM productos WHERE nombre = ?", (nombre,))
                row = cur.fetchone()
            if not row:
                return
            kilos, cajas, unidades, peso = (float(row[0] or 0), float(row[1] or 0), int(row[2] or 0), float(row[3] or 0))
            self.peso_entry.delete(0, tk.END)
            if peso > 0:
                self.peso_entry.insert(0, f"{redondear_dos_decimales(peso):.2f}")
            self.info_label.config(
                text=f"Kilos: {redondear_dos_decimales(kilos):.2f} | Cajas: {redondear_dos_decimales(cajas):.2f} | "
                     f"Unidades: {unidades} | Peso/caja: {redondear_dos_decimales(peso):.2f} kg"
            )
        except Exception:
            pass

    def _on_producto_change_merma(self, _e=None):
        self._actualizar_info_producto(self.combo_producto_merma.get())

    # ---------------------------
    # ENTRADAS
    # ---------------------------
    def registrar_entrada(self):
        nombre = (self.combo_producto.get() or "").strip()
        if not nombre:
            messagebox.showwarning("Falta producto", "Selecciona un producto.")
            return

        try:
            kilos        = to_float(self.kilos_entry.get() or 0, permitir_cero=True)
            num_cajas    = to_float(self.cajas_entry.get() or 0, permitir_cero=True)
            peso_caja    = to_float(self.peso_entry.get() or 0, permitir_cero=True)
            unidades     = to_int(self.unidades_entry.get() or 0, permitir_cero=True)
            monto_compra = to_float(self.monto_compra_entry.get() or 0, permitir_cero=True)
        except ValueError:
            messagebox.showerror("Error", "Valores inválidos. Revisa kilos/cajas/peso/unidades/monto.")
            return
        if any(x < 0 for x in (kilos, num_cajas, peso_caja, unidades, monto_compra)):
            messagebox.showerror("Error", "Los valores no pueden ser negativos.")
            return

        # Autocálculo kilos<->cajas
        if peso_caja > 0:
            if kilos <= 0 and num_cajas > 0:
                kilos = redondear_dos_decimales(num_cajas * peso_caja)
                self.kilos_entry.delete(0, tk.END); self.kilos_entry.insert(0, f"{kilos:.2f}")
            elif num_cajas <= 0 and kilos > 0:
                num_cajas = redondear_dos_decimales(kilos / peso_caja)
                self.cajas_entry.delete(0, tk.END); self.cajas_entry.insert(0, f"{num_cajas:.2f}")

        if (kilos <= 0) and (num_cajas <= 0) and (unidades <= 0):
            messagebox.showerror("Error", "Ingresa kilos, cajas o unidades mayores a 0.")
            return

        tipo = (self.tipo_combo.get() or "Compra").strip()
        pago = (self.pago_combo.get() or "Contado").strip()
        motivo = (self.motivo_entry.get() or "Entrada sin motivo").strip()

        producto_id = self.productos.get(nombre)
        if not producto_id:
            messagebox.showerror("Error", "Producto no encontrado.")
            return

        proveedor_nom = (self.combo_proveedor.get() or "").strip()
        proveedor_id = None
        if proveedor_nom and proveedor_nom != "(sin proveedor)":
            proveedor_id = self.proveedores.get(proveedor_nom)

        # Validaciones de compra a crédito
        if tipo.lower() == "compra" and pago == "Crédito":
            if not proveedor_id:
                messagebox.showerror("Falta proveedor", "Selecciona un proveedor para una compra a crédito.")
                return
            if monto_compra <= 0:
                messagebox.showerror("Monto inválido", "Ingresa un monto de compra mayor a 0 para registrar la deuda.")
                return

        fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with get_connection() as conn:
                cur = conn.cursor()

                # 1) Insertar inventario
                cur.execute("""
                    INSERT INTO inventario (producto_id, kilos, num_cajas, unidades, tipo, motivo, fecha)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (int(producto_id), float(kilos), float(num_cajas), int(unidades), tipo, motivo, fecha_str))
                inventario_id = cur.lastrowid

                # 2) Actualizar stock
                cur.execute("""
                    UPDATE productos
                    SET kilos = kilos + ?, num_cajas = num_cajas + ?, unidades = unidades + ?, peso_caja = ?
                    WHERE id = ?
                """, (float(kilos), float(num_cajas), int(unidades), float(peso_caja), int(producto_id)))

                # 3) Asientos monetarios
                if tipo.lower() == "compra" and monto_compra > 0:
                    if pago == "Contado":
                        # Gasto
                        cur.execute("""
                            INSERT INTO gastos (tipo, monto, descripcion, fecha)
                            VALUES (?, ?, ?, ?)
                        """, ("Compra", float(monto_compra), nombre, fecha_str))
                        gasto_id = cur.lastrowid
                        if self._inv_has_gasto_fk:
                            try:
                                cur.execute("UPDATE inventario SET gasto_id = ? WHERE id = ?", (int(gasto_id), int(inventario_id)))
                            except Exception:
                                pass
                    else:
                        # Deuda proveedor (asegurar que existan tablas de CxP)
                        self._ensure_deudas_proveedores(cur)
                        cur.execute("""
                            INSERT INTO deudas_proveedores (proveedor_id, producto_id, monto, saldo, descripcion, fecha)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (int(proveedor_id), int(producto_id), float(monto_compra), float(monto_compra), motivo or nombre, fecha_str))
                        deuda_id = cur.lastrowid
                        if self._inv_has_deuda_fk:
                            try:
                                cur.execute("UPDATE inventario SET deuda_proveedor_id = ? WHERE id = ?", (int(deuda_id), int(inventario_id)))
                            except Exception:
                                pass



            messagebox.showinfo("Éxito", "Entrada registrada.")
            for e in (self.kilos_entry, self.cajas_entry, self.peso_entry, self.unidades_entry, self.monto_compra_entry, self.motivo_entry):
                e.delete(0, tk.END)
            self.cargar_movimientos()
            self._actualizar_info_producto(nombre)

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la entrada.\n{e}")

    # ---------------------------
    # MERMAS
    # ---------------------------
    def registrar_merma(self):
        nombre = (self.combo_producto_merma.get() or "").strip()
        if not nombre:
            messagebox.showwarning("Falta producto", "Selecciona un producto.")
            return

        try:
            kilos     = to_float(self.merma_kilos_entry.get() or 0, permitir_cero=True)
            num_cajas = to_float(self.merma_cajas_entry.get() or 0, permitir_cero=True)
            unidades  = to_int(self.merma_unidades_entry.get() or 0, permitir_cero=True)
        except ValueError:
            messagebox.showerror("Error", "Valores inválidos. Revisa kilos/cajas/unidades.")
            return
        if kilos < 0 or num_cajas < 0 or unidades < 0:
            messagebox.showerror("Error", "Los valores no pueden ser negativos.")
            return

        # Cargar stock y peso_caja
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, kilos, num_cajas, unidades, peso_caja FROM productos WHERE nombre = ?", (nombre,))
                row = cur.fetchone()
            if not row:
                messagebox.showerror("Error", "Producto no encontrado.")
                return
            producto_id, stock_kilos, stock_cajas, stock_unidades, peso_caja = \
                int(row[0]), float(row[1] or 0), float(row[2] or 0), int(row[3] or 0), float(row[4] or 0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo leer el stock del producto.\n{e}")
            return

        # Autocálculo kilos<->cajas
        if peso_caja > 0:
            if kilos <= 0 and num_cajas > 0:
                kilos = redondear_dos_decimales(num_cajas * peso_caja)
                self.merma_kilos_entry.delete(0, tk.END); self.merma_kilos_entry.insert(0, f"{kilos:.2f}")
            elif num_cajas <= 0 and kilos > 0:
                num_cajas = redondear_dos_decimales(kilos / peso_caja)
                self.merma_cajas_entry.delete(0, tk.END); self.merma_cajas_entry.insert(0, f"{num_cajas:.2f}")

        if (kilos <= 0) and (num_cajas <= 0) and (unidades <= 0):
            messagebox.showerror("Error", "Ingresa al menos un valor mayor a 0.")
            return

        # Stock suficiente
        if kilos > stock_kilos:
            messagebox.showerror("Stock insuficiente", f"Kilos disponibles: {redondear_dos_decimales(stock_kilos)}")
            return
        if num_cajas > stock_cajas:
            messagebox.showerror("Stock insuficiente", f"Cajas disponibles: {redondear_dos_decimales(stock_cajas)}")
            return
        if unidades > stock_unidades:
            messagebox.showerror("Stock insuficiente", f"Unidades disponibles: {stock_unidades}")
            return

        motivo = (self.motivo_merma_entry.get() or "Merma sin motivo").strip()
        fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                # Inserta merma
                cur.execute("""
                    INSERT INTO mermas (producto_id, kilos, num_cajas, unidades, motivo, fecha)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (int(producto_id), float(kilos), float(num_cajas), int(unidades), motivo, fecha_str))
                # Descuenta stock
                cur.execute("""
                    UPDATE productos
                    SET kilos = kilos - ?, num_cajas = num_cajas - ?, unidades = unidades - ?
                    WHERE id = ?
                """, (float(kilos), float(num_cajas), int(unidades), int(producto_id)))

            messagebox.showinfo("Éxito", "Merma registrada.")
            for e in (self.merma_kilos_entry, self.merma_cajas_entry, self.merma_unidades_entry, self.motivo_merma_entry):
                e.delete(0, tk.END)
            self.cargar_movimientos()
            self._actualizar_info_producto(nombre)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la merma.\n{e}")

    # ---------------------------
    # PAGOS A PROVEEDOR
    # ---------------------------
    def registrar_pago_proveedor(self):
        prov_nombre = (self.combo_prov_pago.get() or "").strip()
        if not prov_nombre:
            messagebox.showwarning("Proveedor", "Selecciona un proveedor.")
            return
        prov_id = self.proveedores.get(prov_nombre)
        if not prov_id:
            messagebox.showerror("Proveedor", "Proveedor no encontrado.")
            return

        try:
            monto = to_float(self.pago_monto_entry.get() or 0, permitir_cero=False)
        except ValueError:
            messagebox.showerror("Monto", "Monto inválido. Ingresa un valor numérico mayor a 0.")
            return
        if monto <= 0:
            messagebox.showerror("Monto", "El monto debe ser mayor a 0.")
            return

        nota = (self.pago_desc_entry.get() or "").strip()
        fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ¿Seleccionaste una deuda en la tabla?
        deuda_sel_id = None
        if hasattr(self, "tree_deudas"):
            sel = self.tree_deudas.selection()
            if sel:
                vals = self.tree_deudas.item(sel[0], "values")
                if vals:
                    deuda_sel_id = int(vals[0])

        try:
            with get_connection() as conn:
                cur = conn.cursor()

                # 1) Registrar el pago con las columnas disponibles
                if self._pagos_has_proveedor_id and self._pagos_has_deuda_fk:
                    cur.execute("""
                        INSERT INTO pagos_proveedores (proveedor_id, deuda_proveedor_id, monto, fecha, descripcion)
                        VALUES (?, ?, ?, ?, ?)
                    """, (int(prov_id), deuda_sel_id, float(monto), fecha_str, nota))
                elif self._pagos_has_proveedor_id:
                    cur.execute("""
                        INSERT INTO pagos_proveedores (proveedor_id, monto, fecha, descripcion)
                        VALUES (?, ?, ?, ?)
                    """, (int(prov_id), float(monto), fecha_str, nota))
                elif self._pagos_has_deuda_fk:
                    cur.execute("""
                        INSERT INTO pagos_proveedores (deuda_proveedor_id, monto, fecha, descripcion)
                        VALUES (?, ?, ?, ?)
                    """, (deuda_sel_id, float(monto), fecha_str, nota))
                else:
                    cur.execute("""
                        INSERT INTO pagos_proveedores (monto, fecha, descripcion)
                        VALUES (?, ?, ?)
                    """, (float(monto), fecha_str, nota))

                # 2) Aplicar el pago
                restante = float(monto)

                if self._has_deudas_prov:
                    if deuda_sel_id:
                        # Aplica SOLO a la deuda seleccionada; si sobra, pasa a FIFO
                        cur.execute("SELECT saldo FROM deudas_proveedores WHERE id = ?", (int(deuda_sel_id),))
                        row = cur.fetchone()
                        if not row:
                            raise ValueError("La deuda seleccionada ya no existe.")
                        saldo = float(row[0] or 0.0)
                        aplica = min(restante, saldo)
                        cur.execute("UPDATE deudas_proveedores SET saldo = ? WHERE id = ?",
                                    (float(redondear_dos_decimales(saldo - aplica)), int(deuda_sel_id)))
                        restante = redondear_dos_decimales(restante - aplica)

                        if restante > 0:
                            cur.execute("""
                                SELECT id, saldo FROM deudas_proveedores
                                WHERE proveedor_id = ? AND saldo > 0 AND id <> ?
                                ORDER BY fecha ASC, id ASC
                            """, (int(prov_id), int(deuda_sel_id)))
                            for did, s in [(int(r[0]), float(r[1] or 0.0)) for r in cur.fetchall()]:
                                if restante <= 0: break
                                ap = min(restante, s)
                                cur.execute("UPDATE deudas_proveedores SET saldo = ? WHERE id = ?",
                                            (float(redondear_dos_decimales(s - ap)), int(did)))
                                restante = redondear_dos_decimales(restante - ap)
                    else:
                        # FIFO clásico si no seleccionaste nada
                        cur.execute("""
                            SELECT id, saldo FROM deudas_proveedores
                            WHERE proveedor_id = ? AND saldo > 0
                            ORDER BY fecha ASC, id ASC
                        """, (int(prov_id),))
                        for did, saldo in [(int(r[0]), float(r[1] or 0.0)) for r in cur.fetchall()]:
                            if restante <= 0: break
                            ap = min(restante, saldo)
                            cur.execute("UPDATE deudas_proveedores SET saldo = ? WHERE id = ?",
                                        (float(redondear_dos_decimales(saldo - ap)), int(did)))
                            restante = redondear_dos_decimales(restante - ap)

            messagebox.showinfo("Éxito", "Pago registrado y aplicado.")
            self.pago_monto_entry.delete(0, tk.END)
            self.pago_desc_entry.delete(0, tk.END)
            # Refrescar UI relacionada
            self._actualizar_deuda_proveedor_pago()
            self.cargar_proveedores()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar el pago.\n{e}")


    # ---------------------------
    # Listado / búsqueda
    # ---------------------------
    def _limpiar_filtro_busqueda(self, _e=None):
        self.entry_busqueda.delete(0, tk.END)
        self.cargar_movimientos()

    def cargar_movimientos(self, filtro: str = ""):
        self.tree.delete(*self.tree.get_children())
        try:
            with get_connection() as conn:
                cur = conn.cursor()

                if self._inv_has_gasto_fk:
                    if filtro:
                        like = f"%{filtro}%"
                        cur.execute("""
                            SELECT 'Entrada' AS mov, p.nombre, i.kilos, i.num_cajas, i.unidades,
                                   g.monto, i.tipo, i.motivo, i.fecha
                            FROM inventario i
                            JOIN productos p ON p.id = i.producto_id
                            LEFT JOIN gastos g ON g.id = i.gasto_id
                            WHERE p.nombre LIKE ? OR i.motivo LIKE ? OR IFNULL(i.tipo,'') LIKE ?
                        """, (like, like, like))
                        entradas = cur.fetchall()
                        cur.execute("""
                            SELECT 'Merma' AS mov, p.nombre, m.kilos, m.num_cajas, m.unidades,
                                   NULL, '' AS tipo, m.motivo, m.fecha
                            FROM mermas m
                            JOIN productos p ON p.id = m.producto_id
                            WHERE p.nombre LIKE ? OR m.motivo LIKE ?
                        """, (like, like))
                        mermas = cur.fetchall()
                    else:
                        cur.execute("""
                            SELECT 'Entrada' AS mov, p.nombre, i.kilos, i.num_cajas, i.unidades,
                                   g.monto, i.tipo, i.motivo, i.fecha
                            FROM inventario i
                            JOIN productos p ON p.id = i.producto_id
                            LEFT JOIN gastos g ON g.id = i.gasto_id
                        """)
                        entradas = cur.fetchall()
                        cur.execute("""
                            SELECT 'Merma' AS mov, p.nombre, m.kilos, m.num_cajas, m.unidades,
                                   NULL, '' AS tipo, m.motivo, m.fecha
                            FROM mermas m
                            JOIN productos p ON p.id = m.producto_id
                        """)
                        mermas = cur.fetchall()
                else:
                    # Fallback legacy: join por texto (menos confiable)
                    if filtro:
                        like = f"%{filtro}%"
                        cur.execute("""
                            SELECT 'Entrada' AS mov, p.nombre, i.kilos, i.num_cajas, i.unidades,
                                   COALESCE(g.monto, 0), i.tipo, i.motivo, i.fecha
                            FROM inventario i
                            JOIN productos p ON p.id = i.producto_id
                            LEFT JOIN gastos g
                              ON g.tipo = 'Compra' AND g.descripcion = p.nombre AND g.fecha = i.fecha
                            WHERE p.nombre LIKE ? OR i.motivo LIKE ? OR IFNULL(i.tipo,'') LIKE ?
                        """, (like, like, like))
                        entradas = cur.fetchall()
                        cur.execute("""
                            SELECT 'Merma' AS mov, p.nombre, m.kilos, m.num_cajas, m.unidades,
                                   NULL, '' AS tipo, m.motivo, m.fecha
                            FROM mermas m
                            JOIN productos p ON p.id = m.producto_id
                            WHERE p.nombre LIKE ? OR m.motivo LIKE ?
                        """, (like, like))
                        mermas = cur.fetchall()
                    else:
                        cur.execute("""
                            SELECT 'Entrada' AS mov, p.nombre, i.kilos, i.num_cajas, i.unidades,
                                   COALESCE(g.monto, 0), i.tipo, i.motivo, i.fecha
                            FROM inventario i
                            JOIN productos p ON p.id = i.producto_id
                            LEFT JOIN gastos g
                              ON g.tipo = 'Compra' AND g.descripcion = p.nombre AND g.fecha = i.fecha
                        """)
                        entradas = cur.fetchall()
                        cur.execute("""
                            SELECT 'Merma' AS mov, p.nombre, m.kilos, m.num_cajas, m.unidades,
                                   NULL, '' AS tipo, m.motivo, m.fecha
                            FROM mermas m
                            JOIN productos p ON p.id = m.producto_id
                        """)
                        mermas = cur.fetchall()

            filas = entradas + mermas
            filas.sort(key=lambda r: r[8], reverse=True)  # fecha ISO DESC

            for mov, nombre, kilos, cajas, unidades, monto, tipo, motivo, fecha in filas:
                self.tree.insert("", "end", values=(
                    mov,
                    nombre,
                    f"{redondear_dos_decimales(kilos):.2f}",
                    f"{redondear_dos_decimales(cajas):.2f}",
                    int(unidades or 0),
                    (formato_moneda(monto) if (monto is not None and monto != "") else ""),
                    (tipo or ""),
                    (motivo or ""),
                    formatear_fecha(fecha)
                ))

            set_treeview_stripes(self.tree, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))

        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los movimientos.\n{e}")

    # ---------------------------
    # Proveedores (CRUD)
    # ---------------------------
    def _proveedor_seleccionado(self):
        item = self.tree_prov.focus()
        if not item:
            return None
        vals = self.tree_prov.item(item, "values")
        if not vals:
            return None
        # id, nombre, telefono, direccion, deuda
        pid = int(vals[0])
        nombre = vals[1]
        tel = vals[2] if len(vals) > 2 else ""
        dire = vals[3] if len(vals) > 3 else ""
        return pid, nombre, tel, dire


    def agregar_proveedor(self):
        nombre = (self.prov_nombre_entry.get() or "").strip()
        telefono = (self.prov_tel_entry.get() or "").strip()
        direccion = (getattr(self, "prov_dir_entry", None).get() or "").strip() if hasattr(self, "prov_dir_entry") else ""
        if not nombre:
            messagebox.showerror("Error", "El nombre del proveedor es obligatorio.")
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                if getattr(self, "_prov_has_direccion", False):
                    cur.execute(
                        "INSERT INTO proveedores (nombre, telefono, direccion) VALUES (?, ?, ?)",
                        (nombre, telefono, direccion)
                    )
                else:
                    cur.execute(
                        "INSERT INTO proveedores (nombre, telefono) VALUES (?, ?)",
                        (nombre, telefono)
                    )
            self.prov_nombre_entry.delete(0, tk.END)
            self.prov_tel_entry.delete(0, tk.END)
            if hasattr(self, "prov_dir_entry"):
                self.prov_dir_entry.delete(0, tk.END)
            self.cargar_proveedores()
            messagebox.showinfo("Éxito", "Proveedor agregado.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo agregar el proveedor.\n{e}")

    def editar_proveedor(self):
        sel = self._proveedor_seleccionado()
        if not sel:
            messagebox.showerror("Error", "Selecciona un proveedor en la tabla.")
            return
        pid, nombre_act, tel_act, dir_act = sel

        win = tk.Toplevel(self)
        win.title("Editar proveedor")
        try:
            win.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        win.transient(self.winfo_toplevel())

        # --- Campos ---
        tk.Label(win, text="Nombre:", bg=PALETTE["bg"], fg=PALETTE["text"])\
            .grid(row=0, column=0, padx=10, pady=8, sticky="e")
        ent_nombre = self._entry(win, width=28, row=0, column=1, padx=10, pady=8, sticky="we")
        ent_nombre.insert(0, nombre_act)

        tk.Label(win, text="Teléfono:", bg=PALETTE["bg"], fg=PALETTE["text"])\
            .grid(row=1, column=0, padx=10, pady=8, sticky="e")
        ent_tel = self._entry(win, width=20, row=1, column=1, padx=10, pady=8, sticky="w")
        ent_tel.insert(0, tel_act or "")

        # Dirección solo si existe columna
        ent_dir = None
        if getattr(self, "_prov_has_direccion", False):
            tk.Label(win, text="Dirección:", bg=PALETTE["bg"], fg=PALETTE["text"])\
                .grid(row=2, column=0, padx=10, pady=8, sticky="e")
            ent_dir = self._entry(win, width=40, row=2, column=1, padx=10, pady=8, sticky="we")
            ent_dir.insert(0, dir_act or "")

        win.grid_columnconfigure(1, weight=1)

        def guardar():
            nuevo_nombre = (ent_nombre.get() or "").strip()
            nuevo_tel = (ent_tel.get() or "").strip()
            nuevo_dir = (ent_dir.get() or "").strip() if ent_dir else None
            if not nuevo_nombre:
                messagebox.showerror("Error", "El nombre no puede estar vacío.", parent=win)
                return
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    if getattr(self, "_prov_has_direccion", False):
                        cur.execute(
                            "UPDATE proveedores SET nombre = ?, telefono = ?, direccion = ? WHERE id = ?",
                            (nuevo_nombre, nuevo_tel, nuevo_dir or "", pid)
                        )
                    else:
                        cur.execute(
                            "UPDATE proveedores SET nombre = ?, telefono = ? WHERE id = ?",
                            (nuevo_nombre, nuevo_tel, pid)
                        )
                self.cargar_proveedores()
                messagebox.showinfo("Éxito", "Proveedor actualizado.", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo actualizar el proveedor.\n{e}", parent=win)

        # Usar grid (no pack) para evitar conflictos de gestores de geometría
        ttk.Button(win, text="Guardar", command=guardar, style="Success.TButton")\
            .grid(row=3, column=0, columnspan=2, pady=10)

        # --- Hacer visible y seguro el grab ---
        win.update_idletasks()
        win.deiconify()
        try:
            win.wait_visibility()   # asegúrate que la ventana ya es "viewable"
        except Exception:
            pass
        try:
            win.grab_set()          # ahora sí, toma el foco modal
        except Exception:
            # Si aun así fallara, simplemente omite el grab para no romper el flujo
            pass

        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Return>", lambda e: guardar())
        try:
            win.focus_force()
        except Exception:
            pass



    def eliminar_proveedor(self):
        sel = self._proveedor_seleccionado()
        if not sel:
            messagebox.showerror("Error", "Selecciona un proveedor en la tabla.")
            return
        pid, nombre, _tel = sel
        if not messagebox.askyesno("Confirmar", f"¿Eliminar al proveedor '{nombre}'?"):
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM proveedores WHERE id = ?", (pid,))
            self.cargar_proveedores()
            messagebox.showinfo("Éxito", "Proveedor eliminado.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo eliminar el proveedor.\n{e}")

    # ---------------------------
    # Ordenamiento (interno)
    # ---------------------------
    def _setup_sorting(self, tree: ttk.Treeview, columnas, tipos):
        tree._sort_state = {}
        col_index = {c: i for i, c in enumerate(columnas)}

        def parse_value(col, val):
            t = tipos.get(col, "str")
            s = str(val).strip()

            if t == "float":
                try:
                    return float(s.replace(",", "").replace("$", ""))
                except Exception:
                    return 0.0
            if t == "int":
                try:
                    return int(str(s).replace(",", ""))
                except Exception:
                    return 0
            if t == "money":
                try:
                    return float(s.replace("$", "").replace(",", ""))
                except Exception:
                    return 0.0
            if t == "date":
                from datetime import datetime as _dt
                for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
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
            for n, (_v, iid) in enumerate(data):
                tree.move(iid, "", n)
            tree._sort_state[col] = reverse

        for c in columnas:
            tree.heading(c, text=c, command=lambda cc=c: sort_by(cc))


# Punto de entrada para main.py
def mostrar(frame_contenido):
    for w in frame_contenido.winfo_children():
        w.destroy()
    frame = InventarioFrame(frame_contenido)
    frame.pack(fill="both", expand=True)
