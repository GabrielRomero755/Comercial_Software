# modules/gastos.py
# -----------------------------------------------------------
# Gestión de Gastos
#
# Funcionalidad:
#   - Catálogo de tipos de gasto (CRUD: alta desde modal simple).
#   - Registro de gastos: tipo, monto, descripción, fecha (auto u opcional manual).
#   - Asociación opcional a Empleado y/o Cliente (si el esquema lo soporta).
#   - Búsqueda dinámica (tipo/descripcion/empleado/cliente).
#   - Edición y eliminación de gastos.
#   - Listado con monto formateado y ordenamiento por encabezados.
#
# Mejoras UX:
#   - Validador de 2 decimales (admite coma o punto).
#   - Calendario en modo LIBRE (todas las fechas activas).
#   - ESC cierra ventanas emergentes; ENTER confirma acciones.
#   - Supr elimina seleccionado; doble clic edita.
#   - Reglas: si tipo == 'Salarios' -> empleado requerido.
#
# Integración con BD (opcional según migraciones):
#   - Tabla empleados(id, nombre, telefono).
#   - gastos.empleado_id  (NULL) → empleados.id
#   - gastos.cliente_id   (NULL) → clientes.id
#   - Si columnas/tablas no existen, los controles se ocultan y el módulo
#     funciona en modo básico.
# -----------------------------------------------------------

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from db.database import get_connection
from modules.calendar_widget import CalendarioWidget
from ui.helpers import to_float, formato_moneda, es_fecha_ok, normalizar_fecha

# Tema centralizado
try:
    from ui.theme import THEME
except Exception:
    THEME = {}

COLOR_BG        = THEME.get("bg", "#2C3E50")
COLOR_PANEL     = THEME.get("panel", "#34495E")
COLOR_TEXT      = THEME.get("text", "#ECF0F1")
COLOR_PRIMARY   = THEME.get("primary", "#3498DB")
COLOR_SUCCESS   = THEME.get("success", "#2ECC71")
COLOR_DANGER    = THEME.get("danger", "#E74C3C")
COLOR_ENTRY_BG  = THEME.get("entry_bg", "#3B4A5A")
COLOR_ENTRY_FG  = THEME.get("entry_fg", COLOR_TEXT)
COLOR_SEL_BG    = THEME.get("selection", "#1ABC9C")
COLOR_BORDER    = THEME.get("border", "#22313F")


class GastosFrame(tk.Frame):
    # Flags dinámicos (según esquema)
    _has_empleados: bool = False
    _gastos_has_empleado_fk: bool = False
    _gastos_has_cliente_fk: bool = False

    def __init__(self, master=None):
        super().__init__(master, bg=COLOR_BG)

        # Layout raíz (grid)
        # 0=form, 1=busqueda, 2=tabla, 3=acciones
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self._style = ttk.Style()
        self._aplicar_tema_ttk()
        self._detectar_esquema()

        self.crear_interfaz()
        self.cargar_tipos_gasto()
        self._cargar_empleados()
        self._cargar_clientes()
        self.cargar_gastos()

        # Atajos generales del frame
        try:
            # Enter registra desde cualquier campo del formulario principal
            for w in (self.tipo_combo, self.monto_entry, self.descripcion_entry, self.fecha_entry):
                w.bind("<Return>", lambda e: self.registrar_gasto())
            if self._empleado_combo is not None:
                self._empleado_combo.bind("<Return>", lambda e: self.registrar_gasto())
            if self._cliente_combo is not None:
                self._cliente_combo.bind("<Return>", lambda e: self.registrar_gasto())

            # Supr elimina en la tabla
            self.tree.bind("<Delete>", lambda e: self.eliminar_gasto())
            # Doble clic edita
            self.tree.bind("<Double-1>", lambda e: self.editar_gasto())
        except Exception:
            pass

    # -------------------------------------------------------
    # Esquema dinámico
    # -------------------------------------------------------
    def _detectar_esquema(self):
        """Detecta presencia de tablas/columnas opcionales para habilitar UI avanzada."""
        try:
            with get_connection() as conn:
                # Tabla empleados
                r = conn.execute("""
                    SELECT 1 FROM sqlite_master WHERE type='table' AND name='empleados' LIMIT 1
                """).fetchone()
                self._has_empleados = bool(r)

                # Columnas opcionales en gastos
                cols = {row[1] for row in conn.execute("PRAGMA table_info(gastos)").fetchall()}
                self._gastos_has_empleado_fk = "empleado_id" in cols
                self._gastos_has_cliente_fk = "cliente_id" in cols
        except Exception:
            self._has_empleados = False
            self._gastos_has_empleado_fk = False
            self._gastos_has_cliente_fk = False

    # -------------------------------------------------------
    # Estilos
    # -------------------------------------------------------
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
        self._style.map("Dark.Treeview.Heading", background=[("active", COLOR_PRIMARY)])

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
            fieldbackground=[("readonly", COLOR_ENTRY_BG), ("!readonly", COLOR_ENTRY_BG)],
            foreground=[("readonly", COLOR_TEXT), ("!readonly", COLOR_TEXT)],
            background=[("readonly", COLOR_PANEL), ("!readonly", COLOR_PANEL)],
            arrowcolor=[("readonly", COLOR_TEXT), ("!readonly", COLOR_TEXT)],
        )

    def _panel(self, parent):
        return tk.Frame(parent, bg=COLOR_PANEL, bd=0, highlightthickness=0)

    def _lbl(self, parent, text, **grid):
        w = tk.Label(parent, text=text, bg=parent["bg"], fg=COLOR_TEXT)
        if grid:
            w.grid(**grid)
        return w

    def _entry(self, parent, width=16, **grid):
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

    # ---------------------------
    # Validadores
    # ---------------------------
    @staticmethod
    def _validate_decimal(proposed: str) -> bool:
        """
        Acepta '', '10', '10.', '10.5', '10,5', '10.50', '.5', ',5' con máximo 2 decimales.
        (Permite ',' o '.' como separador decimal durante la edición).
        """
        if proposed == "":
            return True
        import re
        s = (proposed or "").strip()
        if s in (".", ","):
            return True
        return re.fullmatch(r"(\d+([.,]\d{0,2})?|[.,]\d{0,2})", s) is not None

    # -------------------------------------------------------
    # UI
    # -------------------------------------------------------
    def crear_interfaz(self):
        # ---------- Formulario (fila 0) ----------
        form_frame = self._panel(self)
        form_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        # columnas internas
        for c in range(8):
            form_frame.grid_columnconfigure(c, weight=(1 if c in (1, 3, 5, 7) else 0))

        # Tipo + catálogo
        self._lbl(form_frame, "Tipo de Gasto:", row=0, column=0, sticky="e", padx=8, pady=6)
        self.tipo_combo = ttk.Combobox(
            form_frame, state="readonly", width=28, style="Dark.TCombobox",
            postcommand=lambda: self._estilizar_combobox_dropdown(self.tipo_combo)
        )
        self.tipo_combo.grid(row=0, column=1, sticky="we", padx=4, pady=6)
        self._btn(form_frame, "Añadir tipo", COLOR_PRIMARY, self.abrir_ventana_nuevo_tipo,
                  row=0, column=2, padx=8, pady=6, sticky="w")

        # Monto + Descripción
        self._lbl(form_frame, "Monto:", row=1, column=0, sticky="e", padx=8, pady=6)
        vcmd = (self.register(self._validate_decimal), "%P")
        self.monto_entry = self._entry(form_frame, width=16, row=1, column=1, sticky="we", padx=4, pady=6)
        self.monto_entry.configure(validate="key", validatecommand=vcmd)

        self._lbl(form_frame, "Descripción (opcional):", row=1, column=2, sticky="e", padx=8, pady=6)
        self.descripcion_entry = self._entry(form_frame, width=42, row=1, column=3, padx=4, pady=6, sticky="we")

        # Fecha
        self._lbl(form_frame, "Fecha (YYYY-MM-DD):", row=0, column=3, sticky="e", padx=8, pady=6)
        self.fecha_entry = self._entry(form_frame, width=14, row=0, column=4, padx=4, pady=6, sticky="w")
        self._btn(form_frame, "📅", COLOR_PRIMARY, lambda: self._abrir_calendario(self.fecha_entry),
                  row=0, column=5, padx=4, pady=6, sticky="w")

        # Empleado (opcional / requerido si tipo == Salarios)
        self._empleado_combo: Optional[ttk.Combobox] = None
        self._cliente_combo: Optional[ttk.Combobox] = None

        col_base = 0
        if self._has_empleados and self._gastos_has_empleado_fk:
            self._lbl(form_frame, "Empleado:", row=2, column=0, sticky="e", padx=8, pady=6)
            self._empleado_combo = ttk.Combobox(
                form_frame, state="readonly", width=28, style="Dark.TCombobox",
                postcommand=lambda: self._estilizar_combobox_dropdown(self._empleado_combo)
            )
            self._empleado_combo.grid(row=2, column=1, sticky="we", padx=4, pady=6)
            self._btn(form_frame, "Gestionar Empleados", COLOR_PRIMARY, self._abrir_crud_empleados,
                      row=2, column=2, padx=8, pady=6, sticky="w")
            col_base = 3  # desplazamos cliente a la derecha

        # Cliente (opcional)
        if self._gastos_has_cliente_fk:
            self._lbl(form_frame, "Cliente:", row=2, column=col_base, sticky="e", padx=8, pady=6)
            self._cliente_combo = ttk.Combobox(
                form_frame, state="readonly", width=28, style="Dark.TCombobox",
                postcommand=lambda: self._estilizar_combobox_dropdown(self._cliente_combo)
            )
            self._cliente_combo.grid(row=2, column=col_base + 1, sticky="we", padx=4, pady=6)
            self._btn(form_frame, "Gestionar Clientes", COLOR_PRIMARY, self._abrir_crud_clientes,
                      row=2, column=col_base + 2, padx=8, pady=6, sticky="w")

        self._btn(form_frame, "Registrar Gasto", COLOR_SUCCESS, self.registrar_gasto,
                  row=3, column=0, columnspan=8, pady=10)

        # ---------- Búsqueda (fila 1) ----------
        search_frame = self._panel(self)
        search_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 0))
        search_frame.grid_columnconfigure(1, weight=1)

        self._lbl(search_frame, "Buscar (tipo/descr./empleado/cliente):", row=0, column=0, sticky="e", padx=8, pady=6)
        self.buscar_entry = self._entry(search_frame, width=36, row=0, column=1, padx=4, pady=6, sticky="we")
        self.buscar_entry.bind("<KeyRelease>", self.filtrar_gastos)

        # ---------- Tabla (fila 2) ----------
        tabla_panel = self._panel(self)
        tabla_panel.grid(row=2, column=0, sticky="nsew", padx=10, pady=(6, 6))
        tabla_panel.grid_rowconfigure(0, weight=1)
        tabla_panel.grid_columnconfigure(0, weight=1)

        columnas = ["ID", "Tipo", "Monto", "Descripción", "Fecha"]
        if self._gastos_has_empleado_fk:
            columnas.append("Empleado")
        if self._gastos_has_cliente_fk:
            columnas.append("Cliente")
        columnas = tuple(columnas)

        scroll_y = ttk.Scrollbar(tabla_panel, orient="vertical")
        scroll_x = ttk.Scrollbar(tabla_panel, orient="horizontal")

        self.tree = ttk.Treeview(
            tabla_panel, columns=columnas, show="headings", style="Dark.Treeview",
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set
        )
        scroll_y.config(command=self.tree.yview)
        scroll_x.config(command=self.tree.xview)

        # Anchuras
        widths = {
            "ID": 70, "Tipo": 160, "Monto": 110, "Descripción": 320, "Fecha": 140,
            "Empleado": 180, "Cliente": 200
        }
        anchors = {
            "ID": "center", "Tipo": "w", "Monto": "e", "Descripción": "w", "Fecha": "center",
            "Empleado": "w", "Cliente": "w"
        }
        for col in columnas:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths.get(col, 120), anchor=anchors.get(col, "w"),
                             stretch=(col in ("Tipo", "Descripción", "Empleado", "Cliente")))

        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        # Ordenamiento por encabezados
        tipos_sort = {"ID": "int", "Tipo": "str", "Monto": "money", "Descripción": "str", "Fecha": "date"}
        if self._gastos_has_empleado_fk:
            tipos_sort["Empleado"] = "str"
        if self._gastos_has_cliente_fk:
            tipos_sort["Cliente"] = "str"
        self._setup_sorting(tree=self.tree, columnas=columnas, tipos=tipos_sort)

        # ---------- Acciones (fila 3) ----------
        acciones = self._panel(self)
        acciones.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        for c in range(3):
            acciones.grid_columnconfigure(c, weight=1, uniform="btns")

        self._btn(acciones, "Editar seleccionado", COLOR_PRIMARY, self.editar_gasto,
                  row=0, column=0, padx=5, pady=4, sticky="ew")
        self._btn(acciones, "Eliminar seleccionado", COLOR_DANGER, self.eliminar_gasto,
                  row=0, column=1, padx=5, pady=4, sticky="ew")
        self._btn(acciones, "Refrescar", COLOR_PRIMARY, self.cargar_gastos,
                  row=0, column=2, padx=5, pady=4, sticky="ew")

    # ---------- Combobox popdown (colores del desplegable) ----------
    def _estilizar_combobox_dropdown(self, combobox: ttk.Combobox):
        """Ajusta colores del Listbox interno del combobox para tema oscuro."""
        try:
            popdown = combobox.tk.call("ttk::combobox::PopdownWindow", combobox)
            lb = combobox.nametowidget(popdown + ".f.l")
            lb.configure(
                background=COLOR_PANEL,
                foreground=COLOR_TEXT,
                selectbackground=COLOR_SEL_BG,
                selectforeground=COLOR_TEXT,
                highlightthickness=0,
                relief="flat"
            )
        except Exception:
            pass

    # -------------------------------------------------------
    # Calendario
    # -------------------------------------------------------
    def _abrir_calendario(self, entry_widget: tk.Entry):
        """Calendario en modo LIBRE: todas las fechas activas."""
        top = tk.Toplevel(self)
        top.title("Seleccionar fecha")
        try:
            top.configure(bg=COLOR_BG)
        except Exception:
            pass
        top.resizable(False, False)
        top.transient(self.winfo_toplevel())
        top.grab_set()
        CalendarioWidget(top, entry_widget, fuentes=("all",))

    # -------------------------------------------------------
    # Catálogos (Tipos / Empleados / Clientes)
    # -------------------------------------------------------
    def cargar_tipos_gasto(self):
        try:
            with get_connection() as conn:
                rows = conn.execute("SELECT nombre FROM tipos_gasto ORDER BY nombre COLLATE NOCASE").fetchall()
            tipos = [r[0] for r in rows]
            self.tipo_combo['values'] = tipos
            if tipos:
                self.tipo_combo.current(0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los tipos de gasto.\n{e}")

    def _cargar_empleados(self):
        if not (self._has_empleados and self._gastos_has_empleado_fk and self._empleado_combo):
            return
        try:
            with get_connection() as conn:
                rows = conn.execute("SELECT id, nombre FROM empleados ORDER BY nombre COLLATE NOCASE").fetchall()
            self._empleados_map = {r["nombre"]: r["id"] for r in rows}
            self._empleado_combo["values"] = list(self._empleados_map.keys())
            if self._empleados_map:
                self._empleado_combo.current(0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los empleados.\n{e}")

    def _cargar_clientes(self):
        if not (self._gastos_has_cliente_fk and self._cliente_combo):
            return
        try:
            with get_connection() as conn:
                rows = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre COLLATE NOCASE").fetchall()
            self._clientes_map = {r["nombre"]: r["id"] for r in rows}
            self._cliente_combo["values"] = list(self._clientes_map.keys())
            if self._clientes_map:
                self._cliente_combo.current(0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los clientes.\n{e}")

    def abrir_ventana_nuevo_tipo(self):
        """Modal para agregar un nuevo tipo al catálogo (ENTER guarda, ESC cierra)."""
        ventana = tk.Toplevel(self)
        ventana.title("Nuevo tipo de gasto")
        try:
            ventana.configure(bg=COLOR_BG)
        except Exception:
            pass
        ventana.transient(self.winfo_toplevel())
        ventana.grab_set()
        ventana.bind("<Escape>", lambda e: ventana.destroy())

        tk.Label(ventana, text="Nombre del nuevo tipo:", bg=COLOR_BG, fg=COLOR_TEXT)\
            .grid(row=0, column=0, padx=10, pady=10, sticky="e")

        entry_tipo = tk.Entry(ventana, width=28, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                              insertbackground=COLOR_TEXT, relief="flat",
                              highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        entry_tipo.grid(row=0, column=1, padx=10, pady=10)
        entry_tipo.focus()

        def guardar_tipo(event=None):
            nuevo_tipo = entry_tipo.get().strip()
            if not nuevo_tipo:
                messagebox.showerror("Error", "El nombre del tipo no puede estar vacío.", parent=ventana)
                return
            try:
                with get_connection() as conn:
                    conn.execute("INSERT INTO tipos_gasto (nombre) VALUES (?)", (nuevo_tipo,))
                messagebox.showinfo("Éxito", f"Tipo '{nuevo_tipo}' agregado correctamente.", parent=ventana)
                self.cargar_tipos_gasto()
                ventana.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo agregar el tipo.\n{e}", parent=ventana)

        tk.Button(ventana, text="Guardar", command=guardar_tipo,
                  bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=1, column=0, columnspan=2, pady=10)
        ventana.bind("<Return>", guardar_tipo)

    # -------------------------------------------------------
    # Registro y listado
    # -------------------------------------------------------
    def registrar_gasto(self):
        """Valida y registra un gasto. (ENTER ejecuta este método)"""
        tipo = self.tipo_combo.get().strip()
        monto_txt = self.monto_entry.get().strip()
        descripcion = self.descripcion_entry.get().strip()
        fecha_txt = (self.fecha_entry.get() or "").strip()

        if not tipo:
            messagebox.showerror("Error", "Selecciona un tipo de gasto.")
            return

        try:
            monto = to_float(monto_txt, permitir_cero=False)
            if monto <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Monto inválido. Ejemplos válidos: 100, 100.50, 1.234,56, $1,234.56")
            return

        # Empleado requerido si tipo == 'Salarios' (insensible a mayúsculas)
        empleado_id = None
        if (self._has_empleados and self._gastos_has_empleado_fk and self._empleado_combo):
            emp_name = (self._empleado_combo.get() or "").strip()
            if tipo.lower() in ("salarios", "salario"):
                if not emp_name or emp_name not in getattr(self, "_empleados_map", {}):
                    messagebox.showerror("Error", "Para 'Salarios' debes seleccionar un empleado.")
                    return
            if emp_name and emp_name in getattr(self, "_empleados_map", {}):
                empleado_id = self._empleados_map[emp_name]

        cliente_id = None
        if (self._gastos_has_cliente_fk and self._cliente_combo):
            cli_name = (self._cliente_combo.get() or "").strip()
            if cli_name and cli_name in getattr(self, "_clientes_map", {}):
                cliente_id = self._clientes_map[cli_name]

        try:
            with get_connection() as conn:
                cur = conn.cursor()

                if fecha_txt:
                    fecha_n = normalizar_fecha(fecha_txt)
                    if not es_fecha_ok(fecha_n):
                        messagebox.showerror("Error", "Fecha inválida. Usa formato YYYY-MM-DD (o deja vacío).")
                        return
                    fecha_val = fecha_n + " 00:00:00"
                else:
                    fecha_val = None  # que la BD ponga default localtime

                # Build dinámico del INSERT según columnas disponibles
                cols = ["tipo", "monto", "descripcion"]
                vals = [tipo, float(monto), descripcion]
                if fecha_val is not None:
                    cols.append("fecha")
                    vals.append(fecha_val)
                if self._gastos_has_empleado_fk:
                    cols.append("empleado_id")
                    vals.append(empleado_id)
                if self._gastos_has_cliente_fk:
                    cols.append("cliente_id")
                    vals.append(cliente_id)

                placeholders = ", ".join("?" for _ in cols)
                sql = f"INSERT INTO gastos ({', '.join(cols)}) VALUES ({placeholders})"
                cur.execute(sql, tuple(vals))

            # Limpiar y refrescar
            self.monto_entry.delete(0, tk.END)
            self.descripcion_entry.delete(0, tk.END)
            self.fecha_entry.delete(0, tk.END)
            self.cargar_gastos()
            messagebox.showinfo("Éxito", "Gasto registrado correctamente.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar el gasto.\n{e}")

    def cargar_gastos(self, filtro: str = ""):
        """Carga el listado de gastos (más recientes primero)."""
        self.tree.delete(*self.tree.get_children())
        try:
            with get_connection() as conn:
                if self._gastos_has_empleado_fk or self._gastos_has_cliente_fk:
                    # JOINs opcionales
                    sql = """
                        SELECT g.id, g.tipo, g.monto, g.descripcion, g.fecha
                               {emp_sel} {cli_sel}
                        FROM gastos g
                        {emp_join} {cli_join}
                    """
                    emp_sel = ", e.nombre AS empleado" if self._gastos_has_empleado_fk else ""
                    cli_sel = ", c.nombre AS cliente" if self._gastos_has_cliente_fk else ""
                    emp_join = "LEFT JOIN empleados e ON e.id = g.empleado_id" if self._gastos_has_empleado_fk else ""
                    cli_join = "LEFT JOIN clientes  c ON c.id = g.cliente_id"  if self._gastos_has_cliente_fk else ""
                    sql = sql.format(emp_sel=emp_sel, cli_sel=cli_sel, emp_join=emp_join, cli_join=cli_join)

                    if filtro:
                        like = f"%{filtro}%"
                        extra = []
                        params = []
                        # Campos base
                        extra.append("(g.tipo LIKE ? OR g.descripcion LIKE ?)")
                        params += [like, like]
                        # Campos opcionales
                        if self._gastos_has_empleado_fk:
                            extra.append("(e.nombre LIKE ?)")
                            params.append(like)
                        if self._gastos_has_cliente_fk:
                            extra.append("(c.nombre LIKE ?)")
                            params.append(like)
                        sql += f" WHERE {' OR '.join(extra)}"
                        sql += " ORDER BY g.fecha DESC"
                        rows = conn.execute(sql, tuple(params)).fetchall()
                    else:
                        sql += " ORDER BY g.fecha DESC"
                        rows = conn.execute(sql).fetchall()
                else:
                    # Modo básico
                    if filtro:
                        like = f"%{filtro}%"
                        rows = conn.execute("""
                            SELECT id, tipo, monto, descripcion, fecha
                            FROM gastos
                            WHERE tipo LIKE ? OR descripcion LIKE ?
                            ORDER BY fecha DESC
                        """, (like, like)).fetchall()
                    else:
                        rows = conn.execute("""
                            SELECT id, tipo, monto, descripcion, fecha
                            FROM gastos
                            ORDER BY fecha DESC
                        """).fetchall()

                for r in rows:
                    # r es sqlite3.Row con alias opcionales
                    base_vals = [r["id"], r["tipo"], formato_moneda(r["monto"]), r["descripcion"] or "", r["fecha"]]
                    if self._gastos_has_empleado_fk:
                        base_vals.append(r["empleado"] or "")
                    if self._gastos_has_cliente_fk:
                        base_vals.append(r["cliente"] or "")
                    self.tree.insert("", "end", values=tuple(base_vals))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los gastos.\n{e}")

    def filtrar_gastos(self, event=None):
        filtro = (self.buscar_entry.get() or "").strip()
        self.cargar_gastos(filtro)

    # -------------------------------------------------------
    # Edición / Eliminación
    # -------------------------------------------------------
    def _gasto_seleccionado(self):
        item = self.tree.focus()
        if not item:
            return None
        vals = self.tree.item(item, "values")
        if not vals:
            return None
        # vals: (ID, Tipo, MontoFmt, Descripcion, Fecha [, Empleado] [, Cliente])
        gid = int(vals[0])
        tipo = vals[1]
        monto_fmt = vals[2]
        desc = vals[3]
        fecha = vals[4]
        emp_name = vals[5] if self._gastos_has_empleado_fk else None
        cli_name = vals[6] if (self._gastos_has_empleado_fk and self._gastos_has_cliente_fk) else (
            vals[5] if (not self._gastos_has_empleado_fk and self._gastos_has_cliente_fk) else None
        )
        try:
            monto = to_float(monto_fmt, permitir_cero=False)
        except ValueError:
            monto = 0.0
        return gid, tipo, monto, desc, fecha, emp_name, cli_name

    def eliminar_gasto(self):
        sel = self._gasto_seleccionado()
        if not sel:
            messagebox.showerror("Error", "Selecciona un gasto de la tabla.")
            return
        gid, tipo, monto, desc, fecha, *_ = sel
        if not messagebox.askyesno("Confirmar", f"¿Eliminar el gasto '{tipo}' de {formato_moneda(monto)}?"):
            return
        try:
            with get_connection() as conn:
                conn.execute("DELETE FROM gastos WHERE id = ?", (gid,))
            self.cargar_gastos(self.buscar_entry.get().strip())
            messagebox.showinfo("Éxito", "Gasto eliminado.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo eliminar el gasto.\n{e}")

    def editar_gasto(self):
        sel = self._gasto_seleccionado()
        if not sel:
            messagebox.showerror("Error", "Selecciona un gasto de la tabla.")
            return
        gid, tipo_act, monto_act, desc_act, fecha_act, emp_act, cli_act = sel

        win = tk.Toplevel(self)
        win.title("Editar gasto")
        try:
            win.configure(bg=COLOR_BG)
        except Exception:
            pass
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.bind("<Escape>", lambda e: win.destroy())

        # Tipo
        tk.Label(win, text="Tipo:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, padx=10, pady=8, sticky="e")
        cb_tipo = ttk.Combobox(win, state="readonly", width=28, style="Dark.TCombobox",
                               postcommand=lambda: self._estilizar_combobox_dropdown(cb_tipo))
        cb_tipo.grid(row=0, column=1, padx=10, pady=8, sticky="we")
        cb_tipo["values"] = self.tipo_combo["values"]
        try:
            idx = list(cb_tipo["values"]).index(tipo_act)
            cb_tipo.current(idx)
        except Exception:
            if cb_tipo["values"]:
                cb_tipo.current(0)

        # Monto
        tk.Label(win, text="Monto:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, padx=10, pady=8, sticky="e")
        vcmd = (win.register(self._validate_decimal), "%P")
        ent_monto = tk.Entry(win, width=16, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                             insertbackground=COLOR_TEXT, relief="flat",
                             highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY,
                             validate="key", validatecommand=vcmd)
        ent_monto.grid(row=1, column=1, padx=10, pady=8, sticky="w")
        ent_monto.insert(0, f"{monto_act:.2f}")

        # Descripción
        tk.Label(win, text="Descripción:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=2, column=0, padx=10, pady=8, sticky="e")
        ent_desc = tk.Entry(win, width=40, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                            insertbackground=COLOR_TEXT, relief="flat",
                            highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        ent_desc.grid(row=2, column=1, padx=10, pady=8, sticky="we")
        ent_desc.insert(0, desc_act or "")

        # Fecha
        tk.Label(win, text="Fecha (YYYY-MM-DD):", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=3, column=0, padx=10, pady=8, sticky="e")
        ent_fecha = tk.Entry(win, width=16, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                             insertbackground=COLOR_TEXT, relief="flat",
                             highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        ent_fecha.grid(row=3, column=1, padx=(10, 0), pady=8, sticky="w")
        ent_fecha.insert(0, normalizar_fecha(fecha_act))
        tk.Button(win, text="📅", command=lambda: self._abrir_calendario(ent_fecha),
                  bg=COLOR_PRIMARY, fg=COLOR_TEXT, activebackground=COLOR_PRIMARY,
                  activeforeground=COLOR_TEXT, relief="flat", padx=8, pady=4, cursor="hand2")\
            .grid(row=3, column=1, padx=(180, 0), pady=8, sticky="w")

        # Empleado / Cliente (si procede)
        row_next = 4
        cb_emp = None
        cb_cli = None

        if self._gastos_has_empleado_fk and self._has_empleados:
            tk.Label(win, text="Empleado:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=row_next, column=0, padx=10, pady=8, sticky="e")
            cb_emp = ttk.Combobox(win, state="readonly", width=28, style="Dark.TCombobox",
                                  postcommand=lambda: self._estilizar_combobox_dropdown(cb_emp))
            cb_emp.grid(row=row_next, column=1, padx=10, pady=8, sticky="we")
            cb_emp["values"] = list(getattr(self, "_empleados_map", {}).keys())
            try:
                if emp_act and emp_act in getattr(self, "_empleados_map", {}):
                    cb_emp.set(emp_act)
                elif cb_emp["values"]:
                    cb_emp.current(0)
            except Exception:
                pass
            row_next += 1

        if self._gastos_has_cliente_fk:
            tk.Label(win, text="Cliente:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=row_next, column=0, padx=10, pady=8, sticky="e")
            cb_cli = ttk.Combobox(win, state="readonly", width=28, style="Dark.TCombobox",
                                  postcommand=lambda: self._estilizar_combobox_dropdown(cb_cli))
            cb_cli.grid(row=row_next, column=1, padx=10, pady=8, sticky="we")
            cb_cli["values"] = list(getattr(self, "_clientes_map", {}).keys())
            try:
                if cli_act and cli_act in getattr(self, "_clientes_map", {}):
                    cb_cli.set(cli_act)
                elif cb_cli["values"]:
                    cb_cli.current(0)
            except Exception:
                pass
            row_next += 1

        win.grid_columnconfigure(1, weight=1)

        def guardar(event=None):
            tipo_new = cb_tipo.get().strip()
            monto_txt = ent_monto.get().strip()
            desc_new = ent_desc.get().strip()
            fecha_txt = ent_fecha.get().strip()
            emp_id = None
            cli_id = None

            if not tipo_new:
                messagebox.showerror("Error", "El tipo no puede estar vacío.", parent=win)
                return
            try:
                monto_new = to_float(monto_txt, permitir_cero=False)
                if monto_new <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Monto inválido.", parent=win)
                return

            if not es_fecha_ok(normalizar_fecha(fecha_txt)):
                messagebox.showerror("Error", "Fecha inválida. Usa YYYY-MM-DD.", parent=win)
                return

            if cb_emp is not None and self._gastos_has_empleado_fk:
                emp_name = (cb_emp.get() or "").strip()
                if tipo_new.lower() in ("salarios", "salario") and not emp_name:
                    messagebox.showerror("Error", "Para 'Salarios' debes seleccionar un empleado.", parent=win)
                    return
                if emp_name and emp_name in getattr(self, "_empleados_map", {}):
                    emp_id = self._empleados_map[emp_name]

            if cb_cli is not None and self._gastos_has_cliente_fk:
                cli_name = (cb_cli.get() or "").strip()
                if cli_name and cli_name in getattr(self, "_clientes_map", {}):
                    cli_id = self._clientes_map[cli_name]

            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    sets = ["tipo = ?", "monto = ?", "descripcion = ?", "fecha = ?"]
                    vals = [tipo_new, float(monto_new), desc_new, normalizar_fecha(fecha_txt) + " 00:00:00"]
                    if self._gastos_has_empleado_fk:
                        sets.append("empleado_id = ?")
                        vals.append(emp_id)
                    if self._gastos_has_cliente_fk:
                        sets.append("cliente_id = ?")
                        vals.append(cli_id)
                    sql = f"UPDATE gastos SET {', '.join(sets)} WHERE id = ?"
                    vals.append(gid)
                    cur.execute(sql, tuple(vals))

                self.cargar_gastos(self.buscar_entry.get().strip())
                messagebox.showinfo("Éxito", "Gasto actualizado.", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo actualizar el gasto.\n{e}", parent=win)

        tk.Button(win, text="Guardar", command=guardar,
                  bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=row_next, column=0, columnspan=2, pady=10)
        win.bind("<Return>", guardar)

    # -------------------------------------------------------
    # CRUD rápido de Empleados
    # -------------------------------------------------------
    def _abrir_crud_empleados(self):
        if not self._has_empleados:
            messagebox.showwarning("No disponible", "La tabla 'empleados' no existe en la base de datos.")
            return

        top = tk.Toplevel(self)
        top.title("Empleados")
        try:
            top.configure(bg=COLOR_BG)
        except Exception:
            pass
        top.transient(self.winfo_toplevel())
        top.grab_set()
        top.bind("<Escape>", lambda e: top.destroy())

        # Layout
        for c in range(3):
            top.grid_columnconfigure(c, weight=(1 if c == 1 else 0))
        # Form
        tk.Label(top, text="Nombre:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, padx=8, pady=6, sticky="e")
        ent_nombre = tk.Entry(top, width=26, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                              insertbackground=COLOR_TEXT, relief="flat",
                              highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        ent_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we")

        tk.Label(top, text="Teléfono:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, padx=8, pady=6, sticky="e")
        ent_tel = tk.Entry(top, width=20, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                           insertbackground=COLOR_TEXT, relief="flat",
                           highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        ent_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we")

        def add_emp(event=None):
            nombre = ent_nombre.get().strip()
            tel = ent_tel.get().strip()
            if not nombre:
                messagebox.showerror("Error", "El nombre es obligatorio.", parent=top)
                return
            try:
                with get_connection() as conn:
                    conn.execute("INSERT INTO empleados (nombre, telefono) VALUES (?, ?)", (nombre, tel))
                ent_nombre.delete(0, tk.END)
                ent_tel.delete(0, tk.END)
                cargar_lista()
                self._cargar_empleados()
                messagebox.showinfo("Éxito", "Empleado agregado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo agregar el empleado.\n{e}", parent=top)

        btn_add = tk.Button(top, text="Agregar", command=add_emp,
                            bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                            activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")
        btn_add.grid(row=2, column=0, columnspan=2, padx=8, pady=(4, 8))
        top.bind("<Return>", add_emp)

        # Tabla
        cols = ("ID", "Nombre", "Teléfono")
        tree = ttk.Treeview(top, columns=cols, show="headings", style="Dark.Treeview", height=10)
        for c, w in (("ID", 70), ("Nombre", 200), ("Teléfono", 160)):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor=("center" if c == "ID" else "w"))
        tree.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=(6, 6))
        top.grid_rowconfigure(3, weight=1)

        def cargar_lista():
            tree.delete(*tree.get_children())
            try:
                with get_connection() as conn:
                    rows = conn.execute("SELECT id, nombre, telefono FROM empleados ORDER BY nombre COLLATE NOCASE").fetchall()
                for r in rows:
                    tree.insert("", "end", values=(r["id"], r["nombre"], r["telefono"] or ""))
            except Exception:
                pass

        def editar():
            item = tree.focus()
            if not item:
                messagebox.showerror("Error", "Selecciona un empleado.", parent=top)
                return
            vals = tree.item(item, "values")
            emp_id = int(vals[0])
            nombre = vals[1]
            tel = vals[2]

            w = tk.Toplevel(top)
            w.title("Editar empleado")
            try:
                w.configure(bg=COLOR_BG)
            except Exception:
                pass
            w.transient(top)
            w.grab_set()
            w.bind("<Escape>", lambda e: w.destroy())

            tk.Label(w, text="Nombre:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, padx=8, pady=6, sticky="e")
            e_nombre = tk.Entry(w, width=26, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                                insertbackground=COLOR_TEXT, relief="flat",
                                highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
            e_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we")
            e_nombre.insert(0, nombre)

            tk.Label(w, text="Teléfono:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, padx=8, pady=6, sticky="e")
            e_tel = tk.Entry(w, width=20, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                             insertbackground=COLOR_TEXT, relief="flat",
                             highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
            e_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we")
            e_tel.insert(0, tel)

            w.grid_columnconfigure(1, weight=1)

            def save(event=None):
                n = e_nombre.get().strip()
                t = e_tel.get().strip()
                if not n:
                    messagebox.showerror("Error", "El nombre es obligatorio.", parent=w)
                    return
                try:
                    with get_connection() as conn:
                        conn.execute("UPDATE empleados SET nombre = ?, telefono = ? WHERE id = ?", (n, t, emp_id))
                    cargar_lista()
                    self._cargar_empleados()
                    messagebox.showinfo("Éxito", "Empleado actualizado.", parent=w)
                    w.destroy()
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo actualizar el empleado.\n{e}", parent=w)

            tk.Button(w, text="Guardar", command=save,
                      bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                      activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
                .grid(row=2, column=0, columnspan=2, pady=8)
            w.bind("<Return>", save)

        def eliminar():
            item = tree.focus()
            if not item:
                messagebox.showerror("Error", "Selecciona un empleado.", parent=top)
                return
            vals = tree.item(item, "values")
            emp_id = int(vals[0])
            nombre = vals[1]
            if not messagebox.askyesno("Confirmar", f"¿Eliminar empleado '{nombre}'?", parent=top):
                return
            try:
                with get_connection() as conn:
                    # Evitar fallo por FK en gastos
                    cnt = conn.execute("SELECT COUNT(*) FROM gastos WHERE empleado_id = ?", (emp_id,)).fetchone()[0]
                    if cnt > 0:
                        messagebox.showwarning(
                            "No permitido",
                            "No se puede eliminar el empleado porque está referenciado en gastos.",
                            parent=top
                        )
                        return
                    conn.execute("DELETE FROM empleados WHERE id = ?", (emp_id,))
                cargar_lista()
                self._cargar_empleados()
                messagebox.showinfo("Éxito", "Empleado eliminado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el empleado.\n{e}", parent=top)

        # Botones tabla
        tk.Button(top, text="Editar", command=editar,
                  bg=COLOR_PRIMARY, fg=COLOR_TEXT, activebackground=COLOR_PRIMARY,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=4, column=0, padx=8, pady=(0, 8), sticky="ew")
        tk.Button(top, text="Eliminar", command=eliminar,
                  bg=COLOR_DANGER, fg=COLOR_TEXT, activebackground=COLOR_DANGER,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=4, column=1, padx=8, pady=(0, 8), sticky="ew")
        tk.Button(top, text="Cerrar", command=top.destroy,
                  bg=COLOR_PRIMARY, fg=COLOR_TEXT, activebackground=COLOR_PRIMARY,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=4, column=2, padx=8, pady=(0, 8), sticky="ew")

        cargar_lista()

    def _abrir_crud_clientes(self):
        """CRUD rápido y mínimo de clientes dentro del contexto de Gastos."""
        top = tk.Toplevel(self)
        top.title("Clientes")
        try:
            top.configure(bg=COLOR_BG)
        except Exception:
            pass
        top.transient(self.winfo_toplevel())
        top.grab_set()
        top.bind("<Escape>", lambda e: top.destroy())

        for c in range(3):
            top.grid_columnconfigure(c, weight=(1 if c == 1 else 0))

        tk.Label(top, text="Nombre:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, padx=8, pady=6, sticky="e")
        ent_nombre = tk.Entry(top, width=26, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                              insertbackground=COLOR_TEXT, relief="flat",
                              highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        ent_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we")

        tk.Label(top, text="Teléfono:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, padx=8, pady=6, sticky="e")
        ent_tel = tk.Entry(top, width=20, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                           insertbackground=COLOR_TEXT, relief="flat",
                           highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        ent_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we")

        def add_cli(event=None):
            nombre = ent_nombre.get().strip()
            tel = ent_tel.get().strip()
            if not nombre:
                messagebox.showerror("Error", "El nombre es obligatorio.", parent=top)
                return
            try:
                with get_connection() as conn:
                    conn.execute("INSERT INTO clientes (nombre, telefono, deuda_total) VALUES (?, ?, 0.0)", (nombre, tel))
                ent_nombre.delete(0, tk.END)
                ent_tel.delete(0, tk.END)
                cargar_lista()
                self._cargar_clientes()
                messagebox.showinfo("Éxito", "Cliente agregado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo agregar el cliente.\n{e}", parent=top)

        btn_add = tk.Button(top, text="Agregar", command=add_cli,
                            bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                            activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")
        btn_add.grid(row=2, column=0, columnspan=2, padx=8, pady=(4, 8))
        top.bind("<Return>", add_cli)

        cols = ("ID", "Nombre", "Teléfono", "Deuda")
        tree = ttk.Treeview(top, columns=cols, show="headings", style="Dark.Treeview", height=10)
        for c, w, a in (("ID", 70, "center"), ("Nombre", 200, "w"), ("Teléfono", 160, "w"), ("Deuda", 110, "e")):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor=a)
        tree.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=(6, 6))
        top.grid_rowconfigure(3, weight=1)

        def cargar_lista():
            tree.delete(*tree.get_children())
            try:
                with get_connection() as conn:
                    rows = conn.execute("SELECT id, nombre, telefono, deuda_total FROM clientes ORDER BY nombre COLLATE NOCASE").fetchall()
                from ui.helpers import formato_moneda as _fm
                for r in rows:
                    tree.insert("", "end", values=(r["id"], r["nombre"], r["telefono"] or "", _fm(r["deuda_total"])))
            except Exception:
                pass

        def editar():
            item = tree.focus()
            if not item:
                messagebox.showerror("Error", "Selecciona un cliente.", parent=top)
                return
            vals = tree.item(item, "values")
            cid = int(vals[0])
            nombre = vals[1]
            tel = vals[2]

            w = tk.Toplevel(top)
            w.title("Editar cliente")
            try:
                w.configure(bg=COLOR_BG)
            except Exception:
                pass
            w.transient(top)
            w.grab_set()
            w.bind("<Escape>", lambda e: w.destroy())

            tk.Label(w, text="Nombre:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=0, column=0, padx=8, pady=6, sticky="e")
            e_nombre = tk.Entry(w, width=26, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                                insertbackground=COLOR_TEXT, relief="flat",
                                highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
            e_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we")
            e_nombre.insert(0, nombre)

            tk.Label(w, text="Teléfono:", bg=COLOR_BG, fg=COLOR_TEXT).grid(row=1, column=0, padx=8, pady=6, sticky="e")
            e_tel = tk.Entry(w, width=20, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                             insertbackground=COLOR_TEXT, relief="flat",
                             highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
            e_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we")
            e_tel.insert(0, tel)

            w.grid_columnconfigure(1, weight=1)

            def save(event=None):
                n = e_nombre.get().strip()
                t = e_tel.get().strip()
                if not n:
                    messagebox.showerror("Error", "El nombre es obligatorio.", parent=w)
                    return
                try:
                    with get_connection() as conn:
                        conn.execute("UPDATE clientes SET nombre = ?, telefono = ? WHERE id = ?", (n, t, cid))
                    cargar_lista()
                    self._cargar_clientes()
                    messagebox.showinfo("Éxito", "Cliente actualizado.", parent=w)
                    w.destroy()
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo actualizar el cliente.\n{e}", parent=w)

            tk.Button(w, text="Guardar", command=save,
                      bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                      activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
                .grid(row=2, column=0, columnspan=2, pady=8)
            w.bind("<Return>", save)

        def eliminar():
            item = tree.focus()
            if not item:
                messagebox.showerror("Error", "Selecciona un cliente.", parent=top)
                return
            vals = tree.item(item, "values")
            cid = int(vals[0])
            nombre = vals[1]
            if not messagebox.askyesno("Confirmar", f"¿Eliminar cliente '{nombre}'?", parent=top):
                return
            try:
                with get_connection() as conn:
                    # Verificar vínculos (ventas, pagos_credito, gastos.cliente_id)
                    v_ct = conn.execute("SELECT COUNT(*) FROM ventas WHERE cliente_id = ?", (cid,)).fetchone()[0]
                    p_ct = conn.execute("SELECT COUNT(*) FROM pagos_credito WHERE cliente_id = ?", (cid,)).fetchone()[0]
                    g_ct = 0
                    if self._gastos_has_cliente_fk:
                        g_ct = conn.execute("SELECT COUNT(*) FROM gastos WHERE cliente_id = ?", (cid,)).fetchone()[0]
                    if (v_ct + p_ct + g_ct) > 0:
                        messagebox.showwarning(
                            "No permitido",
                            "No se puede eliminar el cliente por tener registros asociados.",
                            parent=top
                        )
                        return
                    conn.execute("DELETE FROM clientes WHERE id = ?", (cid,))
                cargar_lista()
                self._cargar_clientes()
                messagebox.showinfo("Éxito", "Cliente eliminado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el cliente.\n{e}", parent=top)

        tk.Button(top, text="Editar", command=editar,
                  bg=COLOR_PRIMARY, fg=COLOR_TEXT, activebackground=COLOR_PRIMARY,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=4, column=0, padx=8, pady=(0, 8), sticky="ew")
        tk.Button(top, text="Eliminar", command=eliminar,
                  bg=COLOR_DANGER, fg=COLOR_TEXT, activebackground=COLOR_DANGER,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=4, column=1, padx=8, pady=(0, 8), sticky="ew")
        tk.Button(top, text="Cerrar", command=top.destroy,
                  bg=COLOR_PRIMARY, fg=COLOR_TEXT, activebackground=COLOR_PRIMARY,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=4, column=2, padx=8, pady=(0, 8), sticky="ew")

        cargar_lista()

    # -------------------------------------------------------
    # Ordenamiento por columnas
    # -------------------------------------------------------
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
def mostrar(frame_contenido):
    for widget in frame_contenido.winfo_children():
        widget.destroy()
    frame = GastosFrame(frame_contenido)
    # Si main usa grid, esto asegura expansión completa
    try:
        frame.grid(row=0, column=0, sticky="nsew")
    except Exception:
        frame.pack(fill="both", expand=True)
