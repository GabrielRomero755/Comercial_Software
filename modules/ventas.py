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

from ui.tickets import imprimir_ticket

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
        self._has_venta_items = False
        self._ventas_eventos_cols: set[str] = set()
        self._cart: list[dict] = []

        # Modo de precio / crédito / cache
        self.precio_mode = tk.StringVar(value="manual")
        self.var_credito = tk.BooleanVar(value=False)
        self._venta_por_iid: dict[str, dict] = {}

        self._build_ui()
        self._inspect_schema()
        self._load_catalogs()
        self._load_sales()
        self._install_shortcuts()



    # ---------------------------
    # UI
    # ---------------------------
    def _build_ui(self):
        
        # --- contenedor scrollable ---
        outer = tk.Frame(self, bg=BRAND_PALETTE["bg"])
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=BRAND_PALETTE["bg"], highlightthickness=0)
        vbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)

        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # body es donde agregamos el contenido real
        self.body = tk.Frame(canvas, bg=BRAND_PALETTE["bg"])
        # Guardamos el id de la ventana para poder ajustar el ancho
        self._canvas_window = canvas.create_window((0, 0), window=self.body, anchor="nw")

        def _on_body_config(_):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self.body.bind("<Configure>", _on_body_config)

        def _on_canvas_config(e):
            # Hace que el frame interno se estire al ancho del canvas
            canvas.itemconfigure(self._canvas_window, width=e.width)
        canvas.bind("<Configure>", _on_canvas_config)

        # Rueda del mouse
        def _on_mousewheel(evt):
            if evt.num == 4 or evt.delta > 0:
                canvas.yview_scroll(-1, "units")
            elif evt.num == 5 or evt.delta < 0:
                canvas.yview_scroll(1, "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)   # Windows
        canvas.bind_all("<Button-4>", _on_mousewheel)     # Linux
        canvas.bind_all("<Button-5>", _on_mousewheel)     # Linux


        # ajustar el scrollregion cuando cambie el tamaño del contenido
        def _on_body_config(_):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self.body.bind("<Configure>", _on_body_config)

        # Opcional: rueda del mouse
        def _on_mousewheel(evt):
            # Windows / Linux
            if evt.num == 4 or evt.delta > 0:
                canvas.yview_scroll(-1, "units")
            elif evt.num == 5 or evt.delta < 0:
                canvas.yview_scroll(1, "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)   # Windows
        canvas.bind_all("<Button-4>", _on_mousewheel)     # Linux
        canvas.bind_all("<Button-5>", _on_mousewheel)     # Linux

        # --- A PARTIR DE AQUÍ, USA self.body COMO PARENT ---
        # Panel formulario
        form = tk.LabelFrame(self.body, text="Registrar Venta",
                            bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"], bd=0)
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

# ---- Carrito (venta multi-producto) ----
        carrito_box = tk.LabelFrame(self.body, text="Carrito (venta con varios productos)",
                                    bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"], bd=0)
        carrito_box.pack(fill="both", expand=False, padx=10, pady=(0, 8))

        cols_cart = ("Producto", "Modo", "Kilos", "Unidades", "Cajas", "Precio", "Importe", "ProductoID")

        cart_panel = tk.Frame(carrito_box, bg=BRAND_PALETTE["panel"])
        cart_panel.pack(fill="x", expand=False, padx=8, pady=(6, 2))

        self.tree_cart, cart_sx, cart_sy = self._tree_with_scrolls(cart_panel, cols_cart)
        self.tree_cart.config(height=6)

        for col, w, anchor in (
            ("Producto", 200, "w"),
            ("Modo", 90, "center"),
            ("Kilos", 90, "e"),
            ("Unidades", 90, "e"),
            ("Cajas", 90, "e"),
            ("Precio", 100, "e"),
            ("Importe", 110, "e"),
            ("ProductoID", 0, "center"),
        ):
            self.tree_cart.heading(col, text=col)
            self.tree_cart.column(col, width=w, anchor=anchor, stretch=(col in ("Producto",)))

        # barra de acciones del carrito
        bar = tk.Frame(carrito_box, bg=BRAND_PALETTE["panel"])
        bar.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(bar, text="Agregar al carrito", command=self._cart_add_from_form,
                bg=BRAND_PALETTE["primary"], fg=BRAND_PALETTE["text"], relief="flat", padx=10, pady=6)\
            .pack(side="left", padx=(0, 6))
        tk.Button(bar, text="Quitar seleccionado", command=self._cart_remove_selected,
                bg=BRAND_PALETTE["bg"], fg=BRAND_PALETTE["link"], relief="flat", padx=10, pady=6)\
            .pack(side="left", padx=(0, 6))
        tk.Button(bar, text="Vaciar carrito", command=self._cart_clear,
                bg=BRAND_PALETTE["bg"], fg=BRAND_PALETTE["link"], relief="flat", padx=10, pady=6)\
            .pack(side="left", padx=(0, 6))

        self.lbl_cart_total = tk.Label(bar, text="Total carrito: $0.00",
                                    bg=BRAND_PALETTE["panel"], fg=BRAND_PALETTE["text"])
        self.lbl_cart_total.pack(side="right", padx=6)

        tk.Button(bar, text="Registrar venta (carrito)", command=lambda: self._finalize_cart_sale(print_ticket=True),
                bg=BRAND_PALETTE["success"], fg=BRAND_PALETTE["text"], relief="flat", padx=10, pady=6)\
            .pack(side="right", padx=6)

        # ---- Filtro/Busqueda ----
        filtro = tk.Frame(self.body, bg=BRAND_PALETTE["panel"])
        filtro.pack(fill="x", padx=10, pady=(5, 0))
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
        tabla_panel = tk.Frame(self.body, bg=BRAND_PALETTE["panel"])
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
                
                # ... ya tienes otras PRAGMAs arriba
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='venta_items'")
                self._has_venta_items = cur.fetchone() is not None
                # clientes: deuda_total
                cur.execute("PRAGMA table_info(clientes)")
                ccols = {r[1].lower() for r in cur.fetchall()}
                self._clientes_has_deuda = "deuda_total" in ccols
        except Exception:
            self._ventas_has_estado = False
            self._ventas_has_eventos = False
            self._productos_has_unidades = False
            self._has_venta_items = False
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
        # si no es manual, al cambiar de producto refrescamos el precio del modo
        if (self.precio_mode.get() or "").lower() in ("mayoreo", "menudeo"):
            self._set_precio_from_mode()


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
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo obtener la info del producto.\n{e}")

    def _on_precio_mode_change(self):
        """
        - manual: deja editable y NO toca el valor.
        - mayoreo/menudeo: carga desde BD, escribe limpio y bloquea el Entry.
        """
        modo = (self.precio_mode.get() or "").lower()
        if modo == "manual":
            # desbloquear para permitir edición manual
            try:
                self.ent_precio.configure(state="normal")
            except Exception:
                pass
            return
        self._set_precio_from_mode()


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
    
    def _set_entry_value(self, entry: tk.Entry, text: str, lock: bool = False):
        """
        Escribe 'text' en un Entry evitando que el validador impida borrar/insertar.
        Si lock=True, deja el Entry en estado 'disabled' al final.
        """
        try:
            # Guardar estado/validación actuales
            prev_state = entry.cget("state")
            prev_validate = entry.cget("validate")

            # Deshabilitar validación momentáneamente y habilitar edición
            entry.configure(validate="none")
            entry.configure(state="normal")

            entry.delete(0, tk.END)
            entry.insert(0, text)

            # Restaurar validación
            entry.configure(validate=prev_validate)

            # Bloquear si aplica
            entry.configure(state="disabled" if lock else "normal")
        except Exception:
            # Fallback muy conservador
            entry.configure(state="normal")
            entry.delete(0, tk.END)
            entry.insert(0, text)
            entry.configure(state="disabled" if lock else "normal")

    def _set_precio_from_mode(self):
        """
        Rellena self.ent_precio según el modo (mayoreo/menudeo) y BLOQUEA el Entry.
        Limpia el contenido sin que el validador lo impida.
        """
        modo = (self.precio_mode.get() or "").lower()
        if modo == "manual":
            # nada que hacer
            try:
                self.ent_precio.configure(state="normal")
            except Exception:
                pass
            return

        nombre = self.combo_producto.get().strip()
        if not nombre:
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT precio_mayoreo, precio_menudeo FROM productos WHERE nombre = ?", (nombre,))
                row = cur.fetchone()
            if not row:
                return
            pmay = float(row[0] or 0.0)
            pmen = float(row[1] or 0.0)
            valor = pmay if modo == "mayoreo" else pmen

            self._set_entry_value(self.ent_precio, f"{redondear_dos_decimales(valor):.2f}", lock=True)
        except Exception as e:
            messagebox.showerror("Precio", f"No se pudo cargar el precio de {modo}.\n{e}")



    # ---------------------------
    # Acción principal: vender
    # ---------------------------
    def _do_sale(self, print_ticket: bool = False):
        nombre = self.combo_producto.get().strip()
        if not nombre:
            messagebox.showwarning("Producto", "Selecciona un producto")
            return

                # Modalidad (UNIDADES o KILOS) — CAJAS es solo referencial (para descontar stock de cajas)
        unidades_txt = self.ent_unidades.get().strip()
        cajas_txt    = self.ent_cajas.get().strip()
        kilos_txt    = self.ent_kilos.get().strip()

        # CAJAS: opcional, solo para restar stock de num_cajas (no afecta total)
        try:
            num_cajas_vta = to_float(cajas_txt or 0, permitir_cero=True)
            if num_cajas_vta < 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Error", "Número de cajas inválido.")
            return

        modalidad = None
        unidades = 0
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
        elif kilos_txt:
            try:
                kilos = to_float(kilos_txt, permitir_cero=False)
            except ValueError:
                messagebox.showerror("Error", "Kilos inválidos.")
                return
            modalidad = "kilos"
        else:
            # Si solo metieron cajas, NO se permite (total se calcula por kilos o unidades)
            messagebox.showerror("Error", "Ingresa Kilos o Unidades para registrar la venta.\n(Cajas son solo de control de inventario)")
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

        # Stock (kilos / unidades / num_cajas) y peso_caja (solo informativo)
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
                    stock_k, stock_cj, _peso_caja, _pmay, _pmen, stock_u = (
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
                    stock_k, stock_cj, _peso_caja, _pmay, _pmen = (
                        float(row[0] or 0), float(row[1] or 0), float(row[2] or 0),
                        float(row[3] or 0), float(row[4] or 0)
                    )
                    stock_u = None

                # Validaciones de stock según modalidad
                if modalidad == "unidades":
                    if stock_u is None:
                        messagebox.showerror("No disponible", "Este producto no admite venta por unidades.")
                        return
                    if unidades > stock_u:
                        messagebox.showerror("Stock insuficiente", f"Unidades disponibles: {int(stock_u)}")
                        return
                else:  # kilos
                    if kilos > stock_k:
                        messagebox.showerror("Stock insuficiente", f"Kilos disponibles: {redondear_dos_decimales(stock_k)}")
                        return

                # Si ingresaron cajas, también validar stock de cajas
                if num_cajas_vta > 0 and num_cajas_vta > stock_cj:
                    messagebox.showerror("Stock insuficiente", f"Cajas disponibles: {redondear_dos_decimales(stock_cj)}")
                    return

                # Calcular total (solo por kilos o unidades)
                kilos_vta = float(redondear_dos_decimales(kilos)) if modalidad == "kilos" else 0.0
                unidades_vta = int(unidades) if modalidad == "unidades" else 0
                total = (unidades_vta * precio) if modalidad == "unidades" else (kilos_vta * precio)
                fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Insertar venta (persistimos num_cajas como referencial)
                cur.execute("""
                    INSERT INTO ventas (producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha{extra_cols})
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?{extra_vals})
                """.format(
                    extra_cols=", estado" if self._ventas_has_estado else "",
                    extra_vals=", 'ACTIVA'" if self._ventas_has_estado else ""
                ), (producto_id, float(kilos_vta), float(num_cajas_vta), int(unidades_vta), float(precio), float(total),
                    tipo_venta, cliente_id, fecha_str))

                # Descontar stocks
                if unidades_vta > 0 and self._productos_has_unidades:
                    cur.execute("UPDATE productos SET unidades = unidades - ? WHERE id = ?", (unidades_vta, producto_id))
                if kilos_vta > 0:
                    cur.execute("UPDATE productos SET kilos = kilos - ? WHERE id = ?", (float(kilos_vta), producto_id))
                if num_cajas_vta > 0:
                    cur.execute("UPDATE productos SET num_cajas = num_cajas - ? WHERE id = ?", (float(num_cajas_vta), producto_id))

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
    
    def _cart_repaint(self):
        # refresca la tabla y el total
        for iid in self.tree_cart.get_children():
            self.tree_cart.delete(iid)
        total = 0.0
        for it in self._cart:
            total += float(it["importe"] or 0.0)
            self.tree_cart.insert("", "end", values=(
                it["producto_nombre"],
                it["modo"],
                f"{redondear_dos_decimales(it['kilos']):.2f}",
                str(int(it["unidades"] or 0)),
                f"{redondear_dos_decimales(it['num_cajas']):.2f}",
                formato_moneda(redondear_dos_decimales(it["precio"])),
                formato_moneda(redondear_dos_decimales(it["importe"])),
                it["producto_id"]
            ))
        self.lbl_cart_total.config(text=f"Total carrito: {formato_moneda(redondear_dos_decimales(total))}")

    def _cart_add_from_form(self):
        """Toma los campos del formulario actual y los agrega al carrito (no toca BD aún)."""
        nombre = self.combo_producto.get().strip()
        if not nombre:
            messagebox.showwarning("Producto", "Selecciona un producto"); return
        producto_id = self.productos.get(nombre)
        if not producto_id:
            messagebox.showerror("Error", "Producto no encontrado."); return

        # Determina modalidad y cantidades (CAJAS es opcional y no convierte)
        unidades_txt = self.ent_unidades.get().strip()
        cajas_txt    = self.ent_cajas.get().strip()
        kilos_txt    = self.ent_kilos.get().strip()

        modalidad = None
        unidades = 0
        kilos = 0.0
        num_cajas = 0.0

        # cajas opcionales
        try:
            num_cajas = to_float(cajas_txt or 0, permitir_cero=True)
            if num_cajas < 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Error", "Número de cajas inválido."); return

        try:
            if unidades_txt:
                if not self._productos_has_unidades:
                    messagebox.showerror("No disponible", "La BD no soporta venta por unidades.")
                    return
                unidades = int(unidades_txt)
                if unidades <= 0: raise ValueError
                modalidad = "UNIDADES"
            elif kilos_txt:
                kilos = to_float(kilos_txt, permitir_cero=False)
                modalidad = "KILOS"
            else:
                messagebox.showerror("Error", "Ingresa Unidades o Kilos (las Cajas son opcionales)."); return
        except Exception:
            messagebox.showerror("Error", "Cantidad inválida."); return

        try:
            precio = to_float(self.ent_precio.get(), permitir_cero=False)
        except Exception:
            messagebox.showerror("Error", "Precio inválido."); return

        # Obtener peso_caja para convertir si es CAJAS→KILOS
        peso_caja = 0.0
        try:
            with get_connection() as conn:
                r = conn.execute("SELECT peso_caja FROM productos WHERE id=?", (producto_id,)).fetchone()
                peso_caja = float(r[0] or 0.0) if r else 0.0
        except Exception:
            peso_caja = 0.0

        num_cajas = 0.0
        # importe: solo por kilos o unidades
        if modalidad == "UNIDADES":
            importe = redondear_dos_decimales(unidades * precio)
        else:
            kilos = redondear_dos_decimales(kilos)
            importe = redondear_dos_decimales(kilos * precio)
        

        self._cart.append({
            "producto_id": int(producto_id),
            "producto_nombre": nombre,
            "modo": modalidad,
            "kilos": float(kilos or 0.0),
            "unidades": int(unidades or 0),
            "num_cajas": float(num_cajas or 0.0),
            "precio": float(precio),
            "importe": float(importe),
        })
        self._cart_repaint()
        # limpiar campos (conserva precio si no es manual)
        self._clear_form(keep_price=(self.precio_mode.get() != "manual"))

    def _cart_remove_selected(self):
        sel = self.tree_cart.selection()
        if not sel:
            return
        # eliminamos por índice visual
        # mapeamos a (producto_id, kilos, unidades, precio, importe) para distinguir
        vals = self.tree_cart.item(sel[0], "values")
        key = (int(vals[7]), float(vals[2]), int(vals[3]), float(vals[4]), float(vals[5].replace("$","").replace(",","")))
        for i, it in enumerate(self._cart):
            k = (it["producto_id"], round(it["kilos"],2), int(it["unidades"]), round(it["num_cajas"],2), round(it["precio"],2))
            if k == key:
                self._cart.pop(i); break

        self._cart_repaint()

    def _cart_clear(self):
        self._cart.clear()
        self._cart_repaint()

    def _finalize_cart_sale(self, print_ticket: bool = True):
        """Persistir carrito completo como UNA venta con N items."""
        if not self._cart:
            messagebox.showinfo("Carrito", "No hay productos en el carrito."); return
        if not self._has_venta_items:
            messagebox.showerror("Carrito", "La tabla 'venta_items' no existe. Ejecuta la migración."); return

        tipo_venta = "credito" if self.var_credito.get() else "contado"
        cliente_id = None
        if tipo_venta == "credito":
            cli_nombre = self.combo_cliente.get()
            if cli_nombre not in self.clientes:
                messagebox.showerror("Cliente", "Selecciona un cliente válido"); return
            cliente_id = self.clientes[cli_nombre]

        # Validar stock por ítem ANTES de tocar BD
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                stock_map = {}
                # precarga stocks
                for it in self._cart:
                    pid = it["producto_id"]
                    if pid not in stock_map:
                        if self._productos_has_unidades:
                            cur.execute("SELECT kilos, num_cajas, unidades FROM productos WHERE id=?", (pid,))
                            r = cur.fetchone()
                            stock_map[pid] = (float(r[0] or 0.0), float(r[1] or 0.0), int(r[2] or 0))
                        else:
                            cur.execute("SELECT kilos, num_cajas FROM productos WHERE id=?", (pid,))
                            r = cur.fetchone()
                            stock_map[pid] = (float(r[0] or 0.0), float(r[1] or 0.0), None)

                # verificar
                for it in self._cart:
                    pid = it["producto_id"]
                    sk_k, sk_cj, sk_u = stock_map[pid] if self._productos_has_unidades else (*stock_map[pid], None)
                    if it["unidades"] > 0:
                        if sk_u is None or it["unidades"] > sk_u:
                            raise ValueError(f"Stock insuficiente de unidades para {it['producto_nombre']}")
                    if it["kilos"] > 0:
                        if it["kilos"] > sk_k:
                            raise ValueError(f"Stock insuficiente de kilos para {it['producto_nombre']}")
                    if it["num_cajas"] > 0:
                        if it["num_cajas"] > sk_cj:
                            raise ValueError(f"Stock insuficiente de cajas para {it['producto_nombre']}")

        except Exception as e:
            messagebox.showerror("Stock", str(e)); return
        # Persistencia
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                total_venta = sum(float(it["importe"] or 0.0) for it in self._cart)
                # encabezado en 'ventas'
                extra_cols = ", estado" if self._ventas_has_estado else ""
                extra_vals = ", 'ACTIVA'" if self._ventas_has_estado else ""
                cur.execute(f"""
                    INSERT INTO ventas (producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha{extra_cols})
                    VALUES (NULL, 0, 0, 0, 0, ?, ?, ?, ?{extra_vals})
                """, (float(total_venta), tipo_venta, cliente_id, fecha_str))
                venta_id = cur.lastrowid
                # detalle en 'venta_items' + actualización de stock
                for it in self._cart:
                    cur.execute("""
                        INSERT INTO venta_items
                        (venta_id, producto_id, kilos, unidades, num_cajas, precio, importe)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (int(venta_id), int(it["producto_id"]), float(it["kilos"]), int(it["unidades"]),
                        float(it["num_cajas"]), float(it["precio"]), float(it["importe"])))
                    # stock
                    if it["unidades"] > 0 and self._productos_has_unidades:
                        cur.execute("UPDATE productos SET unidades = unidades - ? WHERE id = ?", (int(it["unidades"]), int(it["producto_id"])))
                    if it["kilos"] > 0:
                        cur.execute("UPDATE productos SET kilos = kilos - ? WHERE id = ?", (float(it["kilos"]), int(it["producto_id"])))
                    if it["num_cajas"] > 0:
                        cur.execute("UPDATE productos SET num_cajas = num_cajas - ? WHERE id = ?", (float(it["num_cajas"]), int(it["producto_id"])))

                # deuda cliente si crédito
                if self._clientes_has_deuda and tipo_venta == "credito" and cliente_id:
                    cur.execute("UPDATE clientes SET deuda_total = deuda_total + ? WHERE id = ?", (float(total_venta), int(cliente_id)))
            # limpiar UI
            self._cart_clear()
            self._load_sales(self.ent_buscar.get().strip())
            self._refresh_producto_info()
            messagebox.showinfo("Éxito", "Venta registrada (carrito).")

            if print_ticket:
                self._imprimir_ticket(venta_id=venta_id, reimpresion=False)

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la venta del carrito.\n{e}")

    
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
                                WHEN IFNULL(v.kilos,0)    > 0 THEN 'KILOS'
                                WHEN IFNULL(v.kilos,0)    > 0 THEN 'KILOS'
                                ELSE 'N/A'
                            END AS modo,
                            v.unidades, v.kilos, v.num_cajas,
                            v.precio, COALESCE(v.total, v.kilos * v.precio) AS total,
                            v.tipo_venta, c.nombre
                        FROM ventas v
                         LEFT JOIN productos p ON p.id = v.producto_id
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
                                WHEN IFNULL(v.kilos,0)    > 0 THEN 'KILOS'
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

    def _imprimir_ticket(self, venta_id: int | None = None, reimpresion: bool = True):
        """Intenta imprimir ticket usando ui.tickets si existe."""
        try:
            from ui import tickets  # type: ignore
        except Exception:
            messagebox.showinfo("Ticket", "El módulo de tickets aún no está disponible.")
            return
        try:
            if venta_id is None:
                # Si no se pasa, usar la venta seleccionada
                _iid, data = self._selected_sale()
                if not data:
                    messagebox.showinfo("Ticket", "Selecciona una venta.")
                    return
                venta_id = data["id"]
            tickets.imprimir_ticket(
                int(venta_id),
                reimpresion=reimpresion,
                abrir_archivo=False,     # no abrir visor
                print_direct=True        # mandar a impresora (lp)
                # , printer_name="NOMBRE_DE_TU_IMPRESORA"  # opcional
            )
        except Exception as e:
            messagebox.showerror("Ticket", f"No se pudo generar el ticket.\n{e}")
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

        # Rellenar según modo (cajas es opcional/referencial)
        if data["modo"] == "UNIDADES":
            self.ent_unidades.insert(0, str(int(data["unidades"])))
        else:  # KILOS u otro
            if data["kilos"] > 0:
                self.ent_kilos.insert(0, f"{redondear_dos_decimales(data['kilos']):.2f}")
        if data["num_cajas"] > 0:
            self.ent_cajas.insert(0, f"{redondear_dos_decimales(data['num_cajas']):.2f}")

        # Precio: lo ponemos manual con el precio usado
        self.precio_mode.set("manual")
        self._on_precio_mode_change()
        self._set_entry_value(self.ent_precio, f"{redondear_dos_decimales(data['precio']):.2f}", lock=False)
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
        wrapper = tk.Frame(parent, bg=BRAND_PALETTE["panel"])
        wrapper.pack(fill="both", expand=True)

        # Widgets
        tree = ttk.Treeview(
            wrapper, columns=columnas, show="headings", height=14, style="Brand.Treeview"
        )
        scroll_y = ttk.Scrollbar(wrapper, orient="vertical", command=tree.yview)
        scroll_x = ttk.Scrollbar(wrapper, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        # Layout con grid (barras pegadas al árbol)
        wrapper.grid_rowconfigure(0, weight=1)
        wrapper.grid_columnconfigure(0, weight=1)

        tree.grid(row=0, column=0, sticky="nsew")  # árbol ocupa todo
        scroll_y.grid(row=0, column=1, sticky="ns")  # a la derecha
        scroll_x.grid(row=1, column=0, sticky="ew")  # abajo

        # Esquina inferior derecha para que no quede hueco (opcional)
        tk.Frame(wrapper, width=1, height=1, bg=BRAND_PALETTE["panel"]).grid(row=1, column=1)

        return tree, scroll_x, scroll_y

# -----------------------------------------------------------
# Punto de entrada para main.py
# -----------------------------------------------------------
def mostrar(frame_contenedor):
    for widget in frame_contenedor.winfo_children():
        widget.destroy()
    frame = VentasFrame(frame_contenedor)
    frame.pack(fill="both", expand=True)
