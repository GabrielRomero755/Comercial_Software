# modules/creditos.py
# -----------------------------------------------------------
# Sistema de Comercio — Gestión de Clientes y Créditos
#
# USO / FLUJO / FUNCIONALIDAD
# -----------------------------------------------------------
# - Alta de clientes: nombre (obligatorio) y teléfono (opcional).
# - Listado con búsqueda dinámica por nombre/teléfono.
# - Visualización de la deuda acumulada (deuda_total).
# - Operaciones sobre deuda:
#       * Actualizar (refrescar desde BD)
#       * Abonar monto (pago parcial, máx. 2 decimales)
#       * Pagar deuda (liquidar a 0)
# - Edición y eliminación de clientes (CRUD completo).
# - Bitácora de abonos en 'pagos_credito'.
#
# MEJORAS DE UX
# -----------------------------------------------------------
# - Enter en Nombre/Teléfono => "Agregar Cliente".
# - Enter en Buscar => filtra.
# - Abonos: Enter confirma / Esc cierra.
# - Modificar cliente: Enter guarda / Esc cierra.
# - Doble clic en tabla => Modificar cliente.
#
# DETALLES TÉCNICOS
# -----------------------------------------------------------
# - Persistencia en:
#     * clientes(id, nombre, telefono, deuda_total)
#     * pagos_credito(id, cliente_id, monto, fecha, descripcion)
# - Parseo/validación de números con helpers.to_float (coma/punto, miles).
# - Entradas monetarias validan máx. 2 decimales durante edición.
# - Conexiones SQLite con context manager y PRAGMA foreign_keys=ON.
# - Tema de colores desde ui.theme (con fallbacks).
# -----------------------------------------------------------

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from db.database import get_connection
from ui.helpers import redondear_dos_decimales, formato_moneda, to_float

# Paleta desde tema centralizado (con fallbacks por si falta alguna clave)
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


class CreditosFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master, bg=COLOR_BG, highlightthickness=0, bd=0)

        # Layout raíz (grid responsive)
        self.grid_rowconfigure(0, weight=0)  # alta
        self.grid_rowconfigure(1, weight=0)  # búsqueda
        self.grid_rowconfigure(2, weight=1)  # tabla
        self.grid_rowconfigure(3, weight=0)  # botones
        self.grid_columnconfigure(0, weight=1)

        self._style = ttk.Style()
        self._aplicar_tema_ttk()

        self.crear_interfaz()
        self.cargar_clientes()

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

    # ---------------------------
    # Tema / Estilos
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

        self._style.configure(
            "Dark.TCombobox",
            fieldbackground=COLOR_ENTRY_BG,
            background=COLOR_PANEL,
            foreground=COLOR_TEXT
        )

    def _estilo_label(self, parent, text, **grid):
        lbl = tk.Label(parent, text=text, bg=parent["bg"], fg=COLOR_TEXT)
        if grid:
            lbl.grid(**grid)
        return lbl

    def _estilo_entry(self, parent, width=20, **grid):
        ent = tk.Entry(parent, width=width, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                       insertbackground=COLOR_TEXT, relief="flat", highlightthickness=1,
                       highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        if grid:
            ent.grid(**grid)
        return ent

    def _btn(self, parent, text, color_bg, cmd, **place):
        btn = tk.Button(
            parent, text=text, command=cmd,
            bg=color_bg, fg=COLOR_TEXT, activebackground=color_bg,
            activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2"
        )
        if place:
            uses_grid = any(k in place for k in ("row", "column", "rowspan", "columnspan", "sticky"))
            if uses_grid:
                btn.grid(**place)
            else:
                btn.pack(**place)
        return btn

    def _panel(self, parent):
        return tk.Frame(parent, bg=COLOR_PANEL, bd=0, highlightthickness=0)

    # ---------------------------
    # UI
    # ---------------------------
    def crear_interfaz(self):
        # --------- Fila 0: Formulario alta ----------
        frame_form = self._panel(self)
        frame_form.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        frame_form.grid_columnconfigure(0, weight=0)
        frame_form.grid_columnconfigure(1, weight=1)
        frame_form.grid_columnconfigure(2, weight=1)

        self._estilo_label(frame_form, "Nombre:", row=0, column=0, sticky="e", padx=8, pady=6)
        self.nombre_entry = self._estilo_entry(frame_form, width=28, row=0, column=1, padx=4, pady=6, sticky="we")

        self._estilo_label(frame_form, "Teléfono:", row=1, column=0, sticky="e", padx=8, pady=6)
        self.telefono_entry = self._estilo_entry(frame_form, width=20, row=1, column=1, padx=4, pady=6, sticky="we")

        self._btn(frame_form, "Agregar Cliente", COLOR_SUCCESS, self.agregar_cliente,
                  row=2, column=0, columnspan=2, pady=10, padx=8, sticky="w")

        # Enter en nombre/teléfono => Agregar
        self.nombre_entry.bind("<Return>", lambda e: self.agregar_cliente())
        self.telefono_entry.bind("<Return>", lambda e: self.agregar_cliente())

        # --------- Fila 1: Búsqueda ----------
        busc_panel = self._panel(self)
        busc_panel.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 0))
        busc_panel.grid_columnconfigure(0, weight=0)
        busc_panel.grid_columnconfigure(1, weight=1)

        self._estilo_label(busc_panel, "Buscar cliente (nombre/teléfono):",
                           row=0, column=0, padx=8, pady=(8, 6), sticky="w")
        self.buscar_entry = self._estilo_entry(busc_panel, width=40,
                                               row=0, column=1, padx=8, pady=(8, 6), sticky="we")
        self.buscar_entry.bind("<KeyRelease>", self.filtrar_clientes)
        self.buscar_entry.bind("<Return>", self.filtrar_clientes)

        # --------- Fila 2: Tabla (con scrollbars) ----------
        tabla_panel = self._panel(self)
        tabla_panel.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        tabla_panel.grid_rowconfigure(0, weight=1)
        tabla_panel.grid_columnconfigure(0, weight=1)

        columnas = ("ID", "Nombre", "Teléfono", "Deuda")

        scroll_y = ttk.Scrollbar(tabla_panel, orient="vertical")
        scroll_x = ttk.Scrollbar(tabla_panel, orient="horizontal")

        self.tree = ttk.Treeview(
            tabla_panel, columns=columnas, show="headings",
            style="Dark.Treeview",
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set
        )
        scroll_y.config(command=self.tree.yview)
        scroll_x.config(command=self.tree.xview)

        for col, width, anchor in (
            ("ID", 80, "center"),
            ("Nombre", 260, "w"),
            ("Teléfono", 160, "center"),
            ("Deuda", 120, "e"),
        ):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("Nombre", "Teléfono")))

        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        self._setup_sorting(
            tree=self.tree,
            columnas=columnas,
            tipos={"ID": "int", "Nombre": "str", "Teléfono": "str", "Deuda": "money"},
        )

        # Doble clic para modificar
        self.tree.bind("<Double-1>", lambda e: self.modificar_cliente())

        # --------- Fila 3: Botones de acción ----------
        btn_frame = self._panel(self)
        btn_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        for c in range(5):
            btn_frame.grid_columnconfigure(c, weight=1, uniform="btns")

        self._btn(btn_frame, "Actualizar Deuda", COLOR_PRIMARY, self.actualizar_deuda,
                  row=0, column=0, padx=5, pady=4, sticky="ew")
        self._btn(btn_frame, "Abonar Monto", COLOR_SUCCESS, self.abonar_monto,
                  row=0, column=1, padx=5, pady=4, sticky="ew")
        self._btn(btn_frame, "Pagar Deuda", COLOR_DANGER, self.pagar_deuda,
                  row=0, column=2, padx=5, pady=4, sticky="ew")
        self._btn(btn_frame, "Modificar Cliente", COLOR_PRIMARY, self.modificar_cliente,
                  row=0, column=3, padx=5, pady=4, sticky="ew")
        # NUEVO: Eliminar (CRUD completo)
        self._btn(btn_frame, "Eliminar Cliente", COLOR_DANGER, self.eliminar_cliente,
                  row=0, column=4, padx=5, pady=4, sticky="ew")

    # ---------------------------
    # Acciones
    # ---------------------------
    def agregar_cliente(self):
        """Inserta un cliente nuevo con deuda inicial 0.0."""
        nombre = self.nombre_entry.get().strip()
        telefono = self.telefono_entry.get().strip()

        if not nombre:
            messagebox.showerror("Error", "El nombre es obligatorio.")
            return

        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO clientes (nombre, telefono, deuda_total) VALUES (?, ?, ?)",
                    (nombre, telefono, 0.0),
                )
            messagebox.showinfo("Éxito", "Cliente registrado.")
            self.nombre_entry.delete(0, tk.END)
            self.telefono_entry.delete(0, tk.END)
            self.cargar_clientes()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar el cliente.\n{e}")

    def cargar_clientes(self, filtro: str = ""):
        """Llena la tabla de clientes con filtro por nombre/teléfono."""
        self.tree.delete(*self.tree.get_children())
        try:
            with get_connection() as conn:
                if filtro:
                    like = f"%{filtro}%"
                    rows = conn.execute(
                        """
                        SELECT id, nombre, telefono, deuda_total
                        FROM clientes
                        WHERE nombre LIKE ? OR telefono LIKE ?
                        ORDER BY nombre COLLATE NOCASE
                        """,
                        (like, like),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, nombre, telefono, deuda_total FROM clientes ORDER BY nombre COLLATE NOCASE"
                    ).fetchall()

                for cid, nombre, tel, deuda in rows:
                    self.tree.insert("", "end", values=(cid, nombre, tel or "", formato_moneda(deuda)))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los clientes.\n{e}")

    def filtrar_clientes(self, event=None):
        filtro = (self.buscar_entry.get() or "").strip()
        self.cargar_clientes(filtro)

    def actualizar_deuda(self):
        """Refresca la lista desde DB (la lógica de deuda se mantiene en ventas/pagos)."""
        self.cargar_clientes()
        messagebox.showinfo("Info", "Las deudas han sido actualizadas desde la base de datos.")

    def _obtener_cliente_seleccionado(self):
        """Devuelve (cliente_id, nombre, deuda_float) del cliente seleccionado en la tabla."""
        item = self.tree.focus()
        if not item:
            return None
        valores = self.tree.item(item, "values")
        if not valores:
            return None
        cliente_id = valores[0]
        nombre = valores[1]
        deuda_txt = valores[3]
        try:
            deuda = to_float(deuda_txt, permitir_cero=True)
        except ValueError:
            deuda = 0.0
        return (int(cliente_id), nombre, float(deuda))

    def pagar_deuda(self):
        """Pone la deuda_total del cliente seleccionado en 0 y registra pago total."""
        sel = self._obtener_cliente_seleccionado()
        if not sel:
            messagebox.showerror("Error", "Selecciona un cliente.")
            return
        cliente_id, nombre, deuda_actual = sel

        if deuda_actual <= 0:
            messagebox.showinfo("Info", "Este cliente no tiene deudas.")
            return

        if not messagebox.askyesno("Confirmar", f"¿Deseas marcar como pagada la deuda de {formato_moneda(deuda_actual)} de '{nombre}'?"):
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                # Registrar pago total en pagos_credito
                cur.execute(
                    "INSERT INTO pagos_credito (cliente_id, monto, descripcion) VALUES (?, ?, ?)",
                    (cliente_id, redondear_dos_decimales(deuda_actual), "Liquidación de deuda"),
                )
                # Dejar deuda en 0
                cur.execute("UPDATE clientes SET deuda_total = 0 WHERE id = ?", (cliente_id,))
            self.cargar_clientes()
            messagebox.showinfo("Éxito", "Deuda pagada correctamente.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo actualizar la deuda.\n{e}")

    def abonar_monto(self):
        """Realiza un pago parcial a la deuda del cliente seleccionado y lo registra."""
        sel = self._obtener_cliente_seleccionado()
        if not sel:
            messagebox.showerror("Error", "Selecciona un cliente.")
            return
        cliente_id, nombre, deuda_actual = sel

        if deuda_actual <= 0:
            messagebox.showinfo("Info", f"'{nombre}' no tiene deuda pendiente.")
            return

        # Modal de abono con validador de 2 decimales (admite coma/punto)
        win = tk.Toplevel(self)
        win.title(f"Abonar a: {nombre}")
        try:
            win.configure(bg=COLOR_BG)
        except Exception:
            pass
        win.grab_set()
        win.bind("<Escape>", lambda e: win.destroy())

        vcmd = (win.register(self._validate_decimal), "%P")

        lbl_info = tk.Label(win, text=f"Deuda actual: {formato_moneda(deuda_actual)}",
                            bg=COLOR_BG, fg=COLOR_TEXT)
        lbl_info.grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w")

        lbl_monto = tk.Label(win, text="Monto a abonar:", bg=COLOR_BG, fg=COLOR_TEXT)
        lbl_monto.grid(row=1, column=0, padx=12, pady=6, sticky="e")

        entry_monto = tk.Entry(
            win, width=18, validate="key", validatecommand=vcmd,
            bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG, insertbackground=COLOR_TEXT,
            relief="flat", highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY
        )
        entry_monto.grid(row=1, column=1, padx=12, pady=6, sticky="w")
        entry_monto.focus()

        def confirmar_abono(event=None):
            txt = entry_monto.get().strip()
            try:
                abono = to_float(txt, permitir_cero=False)
            except ValueError:
                messagebox.showerror("Error", "Ingresa un monto válido.", parent=win)
                return
            if abono <= 0:
                messagebox.showerror("Error", "El abono debe ser mayor a 0.", parent=win)
                return

            # No permitir abonar más que la deuda actual
            aplicado = min(abono, deuda_actual)
            nuevo_saldo = redondear_dos_decimales(deuda_actual - aplicado)

            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    # Inserta en pagos_credito (bitácora)
                    cur.execute(
                        "INSERT INTO pagos_credito (cliente_id, monto, descripcion) VALUES (?, ?, ?)",
                        (cliente_id, redondear_dos_decimales(aplicado), "Abono a crédito"),
                    )
                    # Actualiza saldo en clientes
                    cur.execute(
                        "UPDATE clientes SET deuda_total = ? WHERE id = ?",
                        (nuevo_saldo, cliente_id)
                    )
                self.cargar_clientes()
                messagebox.showinfo(
                    "Éxito",
                    f"Se abonó {formato_moneda(aplicado)} a '{nombre}'.\nSaldo restante: {formato_moneda(nuevo_saldo)}.",
                    parent=win
                )
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo registrar el abono.\n{e}", parent=win)

        btn_ok = tk.Button(win, text="Abonar", command=confirmar_abono,
                           bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                           activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")
        btn_ok.grid(row=2, column=0, columnspan=2, pady=12)
        # Enter confirma
        win.bind("<Return>", confirmar_abono)

    def modificar_cliente(self):
        """Abre un modal para editar nombre y teléfono del cliente seleccionado."""
        item = self.tree.focus()
        if not item:
            messagebox.showerror("Error", "Selecciona un cliente para modificar.")
            return

        valores = self.tree.item(item, "values")
        cliente_id = int(valores[0])
        nombre_actual = valores[1]
        telefono_actual = valores[2]

        ventana = tk.Toplevel(self)
        ventana.title("Modificar Cliente")
        try:
            ventana.configure(bg=COLOR_BG)
        except Exception:
            pass
        ventana.grab_set()
        ventana.bind("<Escape>", lambda e: ventana.destroy())

        lbl_n = tk.Label(ventana, text="Nombre:", bg=COLOR_BG, fg=COLOR_TEXT)
        lbl_n.grid(row=0, column=0, padx=10, pady=10, sticky="e")
        nombre_entry = tk.Entry(ventana, width=32, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                                insertbackground=COLOR_TEXT, relief="flat",
                                highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        nombre_entry.grid(row=0, column=1, padx=10, pady=10, sticky="we")
        nombre_entry.insert(0, nombre_actual)

        lbl_t = tk.Label(ventana, text="Teléfono:", bg=COLOR_BG, fg=COLOR_TEXT)
        lbl_t.grid(row=1, column=0, padx=10, pady=10, sticky="e")
        telefono_entry = tk.Entry(ventana, width=20, bg=COLOR_ENTRY_BG, fg=COLOR_ENTRY_FG,
                                  insertbackground=COLOR_TEXT, relief="flat",
                                  highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_PRIMARY)
        telefono_entry.grid(row=1, column=1, padx=10, pady=10, sticky="we")
        telefono_entry.insert(0, telefono_actual)

        ventana.grid_columnconfigure(1, weight=1)

        def guardar_cambios(event=None):
            nuevo_nombre = nombre_entry.get().strip()
            nuevo_telefono = telefono_entry.get().strip()

            if not nuevo_nombre:
                messagebox.showerror("Error", "El nombre es obligatorio.", parent=ventana)
                return

            try:
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE clientes SET nombre = ?, telefono = ? WHERE id = ?",
                        (nuevo_nombre, nuevo_telefono, cliente_id),
                    )
                messagebox.showinfo("Éxito", "Cliente modificado correctamente.", parent=ventana)
                self.cargar_clientes()
                ventana.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo modificar el cliente.\n{e}", parent=ventana)

        btn_save = tk.Button(ventana, text="Guardar", command=guardar_cambios,
                             bg=COLOR_SUCCESS, fg=COLOR_TEXT, activebackground=COLOR_SUCCESS,
                             activeforeground=COLOR_TEXT, relief="flat", padx=10, pady=6, cursor="hand2")
        btn_save.grid(row=2, column=0, columnspan=2, pady=10)
        ventana.bind("<Return>", guardar_cambios)

    def eliminar_cliente(self):
        """
        Elimina el cliente seleccionado si NO tiene registros vinculados en ventas o pagos_credito.
        (El esquema no define ON DELETE CASCADE, así que validamos manualmente).
        """
        item = self.tree.focus()
        if not item:
            messagebox.showerror("Error", "Selecciona un cliente para eliminar.")
            return

        valores = self.tree.item(item, "values")
        cliente_id = int(valores[0])
        nombre = valores[1]

        if not messagebox.askyesno("Confirmar", f"¿Eliminar definitivamente al cliente '{nombre}'?"):
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                ventas_ct = cur.execute("SELECT COUNT(*) FROM ventas WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]
                pagos_ct  = cur.execute("SELECT COUNT(*) FROM pagos_credito WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]

                if ventas_ct > 0 or pagos_ct > 0:
                    messagebox.showwarning(
                        "No permitido",
                        "No se puede eliminar el cliente porque tiene ventas o pagos asociados.\n"
                        "Sugerencia: conserva el registro o anonimízalo editando el nombre.",
                    )
                    return

                cur.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
            self.cargar_clientes()
            messagebox.showinfo("Éxito", f"Cliente '{nombre}' eliminado.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo eliminar el cliente.\n{e}")

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
        try:
            widget.destroy()
        except Exception:
            pass
    frame = CreditosFrame(frame_contenido)
    # Si el contenedor usa grid en main, asegura expansión completa
    try:
        frame.grid(row=0, column=0, sticky="nsew")
    except Exception:
        frame.pack(fill="both", expand=True)
