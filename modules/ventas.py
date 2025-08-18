# modules/ventas.py
# -----------------------------------------------------------
# Sistema de Comercio — Módulo de Ventas (mejorado)
#
# - Modalidades excluyentes: UNIDADES | CAJAS | KILOS
# - Modo de precio: manual / mayoreo / menudeo (bloquea el campo si no es manual)
# - Validaciones robustas (2 decimales; unidades entero ≥ 1)
# - Actualiza inventario con redondeo a 2 decimales
# - Venta por kilos descuenta cajas equivalentes (si peso_caja>0)
# - Registra siempre 'total' en ventas (= cantidad_base * precio)
# - Tabla con búsqueda dinámica y formateo de fecha/moneda
# - Ordenamiento por encabezados (ASC/DESC)
#
# MEJORAS (UX / Atajos)
# -----------------------------------------------------------
# - Enter en cualquier campo del formulario: ejecuta "Nueva Venta".
# - Enter en la búsqueda: aplica el filtro (además del filtrado en vivo).
# - Esc: si está en Toplevel cierra; si no, limpia formulario y filtro.
# - Ctrl+F: enfoca la búsqueda.
# - Doble clic o Enter en la tabla: carga la venta a formulario (para reusar).
# - Supr en tabla: elimina la fila solo de la vista (no borra en BD).
# -----------------------------------------------------------

import tkinter as tk
from tkinter import ttk, messagebox
from db.database import get_connection
from datetime import datetime
from ui.helpers import (
    to_float,
    redondear_dos_decimales,
    formato_moneda,
    formatear_fecha,
)

# Paleta oscura
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


class VentasFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COLOR_BG, highlightthickness=0, bd=0)
        self.productos = {}     # nombre -> id
        self.clientes = {}      # nombre -> id
        self._has_unidades_col = False
        self.precio_mode = tk.StringVar(value="manual")  # 'manual' | 'mayoreo' | 'menudeo'

        # Para "cargar a formulario" desde la tabla
        self._venta_por_iid = {}  # iid -> dict crudo de la venta

        # ------- Estilos TTK (oscuro) -------
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
        self._style.configure(
            "Dark.Treeview.Heading",
            background=COLOR_PANEL, foreground=COLOR_TEXT, relief="flat",
        )
        self._style.map("Dark.Treeview.Heading", background=[("active", COLOR_PRIMARY)])

        self._style.configure(
            "Dark.TCombobox",
            fieldbackground=COLOR_ENTRY_BG,
            background=COLOR_PANEL,
            foreground=COLOR_TEXT
        )
        self._style.configure("Dark.TRadiobutton", background=COLOR_PANEL, foreground=COLOR_TEXT)
        self._style.configure("Dark.TCheckbutton", background=COLOR_PANEL, foreground=COLOR_TEXT)

        self.crear_interfaz()
        self.cargar_datos()
        self._instalar_atajos_globales()

    # ---------------------------
    # Helpers visuales
    # ---------------------------
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

    def _entry(self, parent, width=12, **grid):
        e = tk.Entry(
            parent, width=width, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
            insertbackground=COLOR_TEXT, relief="flat",
            highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY
        )
        if grid:
            e.grid(**grid)
        return e

    def _btn(self, parent, text, color_bg, cmd, **grid):
        b = tk.Button(
            parent, text=text, command=cmd, bg=color_bg, fg=COLOR_TEXT,
            activebackground=color_bg, activeforeground=COLOR_TEXT,
            relief="flat", padx=10, pady=6, cursor="hand2"
        )
        if grid:
            b.grid(**grid)
        return b

    def _estilizar_dropdown(self, cb: ttk.Combobox):
        """Aplica colores al listbox interno del Combobox (tema oscuro)."""
        def _apply():
            try:
                popdown = cb.tk.call("ttk::combobox::PopdownWindow", str(cb))
                win = self.nametowidget(popdown)
                lb = win.children["f"].children["l"]  # listbox
                lb.configure(
                    background=COLOR_PANEL,
                    foreground=COLOR_TEXT,
                    selectbackground=COLOR_SEL_BG,
                    selectforeground=COLOR_TEXT,
                    highlightthickness=0,
                    relief="flat",
                    borderwidth=0,
                )
            except Exception:
                pass
        self.after(50, _apply)

    # ---------------------------
    # UI
    # ---------------------------
    def crear_interfaz(self):
        venta_frame = tk.LabelFrame(self, text="Registrar Venta", bg=COLOR_PANEL, fg=COLOR_TEXT, bd=0)
        venta_frame.pack(fill="x", padx=10, pady=8)

        # columnas pares (1,3,5,7) donde van entradas se expanden
        for col in (1, 3, 5, 7):
            venta_frame.grid_columnconfigure(col, weight=1)

        vcmd_decimal = (self.register(self._validate_decimal), "%P")
        vcmd_entero  = (self.register(self._validate_entero),  "%P")

        # Producto
        self._lbl(venta_frame, "Producto:", row=0, column=0, sticky="e", padx=4, pady=2)
        self.combo_producto = ttk.Combobox(venta_frame, width=25, state="readonly", style="Dark.TCombobox")
        self.combo_producto.grid(row=0, column=1, padx=4, pady=2, sticky="we")
        self._estilizar_dropdown(self.combo_producto)
        self.combo_producto.bind("<Return>", lambda e: self.realizar_venta())

        # Unidades (entero ≥1)
        self._lbl(venta_frame, "Unidades:", row=0, column=2, sticky="e", padx=4, pady=2)
        self.unidades_entry = self._entry(venta_frame, width=10, row=0, column=3, padx=4, pady=2, sticky="we")
        self.unidades_entry.configure(validate="key", validatecommand=vcmd_entero)
        self.unidades_entry.bind("<Return>", lambda e: self.realizar_venta())

        # Kilos (decimal)
        self._lbl(venta_frame, "Kilos:", row=0, column=4, sticky="e", padx=4, pady=2)
        self.kilos_entry = self._entry(venta_frame, width=10, row=0, column=5, padx=4, pady=2, sticky="we")
        self.kilos_entry.configure(validate="key", validatecommand=vcmd_decimal)
        self.kilos_entry.bind("<Return>", lambda e: self.realizar_venta())

        # Cajas (decimal)
        self._lbl(venta_frame, "Cajas:", row=0, column=6, sticky="e", padx=4, pady=2)
        self.cajas_entry = self._entry(venta_frame, width=10, row=0, column=7, padx=4, pady=2, sticky="we")
        self.cajas_entry.configure(validate="key", validatecommand=vcmd_decimal)
        self.cajas_entry.bind("<Return>", lambda e: self.realizar_venta())

        # Modo de precio
        modo_frame = tk.Frame(venta_frame, bg=COLOR_PANEL)
        modo_frame.grid(row=1, column=0, columnspan=8, sticky="w", pady=(2, 0))
        tk.Label(modo_frame, text="Precio a usar:", bg=COLOR_PANEL, fg=COLOR_TEXT)\
            .pack(side="left", padx=(0, 6))
        ttk.Radiobutton(modo_frame, text="Manual", value="manual",  variable=self.precio_mode,
                        command=self._on_precio_mode_change, style="Dark.TRadiobutton").pack(side="left")
        ttk.Radiobutton(modo_frame, text="Mayoreo", value="mayoreo", variable=self.precio_mode,
                        command=self._on_precio_mode_change, style="Dark.TRadiobutton").pack(side="left", padx=(6, 0))
        ttk.Radiobutton(modo_frame, text="Menudeo", value="menudeo", variable=self.precio_mode,
                        command=self._on_precio_mode_change, style="Dark.TRadiobutton").pack(side="left", padx=(6, 0))

        self._lbl(venta_frame, "Precio unitario:", row=2, column=0, sticky="e", padx=4, pady=(2, 4))
        self.precio_entry = self._entry(venta_frame, width=10, row=2, column=1, padx=4, pady=(2, 4), sticky="we")
        self.precio_entry.configure(validate="key", validatecommand=vcmd_decimal)
        self.precio_entry.bind("<Return>", lambda e: self.realizar_venta())

        # Información del producto
        self.label_info = tk.Label(
            venta_frame,
            text=("Kilos disp.: 0 | Cajas: 0 | Peso/caja: 0 kg | "
                  "Unidades: n/d | Mayoreo: 0.00 | Menudeo: 0.00"),
            bg=COLOR_PANEL, fg=COLOR_TEXT, anchor="w"
        )
        self.label_info.grid(row=3, column=0, columnspan=8, pady=(2, 2), sticky="we")

        # Crédito
        self.var_credito = tk.BooleanVar()
        ttk.Checkbutton(
            venta_frame, text="Venta a Crédito", variable=self.var_credito,
            command=self.toggle_credito, style="Dark.TCheckbutton"
        ).grid(row=4, column=0, sticky="w", pady=2, padx=4)

        self._lbl(venta_frame, "Cliente:", row=4, column=1, sticky="e", padx=4)
        self.combo_cliente = ttk.Combobox(venta_frame, state="disabled", width=25, style="Dark.TCombobox")
        self.combo_cliente.grid(row=4, column=2, columnspan=2, sticky="we", padx=4)
        self._estilizar_dropdown(self.combo_cliente)
        self.combo_cliente.bind("<Return>", lambda e: self.realizar_venta())

        # Botón acción principal
        self._btn(venta_frame, "Nueva Venta", COLOR_PRIMARY, self.realizar_venta,
                  row=5, column=0, columnspan=8, pady=8)

        # ----- Filtro de búsqueda -----
        filtro_panel = self._panel(self, padx=10, pady=(2, 0), fill="x")
        tk.Label(filtro_panel, text="Buscar (producto/cliente/tipo/fecha):", bg=COLOR_PANEL, fg=COLOR_TEXT)\
            .pack(side="left", padx=(2, 6))
        self.entry_busqueda = tk.Entry(
            filtro_panel, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
            insertbackground=COLOR_TEXT, relief="flat",
            highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY, width=40
        )
        self.entry_busqueda.pack(side="left", fill="x", expand=True, padx=(0, 6), pady=6)
        self.entry_busqueda.bind("<KeyRelease>", lambda e: self.cargar_ventas(self.entry_busqueda.get().strip()))
        self.entry_busqueda.bind("<Return>",     lambda e: self.cargar_ventas(self.entry_busqueda.get().strip()))
        self._btn(filtro_panel, "Limpiar filtro", COLOR_PRIMARY,
                  lambda: (self.entry_busqueda.delete(0, tk.END), self.cargar_ventas()),
                  ).pack(side="left")

        # Tabla
        tabla_panel = self._panel(self, padx=10, pady=8, fill="both", expand=True)
        columnas = ("Fecha", "Producto", "Cantidad", "Precio", "Total", "Tipo", "Cliente")
        self.tree, _, _ = self._tree_with_scrolls(tabla_panel, columnas)

        for col, width, anchor in (
            ("Fecha", 140, "center"),
            ("Producto", 180, "w"),
            ("Cantidad", 90, "e"),
            ("Precio", 110, "e"),
            ("Total", 120, "e"),
            ("Tipo", 90, "center"),
            ("Cliente", 180, "w"),
        ):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("Producto", "Cliente")))

        # Ordenamiento
        self._setup_sorting(self.tree, columnas, {
            "Fecha": "date",
            "Producto": "str",
            "Cantidad": "float",
            "Precio": "money",
            "Total": "money",
            "Tipo": "str",
            "Cliente": "str",
        })

        # Eventos tabla (UX)
        self.tree.bind("<Double-1>", lambda e: self._cargar_desde_tabla())
        self.tree.bind("<Return>",   lambda e: self._cargar_desde_tabla())
        self.tree.bind("<Delete>",   lambda e: self._eliminar_de_vista())

        self.combo_producto.bind("<<ComboboxSelected>>", self.actualizar_info_producto)

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

    # ---------------------------
    # Validadores
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
    # Precio (modo)
    # ---------------------------
    def _on_precio_mode_change(self):
        modo = self.precio_mode.get()
        if modo == "manual":
            self.precio_entry.config(state="normal")
            return

        nombre = self.combo_producto.get()
        if not nombre:
            self.precio_entry.delete(0, tk.END)
            self.precio_entry.config(state="disabled")
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT precio_mayoreo, precio_menudeo
                    FROM productos WHERE nombre = ?
                """, (nombre,))
                row = cur.fetchone()
            if row:
                pmay, pmen = row
                valor = pmay if modo == "mayoreo" else pmen
                self.precio_entry.config(state="normal")
                self.precio_entry.delete(0, tk.END)
                self.precio_entry.insert(0, f"{redondear_dos_decimales(valor):.2f}")
                self.precio_entry.config(state="disabled")
        except Exception:
            self.precio_entry.config(state="disabled")

    def toggle_credito(self):
        estado = "readonly" if self.var_credito.get() else "disabled"
        self.combo_cliente.config(state=estado)

    # ---------------------------
    # Carga inicial
    # ---------------------------
    def _detectar_columna_unidades(self):
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(productos)")
                cols = [r[1].lower() for r in cur.fetchall()]
                self._has_unidades_col = ("unidades" in cols)
        except Exception:
            self._has_unidades_col = False

    def cargar_datos(self):
        self._detectar_columna_unidades()
        try:
            with get_connection() as conn:
                cur = conn.cursor()

                # Productos
                cur.execute("SELECT id, nombre FROM productos ORDER BY nombre COLLATE NOCASE")
                productos = cur.fetchall()
                self.productos = {nombre: pid for pid, nombre in productos}
                nombres = list(self.productos.keys())
                self.combo_producto["values"] = nombres
                if nombres:
                    self.combo_producto.current(0)
                    self.actualizar_info_producto()

                # Clientes
                cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre COLLATE NOCASE")
                clientes = cur.fetchall()
                self.clientes = {nombre: cid for cid, nombre in clientes}
                self.combo_cliente["values"] = list(self.clientes.keys())
                if self.clientes:
                    self.combo_cliente.current(0)

        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar catálogos.\n{e}")
            return

        self.cargar_ventas()

    def actualizar_info_producto(self, event=None):
        nombre = self.combo_producto.get()
        if not nombre:
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                if self._has_unidades_col:
                    cur.execute("""
                        SELECT kilos, num_cajas, peso_caja,
                               precio_mayoreo, precio_menudeo,
                               unidades
                        FROM productos WHERE nombre = ?
                    """, (nombre,))
                    row = cur.fetchone()
                    if row:
                        kilos_disp, cajas, peso, pmay, pmen, unidades = row
                    else:
                        row = None
                else:
                    cur.execute("""
                        SELECT kilos, num_cajas, peso_caja,
                               precio_mayoreo, precio_menudeo
                        FROM productos WHERE nombre = ?
                    """, (nombre,))
                    row = cur.fetchone()
                    if row:
                        kilos_disp, cajas, peso, pmay, pmen = row
                        unidades = None

            if row:
                txt_unid = f"{int(unidades)}" if (unidades is not None) else "n/d"
                self.label_info.config(
                    text=(
                        f"Kilos disp.: {redondear_dos_decimales(kilos_disp)} | "
                        f"Cajas: {redondear_dos_decimales(cajas)} | "
                        f"Peso/caja: {redondear_dos_decimales(peso)} kg | "
                        f"Unidades: {txt_unid} | "
                        f"Mayoreo: {redondear_dos_decimales(pmay):.2f} | "
                        f"Menudeo: {redondear_dos_decimales(pmen):.2f}"
                    )
                )
                if self.precio_mode.get() in ("mayoreo", "menudeo"):
                    valor = pmay if self.precio_mode.get() == "mayoreo" else pmen
                    self.precio_entry.config(state="normal")
                    self.precio_entry.delete(0, tk.END)
                    self.precio_entry.insert(0, f"{redondear_dos_decimales(valor):.2f}")
                    self.precio_entry.config(state="disabled")
            else:
                self.label_info.config(
                    text=("Kilos disp.: 0 | Cajas: 0 | Peso/caja: 0 kg | "
                          "Unidades: n/d | Mayoreo: 0.00 | Menudeo: 0.00")
                )
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo obtener la info del producto.\n{e}")

    # ---------------------------
    # Acción principal
    # ---------------------------
    def realizar_venta(self):
        nombre = self.combo_producto.get()
        if not nombre:
            messagebox.showwarning("Producto", "Selecciona un producto")
            return

        unidades_txt = self.unidades_entry.get().strip()
        cajas_txt    = self.cajas_entry.get().strip()
        kilos_txt    = self.kilos_entry.get().strip()

        modalidad = None
        unidades = 0
        cajas = 0.0
        kilos = 0.0

        if unidades_txt:
            if not self._has_unidades_col:
                messagebox.showerror("No disponible", "La base de datos no soporta venta por unidades (columna 'unidades' no existe).")
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

        try:
            if self.precio_mode.get() == "manual":
                precio = to_float(self.precio_entry.get(), permitir_cero=False)
            else:
                precio = to_float(self.precio_entry.get() or 0, permitir_cero=False)
        except ValueError:
            messagebox.showerror("Error", "Precio inválido.")
            return
        if precio <= 0:
            messagebox.showerror("Error", "El precio debe ser mayor a 0.")
            return

        producto_id = self.productos[nombre]
        tipo_venta = "credito" if self.var_credito.get() else "contado"
        cliente_id = None

        if tipo_venta == "credito":
            cliente_nombre = self.combo_cliente.get()
            if cliente_nombre not in self.clientes:
                messagebox.showerror("Cliente", "Selecciona un cliente válido")
                return
            cliente_id = self.clientes[cliente_nombre]

        # Transacción
        try:
            with get_connection() as conn:
                cur = conn.cursor()

                if self._has_unidades_col:
                    cur.execute("""
                        SELECT kilos, num_cajas, peso_caja, precio_mayoreo, precio_menudeo, unidades
                        FROM productos WHERE id = ?
                    """, (producto_id,))
                    row = cur.fetchone()
                    if not row:
                        messagebox.showerror("Error", "Producto no encontrado.")
                        return
                    stock_kilos, stock_cajas, peso_caja, pmay, pmen, stock_unidades = (
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
                    stock_kilos, stock_cajas, peso_caja, pmay, pmen = (
                        float(row[0] or 0), float(row[1] or 0),
                        float(row[2] or 0), float(row[3] or 0), float(row[4] or 0)
                    )
                    stock_unidades = None

                kilos_vta = 0.0
                num_cajas_vta = 0.0
                unidades_vta = 0
                total = 0.0
                fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if modalidad == "unidades":
                    if stock_unidades is None:
                        messagebox.showerror("No disponible", "Este producto no admite venta por unidades.")
                        return
                    if unidades > stock_unidades:
                        messagebox.showerror("Stock insuficiente", f"Unidades disponibles: {int(stock_unidades)}")
                        return
                    unidades_vta = int(unidades)
                    total = unidades_vta * precio

                    cur.execute("""
                        INSERT INTO ventas (producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (producto_id, 0.0, 0.0, unidades_vta, float(precio), float(total),
                          tipo_venta, cliente_id, fecha_str))
                    cur.execute("UPDATE productos SET unidades = unidades - ? WHERE id = ?", (unidades_vta, producto_id))

                elif modalidad == "cajas":
                    if peso_caja <= 0:
                        messagebox.showerror("Error", "No se puede vender por cajas: el producto no tiene 'peso_caja' definido.")
                        return
                    kilos_vta = cajas * peso_caja
                    # Redondear lo que se descuenta en inventario
                    kilos_vta = float(redondear_dos_decimales(kilos_vta))
                    if kilos_vta > stock_kilos:
                        messagebox.showerror("Stock insuficiente", f"Kilos disponibles: {redondear_dos_decimales(stock_kilos)}")
                        return
                    if cajas > stock_cajas:
                        messagebox.showerror("Stock insuficiente", f"Cajas disponibles: {redondear_dos_decimales(stock_cajas)}")
                        return
                    num_cajas_vta = float(redondear_dos_decimales(cajas))
                    total = kilos_vta * precio

                    cur.execute("""
                        INSERT INTO ventas (producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (producto_id, float(kilos_vta), float(num_cajas_vta), 0, float(precio), float(total),
                          tipo_venta, cliente_id, fecha_str))
                    cur.execute("UPDATE productos SET kilos = kilos - ?, num_cajas = num_cajas - ? WHERE id = ?",
                                (float(kilos_vta), float(num_cajas_vta), producto_id))

                else:  # kilos
                    if kilos > stock_kilos:
                        messagebox.showerror("Stock insuficiente", f"Kilos disponibles: {redondear_dos_decimales(stock_kilos)}")
                        return
                    kilos_vta = float(redondear_dos_decimales(kilos))
                    total = kilos_vta * precio

                    cur.execute("""
                        INSERT INTO ventas (producto_id, kilos, num_cajas, unidades, precio, total, tipo_venta, cliente_id, fecha)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (producto_id, float(kilos_vta), 0.0, 0, float(precio), float(total),
                          tipo_venta, cliente_id, fecha_str))
                    cur.execute("UPDATE productos SET kilos = kilos - ? WHERE id = ?", (float(kilos_vta), producto_id))
                    if peso_caja > 0:
                        cajas_equiv = float(redondear_dos_decimales(kilos_vta / peso_caja))
                        cur.execute("UPDATE productos SET num_cajas = num_cajas - ? WHERE id = ?",
                                    (cajas_equiv, producto_id))

                if tipo_venta == "credito" and cliente_id is not None:
                    cur.execute("UPDATE clientes SET deuda_total = deuda_total + ? WHERE id = ?",
                                (float(total), cliente_id))

            messagebox.showinfo("Éxito", "Venta registrada")
            self._limpiar_formulario(mantener_precio=(self.precio_mode.get() != "manual"))
            self.cargar_ventas(self.entry_busqueda.get().strip())
            self.actualizar_info_producto()

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la venta.\n{e}")

    # ---------------------------
    # Listado
    # ---------------------------
    def cargar_ventas(self, filtro: str = ""):
        self.tree.delete(*self.tree.get_children())
        self._venta_por_iid.clear()
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                if filtro:
                    like = f"%{filtro}%"
                    cur.execute("""
                        SELECT
                            v.id, v.fecha, p.nombre,
                            v.unidades, v.kilos, v.num_cajas,
                            v.precio, COALESCE(v.total, v.kilos * v.precio) AS total,
                            v.tipo_venta, c.nombre
                        FROM ventas v
                        JOIN productos p ON p.id = v.producto_id
                        LEFT JOIN clientes c ON c.id = v.cliente_id
                        WHERE p.nombre LIKE ? OR IFNULL(c.nombre,'') LIKE ? OR IFNULL(v.tipo_venta,'') LIKE ? OR DATE(v.fecha) LIKE ?
                        ORDER BY v.fecha DESC
                    """, (like, like, like, like))
                    rows = cur.fetchall()
                else:
                    cur.execute("""
                        SELECT
                            v.id, v.fecha, p.nombre,
                            v.unidades, v.kilos, v.num_cajas,
                            v.precio, COALESCE(v.total, v.kilos * v.precio) AS total,
                            v.tipo_venta, c.nombre
                        FROM ventas v
                        JOIN productos p ON p.id = v.producto_id
                        LEFT JOIN clientes c ON c.id = v.cliente_id
                        ORDER BY v.fecha DESC
                    """)
                    rows = cur.fetchall()

                for (vid, fecha, prod, unidades, kilos, num_cajas, precio, total, tipo, cliente) in rows:
                    # Cantidad mostrada (lo más representativo)
                    if (unidades or 0) > 0:
                        cantidad_mostrar = float(unidades or 0.0)
                    elif (kilos or 0) > 0:
                        cantidad_mostrar = float(kilos or 0.0)
                    else:
                        cantidad_mostrar = float(kilos or 0.0)

                    iid = self.tree.insert("", "end", values=(
                        formatear_fecha(fecha),
                        prod,
                        f"{redondear_dos_decimales(cantidad_mostrar):.2f}",
                        formato_moneda(redondear_dos_decimales(precio)),
                        formato_moneda(redondear_dos_decimales(total)),
                        tipo or "",
                        cliente or ""
                    ))
                    # Guardar datos crudos para "cargar a formulario"
                    self._venta_por_iid[iid] = {
                        "producto": prod,
                        "unidades": int(unidades or 0),
                        "kilos": float(kilos or 0.0),
                        "num_cajas": float(num_cajas or 0.0),
                        "precio": float(precio or 0.0),
                        "tipo": (tipo or ""),
                        "cliente": (cliente or "")
                    }
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar las ventas.\n{e}")

    # ---------------------------
    # UX: cargar desde tabla / eliminar de vista / limpiar / atajos
    # ---------------------------
    def _cargar_desde_tabla(self):
        sel = self.tree.selection()
        if not sel:
            return
        data = self._venta_por_iid.get(sel[0])
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

        # Modalidad -> rellena solo el campo correspondiente
        self.unidades_entry.delete(0, tk.END)
        self.kilos_entry.delete(0, tk.END)
        self.cajas_entry.delete(0, tk.END)

        if data["unidades"] > 0:
            self.unidades_entry.insert(0, str(int(data["unidades"])))
        elif data["num_cajas"] > 0:
            self.cajas_entry.insert(0, f"{redondear_dos_decimales(data['num_cajas']):.2f}")
        elif data["kilos"] > 0:
            self.kilos_entry.insert(0, f"{redondear_dos_decimales(data['kilos']):.2f}")

        # Precio: lo ponemos en modo manual con el precio usado
        self.precio_mode.set("manual")
        self._on_precio_mode_change()
        self.precio_entry.config(state="normal")
        self.precio_entry.delete(0, tk.END)
        self.precio_entry.insert(0, f"{redondear_dos_decimales(data['precio']):.2f}")

        # Crédito / cliente
        if (data["tipo"] or "").lower() == "credito":
            self.var_credito.set(True)
            self.toggle_credito()
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
            self.toggle_credito()

        # Focus cómodo
        if data["unidades"] > 0:
            self.unidades_entry.focus_set()
        elif data["num_cajas"] > 0:
            self.cajas_entry.focus_set()
        else:
            self.kilos_entry.focus_set()

    def _eliminar_de_vista(self):
        """Elimina la fila seleccionada SOLO de la tabla (no toca BD)."""
        sel = self.tree.selection()
        if not sel:
            return
        for iid in sel:
            try:
                self.tree.delete(iid)
            except Exception:
                pass
        # No mostramos diálogo para que sea fluido; es solo visual.

    def _limpiar_formulario(self, mantener_precio: bool = False):
        self.unidades_entry.delete(0, tk.END)
        self.kilos_entry.delete(0, tk.END)
        self.cajas_entry.delete(0, tk.END)
        if not mantener_precio:
            self.precio_entry.config(state="normal")
            self.precio_entry.delete(0, tk.END)

    def _limpiar_filtro(self):
        self.entry_busqueda.delete(0, tk.END)

    def _on_escape(self, ev=None):
        top = self.winfo_toplevel()
        # Si es un Toplevel "hijo" (no la ventana raíz), ciérralo.
        if isinstance(top, tk.Toplevel) and not isinstance(top, tk.Tk):
            try:
                top.destroy()
                return
            except Exception:
                pass
        # Si es la principal, limpia formulario y filtro
        self._limpiar_formulario(mantener_precio=(self.precio_mode.get() != "manual"))
        self._limpiar_filtro()
        self.cargar_ventas()

    def _instalar_atajos_globales(self):
        # Ctrl+F: enfocar búsqueda
        self.bind_all("<Control-f>", lambda e: (self.entry_busqueda.focus_set(),
                                                self.entry_busqueda.select_range(0, tk.END)))
        # Esc: cerrar Toplevel o limpiar en ventana principal
        self.bind_all("<Escape>", self._on_escape)

    # ---------------------------
    # Ordenamiento por columnas
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
            if t == "money":
                try:
                    return float(s.replace("$", "").replace(",", ""))
                except Exception:
                    return 0.0
            if t == "date":
                from datetime import datetime as _dt
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
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


# Punto de entrada desde main.py
def mostrar(frame_contenedor):
    for widget in frame_contenedor.winfo_children():
        widget.destroy()
    ventas_frame = VentasFrame(frame_contenedor)
    ventas_frame.pack(fill="both", expand=True)
