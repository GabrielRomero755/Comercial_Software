# modules/gastos.py
# -----------------------------------------------------------
# Gestión de Gastos
#
# Funcionalidad:
#   - Alta de tipos de gasto (catálogo editable).
#   - Registro de gastos: tipo, monto, descripción, fecha (auto u opcional manual).
#   - Búsqueda dinámica (tipo/descripcion).
#   - Edición y eliminación de gastos.
#   - Listado con monto formateado y ordenamiento por encabezados.
#
# Mejoras:
#   - Validador de 2 decimales (admite coma o punto).
#   - Calendario para seleccionar fecha.
#   - (Nuevo) En Gastos el calendario se muestra con TODAS las fechas activas (modo libre).
#   - (Nuevo) ESC cierra las ventanas emergentes (nuevo tipo / editar gasto).
#   - (Nuevo) ENTER registra/guarda sin necesidad de pulsar los botones.
#   - (Nuevo) Atajos: Supr elimina seleccionado; doble clic edita.
# -----------------------------------------------------------

import tkinter as tk
from tkinter import ttk, messagebox
from db.database import get_connection
from modules.calendar_widget import CalendarioWidget
from ui.helpers import to_float, formato_moneda, es_fecha_ok, normalizar_fecha

# -----------------------------------------------------------
# Paleta oscura (consistente con la app)
# -----------------------------------------------------------
COLOR_BG        = "#2C3E50"  # Fondo general
COLOR_PANEL     = "#34495E"  # Paneles / contenedores
COLOR_TEXT      = "#ECF0F1"  # Texto
COLOR_PRIMARY   = "#3498DB"  # Botones principales
COLOR_SUCCESS   = "#2ECC71"  # Confirmación / Éxito
COLOR_DANGER    = "#E74C3C"  # Alerta / Error
COLOR_ENTRY_BG  = "#3B4A5A"  # Fondo de entradas
COLOR_ENTRY_FG  = COLOR_TEXT
COLOR_SEL_BG    = "#1ABC9C"  # Selección en tablas/listas
COLOR_BORDER    = "#22313F"


class GastosFrame(tk.Frame):
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

        self.crear_interfaz()
        self.cargar_tipos_gasto()
        self.cargar_gastos()

        # Atajos generales del frame
        try:
            # Enter registra desde cualquier campo del formulario principal
            for w in (self.tipo_combo, self.monto_entry, self.descripcion_entry, self.fecha_entry):
                w.bind("<Return>", lambda e: self.registrar_gasto())
            # Supr elimina en la tabla
            self.tree.bind("<Delete>", lambda e: self.eliminar_gasto())
            # Doble clic edita
            self.tree.bind("<Double-1>", lambda e: self.editar_gasto())
        except Exception:
            pass

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
        for c in range(6):
            form_frame.grid_columnconfigure(c, weight=(1 if c in (1, 3, 5) else 0))

        self._lbl(form_frame, "Tipo de Gasto:", row=0, column=0, sticky="e", padx=8, pady=6)
        self.tipo_combo = ttk.Combobox(
            form_frame, state="readonly", width=28, style="Dark.TCombobox",
            postcommand=lambda: self._estilizar_combobox_dropdown(self.tipo_combo)
        )
        self.tipo_combo.grid(row=0, column=1, sticky="we", padx=4, pady=6)

        self._btn(form_frame, "Añadir tipo", COLOR_PRIMARY, self.abrir_ventana_nuevo_tipo,
                  row=0, column=2, padx=10, pady=6, sticky="w")

        self._lbl(form_frame, "Monto:", row=1, column=0, sticky="e", padx=8, pady=6)
        vcmd = (self.register(self._validate_decimal), "%P")
        self.monto_entry = self._entry(form_frame, width=16, row=1, column=1, sticky="we", padx=4, pady=6)
        self.monto_entry.configure(validate="key", validatecommand=vcmd)

        self._lbl(form_frame, "Descripción (opcional):", row=1, column=2, sticky="e", padx=8, pady=6)
        self.descripcion_entry = self._entry(form_frame, width=42, row=1, column=3, padx=4, pady=6, sticky="we")

        self._lbl(form_frame, "Fecha (YYYY-MM-DD):", row=0, column=3, sticky="e", padx=8, pady=6)
        self.fecha_entry = self._entry(form_frame, width=14, row=0, column=4, padx=4, pady=6, sticky="w")
        self._btn(form_frame, "📅", COLOR_PRIMARY, lambda: self._abrir_calendario(self.fecha_entry),
                  row=0, column=5, padx=4, pady=6, sticky="w")

        self._btn(form_frame, "Registrar Gasto", COLOR_SUCCESS, self.registrar_gasto,
                  row=2, column=0, columnspan=6, pady=10)

        # ---------- Búsqueda (fila 1) ----------
        search_frame = self._panel(self)
        search_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 0))
        search_frame.grid_columnconfigure(1, weight=1)

        self._lbl(search_frame, "Buscar (tipo/descr.):", row=0, column=0, sticky="e", padx=8, pady=6)
        self.buscar_entry = self._entry(search_frame, width=36, row=0, column=1, padx=4, pady=6, sticky="we")
        self.buscar_entry.bind("<KeyRelease>", self.filtrar_gastos)

        # ---------- Tabla (fila 2) ----------
        tabla_panel = self._panel(self)
        tabla_panel.grid(row=2, column=0, sticky="nsew", padx=10, pady=(6, 6))
        tabla_panel.grid_rowconfigure(0, weight=1)    # Treeview crece
        tabla_panel.grid_columnconfigure(0, weight=1)

        columnas = ("ID", "Tipo", "Monto", "Descripción", "Fecha")

        scroll_y = ttk.Scrollbar(tabla_panel, orient="vertical")
        scroll_x = ttk.Scrollbar(tabla_panel, orient="horizontal")

        self.tree = ttk.Treeview(
            tabla_panel, columns=columnas, show="headings", style="Dark.Treeview",
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set
        )
        scroll_y.config(command=self.tree.yview)
        scroll_x.config(command=self.tree.xview)

        for col, width, anchor in (
            ("ID", 70, "center"),
            ("Tipo", 180, "w"),
            ("Monto", 110, "e"),
            ("Descripción", 360, "w"),
            ("Fecha", 140, "center"),
        ):
            self.tree.heading(col, text=col)  # el comando para ordenar se añade abajo
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("Tipo", "Descripción")))

        # Colocar con grid para responsividad real
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        # Ordenamiento por encabezados
        self._setup_sorting(
            tree=self.tree,
            columnas=columnas,
            tipos={
                "ID": "int",
                "Tipo": "str",
                "Monto": "money",
                "Descripción": "str",
                "Fecha": "date",
            },
        )

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
        """
        Ajusta colores del Listbox interno del combobox para que
        texto y selección sean legibles con el tema oscuro.
        """
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
        """
        Abre calendario en modo LIBRE (todas las fechas activas),
        para poder registrar gastos de cualquier día pasado.
        """
        top = tk.Toplevel(self)
        top.title("Seleccionar fecha")
        try:
            top.configure(bg=COLOR_BG)
        except Exception:
            pass
        top.resizable(False, False)
        top.transient(self.winfo_toplevel())
        top.grab_set()
        # Modo libre: todas las fechas activas
        CalendarioWidget(top, entry_widget, fuentes=("all",))

    # -------------------------------------------------------
    # Catálogo de tipos de gasto
    # -------------------------------------------------------
    def cargar_tipos_gasto(self):
        """Carga el catálogo de tipos para el combobox."""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT nombre FROM tipos_gasto ORDER BY nombre COLLATE NOCASE")
                tipos = [row[0] for row in cur.fetchall()]
            self.tipo_combo['values'] = tipos
            if tipos:
                self.tipo_combo.current(0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los tipos de gasto.\n{e}")

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

        def guardar_tipo():
            nuevo_tipo = entry_tipo.get().strip()
            if not nuevo_tipo:
                messagebox.showerror("Error", "El nombre del tipo no puede estar vacío.", parent=ventana)
                return
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("INSERT INTO tipos_gasto (nombre) VALUES (?)", (nuevo_tipo,))
                messagebox.showinfo("Éxito", f"Tipo '{nuevo_tipo}' agregado correctamente.", parent=ventana)
                self.cargar_tipos_gasto()
                ventana.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo agregar el tipo.\n{e}", parent=ventana)

        tk.Button(ventana, text="Guardar", command=guardar_tipo,
                  bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=1, column=0, columnspan=2, pady=10)

        # ENTER guarda
        ventana.bind("<Return>", lambda e: guardar_tipo())

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

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                if fecha_txt:
                    # Validar y normalizar fecha
                    fecha_n = normalizar_fecha(fecha_txt)
                    if not es_fecha_ok(fecha_n):
                        messagebox.showerror("Error", "Fecha inválida. Usa formato YYYY-MM-DD (o deja vacío).")
                        return
                    cur.execute("""
                        INSERT INTO gastos (tipo, monto, descripcion, fecha)
                        VALUES (?, ?, ?, ?)
                    """, (tipo, float(monto), descripcion, fecha_n + " 00:00:00"))
                else:
                    cur.execute("""
                        INSERT INTO gastos (tipo, monto, descripcion)
                        VALUES (?, ?, ?)
                    """, (tipo, float(monto), descripcion))
            # Limpiar y refrescar
            self.monto_entry.delete(0, tk.END)
            self.descripcion_entry.delete(0, tk.END)
            self.fecha_entry.delete(0, tk.END)
            self.cargar_gastos()
            messagebox.showinfo("Éxito", "Gasto registrado correctamente.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar el gasto.\n{e}")

    def cargar_gastos(self, filtro: str = ""):
        """Carga el listado de gastos más recientes primero (con filtro opcional)."""
        self.tree.delete(*self.tree.get_children())
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                if filtro:
                    like = f"%{filtro}%"
                    cur.execute("""
                        SELECT id, tipo, monto, descripcion, fecha
                        FROM gastos
                        WHERE tipo LIKE ? OR descripcion LIKE ?
                        ORDER BY fecha DESC
                    """, (like, like))
                else:
                    cur.execute("""
                        SELECT id, tipo, monto, descripcion, fecha
                        FROM gastos
                        ORDER BY fecha DESC
                    """)
                for gid, tipo, monto, desc, fecha in cur.fetchall():
                    self.tree.insert("", "end", values=(gid, tipo, formato_moneda(monto), desc or "", fecha))
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
        # vals: (ID, Tipo, MontoFmt, Descripcion, Fecha)
        gid = int(vals[0])
        tipo = vals[1]
        monto_fmt = vals[2]
        desc = vals[3]
        fecha = vals[4]
        try:
            monto = to_float(monto_fmt, permitir_cero=False)
        except ValueError:
            monto = 0.0
        return gid, tipo, monto, desc, fecha

    def eliminar_gasto(self):
        sel = self._gasto_seleccionado()
        if not sel:
            messagebox.showerror("Error", "Selecciona un gasto de la tabla.")
            return
        gid, tipo, monto, desc, fecha = sel
        if not messagebox.askyesno("Confirmar", f"¿Eliminar el gasto '{tipo}' de {formato_moneda(monto)}?"):
            return
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM gastos WHERE id = ?", (gid,))
            self.cargar_gastos(self.buscar_entry.get().strip())
            messagebox.showinfo("Éxito", "Gasto eliminado.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo eliminar el gasto.\n{e}")

    def editar_gasto(self):
        sel = self._gasto_seleccionado()
        if not sel:
            messagebox.showerror("Error", "Selecciona un gasto de la tabla.")
            return
        gid, tipo_act, monto_act, desc_act, fecha_act = sel

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
        # Seleccionar actual (si existe), o primera opción
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
        # Normaliza a Y-m-d por si viene con hora
        ent_fecha.insert(0, normalizar_fecha(fecha_act))
        tk.Button(win, text="📅", command=lambda: self._abrir_calendario(ent_fecha),
                  bg=COLOR_PRIMARY, fg=COLOR_TEXT, activebackground=COLOR_PRIMARY,
                  activeforeground=COLOR_TEXT, relief="flat", padx=8, pady=4, cursor="hand2")\
            .grid(row=3, column=1, padx=(180, 0), pady=8, sticky="w")

        win.grid_columnconfigure(1, weight=1)

        def guardar():
            tipo_new = cb_tipo.get().strip()
            monto_txt = ent_monto.get().strip()
            desc_new = ent_desc.get().strip()
            fecha_txt = ent_fecha.get().strip()

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

            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE gastos
                           SET tipo = ?, monto = ?, descripcion = ?, fecha = ?
                         WHERE id = ?
                    """, (tipo_new, float(monto_new), desc_new, normalizar_fecha(fecha_txt) + " 00:00:00", gid))
                self.cargar_gastos(self.buscar_entry.get().strip())
                messagebox.showinfo("Éxito", "Gasto actualizado.", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo actualizar el gasto.\n{e}", parent=win)

        tk.Button(win, text="Guardar", command=guardar,
                  bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                  activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")\
            .grid(row=4, column=0, columnspan=2, pady=10)

        # ENTER guarda
        win.bind("<Return>", lambda e: guardar())

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
