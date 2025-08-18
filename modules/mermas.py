# modules/mermas.py
# -----------------------------------------------------------
# Sistema de Comercio — Módulo de Mermas
#
# USO / FLUJO / FUNCIONALIDAD
# -----------------------------------------------------------
# - Registrar mermas (pérdidas/daños) por producto:
#     * Kilos (REAL, 2 decimales)
#     * Núm. de cajas (REAL, 2 decimales)
#     * Unidades (INTEGER)
#     * Motivo
# - Valida stock suficiente (kilos, cajas y unidades) antes de descontar.
# - Autocálculo: si peso_caja > 0 y se ingresa solo kilos o solo cajas,
#   se calcula el otro (kilos = cajas * peso_caja; cajas = kilos / peso_caja).
# - Actualiza existencias en 'productos':
#     productos.kilos     -= kilos_merma
#     productos.num_cajas -= num_cajas_merma
#     productos.unidades  -= unidades_merma
# - Listado de mermas (más recientes primero) con ordenamiento por encabezados:
#     Producto | Kilos | Cajas | Unidades | Motivo | Fecha
#
# MEJORAS (UX)
# -----------------------------------------------------------
# - Enter para confirmar también desde el combobox de Producto.
# - Foco inicial en Producto.
# - Esc limpia el formulario (kilos/cajas/unidades/motivo) y devuelve el foco.
# -----------------------------------------------------------

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from db.database import get_connection
from ui.helpers import (
    redondear_dos_decimales,
    formatear_fecha,
    to_float,
    to_int,
    adjuntar_validador_2_decimales,
)

# -----------------------------------------------------------
# Paleta oscura (consistente con la app)
# -----------------------------------------------------------
COLOR_BG        = "#2C3E50"  # Fondo general
COLOR_PANEL     = "#34495E"  # Paneles / contenedores
COLOR_TEXT      = "#ECF0F1"  # Texto
COLOR_PRIMARY   = "#3498DB"  # Botones principales
COLOR_ENTRY_BG  = "#3B4A5A"  # Entradas
COLOR_ENTRY_FG  = COLOR_TEXT
COLOR_BORDER    = "#22313F"
COLOR_SEL_BG    = "#1ABC9C"  # Selección en tablas/listas


class MermasFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master, bg=COLOR_BG)
        self.productos = {}  # nombre -> id

        self._style = ttk.Style()
        self._aplicar_tema_ttk()

        self.crear_interfaz()
        self.cargar_productos()
        self.cargar_mermas()

        # Esc: limpiar formulario
        self.bind("<Escape>", self._limpiar_formulario)
        # Foco inicial
        self.after_idle(lambda: self.producto_combo.focus_set())

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

    def _btn(self, parent, text, bgc, cmd, **grid):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bgc, fg=COLOR_TEXT, activebackground=bgc,
                      activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")
        if grid:
            b.grid(**grid)
        return b

    def _combobox(self, parent, **grid):
        cb = ttk.Combobox(parent, state="readonly", style="Dark.TCombobox", **grid)
        cb.configure(postcommand=lambda c=cb: self._estilizar_dropdown(c))
        return cb

    def _estilizar_dropdown(self, combobox: ttk.Combobox):
        """Aplica tema oscuro al listbox del desplegable."""
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
        form_panel = self._panel(self, pady=8, padx=8, fill="x")
        grid = tk.Frame(form_panel, bg=COLOR_PANEL)
        grid.pack(fill="x", padx=8, pady=6)

        # Producto
        self._lbl(grid, "Producto:", row=0, column=0, sticky="e", padx=4, pady=2)
        self.producto_combo = self._combobox(grid, width=32)
        self.producto_combo.grid(row=0, column=1, sticky="we", padx=4, pady=2)  # responsive
        grid.grid_columnconfigure(1, weight=1)  # la columna del combobox se expande
        self.producto_combo.bind("<<ComboboxSelected>>", self._on_producto_change)
        # NUEVO: Enter en el combobox también registra la merma
        self.producto_combo.bind("<Return>", lambda e: self.registrar_merma())

        # Kilos / Cajas / Unidades
        self._lbl(grid, "Kilos (-):", row=1, column=0, sticky="e", padx=4, pady=2)
        self.kilos_entry = self._entry(grid, width=12, row=1, column=1, sticky="w", padx=4, pady=2)

        self._lbl(grid, "Núm. Cajas (-):", row=1, column=2, sticky="e", padx=4, pady=2)
        self.cajas_entry = self._entry(grid, width=12, row=1, column=3, sticky="w", padx=4, pady=2)

        self._lbl(grid, "Unidades (-):", row=1, column=4, sticky="e", padx=4, pady=2)
        self.unidades_entry = self._entry(grid, width=12, row=1, column=5, sticky="w", padx=4, pady=2)

        # Motivo
        self._lbl(grid, "Motivo:", row=2, column=0, sticky="e", padx=4, pady=2)
        self.motivo_entry = self._entry(grid, width=48, row=2, column=1, columnspan=5, sticky="we", padx=4, pady=2)
        grid.grid_columnconfigure(1, weight=1)  # asegura expansión del motivo también

        # Validadores de 2 decimales (coma/punto) para kilos/cajas
        for e in (self.kilos_entry, self.cajas_entry):
            adjuntar_validador_2_decimales(e, permitir_vacio=True)

        # Atajos Enter
        self.kilos_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.cajas_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.unidades_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.motivo_entry.bind("<Return>", lambda e: self.registrar_merma())

        # Botón
        self._btn(grid, "Registrar Merma", COLOR_PRIMARY, self.registrar_merma,
                  row=3, column=0, columnspan=6, pady=10)

        # Info stock / peso
        self.info_label = tk.Label(
            form_panel,
            text="Kilos: 0.00 | Cajas: 0.00 | Unidades: 0 | Peso/caja: 0.00 kg",
            bg=COLOR_PANEL, fg=COLOR_TEXT, anchor="w"
        )
        self.info_label.pack(fill="x", padx=16, pady=(0, 6))

        # --- Tabla de mermas ---
        tabla_panel = self._panel(self, pady=6, padx=8, fill="both", expand=True)

        columnas = ("Producto", "Kilos", "Cajas", "Unidades", "Motivo", "Fecha")

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
            ("Producto", 200, "w"),
            ("Kilos", 100, "e"),
            ("Cajas", 100, "e"),
            ("Unidades", 100, "e"),
            ("Motivo", 320, "w"),
            ("Fecha", 150, "center"),
        ):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("Producto", "Motivo")))

        self.tree.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        scroll_x.pack(fill="x", padx=8, pady=(0, 6))
        scroll_y.place(relx=1.0, rely=0.0, relheight=1.0, anchor="ne")

        # Ordenamiento por encabezados
        self._setup_sorting(
            tree=self.tree,
            columnas=columnas,
            tipos={
                "Producto": "str",
                "Kilos": "float",
                "Cajas": "float",
                "Unidades": "int",
                "Motivo": "str",
                "Fecha": "date",
            },
        )

    # ---------------------------
    # Datos / selección
    # ---------------------------
    def cargar_productos(self):
        """Carga productos (id, nombre) para el combobox."""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, nombre FROM productos ORDER BY nombre COLLATE NOCASE")
                productos = cur.fetchall()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los productos.\n{e}")
            return

        self.productos = {p[1]: int(p[0]) for p in productos}  # nombre -> id
        nombres = [p[1] for p in productos]
        self.producto_combo["values"] = nombres
        if nombres:
            self.producto_combo.current(0)
            self._actualizar_info_producto(self.producto_combo.get())

    def _on_producto_change(self, event=None):
        self._actualizar_info_producto(self.producto_combo.get())

    def _actualizar_info_producto(self, nombre: str):
        if not nombre:
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT kilos, num_cajas, unidades, peso_caja FROM productos WHERE nombre = ?",
                    (nombre,)
                )
                row = cur.fetchone()
            if not row:
                return
            kilos, cajas, unidades, peso = (
                float(row[0] or 0), float(row[1] or 0), int(row[2] or 0), float(row[3] or 0)
            )
            self.info_label.config(
                text=f"Kilos: {redondear_dos_decimales(kilos):.2f} | "
                     f"Cajas: {redondear_dos_decimales(cajas):.2f} | "
                     f"Unidades: {unidades} | "
                     f"Peso/caja: {redondear_dos_decimales(peso):.2f} kg"
            )
        except Exception:
            pass

    # ---------------------------
    # Registro de merma
    # ---------------------------
    def registrar_merma(self):
        """Inserta una merma (kilos/cajas/unidades) y descuenta stock."""
        nombre_producto = self.producto_combo.get().strip()
        if not nombre_producto:
            messagebox.showerror("Error", "Selecciona un producto.")
            return

        # Convertir entradas
        try:
            kilos_txt = (self.kilos_entry.get() or "").strip()
            cajas_txt = (self.cajas_entry.get() or "").strip()
            unidades_txt = (self.unidades_entry.get() or "").strip()

            kilos     = to_float(kilos_txt or 0, permitir_cero=True)
            num_cajas = to_float(cajas_txt or 0, permitir_cero=True)
            unidades  = to_int(unidades_txt or 0, permitir_cero=True)
        except ValueError:
            messagebox.showerror("Error", "Valores inválidos. Revisa kilos/cajas/unidades (máx. 2 decimales donde aplica).")
            return

        if kilos < 0 or num_cajas < 0 or unidades < 0:
            messagebox.showerror("Error", "Los valores no pueden ser negativos.")
            return

        motivo = (self.motivo_entry.get().strip() or "Merma sin motivo")

        producto_id = self.productos.get(nombre_producto)
        if not producto_id:
            messagebox.showerror("Error", "Producto no válido.")
            return

        # Leer stock y peso_caja
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT kilos, num_cajas, unidades, peso_caja FROM productos WHERE id = ?", (producto_id,))
                row = cur.fetchone()
            if not row:
                messagebox.showerror("Error", "Producto no encontrado en la base de datos.")
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
                self.kilos_entry.delete(0, tk.END)
                self.kilos_entry.insert(0, f"{kilos:.2f}")
            elif num_cajas <= 0 and kilos > 0:
                num_cajas = redondear_dos_decimales(kilos / peso_caja)
                self.cajas_entry.delete(0, tk.END)
                self.cajas_entry.insert(0, f"{num_cajas:.2f}")

        if (kilos <= 0) and (num_cajas <= 0) and (unidades <= 0):
            messagebox.showerror("Error", "Ingresa al menos un valor mayor a 0 (kilos, cajas o unidades).")
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

        # Ejecutar operación
        try:
            fecha_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with get_connection() as conn:
                cur = conn.cursor()

                # Insertar merma
                cur.execute("""
                    INSERT INTO mermas (producto_id, kilos, num_cajas, unidades, motivo, fecha)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (producto_id, float(kilos), float(num_cajas), int(unidades), motivo, fecha_str))

                # Actualizar stock
                cur.execute("""
                    UPDATE productos
                    SET kilos = kilos - ?, num_cajas = num_cajas - ?, unidades = unidades - ?
                    WHERE id = ?
                """, (float(kilos), float(num_cajas), int(unidades), producto_id))

            messagebox.showinfo(
                "Éxito",
                "Merma registrada correctamente."
            )

            # Limpiar campos
            for e in (self.kilos_entry, self.cajas_entry, self.unidades_entry, self.motivo_entry):
                e.delete(0, tk.END)

            # Refrescar tabla e info
            self.cargar_mermas()
            self._actualizar_info_producto(nombre_producto)

        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la merma.\n{e}")

    # ---------------------------
    # Listado
    # ---------------------------
    def cargar_mermas(self):
        """Carga la tabla de mermas más recientes primero."""
        self.tree.delete(*self.tree.get_children())
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT p.nombre, m.kilos, m.num_cajas, m.unidades, m.motivo, m.fecha
                    FROM mermas m
                    JOIN productos p ON m.producto_id = p.id
                    ORDER BY m.fecha DESC
                """)
                for nombre, kilos, cajas, unidades, motivo, fecha in cur.fetchall():
                    self.tree.insert("", "end", values=(
                        nombre,
                        f"{redondear_dos_decimales(kilos):.2f}",
                        f"{redondear_dos_decimales(cajas):.2f}",
                        int(unidades or 0),
                        motivo or "",
                        formatear_fecha(fecha)
                    ))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar las mermas.\n{e}")

    # ---------------------------
    # Ordenamiento por columnas
    # ---------------------------
    def _setup_sorting(self, tree: ttk.Treeview, columnas, tipos):
        """
        Añade ordenamiento por encabezados.
        tipos: dict nombre_col -> 'int'|'float'|'money'|'date'|'str'
        """
        tree._sort_state = {}  # col -> bool(reverse)
        col_index = {c: i for i, c in enumerate(columnas)}

        def parse_value(col, val):
            t = tipos.get(col, "str")
            s = str(val).strip()

            if t == "int":
                try:
                    return int(float(s.replace(",", "")))
                except Exception:
                    return 0
            if t == "float":
                try:
                    return float(s.replace(",", ""))
                except Exception:
                    return 0.0
            if t == "money":
                try:
                    return float(s.replace("$", "").replace(",", ""))
                except Exception:
                    return 0.0
            if t == "date":
                from datetime import datetime as _dt
                # Intentar múltiples formatos comunes en el sistema
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        return _dt.strptime(s, fmt)
                    except Exception:
                        pass
                return s
            # 'str'
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

        # Asignar comando a cada encabezado
        for c in columnas:
            tree.heading(c, text=c, command=lambda cc=c: sort_by(cc))

    # ---------------------------
    # Utilidades UX
    # ---------------------------
    def _limpiar_formulario(self, event=None):
        """Limpia campos de captura y regresa el foco al Producto."""
        for e in (self.kilos_entry, self.cajas_entry, self.unidades_entry, self.motivo_entry):
            e.delete(0, tk.END)
        try:
            self.producto_combo.focus_set()
        except Exception:
            pass


def mostrar(frame_contenido):
    """Punto de entrada usado por main.py para montar la vista."""
    for widget in frame_contenido.winfo_children():
        widget.destroy()
    frame = MermasFrame(frame_contenido)
    frame.pack(fill="both", expand=True)
