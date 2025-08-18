# modules/inventario.py
# -----------------------------------------------------------
# Sistema de Comercio — Módulo de Inventario
#
# USO / FLUJO / FUNCIONALIDAD
# -----------------------------------------------------------
# - ENTRADAS (compras/ajustes):
#     * Producto, Kilos (+), Núm. Cajas (+), Peso/Caja (kg), Unidades (+),
#       Tipo (por defecto "Compra"), Motivo y Monto (Compra $).
#     * Actualiza existencias en productos (kilos, num_cajas, unidades, peso_caja).
#     * Si Tipo = "Compra" y Monto > 0 => inserta en 'gastos':
#         - tipo = "Compra"
#         - monto = ingresado
#         - descripcion = nombre del producto (como en inventario)
#         - fecha = misma fecha/hora de la entrada
# - MERMAS:
#     * Producto, Kilos (-), Núm. Cajas (-), Unidades (-), Motivo.
#     * Valida stock suficiente antes de descontar.
# - Búsqueda dinámica:
#     * Filtra por nombre de producto, motivo y TIPO (entradas).
# - Tabla de movimientos (con ordenamiento por encabezados):
#     * Columnas:
#       Movimiento | Producto | Kilos | Cajas | Unidades | Monto | Tipo | Motivo | Fecha
#
# MEJORAS (esta versión)
# -----------------------------------------------------------
# - Validadores de 2 decimales usando helpers.adjuntar_validador_2_decimales (soporta coma/punto).
# - Autocálculo kilos<->cajas usando peso_caja cuando falte uno de los dos.
# - Prefill de peso_caja e info de stock al cambiar de producto.
# - Enter para confirmar Entrada/Merma; refresco de info tras operar.
# - UX: Enter en buscador aplica filtro; Esc en buscador limpia y recarga.
# -----------------------------------------------------------

import tkinter as tk
from tkinter import ttk, messagebox
from db.database import get_connection
from datetime import datetime
from ui.helpers import (
    formatear_fecha,
    redondear_dos_decimales,
    formato_moneda,
    to_float,
    to_int,
    adjuntar_validador_2_decimales,
)

# -----------------------------------------------------------
# Paleta oscura
# -----------------------------------------------------------
COLOR_BG        = "#2C3E50"  # Fondo general
COLOR_PANEL     = "#34495E"  # Paneles / contenedores
COLOR_TEXT      = "#ECF0F1"  # Texto
COLOR_PRIMARY   = "#3498DB"  # Botones principales
COLOR_SUCCESS   = "#2ECC71"  # Confirmación / Éxito
COLOR_ENTRY_BG  = "#3B4A5A"  # Entradas
COLOR_ENTRY_FG  = COLOR_TEXT
COLOR_BORDER    = "#22313F"
COLOR_SEL_BG    = "#1ABC9C"  # Selección en listas/tablas


class InventarioFrame(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COLOR_BG)
        self.productos = {}  # nombre -> id

        self._style = ttk.Style()
        self._aplicar_tema_ttk()

        self.crear_interfaz()
        self.mostrar()

    # ---------------------------
    # Estilos / helpers UI
    # ---------------------------
    def _aplicar_tema_ttk(self):
        try:
            self._style.theme_use("default")
        except Exception:
            pass

        # Treeview oscuro
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
            background=COLOR_PANEL,
            foreground=COLOR_TEXT,
            relief="flat"
        )
        self._style.map("Dark.Treeview.Heading",
                        background=[("active", COLOR_PRIMARY)])

        # Combobox oscuro
        self._style.configure(
            "Dark.TCombobox",
            fieldbackground=COLOR_ENTRY_BG,
            background=COLOR_PANEL,
            foreground=COLOR_TEXT,
            arrowsize=14
        )
        self._style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", COLOR_ENTRY_BG)],
            foreground=[("readonly", COLOR_TEXT)],
            background=[("readonly", COLOR_PANEL)],
            arrowcolor=[("readonly", COLOR_TEXT)],
        )

    def _panel(self, parent, **pack):
        f = tk.Frame(parent, bg=COLOR_PANEL, bd=0, highlightthickness=0)
        if pack:
            f.pack(**pack)
        return f

    def _titulo(self, parent, texto):
        tk.Label(parent, text=texto, bg=COLOR_PANEL, fg=COLOR_TEXT,
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 4))

    def _lbl(self, parent, text, **grid):
        w = tk.Label(parent, text=text, bg=parent["bg"], fg=COLOR_TEXT)
        if grid:
            w.grid(**grid)
        return w

    def _entry(self, parent, width=12, **grid):
        e = tk.Entry(parent, width=width, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                     insertbackground=COLOR_TEXT, relief="flat",
                     highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        if grid:
            e.grid(**grid)
        return e

    def _btn(self, parent, text, bgc, cmd, **place):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bgc, fg=COLOR_TEXT, activebackground=bgc,
                      activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")
        if place:
            uses_grid = any(k in place for k in ("row", "column", "rowspan", "columnspan", "sticky"))
            if uses_grid:
                b.grid(**place)
            else:
                b.pack(**place)
        return b

    def _combobox(self, parent, **grid):
        cb = ttk.Combobox(parent, state="readonly", style="Dark.TCombobox", **grid)
        # Estilizar el listbox del desplegable al abrirse (tema oscuro)
        cb.configure(postcommand=lambda c=cb: self._estilizar_dropdown(c))
        return cb

    def _estilizar_dropdown(self, combobox: ttk.Combobox):
        try:
            pop = combobox.tk.call("ttk::combobox::PopdownWindow", combobox)
            lb = combobox.nametowidget(pop + ".f.l")
            lb.configure(
                background=COLOR_PANEL,
                foreground=COLOR_TEXT,
                selectbackground=COLOR_SEL_BG,
                selectforeground=COLOR_TEXT,
                highlightthickness=0,
                relief="flat",
            )
        except Exception:
            pass

    # ---------------------------
    # UI
    # ---------------------------
    def crear_interfaz(self):
        # === Entradas de Inventario ===
        entrada_panel = self._panel(self, pady=8, padx=8, fill="x")
        self._titulo(entrada_panel, "Entradas de Inventario (Compra)")

        grid = tk.Frame(entrada_panel, bg=COLOR_PANEL)
        grid.pack(fill="x", padx=8, pady=(0, 4))

        self._lbl(grid, "Producto:", row=0, column=0, padx=4, pady=4, sticky="e")
        self.combo_producto = self._combobox(grid, width=25)
        self.combo_producto.grid(row=0, column=1, padx=4, pady=4, sticky="we")  # <-- expand
        grid.grid_columnconfigure(1, weight=1)
        self.combo_producto.bind("<<ComboboxSelected>>", self._on_producto_change)
        # NUEVO: Enter en el combobox confirma Entrada
        self.combo_producto.bind("<Return>", lambda e: self.registrar_entrada())

        self._lbl(grid, "Kilos (+):", row=0, column=2, padx=4, pady=4, sticky="e")
        self.kilos_entry = self._entry(grid, width=10, row=0, column=3, padx=4, pady=4)

        self._lbl(grid, "Núm. Cajas (+):", row=0, column=4, padx=4, pady=4, sticky="e")
        self.cajas_entry = self._entry(grid, width=10, row=0, column=5, padx=4, pady=4)

        self._lbl(grid, "Peso/Caja (kg):", row=0, column=6, padx=4, pady=4, sticky="e")
        self.peso_entry = self._entry(grid, width=10, row=0, column=7, padx=4, pady=4)

        self._lbl(grid, "Unidades (+):", row=1, column=0, padx=4, pady=4, sticky="e")
        self.unidades_entry = self._entry(grid, width=10, row=1, column=1, padx=4, pady=4, sticky="w")

        self._lbl(grid, "Tipo:", row=1, column=2, padx=4, pady=4, sticky="e")
        self.tipo_combo = self._combobox(grid, width=18)
        self.tipo_combo["values"] = ["Compra", "Ajuste", "Devolución", "Otro"]
        self.tipo_combo.grid(row=1, column=3, padx=4, pady=4, sticky="w")
        if self.tipo_combo["values"]:
            self.tipo_combo.current(0)
        # Enter en tipo => confirma Entrada
        self.tipo_combo.bind("<Return>", lambda e: self.registrar_entrada())

        self._lbl(grid, "Motivo:", row=1, column=4, padx=4, pady=4, sticky="e")
        self.motivo_entry = self._entry(grid, width=35, row=1, column=5, columnspan=3, padx=4, pady=4, sticky="we")
        grid.grid_columnconfigure(5, weight=1)

        self._lbl(grid, "Monto (Compra $):", row=2, column=0, padx=4, pady=4, sticky="e")
        self.monto_compra_entry = self._entry(grid, width=12, row=2, column=1, padx=4, pady=4)

        self._btn(grid, "Registrar Entrada", COLOR_SUCCESS, self.registrar_entrada,
                  row=2, column=2, columnspan=6, padx=4, pady=6, sticky="w")

        # Info producto (stock/peso)
        self.info_label = tk.Label(
            entrada_panel,
            text="Kilos: 0.00 | Cajas: 0.00 | Unidades: 0 | Peso/caja: 0.00 kg",
            bg=COLOR_PANEL, fg=COLOR_TEXT, anchor="w"
        )
        self.info_label.pack(fill="x", padx=16, pady=(0, 8))

        # Validadores decimales (permite ',' o '.')
        for e in (self.kilos_entry, self.cajas_entry, self.peso_entry, self.monto_compra_entry):
            adjuntar_validador_2_decimales(e, permitir_vacio=True)

        # Atajos (Enter confirma)
        self.kilos_entry.bind("<Return>", lambda e: self.registrar_entrada())
        self.cajas_entry.bind("<Return>", lambda e: self.registrar_entrada())
        self.peso_entry.bind("<Return>", lambda e: self.registrar_entrada())
        self.unidades_entry.bind("<Return>", lambda e: self.registrar_entrada())
        self.monto_compra_entry.bind("<Return>", lambda e: self.registrar_entrada())
        self.motivo_entry.bind("<Return>", lambda e: self.registrar_entrada())

        # === Registro de Mermas ===
        merma_panel = self._panel(self, pady=8, padx=8, fill="x")
        self._titulo(merma_panel, "Registro de Mermas")

        grid_m = tk.Frame(merma_panel, bg=COLOR_PANEL)
        grid_m.pack(fill="x", padx=8, pady=(0, 8))

        self._lbl(grid_m, "Producto:", row=0, column=0, padx=4, pady=4, sticky="e")
        self.combo_producto_merma = self._combobox(grid_m, width=25)
        self.combo_producto_merma.grid(row=0, column=1, padx=4, pady=4, sticky="we")
        grid_m.grid_columnconfigure(1, weight=1)
        self.combo_producto_merma.bind("<<ComboboxSelected>>", self._on_producto_change_merma)
        # NUEVO: Enter en combobox merma => confirma
        self.combo_producto_merma.bind("<Return>", lambda e: self.registrar_merma())

        self._lbl(grid_m, "Kilos (-):", row=0, column=2, padx=4, pady=4, sticky="e")
        self.merma_kilos_entry = self._entry(grid_m, width=10, row=0, column=3, padx=4, pady=4)

        self._lbl(grid_m, "Núm. Cajas (-):", row=0, column=4, padx=4, pady=4, sticky="e")
        self.merma_cajas_entry = self._entry(grid_m, width=10, row=0, column=5, padx=4, pady=4)

        self._lbl(grid_m, "Unidades (-):", row=0, column=6, padx=4, pady=4, sticky="e")
        self.merma_unidades_entry = self._entry(grid_m, width=10, row=0, column=7, padx=4, pady=4)

        self._lbl(grid_m, "Motivo:", row=1, column=0, padx=4, pady=4, sticky="e")
        self.motivo_merma_entry = self._entry(grid_m, width=50, row=1, column=1, columnspan=7, padx=4, pady=4, sticky="we")
        grid_m.grid_columnconfigure(1, weight=1)

        self._btn(grid_m, "Registrar Merma", COLOR_PRIMARY, self.registrar_merma,
                  row=2, column=0, columnspan=8, padx=4, pady=6)

        for e in (self.merma_kilos_entry, self.merma_cajas_entry):
            adjuntar_validador_2_decimales(e, permitir_vacio=True)

        # Atajos (Enter confirma)
        self.merma_kilos_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.merma_cajas_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.merma_unidades_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.motivo_merma_entry.bind("<Return>", lambda e: self.registrar_merma())

        # === Buscador dinámico ===
        busc_panel = self._panel(self, pady=(2, 0), padx=8, fill="x")
        tk.Label(busc_panel, text="Buscar en inventario/mermas:", bg=COLOR_PANEL, fg=COLOR_TEXT)\
            .pack(side=tk.LEFT, padx=8, pady=8)
        self.entry_busqueda = tk.Entry(busc_panel, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                                       insertbackground=COLOR_TEXT, relief="flat",
                                       highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        self.entry_busqueda.pack(side=tk.LEFT, padx=8, pady=6, fill="x", expand=True)
        self.entry_busqueda.bind("<KeyRelease>", lambda e: self.cargar_movimientos(self.entry_busqueda.get().strip()))
        # NUEVO: Enter aplica filtro; Esc limpia y recarga
        self.entry_busqueda.bind("<Return>", lambda e: self.cargar_movimientos(self.entry_busqueda.get().strip()))
        self.entry_busqueda.bind("<Escape>", self._limpiar_filtro_busqueda)

        # === Tabla de movimientos ===
        tabla_panel = self._panel(self, pady=8, padx=8, fill="both", expand=True)

        columnas = ("Movimiento", "Producto", "Kilos", "Cajas", "Unidades", "Monto", "Tipo", "Motivo", "Fecha")

        # Scrollbars
        scroll_y = ttk.Scrollbar(tabla_panel, orient="vertical")
        scroll_x = ttk.Scrollbar(tabla_panel, orient="horizontal")

        self.tree = ttk.Treeview(
            tabla_panel, columns=columnas, show="headings", height=14, style="Dark.Treeview",
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set
        )
        scroll_y.config(command=self.tree.yview)
        scroll_x.config(command=self.tree.xview)

        for col, width, anchor in (
            ("Movimiento", 100, "center"),
            ("Producto",   180, "w"),
            ("Kilos",       90, "e"),
            ("Cajas",       90, "e"),
            ("Unidades",    90, "e"),
            ("Monto",      110, "e"),
            ("Tipo",       120, "center"),
            ("Motivo",     320, "w"),
            ("Fecha",      150, "center"),
        ):
            self.tree.heading(col, text=col)  # el command se añade en _setup_sorting
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("Producto", "Motivo")))

        self.tree.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        scroll_x.pack(fill="x", padx=8, pady=(0, 6))
        scroll_y.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")

        # Activar ordenamiento por columnas
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

        # Foco inicial en producto de entradas
        self.after_idle(lambda: self.combo_producto.focus_set())

    # ---------------------------
    # Carga / mostrar
    # ---------------------------
    def mostrar(self):
        self.cargar_productos()
        self.cargar_movimientos()

    def _limpiar_filtro_busqueda(self, event=None):
        self.entry_busqueda.delete(0, tk.END)
        self.cargar_movimientos()

    def cargar_productos(self):
        """Carga listado de productos al par de combobox y actualiza info/peso del seleccionado."""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, nombre FROM productos ORDER BY nombre COLLATE NOCASE")
                rows = cur.fetchall()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los productos.\n{e}")
            return

        self.productos = {row[1]: row[0] for row in rows}  # nombre -> id
        nombres = list(self.productos.keys())
        self.combo_producto["values"] = nombres
        self.combo_producto_merma["values"] = nombres
        if nombres:
            if not self.combo_producto.get():
                self.combo_producto.current(0)
            if not self.combo_producto_merma.get():
                self.combo_producto_merma.current(0)
            # Actualizar info del seleccionado
            self._actualizar_info_producto(self.combo_producto.get())
            self._actualizar_info_producto_merma(self.combo_producto_merma.get())

    # ---------------------------
    # Eventos de selección
    # ---------------------------
    def _on_producto_change(self, event=None):
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
            # Prefill del peso/caja
            self.peso_entry.delete(0, tk.END)
            if peso > 0:
                self.peso_entry.insert(0, f"{redondear_dos_decimales(peso):.2f}")
            # Info
            self.info_label.config(
                text=f"Kilos: {redondear_dos_decimales(kilos):.2f} | Cajas: {redondear_dos_decimales(cajas):.2f} | "
                     f"Unidades: {unidades} | Peso/caja: {redondear_dos_decimales(peso):.2f} kg"
            )
        except Exception:
            pass

    def _on_producto_change_merma(self, event=None):
        self._actualizar_info_producto_merma(self.combo_producto_merma.get())

    def _actualizar_info_producto_merma(self, nombre: str):
        # Reutilizamos el mismo texto de info para entradas; es un resumen útil también para mermas
        self._actualizar_info_producto(nombre)

    # ---------------------------
    # Acciones: Entradas
    # ---------------------------
    def registrar_entrada(self):
        """Inserta una entrada, actualiza stock y registra gasto 'Compra' (si aplica)."""
        nombre = self.combo_producto.get().strip()
        if not nombre:
            messagebox.showwarning("Falta producto", "Selecciona un producto.")
            return

        try:
            kilos         = to_float(self.kilos_entry.get() or 0, permitir_cero=True)
            num_cajas     = to_float(self.cajas_entry.get() or 0, permitir_cero=True)
            peso_caja     = to_float(self.peso_entry.get() or 0, permitir_cero=True)
            unidades      = to_int(self.unidades_entry.get() or 0, permitir_cero=True)
            monto_compra  = to_float(self.monto_compra_entry.get() or 0, permitir_cero=True)
        except ValueError:
            messagebox.showerror("Error", "Valores inválidos. Revisa kilos/cajas/peso/unidades/monto.")
            return

        if kilos < 0 or num_cajas < 0 or peso_caja < 0 or unidades < 0 or monto_compra < 0:
            messagebox.showerror("Error", "Los valores no pueden ser negativos.")
            return

        # Autocálculo kilos<->cajas si falta uno y hay peso_caja
        if peso_caja > 0:
            if kilos <= 0 and num_cajas > 0:
                kilos = redondear_dos_decimales(num_cajas * peso_caja)
                self.kilos_entry.delete(0, tk.END)
                self.kilos_entry.insert(0, f"{kilos:.2f}")
            elif num_cajas <= 0 and kilos > 0:
                num_cajas = redondear_dos_decimales(kilos / peso_caja)
                self.cajas_entry.delete(0, tk.END)
                self.cajas_entry.insert(0, f"{num_cajas:.2f}")

        # Al menos una cantidad > 0
        if (kilos <= 0) and (num_cajas <= 0) and (unidades <= 0):
            messagebox.showerror("Error", "Ingresa kilos, cajas o unidades mayores a 0.")
            return

        tipo   = (self.tipo_combo.get().strip() or "Compra")
        motivo = self.motivo_entry.get().strip() or "Entrada sin motivo"
        producto_id = self.productos.get(nombre)
        if not producto_id:
            messagebox.showerror("Error", "Producto no encontrado.")
            return
        fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            with get_connection() as conn:
                cur = conn.cursor()

                # Inserta movimiento en inventario
                cur.execute("""
                    INSERT INTO inventario (producto_id, kilos, num_cajas, unidades, tipo, motivo, fecha)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (producto_id, float(kilos), float(num_cajas), int(unidades), tipo, motivo, fecha_str))

                # Actualiza stock
                cur.execute("""
                    UPDATE productos
                    SET kilos = kilos + ?, num_cajas = num_cajas + ?, unidades = unidades + ?, peso_caja = ?
                    WHERE id = ?
                """, (float(kilos), float(num_cajas), int(unidades), float(peso_caja), producto_id))

                # Registrar gasto si aplica
                if tipo.lower() == "compra" and monto_compra > 0:
                    cur.execute("""
                        INSERT INTO gastos (tipo, monto, descripcion, fecha)
                        VALUES (?, ?, ?, ?)
                    """, ("Compra", float(monto_compra), nombre, fecha_str))

            messagebox.showinfo("Éxito", "Entrada registrada.")
            # Limpiar campos
            for e in (
                self.kilos_entry, self.cajas_entry, self.peso_entry,
                self.unidades_entry, self.monto_compra_entry, self.motivo_entry
            ):
                e.delete(0, tk.END)
            # Refrescar listados e info
            self.cargar_movimientos()
            self._actualizar_info_producto(nombre)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la entrada.\n{e}")

    # ---------------------------
    # Acciones: Mermas
    # ---------------------------
    def registrar_merma(self):
        """Inserta una merma y descuenta stock (kilos, cajas y unidades)."""
        nombre = self.combo_producto_merma.get().strip()
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

        # Cargar stock y peso_caja del producto
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT kilos, num_cajas, unidades, peso_caja FROM productos WHERE id = ?", (self.productos.get(nombre),))
                row = cur.fetchone()
            if not row:
                messagebox.showerror("Error", "Producto no encontrado.")
                return
            stock_kilos    = float(row[0] or 0.0)
            stock_cajas    = float(row[1] or 0.0)
            stock_unidades = int(row[2] or 0)
            peso_caja      = float(row[3] or 0.0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo leer el stock del producto.\n{e}")
            return

        # Autocálculo kilos<->cajas si falta uno y hay peso_caja
        if peso_caja > 0:
            if kilos <= 0 and num_cajas > 0:
                kilos = redondear_dos_decimales(num_cajas * peso_caja)
                self.merma_kilos_entry.delete(0, tk.END)
                self.merma_kilos_entry.insert(0, f"{kilos:.2f}")
            elif num_cajas <= 0 and kilos > 0:
                num_cajas = redondear_dos_decimales(kilos / peso_caja)
                self.merma_cajas_entry.delete(0, tk.END)
                self.merma_cajas_entry.insert(0, f"{num_cajas:.2f}")

        if (kilos <= 0) and (num_cajas <= 0) and (unidades <= 0):
            messagebox.showerror("Error", "Ingresa al menos un valor mayor a 0.")
            return

        # Validar stock suficiente
        if kilos > stock_kilos:
            messagebox.showerror("Stock insuficiente", f"Kilos disponibles: {redondear_dos_decimales(stock_kilos)}")
            return
        if num_cajas > stock_cajas:
            messagebox.showerror("Stock insuficiente", f"Cajas disponibles: {redondear_dos_decimales(stock_cajas)}")
            return
        if unidades > stock_unidades:
            messagebox.showerror("Stock insuficiente", f"Unidades disponibles: {stock_unidades}")
            return

        motivo = self.motivo_merma_entry.get().strip() or "Merma sin motivo"
        producto_id = self.productos.get(nombre)

        try:
            with get_connection() as conn:
                cur = conn.cursor()

                # Insertar merma
                cur.execute("""
                    INSERT INTO mermas (producto_id, kilos, num_cajas, unidades, motivo, fecha)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (producto_id, float(kilos), float(num_cajas), int(unidades), motivo,
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

                # Descontar stock
                cur.execute("""
                    UPDATE productos
                    SET kilos = kilos - ?, num_cajas = num_cajas - ?, unidades = unidades - ?
                    WHERE id = ?
                """, (float(kilos), float(num_cajas), int(unidades), producto_id))

            messagebox.showinfo("Éxito", "Merma registrada.")
            for e in (self.merma_kilos_entry, self.merma_cajas_entry, self.merma_unidades_entry, self.motivo_merma_entry):
                e.delete(0, tk.END)
            self.cargar_movimientos()
            self._actualizar_info_producto(nombre)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la merma.\n{e}")

    # ---------------------------
    # Listado y búsqueda
    # ---------------------------
    def cargar_movimientos(self, filtro: str = ""):
        """
        Carga la tabla combinando:
          - ENTRADAS desde 'inventario' + LEFT JOIN 'gastos' (tipo='Compra') para monto
          - MERMAS   desde 'mermas' (monto = vacío)
        Filtra por nombre de producto, motivo y TIPO (inventario).
        """
        self.tree.delete(*self.tree.get_children())

        try:
            with get_connection() as conn:
                cur = conn.cursor()

                if filtro:
                    like = f"%{filtro}%"
                    # Entradas con monto desde 'gastos' (coinciden en fecha y descripción=producto)
                    cur.execute("""
                        SELECT 'Entrada' AS mov, p.nombre, i.kilos, i.num_cajas, i.unidades,
                               COALESCE(g.monto, 0) AS monto, i.tipo, i.motivo, i.fecha
                        FROM inventario i
                        JOIN productos p ON p.id = i.producto_id
                        LEFT JOIN gastos g
                          ON g.tipo = 'Compra' AND g.descripcion = p.nombre AND g.fecha = i.fecha
                        WHERE p.nombre LIKE ? OR i.motivo LIKE ? OR IFNULL(i.tipo,'') LIKE ?
                    """, (like, like, like))
                    entradas = cur.fetchall()

                    # Mermas (monto vacío)
                    cur.execute("""
                        SELECT 'Merma' AS mov, p.nombre, m.kilos, m.num_cajas, m.unidades,
                               NULL AS monto, '' AS tipo, m.motivo, m.fecha
                        FROM mermas m
                        JOIN productos p ON p.id = m.producto_id
                        WHERE p.nombre LIKE ? OR m.motivo LIKE ?
                    """, (like, like))
                    mermas = cur.fetchall()

                else:
                    cur.execute("""
                        SELECT 'Entrada' AS mov, p.nombre, i.kilos, i.num_cajas, i.unidades,
                               COALESCE(g.monto, 0) AS monto, i.tipo, i.motivo, i.fecha
                        FROM inventario i
                        JOIN productos p ON p.id = i.producto_id
                        LEFT JOIN gastos g
                          ON g.tipo = 'Compra' AND g.descripcion = p.nombre AND g.fecha = i.fecha
                    """)
                    entradas = cur.fetchall()

                    cur.execute("""
                        SELECT 'Merma' AS mov, p.nombre, m.kilos, m.num_cajas, m.unidades,
                               NULL AS monto, '' AS tipo, m.motivo, m.fecha
                        FROM mermas m
                        JOIN productos p ON p.id = m.producto_id
                    """)
                    mermas = cur.fetchall()

            # Mezcla y ordena por fecha DESC (ISO ordena bien como string)
            filas = entradas + mermas
            filas.sort(key=lambda r: r[8], reverse=True)

            for mov, nombre, kilos, cajas, unidades, monto, tipo, motivo, fecha in filas:
                self.tree.insert("", "end", values=(
                    mov,
                    nombre,
                    f"{redondear_dos_decimales(kilos):.2f}",
                    f"{redondear_dos_decimales(cajas):.2f}",
                    int(unidades or 0),
                    (formato_moneda(monto) if monto is not None else ""),
                    (tipo or ""),
                    (motivo or ""),
                    formatear_fecha(fecha)
                ))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los movimientos.\n{e}")

    # ---------------------------
    # Ordenamiento por columnas
    # ---------------------------
    def _setup_sorting(self, tree: ttk.Treeview, columnas, tipos):
        tree._sort_state = {}  # col -> bool(reverse)
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
                from datetime import datetime as _dt
                for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return _dt.strptime(s, fmt)
                    except Exception:
                        pass
                return s  # fallback string
            return s.lower()

        def sort_by(col):
            reverse = not tree._sort_state.get(col, False)
            data = []
            idx = col_index[col]
            for iid in tree.get_children(""):
                vals = self.tree.item(iid, "values")
                v = vals[idx] if idx < len(vals) else ""
                data.append((parse_value(col, v), iid))
            data.sort(key=lambda x: x[0], reverse=reverse)
            for n, (_, iid) in enumerate(data):
                tree.move(iid, "", n)
            tree._sort_state[col] = reverse

        # Añadir command a cada encabezado
        for c in columnas:
            tree.heading(c, text=c, command=lambda cc=c: sort_by(cc))


def mostrar(frame_contenido):
    """Función de entrada usada por main.py para montar la vista."""
    for widget in frame_contenido.winfo_children():
        widget.destroy()
    frame = InventarioFrame(frame_contenido)
    frame.pack(fill="both", expand=True)
