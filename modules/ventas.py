# modules/ventas.py
# -----------------------------------------------------------
# Sistema de Comercio — Módulo de Ventas (mejorado y saneado)
#
# REGLAS CLAVE
# - El total de la venta se calcula SIEMPRE por:
#     * KILOS:     kilos * precio
#     * UNIDADES:  unidades * precio
# - Las CAJAS NO influyen en el total ni descuentan stock; sólo pueden
#   convertir a kilos usando peso_caja del producto (si el usuario las ingresa).
# - Persistimos en ventas: kilos, unidades y opcionalmente num_cajas (referencial).
# - Post-venta:
#     * Cancelar (soft-delete): ventas.estado='cancelada', fecha_cancelacion, motivo_cancelacion.
#       Revertir inventario y ajustar deuda si fue a crédito.
#     * Modificar: editor con ajuste diferencial y auditoría opcional en ventas_eventos.
#
# UI/UX
# - Modos de precio: manual/mayoreo/menudeo (bloquea campo si no es manual).
# - Validadores (helpers): 2 decimales y entero positivo.
# - Tabla: búsqueda dinámica, ordenamiento por encabezados, formateos.
# - Accesos rápidos: Enter vende, Ctrl+F enfoca búsqueda, Esc limpia/cierra,
#   doble clic/Enter carga venta al formulario, Supr borra fila de la vista.
#
# Integraciones
# - Tema unificado (ui/theme.apply_brand_ttk_theme).
# - Tickets: ui.tickets.imprimir_ticket(venta_id, reimpresion=False) si existe.
# - DB: usa db.database.get_connection() (PRAGMA FK ON), Decimal vía helpers.
# -----------------------------------------------------------

from __future__ import annotations

import tkinter as tk
import os, shutil, subprocess, tempfile, webbrowser
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime

from db.database import get_connection
from ui.theme import apply_brand_ttk_theme, BRAND_PALETTE
from ui.helpers import (
    to_float,
    formato_moneda,
    redondear_dos_decimales,
    formatear_fecha,
    adjuntar_validador_2_decimales,
)

# -----------------------------------------------------------
# VentasFrame
# -----------------------------------------------------------

class VentasFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=BRAND_PALETTE["bg"])
        self.style = apply_brand_ttk_theme(self)

        # Catálogos
        self.productos: dict[str, int] = {}
        self.clientes: dict[str, int] = {}

        # Estado de esquema dinámico
        self._ventas_has_estado = False
        self._ventas_has_eventos = False
        self._productos_has_unidades = False
        self._clientes_has_deuda = False

        # <-- AGREGA esto aquí (antes de _inspect_schema) y NO lo repitas luego
        self._ventas_eventos_cols: set[str] = set()

        # Modo de precio / crédito / cache
        self.precio_mode = tk.StringVar(value="manual")
        self.var_credito = tk.BooleanVar(value=False)
        self._venta_por_iid: dict[str, dict] = {}

        self._build_ui()
        self._inspect_schema()   # <- ahora sí pobla self._ventas_eventos_cols
        self._load_catalogs()
        self._load_sales()
        self._install_shortcuts()



    # ---------------------------
    # UI
    # ---------------------------
    def _build_ui(self):
        # Panel formulario
        form = tk.LabelFrame(self, text="Registrar Venta", bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"], bd=0)
        form.pack(fill="x", padx=10, pady=8)

        for col in (1, 3, 5, 7):
            form.grid_columnconfigure(col, weight=1)

        # Validadores
        vcmd_decimal = (self.register(self._validate_decimal), "%P")
        vcmd_entero  = (self.register(self._validate_entero),  "%P")

        # Producto
        tk.Label(form, text="Producto:", bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])\
            .grid(row=0, column=0, sticky="e", padx=4, pady=2)
        self.combo_producto = ttk.Combobox(form, width=26, state="readonly")
        self.combo_producto.grid(row=0, column=1, padx=4, pady=2, sticky="we")
        self.combo_producto.bind("<<ComboboxSelected>>", self._on_producto_change)
        self.combo_producto.bind("<Return>", lambda e: self._do_sale())

        # Unidades (entero ≥ 1)
        tk.Label(form, text="Unidades:", bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])\
            .grid(row=0, column=2, sticky="e", padx=4, pady=2)
        self.ent_unidades = tk.Entry(form, width=10,
                                     bg=BRAND_PALETTE["entry_bg"], fg=BRAND_PALETTE["entry_fg"],
                                     relief="flat", highlightthickness=1,
                                     highlightbackground=BRAND_PALETTE["border"], highlightcolor=BRAND_PALETTE["accent"],
                                     validate="key", validatecommand=vcmd_entero)
        self.ent_unidades.grid(row=0, column=3, padx=4, pady=2, sticky="we")
        self.ent_unidades.bind("<Return>", lambda e: self._do_sale())

        # Kilos (decimal)
        tk.Label(form, text="Kilos:", bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])\
            .grid(row=0, column=4, sticky="e", padx=4, pady=2)
        self.ent_kilos = tk.Entry(form, width=10,
                                  bg=BRAND_PALETTE["entry_bg"], fg=BRAND_PALETTE["entry_fg"],
                                  relief="flat", highlightthickness=1,
                                  highlightbackground=BRAND_PALETTE["border"], highlightcolor=BRAND_PALETTE["accent"],
                                  validate="key", validatecommand=vcmd_decimal)
        self.ent_kilos.grid(row=0, column=5, padx=4, pady=2, sticky="we")
        self.ent_kilos.bind("<Return>", lambda e: self._do_sale())
        adjuntar_validador_2_decimales(self.ent_kilos, permitir_vacio=True)

        # Cajas (decimal — informativo/convertidor)
        tk.Label(form, text="Cajas:", bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])\
            .grid(row=0, column=6, sticky="e", padx=4, pady=2)
        self.ent_cajas = tk.Entry(form, width=10,
                                  bg=BRAND_PALETTE["entry_bg"], fg=BRAND_PALETTE["entry_fg"],
                                  relief="flat", highlightthickness=1,
                                  highlightbackground=BRAND_PALETTE["border"], highlightcolor=BRAND_PALETTE["accent"],
                                  validate="key", validatecommand=vcmd_decimal)
        self.ent_cajas.grid(row=0, column=7, padx=4, pady=2, sticky="we")
        self.ent_cajas.bind("<Return>", lambda e: self._do_sale())
        adjuntar_validador_2_decimales(self.ent_cajas, permitir_vacio=True)

        # Modo de precio
        mode_frame = tk.Frame(form, bg=BRAND_PALETTE["panel"])
        mode_frame.grid(row=1, column=0, columnspan=8, sticky="w", pady=(2, 0))
        tk.Label(mode_frame, text="Precio a usar:", bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])\
            .pack(side="left", padx=(0, 6))
        ttk.Radiobutton(mode_frame, text="Manual",  value="manual",  variable=self.precio_mode,
                        command=self._on_precio_mode_change).pack(side="left")
        ttk.Radiobutton(mode_frame, text="Mayoreo", value="mayoreo", variable=self.precio_mode,
                        command=self._on_precio_mode_change).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(mode_frame, text="Menudeo", value="menudeo", variable=self.precio_mode,
                        command=self._on_precio_mode_change).pack(side="left", padx=(6, 0))

        # Precio unitario
        tk.Label(form, text="Precio unitario:", bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])\
            .grid(row=2, column=0, sticky="e", padx=4, pady=(2, 4))
        self.ent_precio = tk.Entry(form, width=10,
                                   bg=BRAND_PALETTE["entry_bg"], fg=BRAND_PALETTE["entry_fg"],
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=BRAND_PALETTE["border"], highlightcolor=BRAND_PALETTE["accent"],
                                   validate="key", validatecommand=vcmd_decimal)
        self.ent_precio.grid(row=2, column=1, padx=4, pady=(2, 4), sticky="we")
        self.ent_precio.bind("<Return>", lambda e: self._do_sale())
        adjuntar_validador_2_decimales(self.ent_precio, permitir_vacio=False)

        # Info producto (stock/precios referenciales)
        self.lbl_info = tk.Label(form,
            text=("Kilos disp.: 0 | Cajas: 0 | Peso/caja: 0 kg | "
                  "Unidades: n/d | Mayoreo: 0.00 | Menudeo: 0.00"),
            bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"], anchor="w")
        self.lbl_info.grid(row=3, column=0, columnspan=8, pady=(2, 2), sticky="we")

        # Crédito / Cliente
        ttk.Checkbutton(form, text="Venta a Crédito", variable=self.var_credito,
                        command=self._toggle_credito).grid(row=4, column=0, sticky="w", pady=2, padx=4)
        tk.Label(form, text="Cliente:", bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])\
            .grid(row=4, column=1, sticky="e", padx=4)
        self.combo_cliente = ttk.Combobox(form, state="disabled", width=25)
        self.combo_cliente.grid(row=4, column=2, columnspan=2, sticky="we", padx=4)
        self.combo_cliente.bind("<Return>", lambda e: self._do_sale())

        # Botones
        tk.Button(form, text="Nueva Venta", bg=BRAND_PALETTE["primary"], fg=BRAND_PALETTE["text"],
                  relief="flat", padx=10, pady=6, command=self._do_sale)\
            .grid(row=5, column=0, columnspan=4, pady=8, sticky="w")
        tk.Button(form, text="Imprimir ticket al guardar", bg=BRAND_PALETTE["bg"], fg=BRAND_PALETTE["link"],
                  relief="flat", padx=10, pady=6, command=lambda: self._do_sale(print_ticket=True))\
            .grid(row=5, column=4, columnspan=4, pady=8, sticky="w")

        # ---- Filtro/Busqueda ----
        filtro = tk.Frame(self, bg=BRAND_PALETTE["panel"])
        filtro.pack(fill="x", padx=10, pady=(2, 0))
        tk.Label(filtro, text="Buscar (producto/cliente/tipo/fecha):",
                 bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])\
            .pack(side="left", padx=(6, 6))
        self.ent_buscar = tk.Entry(filtro, width=40,
                                   bg=BRAND_PALETTE["entry_bg"], fg=BRAND_PALETTE["entry_fg"],
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=BRAND_PALETTE["border"], highlightcolor=BRAND_PALETTE["accent"])
        self.ent_buscar.pack(side="left", fill="x", expand=True, padx=(0, 6), pady=6)
        self.ent_buscar.bind("<KeyRelease>", lambda e: self._load_sales(self.ent_buscar.get().strip()))
        self.ent_buscar.bind("<Return>",     lambda e: self._load_sales(self.ent_buscar.get().strip()))
        tk.Button(filtro, text="Limpiar filtro", bg=BRAND_PALETTE["primary"], fg=BRAND_PALETTE["text"],
                  relief="flat", padx=10, pady=6,
                  command=lambda: (self.ent_buscar.delete(0, tk.END), self._load_sales()))\
            .pack(side="left", padx=6)

        # ---- Tabla ----
        tabla_panel = tk.Frame(self, bg=BRAND_PALETTE["panel"])
        tabla_panel.pack(fill="both", expand=True, padx=10, pady=8)

        columnas = ("ID", "Fecha", "Estado", "Producto", "Modo", "Cantidad", "Precio", "Total", "Tipo", "Cliente")
        self.tree, _, _ = self._tree_with_scrolls(tabla_panel, columnas)

        for col, width, anchor in (
            ("ID", 60, "center"),
            ("Fecha", 140, "center"),
            ("Estado", 100, "center"),
            ("Producto", 200, "w"),
            ("Modo", 90, "center"),
            ("Cantidad", 100, "e"),
            ("Precio", 110, "e"),
            ("Total", 120, "e"),
            ("Tipo", 90, "center"),
            ("Cliente", 180, "w"),
        ):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("Producto", "Cliente")))

        self._setup_sorting(self.tree, columnas, {
            "ID": "int",
            "Fecha": "date",
            "Estado": "str",
            "Producto": "str",
            "Modo": "str",
            "Cantidad": "float",
            "Precio": "money",
            "Total": "money",
            "Tipo": "str",
            "Cliente": "str",
        })

        # Menú contextual (Cancelar / Modificar / Reimprimir)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Cancelar venta…", command=self._cancelar_venta)
        self.menu.add_command(label="Modificar venta…", command=self._modificar_venta)
        self.menu.add_separator()
        self.menu.add_command(label="Reimprimir ticket", command=lambda: self._imprimir_ticket(reimpresion=True))
        self.tree.bind("<Button-3>", self._show_context_menu)

        # Eventos tabla (UX)
        self.tree.bind("<Double-1>", lambda e: self._cargar_desde_tabla())
        self.tree.bind("<Return>",   lambda e: self._cargar_desde_tabla())
        self.tree.bind("<Delete>",   lambda e: self._remove_row_view())

    # ---------------------------
    # Init / catálogo / esquema
    # ---------------------------
    def _inspect_schema(self):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                # ventas: estado / cancelación
                cur.execute("PRAGMA table_info(ventas)")
                vcols = {r[1].lower() for r in cur.fetchall()}
                self._ventas_has_estado = "estado" in vcols
                # eventos de auditoría
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ventas_eventos'")
                self._ventas_has_eventos = cur.fetchone() is not None
                self._ventas_eventos_cols = set()
                if self._ventas_has_eventos:
                    cur.execute("PRAGMA table_info(ventas_eventos)")
                    self._ventas_eventos_cols = { (r[1] or "").lower() for r in cur.fetchall() }
                # productos: unidades
                cur.execute("PRAGMA table_info(productos)")
                pcols = {r[1].lower() for r in cur.fetchall()}
                self._productos_has_unidades = "unidades" in pcols
                # clientes: deuda_total
                cur.execute("PRAGMA table_info(clientes)")
                ccols = {r[1].lower() for r in cur.fetchall()}
                self._clientes_has_deuda = "deuda_total" in ccols
        except Exception:
            self._ventas_has_estado = False
            self._ventas_has_eventos = False
            self._productos_has_unidades = False
            self._clientes_has_deuda = False

    def _load_catalogs(self):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, nombre FROM productos ORDER BY nombre COLLATE NOCASE")
                self.productos = {row[1]: row[0] for row in cur.fetchall()}
                self.combo_producto["values"] = list(self.productos.keys())
                if self.productos and not self.combo_producto.get():
                    self.combo_producto.current(0)

                cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre COLLATE NOCASE")
                self.clientes = {row[1]: row[0] for row in cur.fetchall()}
                self.combo_cliente["values"] = list(self.clientes.keys())
                if self.clientes and not self.combo_cliente.get():
                    self.combo_cliente.current(0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar catálogos.\n{e}")
            return

        self._refresh_producto_info()

    # ---------------------------
    # Handlers UI
    # ---------------------------
    def _on_producto_change(self, event=None):
        self._refresh_producto_info()

    def _refresh_producto_info(self):
        nombre = self.combo_producto.get()
        if not nombre:
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                base_cols = "kilos, num_cajas, peso_caja, precio_mayoreo, precio_menudeo"
                add_units = ", unidades" if self._productos_has_unidades else ""
                cur.execute(f"SELECT {base_cols}{add_units} FROM productos WHERE nombre = ?", (nombre,))
                row = cur.fetchone()
            if not row:
                return

            kilos, cajas, peso, pmay, pmen = float(row[0] or 0), float(row[1] or 0), float(row[2] or 0), float(row[3] or 0), float(row[4] or 0)
            unidades = int(row[5]) if self._productos_has_unidades and row[5] is not None else None
            txt_unid = f"{unidades}" if unidades is not None else "n/d"
            self.lbl_info.config(
                text=(f"Kilos disp.: {redondear_dos_decimales(kilos):.2f} | "
                      f"Cajas: {redondear_dos_decimales(cajas):.2f} | "
                      f"Peso/caja: {redondear_dos_decimales(peso):.2f} kg | "
                      f"Unidades: {txt_unid} | "
                      f"Mayoreo: {redondear_dos_decimales(pmay):.2f} | "
                      f"Menudeo: {redondear_dos_decimales(pmen):.2f}")
            )

            # Autorellenar precio si el modo no es manual
            if self.precio_mode.get() in ("mayoreo", "menudeo"):
                valor = pmay if self.precio_mode.get() == "mayoreo" else pmen
                self.ent_precio.config(state="normal")
                self.ent_precio.delete(0, tk.END)
                self.ent_precio.insert(0, f"{redondear_dos_decimales(valor):.2f}")
                self.ent_precio.config(state="disabled")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo obtener la info del producto.\n{e}")

    def _on_precio_mode_change(self):
        modo = self.precio_mode.get()
        if modo == "manual":
            self.ent_precio.config(state="normal")
            return
        self._refresh_producto_info()
        self.ent_precio.config(state="disabled")

    def _toggle_credito(self):
        estado = "readonly" if self.var_credito.get() else "disabled"
        self.combo_cliente.config(state=estado)

    # ---------------------------
    # Validadores Entry
    # ---------------------------
    def _validate_decimal(self, proposed: str) -> bool:
        if proposed == "":
            return True
        import re
        return re.fullmatch(r"(\d+(\.\d{0,2})?|\.\d{0,2})", proposed) is not None

    def _validate_entero(self, proposed: str) -> bool:
        if proposed == "":
            return True
        return proposed.isdigit()

    # ---------------------------
    # Acción principal: vender
    # ---------------------------
    def _do_sale(self, print_ticket: bool = False):
        nombre = self.combo_producto.get().strip()
        if not nombre:
            messagebox.showwarning("Producto", "Selecciona un producto")
            return

        # Modalidad (unidades > cajas > kilos)
        unidades_txt = self.ent_unidades.get().strip()
        cajas_txt    = self.ent_cajas.get().strip()
        kilos_txt    = self.ent_kilos.get().strip()

        modalidad = None
        unidades = 0
        cajas = 0.0
        kilos = 0.0

        if unidades_txt:
            if not self._productos_has_unidades:
                messagebox.showerror("No disponible", "La BD no soporta venta por unidades (no existe 'productos.unidades').")
                return
            try:
                unidades = int(unidades_txt)
                if unidades <= 0:
                    raise ValueError
            except Exception:
                messagebox.showerror("Error", "Unidades inválidas (entero positivo).")
                return
            modalidad = "unidades"
        elif cajas_txt:
            try:
                cajas = to_float(cajas_txt, permitir_cero=False)
            except ValueError:
                messagebox.showerror("Error", "Cajas inválidas.")
                return
            modalidad = "cajas"
        elif kilos_txt:
            try:
                kilos = to_float(kilos_txt, permitir_cero=False)
            except ValueError:
                messagebox.showerror("Error", "Kilos inválidos.")
                return
            modalidad = "kilos"
        else:
            messagebox.showerror("Error", "Ingresa Unidades, Cajas o Kilos para la venta.")
            return

        # Precio
        try:
            precio = to_float(self.ent_precio.get(), permitir_cero=False)
        except ValueError:
            messagebox.showerror("Error", "Precio inválido.")
            return
        if precio <= 0:
            messagebox.showerror("Error", "El precio debe ser mayor a 0.")
            return

        producto_id = self.productos.get(nombre)
        if not producto_id:
            messagebox.showerror("Error", "Producto no encontrado.")
            return

        tipo_venta = "credito" if self.var_credito.get() else "contado"
        cliente_id = None
        if tipo_venta == "credito":
            cli_nombre = self.combo_cliente.get()
            if cli_nombre not in self.clientes:
                messagebox.showerror("Cliente", "Selecciona un cliente válido")
                return
            cliente_id = self.clientes[cli_nombre]

        # Stock y peso_caja
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                if self._productos_has_unidades:
                    cur.execute("""
                        SELECT kilos, num_cajas, peso_caja, precio_mayoreo, precio_menudeo, unidades
                        FROM productos WHERE id = ?
                    """, (producto_id,))
                    row = cur.fetchone()
                    if not row:
                        messagebox.showerror("Error", "Producto no encontrado.")
                        return
                    stock_k, stock_cj, peso_caja, pmay, pmen, stock_u = (
                        float(row[0] or 0), float(row[1] or 0), float(row[2] or 0),
                        float(row[3] or 0), float(row[4] or 0), int(row[5] or 0)
                    )
                else:
                    cur.execute("""
                        SELECT kilos, num_cajas, peso_caja, precio_mayoreo, precio_menudeo
                        FROM productos WHERE id = ?
                    """, (producto_id,))
                    row = cur.fetchone()
                    if not row:
                        messagebox.showerror("Error", "Producto no encontrado.")
                        return
                    stock_k, stock_cj, peso_caja, pmay, pmen = (
                        float(row[0] or 0), float(row[1] or 0), float(row[2] or 0),
                        float(row[3] or 0), float(row[4] or 0)
                    )
                    stock_u = None

                kilos_vta = 0.0
                num_cajas_vta = 0.0
                unidades_vta = 0
                total = 0.0
                fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if modalidad == "unidades":
                    if stock_u is None:
                        messagebox.showerror("No disponible", "Este producto no admite venta por unidades.")
                        return
                    if unidades > stock_u:
                        messagebox.showerror("Stock insuficiente", f"Unidades disponibles: {int(stock_u)}")
                        return
                    unidades_vta = int(unidades)
                    total = unidades_vta * precio

                    cur.execute("""
                        INSERT INTO ventas (producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha{extra_cols})
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?{extra_vals})
                    """.format(
                        extra_cols=", estado" if self._ventas_has_estado else "",
                        extra_vals=", 'ACTIVA'" if self._ventas_has_estado else ""
                    ), (producto_id, 0.0, 0.0, unidades_vta, float(precio), float(total),
                        tipo_venta, cliente_id, fecha_str))
                    cur.execute("UPDATE productos SET unidades = unidades - ? WHERE id = ?",
                                (unidades_vta, producto_id))

                elif modalidad == "cajas":
                    # Cajas sólo convierten a kilos (no descuentan num_cajas)
                    if peso_caja <= 0:
                        messagebox.showerror("Error", "No se puede vender por cajas sin 'peso_caja'.")
                        return
                    kilos_vta = float(redondear_dos_decimales(cajas * peso_caja))
                    if kilos_vta > stock_k:
                        messagebox.showerror("Stock insuficiente", f"Kilos disponibles: {redondear_dos_decimales(stock_k)}")
                        return
                    num_cajas_vta = float(redondear_dos_decimales(cajas))
                    total = kilos_vta * precio

                    cur.execute("""
                        INSERT INTO ventas (producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha{extra_cols})
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?{extra_vals})
                    """.format(
                        extra_cols=", estado" if self._ventas_has_estado else "",
                        extra_vals=", 'ACTIVA'" if self._ventas_has_estado else ""
                    ), (producto_id, float(kilos_vta), float(num_cajas_vta), 0, float(precio), float(total),
                        tipo_venta, cliente_id, fecha_str))
                    cur.execute("UPDATE productos SET kilos = kilos - ? WHERE id = ?",
                                (float(kilos_vta), producto_id))

                else:  # kilos
                    if kilos > stock_k:
                        messagebox.showerror("Stock insuficiente", f"Kilos disponibles: {redondear_dos_decimales(stock_k)}")
                        return
                    kilos_vta = float(redondear_dos_decimales(kilos))
                    total = kilos_vta * precio

                    cur.execute("""
                        INSERT INTO ventas (producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha{extra_cols})
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?{extra_vals})
                    """.format(
                        extra_cols=", estado" if self._ventas_has_estado else "",
                        extra_vals=", 'ACTIVA'" if self._ventas_has_estado else ""
                    ), (producto_id, float(kilos_vta), 0.0, 0, float(precio), float(total),
                        tipo_venta, cliente_id, fecha_str))
                    cur.execute("UPDATE productos SET kilos = kilos - ? WHERE id = ?",
                                (float(kilos_vta), producto_id))

                # Ajuste deuda cliente (si hay columna)
                if self._clientes_has_deuda and tipo_venta == "credito" and cliente_id:
                    cur.execute("UPDATE clientes SET deuda_total = deuda_total + ? WHERE id = ?",
                                (float(total), cliente_id))

                venta_id = cur.lastrowid

            messagebox.showinfo("Éxito", "Venta registrada")
            self._clear_form(keep_price=(self.precio_mode.get() != "manual"))
            self._load_sales(self.ent_buscar.get().strip())
            self._refresh_producto_info()

            if print_ticket:
                self._imprimir_ticket(venta_id=venta_id, reimpresion=False)

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la venta.\n{e}")
    
    def _load_sales(self, filtro: str = ""):
        self.tree.delete(*self.tree.get_children())
        self._venta_por_iid.clear()
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                extra_estado = ", v.estado" if self._ventas_has_estado else ", 'ACTIVA' AS estado"
                if filtro:
                    like = f"%{filtro}%"
                    cur.execute(f"""
                        SELECT
                            v.id, v.fecha{extra_estado}, p.nombre,
                            CASE
                                WHEN IFNULL(v.unidades,0) > 0 THEN 'UNIDADES'
                                WHEN IFNULL(v.kilos,0)    > 0 AND IFNULL(v.num_cajas,0) > 0 THEN 'CAJAS→KILOS'
                                WHEN IFNULL(v.kilos,0)    > 0 THEN 'KILOS'
                                ELSE 'N/A'
                            END AS modo,
                            v.unidades, v.kilos, v.num_cajas,
                            v.precio, COALESCE(v.total, v.kilos * v.precio) AS total,
                            v.tipo_venta, c.nombre
                        FROM ventas v
                        JOIN productos p ON p.id = v.producto_id
                        LEFT JOIN clientes c ON c.id = v.cliente_id
                        WHERE p.nombre LIKE ? OR IFNULL(c.nombre,'') LIKE ? OR IFNULL(v.tipo_venta,'') LIKE ? OR DATE(v.fecha) LIKE ?
                        ORDER BY v.fecha DESC
                    """, (like, like, like, like))
                else:
                    cur.execute(f"""
                        SELECT
                            v.id, v.fecha{extra_estado}, p.nombre,
                            CASE
                                WHEN IFNULL(v.unidades,0) > 0 THEN 'UNIDADES'
                                WHEN IFNULL(v.kilos,0)    > 0 AND IFNULL(v.num_cajas,0) > 0 THEN 'CAJAS→KILOS'
                                WHEN IFNULL(v.kilos,0)    > 0 THEN 'KILOS'
                                ELSE 'N/A'
                            END AS modo,
                            v.unidades, v.kilos, v.num_cajas,
                            v.precio, COALESCE(v.total, v.kilos * v.precio) AS total,
                            v.tipo_venta, c.nombre
                        FROM ventas v
                        JOIN productos p ON p.id = v.producto_id
                        LEFT JOIN clientes c ON c.id = v.cliente_id
                        ORDER BY v.fecha DESC
                    """)
                rows = cur.fetchall()

            for (vid, fecha, estado, prod, modo, unidades, kilos, num_cajas, precio, total, tipo, cliente) in rows:
                if (unidades or 0) > 0:
                    cantidad = float(unidades or 0.0)
                elif (kilos or 0) > 0:
                    cantidad = float(kilos or 0.0)
                else:
                    cantidad = 0.0

                estado_txt = (str(estado or "ACTIVA")).upper()

                iid = self.tree.insert("", "end", values=(
                    int(vid),
                    formatear_fecha(fecha),
                    estado_txt,
                    prod or "",
                    modo,
                    f"{redondear_dos_decimales(cantidad):.2f}",
                    formato_moneda(redondear_dos_decimales(precio)),
                    formato_moneda(redondear_dos_decimales(total)),
                    (tipo or ""),
                    (cliente or "")
                ))
                self._venta_por_iid[iid] = {
                    "id": int(vid),
                    "fecha": fecha,
                    "estado": estado_txt,
                    "producto": prod,
                    "modo": modo,
                    "unidades": int(unidades or 0),
                    "kilos": float(kilos or 0.0),
                    "num_cajas": float(num_cajas or 0.0),
                    "precio": float(precio or 0.0),
                    "total": float(total or 0.0),
                    "tipo": (tipo or ""),
                    "cliente": (cliente or ""),
                }
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar las ventas.\n{e}")

    def _log_venta_event(self, cur, venta_id: int, accion: str, detalle_json: str):
        """
        Inserta un evento en ventas_eventos ajustándose a las columnas existentes.
        Maneja opcionalmente columnas: tipo (con CHECK), accion/evento/descripcion, detalle_json/detalle, usuario, fecha.
        """
        if not self._ventas_has_eventos or not self._ventas_eventos_cols:
            return

        cols = self._ventas_eventos_cols
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        venta_id_col = "venta_id" if "venta_id" in cols else None
        accion_col   = "accion" if "accion" in cols else ("evento" if "evento" in cols else ("descripcion" if "descripcion" in cols else None))
        detalle_col  = "detalle_json" if "detalle_json" in cols else ("detalle" if "detalle" in cols else None)
        usuario_col  = "usuario" if "usuario" in cols else None
        fecha_col    = "fecha" if "fecha" in cols else None
        tipo_col     = "tipo" if "tipo" in cols else None

        # --- Normalización del TIPO para cumplir el CHECK ---
        a = (accion or "").strip().lower()
        # mapa de acciones -> valores válidos del CHECK
        tipo_map = {
            "crear": "CREADA",
            "registrar": "CREADA",
            "venta": "CREADA",
            "modificar": "MODIFICADA",
            "cancelar": "CANCELADA",
            # por si ya viene en mayúsculas válidas
            "creada": "CREADA",
            "modificada": "MODIFICADA",
            "cancelada": "CANCELADA",
        }
        tipo_val = tipo_map.get(a, "CREADA")
        # -----------------------------------------------

        fields, values = [], []
        if venta_id_col:
            fields.append(venta_id_col); values.append(int(venta_id))
        if accion_col:
            fields.append(accion_col);   values.append(str(accion))
        if tipo_col:
            fields.append(tipo_col);     values.append(tipo_val)
        if detalle_col:
            fields.append(detalle_col);  values.append(str(detalle_json))
        if usuario_col:
            fields.append(usuario_col);  values.append(None)
        if fecha_col:
            fields.append(fecha_col);    values.append(now)

        if not fields or not venta_id_col or (detalle_col is None and accion_col is None and fecha_col is None):
            return

        placeholders = ", ".join("?" for _ in fields)
        cols_sql = ", ".join(fields)
        cur.execute(f"INSERT INTO ventas_eventos ({cols_sql}) VALUES ({placeholders})", tuple(values))


    def _cancelar_venta(self):
        iid, data = self._selected_sale()
        if not data:
            messagebox.showinfo("Cancelar", "Selecciona una venta en la tabla.")
            return

        # Evita doble cancelación (robusto en MAYÚSCULAS)
        if self._ventas_has_estado and str(data.get("estado", "")).strip().upper() == "CANCELADA":
            messagebox.showinfo("Cancelar", "La venta ya está cancelada.")
            return

        motivo = simpledialog.askstring("Cancelar venta", "Motivo de cancelación:")
        if motivo is None:
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                # Info original
                cur.execute("""
                    SELECT producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id
                    FROM ventas WHERE id = ?
                """, (data["id"],))
                row = cur.fetchone()
                if not row:
                    messagebox.showerror("Error", "Venta no encontrada.")
                    return

                producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id = row
                kilos      = float(kilos or 0.0)
                unidades   = int(unidades or 0)
                total      = float(total or 0.0)
                tipo_venta = (tipo_venta or "").lower()

                # Revertir inventario
                if unidades > 0:
                    cur.execute("UPDATE productos SET unidades = unidades + ? WHERE id = ?", (unidades, producto_id))
                if kilos > 0:
                    cur.execute("UPDATE productos SET kilos = kilos + ? WHERE id = ?", (kilos, producto_id))

                # Marcar cancelación
                if self._ventas_has_estado:
                    fecha_cancel = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        cur.execute("""
                            UPDATE ventas
                            SET estado = 'CANCELADA', fecha_cancelacion = ?, motivo_cancelacion = ?
                            WHERE id = ?
                        """, (fecha_cancel, motivo, data["id"]))
                    except Exception:
                        cur.execute("UPDATE ventas SET estado = 'CANCELADA' WHERE id = ?", (data["id"],))

                # Ajustar deuda si fue a crédito
                if self._clientes_has_deuda and (tipo_venta == "credito") and (cliente_id is not None):
                    cur.execute("UPDATE clientes SET deuda_total = deuda_total - ? WHERE id = ?",
                                (total, int(cliente_id)))

                # Auditoría adaptable
                if self._ventas_has_eventos:
                    import json
                    self._log_venta_event(
                        cur,
                        venta_id=int(data["id"]),
                        accion="cancelar",
                        detalle_json=json.dumps({"motivo": motivo or ""}, ensure_ascii=False)
                    )

            messagebox.showinfo("Cancelar", "Venta cancelada.")
            self._load_sales(self.ent_buscar.get().strip())
            self._refresh_producto_info()

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cancelar la venta.\n{e}")
    
    def _modificar_venta(self):
        iid, data = self._selected_sale()
        if not data:
            messagebox.showinfo("Modificar", "Selecciona una venta.")
            return
        if self._ventas_has_estado and str(data.get("estado", "")).strip().upper() == "CANCELADA":
            messagebox.showinfo("Modificar", "No se puede modificar una venta cancelada.")
            return

        # Editor simple (cantidad, precio, tipo contado/credito)
        edit = tk.Toplevel(self)
        edit.title(f"Modificar venta #{data['id']}")
        edit.configure(bg=BRAND_PALETTE["bg"])
        edit.transient(self.winfo_toplevel())
        edit.grab_set()
        edit.bind("<Escape>", lambda e: edit.destroy())

        tk.Label(edit, text=f"Producto: {data['producto']}", bg=BRAND_PALETTE["bg"], fg=BRAND_PALETTE["text"])\
            .grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8,4))
        tk.Label(edit, text=f"Modo: {data['modo']}", bg=BRAND_PALETTE["bg"], fg=BRAND_PALETTE["text"])\
            .grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0,8))

        tk.Label(edit, text="Cantidad:", bg=BRAND_PALETTE["bg"], fg=BRAND_PALETTE["text"])\
            .grid(row=2, column=0, sticky="e", padx=8, pady=4)
        ent_cantidad = tk.Entry(edit, width=12, bg=BRAND_PALETTE["entry_bg"], fg=BRAND_PALETTE["entry_fg"],
                                relief="flat", highlightthickness=1,
                                highlightbackground=BRAND_PALETTE["border"], highlightcolor=BRAND_PALETTE["accent"])
        ent_cantidad.grid(row=2, column=1, padx=8, pady=4, sticky="w")
        adjuntar_validador_2_decimales(ent_cantidad, permitir_vacio=False)
        ent_cantidad.insert(0, f"{data['unidades'] if data['modo']=='UNIDADES' else data['kilos']:.2f}")

        tk.Label(edit, text="Precio:", bg=BRAND_PALETTE["bg"], fg=BRAND_PALETTE["text"])\
            .grid(row=3, column=0, sticky="e", padx=8, pady=4)
        ent_precio = tk.Entry(edit, width=12, bg=BRAND_PALETTE["entry_bg"], fg=BRAND_PALETTE["entry_fg"],
                            relief="flat", highlightthickness=1,
                            highlightbackground=BRAND_PALETTE["border"], highlightcolor=BRAND_PALETTE["accent"])
        ent_precio.grid(row=3, column=1, padx=8, pady=4, sticky="w")
        adjuntar_validador_2_decimales(ent_precio, permitir_vacio=False)
        ent_precio.insert(0, f"{data['precio']:.2f}")

        tipo_var = tk.StringVar(value=(data["tipo"] or "contado"))
        tk.Label(edit, text="Tipo:", bg=BRAND_PALETTE["bg"], fg=BRAND_PALETTE["text"])\
            .grid(row=4, column=0, sticky="e", padx=8, pady=4)
        ttk.Combobox(edit, textvariable=tipo_var, state="readonly", values=["contado", "credito"], width=12)\
            .grid(row=4, column=1, padx=8, pady=4, sticky="w")

        def guardar():
            try:
                cant = to_float(ent_cantidad.get(), permitir_cero=False)
                pre  = to_float(ent_precio.get(), permitir_cero=False)
            except Exception:
                messagebox.showerror("Error", "Cantidad/precio inválidos.", parent=edit)
                return

            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    # Leer venta actual
                    cur.execute("""
                        SELECT producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id
                        FROM ventas WHERE id = ?
                    """, (data["id"],))
                    row = cur.fetchone()
                    if not row:
                        messagebox.showerror("Error", "Venta no encontrada.", parent=edit)
                        return
                    producto_id, ok_kilos, ok_cajas, ok_unidades, ok_precio, ok_total, ok_tipo, cliente_id = row
                    ok_kilos  = float(ok_kilos or 0.0)
                    ok_unid   = int(ok_unidades or 0)
                    ok_total  = float(ok_total or 0.0)
                    ok_precio = float(ok_precio or 0.0)

                    # Stock actual
                    if self._productos_has_unidades:
                        cur.execute("SELECT kilos, unidades FROM productos WHERE id = ?", (producto_id,))
                        srow = cur.fetchone()
                        stock_k, stock_u = float(srow[0] or 0.0), int(srow[1] or 0)
                    else:
                        cur.execute("SELECT kilos FROM productos WHERE id = ?", (producto_id,))
                        srow = cur.fetchone()
                        stock_k, stock_u = float(srow[0] or 0.0), None

                    modo = data["modo"]
                    if modo == "UNIDADES":
                        diff_u = int(round(cant)) - ok_unid
                        if diff_u > 0 and stock_u is not None and diff_u > stock_u:
                            messagebox.showerror("Stock", f"Unidades disponibles: {stock_u}", parent=edit)
                            return
                        cur.execute(
                            "UPDATE ventas SET unidades=?, kilos=0, precio=?, total=?, tipo_venta=? WHERE id=?",
                            (int(round(cant)), float(pre), float(int(round(cant)) * pre), tipo_var.get(), data["id"])
                        )
                        cur.execute("UPDATE productos SET unidades = unidades - ? WHERE id = ?", (diff_u, producto_id))
                        total_nuevo = int(round(cant)) * pre
                    else:  # KILOS o CAJAS→KILOS
                        diff_k = float(cant) - ok_kilos
                        if diff_k > 0 and diff_k > stock_k:
                            messagebox.showerror("Stock", f"Kilos disponibles: {redondear_dos_decimales(stock_k)}", parent=edit)
                            return
                        cur.execute(
                            "UPDATE ventas SET kilos=?, precio=?, total=?, tipo_venta=? WHERE id=?",
                            (float(cant), float(pre), float(cant * pre), tipo_var.get(), data["id"])
                        )
                        cur.execute("UPDATE productos SET kilos = kilos - ? WHERE id = ?", (diff_k, producto_id))
                        total_nuevo = float(cant * pre)

                    # Ajuste de deuda si corresponde
                    if self._clientes_has_deuda and (ok_tipo == "credito" or tipo_var.get() == "credito") and cliente_id:
                        ajuste = float(total_nuevo) - ok_total
                        cur.execute("UPDATE clientes SET deuda_total = deuda_total + ? WHERE id = ?",
                                    (ajuste, int(cliente_id)))

                    # Auditoría adaptable
                    if self._ventas_has_eventos:
                        import json
                        self._log_venta_event(
                            cur,
                            venta_id=int(data["id"]),
                            accion="modificar",
                            detalle_json=json.dumps(
                                {"de": {"precio": ok_precio, "total": ok_total},
                                "a":  {"precio": float(pre), "total": float(total_nuevo)}},
                                ensure_ascii=False
                            )
                        )

                messagebox.showinfo("Modificar", "Venta actualizada.", parent=edit)
                edit.destroy()
                self._load_sales(self.ent_buscar.get().strip())
                self._refresh_producto_info()

            except Exception as e:
                messagebox.showerror("Error", f"No se pudo modificar la venta.\n{e}", parent=edit)

        tk.Button(edit, text="Guardar cambios", command=guardar,
                bg=BRAND_PALETTE["success"], fg=BRAND_PALETTE["text"], relief="flat", padx=10, pady=6)\
            .grid(row=5, column=0, columnspan=2, pady=10)
        edit.grid_columnconfigure(1, weight=1)
        edit.bind("<Return>", lambda e: guardar())
  
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
                    return int(s.replace(",", ""))
                except Exception:
                    return 0
            if t == "money":
                try:
                    return float(s.replace("$", "").replace(",", ""))
                except Exception:
                    return 0.0
            if t == "date":
                for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(s, fmt)
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

    # ---------------------------
    # Menú contextual / acciones
    # ---------------------------
    def _show_context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _selected_sale(self):
        sel = self.tree.selection()
        if not sel:
            return None, None
        iid = sel[0]
        data = self._venta_por_iid.get(iid)
        return iid, data

def _abrir_archivo_con_sistema(path):
    """Abre un archivo con el manejador por defecto (evita forzar Chrome)."""
    try:
        if shutil.which("gio"):
            subprocess.Popen(["gio", "open", path])
            return True
        if shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", path])
            return True
    except Exception:
        pass
    # Fallback: navegador por defecto
    try:
        webbrowser.open("file://" + os.path.abspath(path))
        return True
    except Exception:
        return False

def imprimir_ticket_html(path_html, printer_name=None, ancho_mm=80, alto_mm=None):
    """
    Imprime un ticket HTML sin depender de Chrome:

    1) Si hay wkhtmltopdf + lp: convierte a PDF y manda a CUPS.
       - Para térmicas 80mm: usa --page-width 80mm; alto dinámico (si alto_mm=None).
    2) Si falta algo, abre el HTML con el manejador del sistema (gio/xdg-open).

    :param path_html: ruta del HTML ya generado.
    :param printer_name: nombre de impresora CUPS (lpstat -p -d) o None para la predeterminada.
    :param ancho_mm: ancho del papel (típico 80 o 58 mm).
    :param alto_mm: alto fijo en mm; si None, se deja “infinito” (wkhtmltopdf calcula).
    """
    path_html = os.path.abspath(path_html)

    if shutil.which("wkhtmltopdf") and shutil.which("lp"):
        try:
            fd, pdf_path = tempfile.mkstemp(suffix=".pdf"); os.close(fd)

            # Construir argumentos de tamaño para tickets térmicos
            size_args = ["--page-width", f"{ancho_mm}mm"]
            if alto_mm:
                size_args += ["--page-height", f"{alto_mm}mm"]
            else:
                # Márgenes mínimos para térmica
                size_args += ["--margin-top", "3mm", "--margin-bottom", "3mm",
                              "--margin-left", "3mm", "--margin-right", "3mm"]

            # HTML -> PDF silencioso
            subprocess.run(
                ["wkhtmltopdf", "--quiet", *size_args, path_html, pdf_path],
                check=True
            )

            # Enviar a impresora
            lp_cmd = ["lp", pdf_path]
            if printer_name:
                lp_cmd.extend(["-d", printer_name])
            subprocess.run(lp_cmd, check=True)
            return True
        except Exception as e:
            print(f"[print] wkhtmltopdf/lp falló: {e}")

    # Fallback: abrir el HTML con el sistema (visión previa manual)
    return _abrir_archivo_con_sistema(path_html)

    # ---------------------------
    # UX helpers
    # ---------------------------
    def _cargar_desde_tabla(self):
        _iid, data = self._selected_sale()
        if not data:
            return
        # Producto
        prod = data["producto"]
        if prod in self.productos:
            try:
                idx = list(self.productos.keys()).index(prod)
                self.combo_producto.current(idx)
            except Exception:
                self.combo_producto.set(prod)
        else:
            self.combo_producto.set(prod)

        # Limpiar entradas
        self.ent_unidades.delete(0, tk.END)
        self.ent_kilos.delete(0, tk.END)
        self.ent_cajas.delete(0, tk.END)

        # Rellenar según modo
        if data["modo"] == "UNIDADES":
            self.ent_unidades.insert(0, str(int(data["unidades"])))
        elif data["modo"] == "CAJAS→KILOS":
            # mostramos cajas referenciales si existen, si no, los kilos
            if data["num_cajas"] > 0:
                self.ent_cajas.insert(0, f"{redondear_dos_decimales(data['num_cajas']):.2f}")
            else:
                self.ent_kilos.insert(0, f"{redondear_dos_decimales(data['kilos']):.2f}")
        else:  # KILOS
            self.ent_kilos.insert(0, f"{redondear_dos_decimales(data['kilos']):.2f}")

        # Precio: lo ponemos manual con el precio usado
        self.precio_mode.set("manual")
        self._on_precio_mode_change()
        self.ent_precio.config(state="normal")
        self.ent_precio.delete(0, tk.END)
        self.ent_precio.insert(0, f"{redondear_dos_decimales(data['precio']):.2f}")

        # Crédito / cliente
        if (data["tipo"] or "").lower() == "credito":
            self.var_credito.set(True)
            self._toggle_credito()
            if data["cliente"] in self.clientes:
                try:
                    idx = list(self.clientes.keys()).index(data["cliente"])
                    self.combo_cliente.current(idx)
                except Exception:
                    self.combo_cliente.set(data["cliente"])
            else:
                self.combo_cliente.set(data["cliente"])
        else:
            self.var_credito.set(False)
            self._toggle_credito()

        # Focus cómodo
        if data["modo"] == "UNIDADES":
            self.ent_unidades.focus_set()
        elif data["modo"] == "CAJAS→KILOS":
            (self.ent_cajas if self.ent_cajas.get() else self.ent_kilos).focus_set()
        else:
            self.ent_kilos.focus_set()

    def _remove_row_view(self):
        """Elimina la fila seleccionada SOLO de la vista (no toca BD)."""
        sel = self.tree.selection()
        if not sel:
            return
        for iid in sel:
            try:
                self.tree.delete(iid)
            except Exception:
                pass

    def _clear_form(self, keep_price: bool = False):
        for e in (self.ent_unidades, self.ent_kilos, self.ent_cajas):
            e.delete(0, tk.END)
        if not keep_price:
            self.ent_precio.config(state="normal")
            self.ent_precio.delete(0, tk.END)

    def _on_escape(self, ev=None):
        top = self.winfo_toplevel()
        if isinstance(top, tk.Toplevel) and not isinstance(top, tk.Tk):
            try:
                top.destroy()
                return
            except Exception:
                pass
        self._clear_form(keep_price=(self.precio_mode.get() != "manual"))
        self.ent_buscar.delete(0, tk.END)
        self._load_sales()

    def _install_shortcuts(self):
        self.bind_all("<Control-f>", lambda e: (self.ent_buscar.focus_set(),
                                                self.ent_buscar.select_range(0, tk.END)))
        self.bind_all("<Escape>", self._on_escape)

    # ---------------------------
    # Infra de tabla y scrolls
    # ---------------------------
    def _tree_with_scrolls(self, parent, columnas):
        scroll_y = ttk.Scrollbar(parent, orient="vertical")
        scroll_x = ttk.Scrollbar(parent, orient="horizontal")
        tree = ttk.Treeview(
            parent, columns=columnas, show="headings", height=14, style="Brand.Treeview",
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set
        )
        scroll_y.config(command=tree.yview)
        scroll_x.config(command=tree.xview)

        tree.pack(fill="both", expand=True)
        scroll_x.pack(fill="x")
        scroll_y.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")
        return tree, scroll_x, scroll_y


# -----------------------------------------------------------
# Punto de entrada para main.py
# -----------------------------------------------------------
def mostrar(frame_contenedor):
    for widget in frame_contenedor.winfo_children():
        widget.destroy()
    frame = VentasFrame(frame_contenedor)
    frame.pack(fill="both", expand=True)
