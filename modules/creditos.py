# modules/creditos.py
# -----------------------------------------------------------
# Sistema de Comercio — Gestión de Clientes y Créditos
#
# FLUJO / FUNCIONALIDAD
# -----------------------------------------------------------
# - Alta de clientes: nombre (obligatorio) y teléfono (opcional).
# - Búsqueda dinámica por nombre/teléfono.
# - Visualización de la deuda acumulada (clientes.deuda_total).
# - Operaciones sobre deuda:
#       * Actualizar (refrescar desde BD)
#       * Abonar monto (pago parcial, máx. 2 decimales)
#       * Pagar deuda (liquidar a 0)
# - Edición y eliminación de clientes (CRUD completo).
# - Bitácora de abonos:
#       * Preferente: 'pagos_cliente' (esquema nuevo).
#       * Compatibilidad: 'pagos_credito' (esquema legacy).
#
# MEJORAS DE ARQUITECTURA/UX (esta versión)
# -----------------------------------------------------------
# - Tema visual unificado (ui/theme.py): paleta beige/rosa/café.
# - Entradas monetarias con validador de 2 decimales (helpers).
# - Helpers de parseo/formateo centralizados (helpers).
# - Ordenamiento por encabezados (int/money/str/date).
# - Doble clic para editar cliente; Supr para eliminar.
# - ENTER agrega cliente / confirma abono / guarda cambios.
# - Transacciones atómicas (INSERT pago + UPDATE deuda).
# - Detección automática de tabla de pagos disponible
#   (pagos_cliente → preferente; si no existe → pagos_credito).
# -----------------------------------------------------------

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from .calendar_widget import CalendarioWidget

from db.database import get_connection
from ui.helpers import (
    redondear_dos_decimales,
    formato_moneda,
    to_float,
    adjuntar_validador_2_decimales,
)
from ui.theme import (
    apply_brand_ttk_theme,
    stylize_combobox_dropdown,
    set_treeview_stripes,
    BRAND_PALETTE,
)

PALETTE = BRAND_PALETTE


class CreditosFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master, bg=PALETTE["bg"], highlightthickness=0, bd=0)

        # Tema / estilos unificados (ttk)
        self._style = apply_brand_ttk_theme(self)
        self._tree_style_name = "Brand.Treeview"

        # Descubrir tabla de pagos disponible (nuevo/legacy)
        self._tabla_pagos = self._detectar_tabla_pagos()

        # UI
        self._init_scroll_area()
        self._build_ui()
        self.cargar_clientes()
        
        # --------- Área scrollable (canvas + frame) ---------
    # --------- Área scrollable (canvas + frame) ---------
    def _init_scroll_area(self):
        # Usar GRID (no pack) para no mezclar geometry managers
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._scroll_canvas = tk.Canvas(self, bg=PALETTE["bg"], highlightthickness=0)
        self._scroll_vbar = ttk.Scrollbar(self, orient="vertical", command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=self._scroll_vbar.set)

        # El canvas ocupa col 0; la barra col 1
        self._scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self._scroll_vbar.grid(row=0, column=1, sticky="ns")

        # Frame interno donde se cuelga TODO el contenido
        self._scroll_body = tk.Frame(self._scroll_canvas, bg=PALETTE["bg"])
        self._scroll_window = self._scroll_canvas.create_window((0, 0), window=self._scroll_body, anchor="nw")
        
        # Hacer que la columna 0 del body crezca con el ancho disponible
        self._scroll_body.grid_columnconfigure(0, weight=1)

        # Ajustar scrollregion al tamaño del contenido
        def _on_body_config(_event=None):
            self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))
        self._scroll_body.bind("<Configure>", _on_body_config)

        # Hacer que el body siempre tenga el mismo ancho visible del canvas
        def _on_canvas_config(event):
            self._scroll_canvas.itemconfig(self._scroll_window, width=event.width)
        self._scroll_canvas.bind("<Configure>", _on_canvas_config)

        # Scroll con rueda (solo cuando el foco esté dentro del body)
        def _wheel(e):
            self._scroll_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self._scroll_body.bind("<Enter>", lambda _e: self._scroll_body.bind_all("<MouseWheel>", _wheel))
        self._scroll_body.bind("<Leave>", lambda _e: self._scroll_body.unbind_all("<MouseWheel>"))



    # -------------------------------------------------------
    # Infra / helpers de UI
    # -------------------------------------------------------
    def _panel(self, parent, **pack):
        f = tk.Frame(parent, bg=PALETTE["panel"], bd=0, highlightthickness=0)
        if pack:
            f.pack(**pack)
        return f

    def _lbl(self, parent, text, **grid):
        w = tk.Label(parent, text=text, bg=parent["bg"], fg=PALETTE["text"])
        if grid:
            w.grid(**grid)
        return w

    def _entry(self, parent, width=20, **grid):
        e = ttk.Entry(parent, width=width, style="TEntry")
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

    def _combobox(self, parent, width=24, **grid):
        cb = ttk.Combobox(parent, state="readonly", width=width, style="TCombobox")
        if grid:
            cb.grid(**grid)
        cb.configure(postcommand=lambda c=cb: stylize_combobox_dropdown(c, PALETTE))
        return cb

    def _tree_with_scrolls(self, parent, columnas, height=12):
        # Asegura que el contenedor permita expandir el Treeview
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
            height=height,
            style=self._tree_style_name,
            yscrollcommand=scroll_y.set,
            xscrollcommand=scroll_x.set,
        )
        scroll_y.config(command=tree.yview)
        scroll_x.config(command=tree.xview)

        # Grid del arbol y scrollbars
        tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        # Filler en la esquina para evitar el "huevito" vacío
        try:
            corner = tk.Frame(parent, bg=PALETTE.get("panel", parent.cget("bg")), width=10, height=10)
            corner.grid(row=1, column=1, sticky="nsew")
            corner.grid_propagate(False)
        except Exception:
            pass

        return tree


    # -------------------------------------------------------
    # Descubrimiento de esquema
    # -------------------------------------------------------
    def _detectar_tabla_pagos(self) -> str:
        """
        Devuelve la tabla de pagos a usar y setea flags de esquema:
        - self._pagos_has_venta_id: True si pagos_cliente.venta_id existe.
        """
        self._pagos_has_venta_id = False
        try:
            with get_connection() as conn:
                has_pagos_cliente = bool(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pagos_cliente'"
                    ).fetchone()
                )
                if has_pagos_cliente:
                    # ¿tiene venta_id?
                    try:
                        cols = conn.execute("PRAGMA table_info(pagos_cliente)").fetchall()
                        names = {str(c[1]).lower() for c in cols}
                        self._pagos_has_venta_id = ("venta_id" in names)
                    except Exception:
                        self._pagos_has_venta_id = False
                    return "pagos_cliente"

                has_pagos_credito = bool(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pagos_credito'"
                    ).fetchone()
                )
                if has_pagos_credito:
                    # pagos_credito no tiene venta_id
                    self._pagos_has_venta_id = False
                    return "pagos_credito"
        except Exception:
            pass
        # Sin tablas de pagos; se operará solo sobre clientes.deuda_total
        self._pagos_has_venta_id = False
        return ""    

    # -------------------------------------------------------
    # UI
    # -------------------------------------------------------
    def _build_ui(self):
        # ---------- Fila 0: Alta ----------
        frame_form = self._panel(self._scroll_body)
        frame_form.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        for c in range(3):
            frame_form.grid_columnconfigure(c, weight=(1 if c in (1, 2) else 0))

        self._lbl(frame_form, "Nombre:", row=0, column=0, sticky="e", padx=8, pady=6)
        self.nombre_entry = self._entry(frame_form, width=28, row=0, column=1, padx=4, pady=6, sticky="we")

        self._lbl(frame_form, "Teléfono:", row=1, column=0, sticky="e", padx=8, pady=6)
        self.telefono_entry = self._entry(frame_form, width=20, row=1, column=1, padx=4, pady=6, sticky="we")

        self._lbl(frame_form, "Dirección:", row=2, column=0, sticky="e", padx=8, pady=6)
        self.direccion_entry = self._entry(frame_form, width=36, row=2, column=1, padx=4, pady=6, sticky="we")

        
        self._btn(frame_form, "Agregar Cliente", "Success.TButton", self.agregar_cliente,
                  row=3, column=0, columnspan=2, pady=10, padx=8, sticky="w")

        # ENTER en nombre/teléfono => Agregar
        self.nombre_entry.bind("<Return>", lambda _e: self.agregar_cliente())
        self.telefono_entry.bind("<Return>", lambda _e: self.agregar_cliente())
        self.direccion_entry.bind("<Return>", lambda _e: self.agregar_cliente())


        # ---------- Fila 1: Búsqueda ----------
        busc_panel = self._panel(self._scroll_body)
        busc_panel.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 0))
        busc_panel.grid_columnconfigure(1, weight=1)

        self._lbl(busc_panel, "Buscar cliente (nombre/teléfono):", row=0, column=0, padx=8, pady=(8, 6), sticky="w")
        self.buscar_entry = self._entry(busc_panel, width=40, row=0, column=1, padx=8, pady=(8, 6), sticky="we")
        self.buscar_entry.bind("<KeyRelease>", self.filtrar_clientes)
        self.buscar_entry.bind("<Return>", self.filtrar_clientes)

        # ---------- Fila 2: Tabla ----------
        tabla_panel = self._panel(self._scroll_body)
        tabla_panel.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        tabla_panel.grid_rowconfigure(0, weight=1)
        tabla_panel.grid_columnconfigure(0, weight=1)

        columnas = ("ID", "Nombre", "Teléfono", "Dirección", "Deuda")
        self.tree = self._tree_with_scrolls(tabla_panel, columnas, height=12)

        for col, width, anchor in (
            ("ID", 80, "center"),
            ("Nombre", 260, "w"),
            ("Teléfono", 160, "center"),
            ("Dirección", 260, "w"),
            ("Deuda", 120, "e"),
        ):
            self.tree.heading(col, text=col)
            self.tree.column(
                col,
                width=width,
                anchor=anchor,
                stretch=(col in ("Nombre", "Teléfono", "Dirección")))

        self._setup_sorting(
            tree=self.tree,
            columnas=columnas,
            tipos={"ID": "int", "Nombre": "str", "Teléfono": "str", "Dirección": "str", "Deuda": "money"},
        )

        # Doble clic para modificar
        self.tree.bind("<Double-1>", lambda _e: self.modificar_cliente())
        # Supr elimina
        self.tree.bind("<Delete>", lambda _e: self.eliminar_cliente())

        # ---------- Fila 3: Botones ----------
        btn_frame = self._panel(self._scroll_body)
        btn_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))

        # Primera fila (ya la tienes)
        for c in range(5):
            btn_frame.grid_columnconfigure(c, weight=1, uniform="btns")

        self._btn(btn_frame, "Actualizar Deuda", "TButton", self.actualizar_deuda,
                row=0, column=0, padx=5, pady=4, sticky="ew")
        self._btn(btn_frame, "Abonar Monto", "Success.TButton", self.abonar_monto,
                row=0, column=1, padx=5, pady=4, sticky="ew")
        self._btn(btn_frame, "Pagar Deuda", "Danger.TButton", self.pagar_deuda,
                row=0, column=2, padx=5, pady=4, sticky="ew")
        self._btn(btn_frame, "Modificar Cliente", "TButton", self.modificar_cliente,
                row=0, column=3, padx=5, pady=4, sticky="ew")
        self._btn(btn_frame, "Eliminar Cliente", "Danger.TButton", self.eliminar_cliente,
                row=0, column=4, padx=5, pady=4, sticky="ew")
        
        self._build_ui_gestion_por_venta()
        self._cargar_clientes_combo_creditos()
        self._rango_hoy()  
        
    # -------------------------------------------------------
    # Data / Listado
    # -------------------------------------------------------
    def cargar_clientes(self, filtro: str = ""):
        """Llena la tabla de clientes (incluye dirección si la columna existe)."""
        self.tree.delete(*self.tree.get_children())
        try:
            with get_connection() as conn:
                # Detectar si existe la columna direccion
                try:
                    cols = conn.execute("PRAGMA table_info(clientes)").fetchall()
                    colnames = {str(c[1]).lower() for c in cols}
                    has_dir = ("direccion" in colnames)
                except Exception:
                    has_dir = False

                if filtro:
                    like = f"%{filtro}%"
                    if has_dir:
                        rows = conn.execute(
                            """
                            SELECT id, nombre, telefono, direccion, deuda_total
                            FROM clientes
                            WHERE nombre LIKE ? OR telefono LIKE ? OR IFNULL(direccion,'') LIKE ?
                            ORDER BY nombre COLLATE NOCASE
                            """,
                            (like, like, like),
                        ).fetchall()
                    else:
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
                    if has_dir:
                        rows = conn.execute(
                            "SELECT id, nombre, telefono, direccion, deuda_total FROM clientes ORDER BY nombre COLLATE NOCASE"
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            "SELECT id, nombre, telefono, deuda_total FROM clientes ORDER BY nombre COLLATE NOCASE"
                        ).fetchall()

                # Insertar filas en la tabla
                if has_dir:
                    for r in rows:
                        cid, nombre, tel, dir_, deuda = r[0], r[1], r[2], (r[3] or ""), float(r[4] or 0)
                        self.tree.insert("", "end", values=(cid, nombre, tel or "", dir_, formato_moneda(deuda)))
                else:
                    for r in rows:
                        cid, nombre, tel, deuda = r[0], r[1], r[2], float(r[3] or 0)
                        self.tree.insert("", "end", values=(cid, nombre, tel or "", "", formato_moneda(deuda)))

            set_treeview_stripes(self.tree, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los clientes.\n{e}")


    def filtrar_clientes(self, _event=None):
        self.cargar_clientes((self.buscar_entry.get() or "").strip())

    def actualizar_deuda(self):
        """Recalcula deuda_total desde ventas/pagos y refresca la tabla."""
        self._recalcular_deuda_todos()
        self.cargar_clientes()
        messagebox.showinfo("Info", "Las deudas se recalcularon desde ventas y pagos.")


    # -------------------------------------------------------
    # CRUD Clientes
    # -------------------------------------------------------
    def agregar_cliente(self):
        """Inserta un cliente nuevo con deuda inicial 0.00 (compatible con esquema con/sin 'direccion')."""
        nombre = (self.nombre_entry.get() or "").strip()
        telefono = (self.telefono_entry.get() or "").strip()
        # Puede que aún no exista la caja de dirección; si no está, usamos ""
        direccion_entry = getattr(self, "direccion_entry", None)
        direccion = (direccion_entry.get() or "").strip() if direccion_entry else ""

        if not nombre:
            messagebox.showerror("Error", "El nombre es obligatorio.")
            return

        try:
            with get_connection() as conn:
                # ¿La tabla clientes tiene columna 'direccion'?
                has_dir = False
                try:
                    cols = conn.execute("PRAGMA table_info(clientes)").fetchall()
                    colnames = {str(c[1]).lower() for c in cols}
                    has_dir = ("direccion" in colnames)
                except Exception:
                    has_dir = False

                if has_dir:
                    # 4 columnas -> 4 valores
                    conn.execute(
                        "INSERT INTO clientes (nombre, telefono, direccion, deuda_total) VALUES (?, ?, ?, ?)",
                        (nombre, telefono, direccion, 0.0),
                    )
                else:
                    # Esquema legacy (sin 'direccion')
                    conn.execute(
                        "INSERT INTO clientes (nombre, telefono, deuda_total) VALUES (?, ?, ?)",
                        (nombre, telefono, 0.0),
                    )

            messagebox.showinfo("Éxito", "Cliente registrado.")
            self.nombre_entry.delete(0, tk.END)
            self.telefono_entry.delete(0, tk.END)
            if direccion_entry:
                direccion_entry.delete(0, tk.END)
            self.cargar_clientes()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar el cliente.\n{e}")


    def _cliente_sel(self):
        item = self.tree.focus()
        if not item:
            return None
        vals = self.tree.item(item, "values")
        if not vals:
            return None
        try:
            deuda = to_float(vals[4], permitir_cero=True)
        except Exception:
            deuda = 0.0
        return int(vals[0]), vals[1], vals[2], float(deuda)

    def modificar_cliente(self):
        """Abre un modal para editar nombre/teléfono/(dirección si existe) del cliente seleccionado."""
        sel = self._cliente_sel()
        if not sel:
            messagebox.showerror("Error", "Selecciona un cliente para modificar.")
            return
        cliente_id, nombre_act, tel_act, _deuda = sel

        # --- detectar si existe la columna 'direccion' y obtener valor actual ---
        has_dir, dir_act = False, ""
        try:
            with get_connection() as conn:
                cols = conn.execute("PRAGMA table_info(clientes)").fetchall()
                colnames = {str(c[1]).lower() for c in cols}
                has_dir = ("direccion" in colnames)
                if has_dir:
                    row = conn.execute("SELECT direccion FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
                    dir_act = (row[0] or "") if row else ""
        except Exception:
            has_dir, dir_act = False, ""

        win = tk.Toplevel(self)
        win.title("Modificar Cliente")
        try:
            win.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        win.bind("<Escape>", lambda _e: win.destroy())

        # --- Nombre ---
        self._lbl(win, "Nombre:", row=0, column=0, padx=10, pady=10, sticky="e")
        ent_nombre = self._entry(win, width=32, row=0, column=1, padx=10, pady=10, sticky="we")
        ent_nombre.insert(0, nombre_act)

        # --- Teléfono ---
        self._lbl(win, "Teléfono:", row=1, column=0, padx=10, pady=10, sticky="e")
        ent_tel = self._entry(win, width=20, row=1, column=1, padx=10, pady=10, sticky="we")
        ent_tel.insert(0, tel_act)

        # --- Dirección (opcional según esquema) ---
        if has_dir:
            self._lbl(win, "Dirección:", row=2, column=0, padx=10, pady=10, sticky="e")
            ent_dir = self._entry(win, width=36, row=2, column=1, padx=10, pady=10, sticky="we")
            ent_dir.insert(0, dir_act)
            row_btn = 3
        else:
            ent_dir = None
            row_btn = 2

        win.grid_columnconfigure(1, weight=1)

        def guardar(_=None):
            n = (ent_nombre.get() or "").strip()
            t = (ent_tel.get() or "").strip()
            d = (ent_dir.get() or "").strip() if ent_dir else None
            if not n:
                messagebox.showerror("Error", "El nombre es obligatorio.", parent=win)
                return
            try:
                with get_connection() as conn:
                    if has_dir:
                        conn.execute(
                            "UPDATE clientes SET nombre = ?, telefono = ?, direccion = ? WHERE id = ?",
                            (n, t, d, cliente_id),
                        )
                    else:
                        conn.execute(
                            "UPDATE clientes SET nombre = ?, telefono = ? WHERE id = ?",
                            (n, t, cliente_id),
                        )
                messagebox.showinfo("Éxito", "Cliente modificado correctamente.", parent=win)
                self.cargar_clientes()
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo modificar el cliente.\n{e}", parent=win)

        ttk.Button(win, text="Guardar", command=guardar, style="Success.TButton")\
            .grid(row=row_btn, column=0, columnspan=2, pady=10)
        win.bind("<Return>", guardar)

        # --- asegurar visibilidad y luego tomar el grab (evita 'grab failed: window not viewable') ---
        try:
            win.update_idletasks()
            win.deiconify()
            win.transient(self.winfo_toplevel())
            win.wait_visibility(win)
            win.grab_set()
            (ent_nombre if not has_dir else ent_dir).focus_set()
        except Exception:
            pass

    def eliminar_cliente(self):
        """
        Elimina el cliente seleccionado si NO tiene registros vinculados.
        - ventas.cliente_id
        - pagos_cliente / pagos_credito
        """
        sel = self._cliente_sel()
        if not sel:
            messagebox.showerror("Error", "Selecciona un cliente para eliminar.")
            return
        cliente_id, nombre, _tel, _deuda = sel

        if not messagebox.askyesno("Confirmar", f"¿Eliminar definitivamente al cliente '{nombre}'?"):
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                refs = 0
                try:
                    refs += cur.execute("SELECT COUNT(*) FROM ventas WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]
                except Exception:
                    pass
                # pagos_cliente preferente; legacy pagos_credito
                if self._tabla_pagos == "pagos_cliente":
                    refs += cur.execute("SELECT COUNT(*) FROM pagos_cliente WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]
                elif self._tabla_pagos == "pagos_credito":
                    refs += cur.execute("SELECT COUNT(*) FROM pagos_credito WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]
                else:
                    # Intentar ambas por si existen
                    try:
                        refs += cur.execute("SELECT COUNT(*) FROM pagos_cliente WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]
                    except Exception:
                        pass
                    try:
                        refs += cur.execute("SELECT COUNT(*) FROM pagos_credito WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]
                    except Exception:
                        pass

                if refs > 0:
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

    # -------------------------------------------------------
    # Operaciones de crédito
    # -------------------------------------------------------
    def pagar_deuda(self):
        """Pone la deuda_total del cliente en 0 y registra pago total en la tabla de pagos disponible."""
        sel = self._cliente_sel()

        if not sel:
            messagebox.showerror("Error", "Selecciona un cliente.")
            return
        cliente_id, nombre, _tel, deuda_actual = sel

        if deuda_actual <= 0:
            messagebox.showinfo("Info", "Este cliente no tiene deudas.")
            return

        if not messagebox.askyesno(
            "Confirmar", f"¿Marcar como pagada la deuda de {formato_moneda(deuda_actual)} de '{nombre}'?"
        ):
            return

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                # 1) Registrar pago total (si existe tabla de pagos)
                if self._tabla_pagos == "pagos_cliente":
                    cur.execute(
                        "INSERT INTO pagos_cliente (cliente_id, venta_id, monto, fecha, nota) "
                        "VALUES (?, NULL, ?, datetime('now','localtime'), ?)",
                        (cliente_id, redondear_dos_decimales(deuda_actual), "Liquidación de deuda"),
                    )
                elif self._tabla_pagos == "pagos_credito":
                    cur.execute(
                        "INSERT INTO pagos_credito (cliente_id, monto, descripcion) VALUES (?, ?, ?)",
                        (cliente_id, redondear_dos_decimales(deuda_actual), "Liquidación de deuda"),
                    )
                # 2) Dejar deuda en 0
                cur.execute("UPDATE clientes SET deuda_total = 0 WHERE id = ?", (cliente_id,))
            self.cargar_clientes()
            messagebox.showinfo("Éxito", "Deuda pagada correctamente.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo actualizar la deuda.\n{e}")

    def abonar_monto(self):
        """Realiza un pago parcial a la deuda del cliente y registra la bitácora."""
        sel = self._cliente_sel()
        if not sel:
            messagebox.showerror("Error", "Selecciona un cliente.")
            return
        cliente_id, nombre, _tel, deuda_actual = sel

        if deuda_actual <= 0:
            messagebox.showinfo("Info", f"'{nombre}' no tiene deuda pendiente.")
            return

        # Modal de abono
        win = tk.Toplevel(self)
        win.title(f"Abonar a: {nombre}")
        try:
            win.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        win.bind("<Escape>", lambda _e: win.destroy())

        ttk.Label(win, text=f"Deuda actual: {formato_moneda(deuda_actual)}", style="Brand.TLabel").grid(
            row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w"
        )

        ttk.Label(win, text="Monto a abonar:", style="Brand.TLabel").grid(row=1, column=0, padx=12, pady=6, sticky="e")
        ent_monto = ttk.Entry(win, width=18, style="TEntry")
        ent_monto.grid(row=1, column=1, padx=12, pady=6, sticky="w")
        adjuntar_validador_2_decimales(ent_monto, permitir_vacio=False)

        def confirmar(_=None):
            txt = (ent_monto.get() or "").strip()
            try:
                abono = to_float(txt, permitir_cero=False)  # debe ser > 0
            except ValueError:
                messagebox.showerror("Error", "Ingresa un monto válido.", parent=win)
                return

            aplicado = min(abono, deuda_actual)
            aplicado_red = redondear_dos_decimales(aplicado)
            if aplicado_red <= 0:
                messagebox.showerror("Error", "El abono debe ser mayor a 0.", parent=win)
                return

            nuevo_saldo = max(0.0, redondear_dos_decimales(deuda_actual - aplicado_red))

            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    # 1) Registrar bitácora (monto POSITIVO)
                    if self._tabla_pagos == "pagos_cliente":
                        cur.execute(
                            "INSERT INTO pagos_cliente (cliente_id, venta_id, monto, fecha, nota) "
                            "VALUES (?, NULL, ?, datetime('now','localtime'), ?)",
                            (cliente_id, aplicado_red, "Abono a crédito"),
                        )
                    elif self._tabla_pagos == "pagos_credito":
                        cur.execute(
                            "INSERT INTO pagos_credito (cliente_id, monto, descripcion) VALUES (?, ?, ?)",
                            (cliente_id, aplicado_red, "Abono a crédito"),
                        )
                    # 2) Ajustar saldo mostrado (protección a 2 decimales)
                    cur.execute("UPDATE clientes SET deuda_total = ? WHERE id = ?", (nuevo_saldo, cliente_id))

                # Recalcular desde ventas/pagos para asegurar sincronía global
                try:
                    self._recalcular_deuda_global_cliente(cliente_id)
                except Exception:
                    pass

                # Refrescos de UI
                self.cargar_clientes()
                try:
                    self._recargar_panel_creditos()
                except Exception:
                    pass

                messagebox.showinfo(
                    "Éxito",
                    f"Se abonó {formato_moneda(aplicado_red)} a '{nombre}'.\n"
                    f"Saldo restante: {formato_moneda(nuevo_saldo)}.",
                    parent=win,
                )
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo registrar el abono.\n{e}", parent=win)

        ttk.Button(win, text="Abonar", command=confirmar, style="Success.TButton")\
            .grid(row=2, column=0, columnspan=2, pady=12)
        win.bind("<Return>", confirmar)

        # --- asegurar visibilidad y luego tomar el grab ---
        try:
            win.update_idletasks()
            win.deiconify()
            win.transient(self.winfo_toplevel())
            win.wait_visibility(win)
            win.grab_set()
            win.focus_set()
            ent_monto.focus_set()
        except Exception:
            pass
        
    def _recalcular_deuda_todos(self):
        """Recalcula clientes.deuda_total a partir de ventas y pagos (sin fechas)."""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                if self._tabla_pagos == "pagos_cliente" and self._pagos_has_venta_id:
                    # Suma de (total venta - pagos por venta), excluyendo CANCELADAS
                    cur.execute("""
                        UPDATE clientes AS c
                        SET deuda_total = IFNULL((
                            SELECT ROUND(SUM(
                                IFNULL(v.total, v.kilos * v.precio) -
                                IFNULL((SELECT SUM(monto) FROM pagos_cliente pc WHERE pc.venta_id = v.id), 0)
                            ), 2)
                            FROM ventas v
                            WHERE LOWER(IFNULL(v.tipo_venta,''))='credito'
                            AND v.cliente_id = c.id
                            AND UPPER(IFNULL(v.estado,'')) <> 'CANCELADA'
                        ), 0)
                    """)
                elif self._tabla_pagos == "pagos_credito":
                    # Legacy: total crédito - sum(pagos_credito)
                    cur.execute("""
                        UPDATE clientes AS c
                        SET deuda_total = IFNULL((
                            SELECT ROUND(
                                IFNULL((
                                    SELECT SUM(IFNULL(v.total, v.kilos * v.precio))
                                    FROM ventas v
                                    WHERE LOWER(IFNULL(v.tipo_venta,''))='credito'
                                    AND v.cliente_id = c.id
                                    AND UPPER(IFNULL(v.estado,'')) <> 'CANCELADA'
                                ), 0)
                                - IFNULL((
                                    SELECT SUM(monto) FROM pagos_credito pc WHERE pc.cliente_id = c.id
                                ), 0)
                            , 2)
                        ), 0)
                    """)
                # Si no existe tabla de pagos, no hay nada que recalcular más allá de lo ya guardado.
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo recalcular la deuda.\n{e}")


    def _recalcular_deuda_global_cliente(self, cid: int):
        """Recalcula la deuda_total de UN cliente desde ventas/pagos."""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                if self._tabla_pagos == "pagos_cliente" and self._pagos_has_venta_id:
                    row = cur.execute("""
                        SELECT ROUND(SUM(
                            IFNULL(v.total, v.kilos * v.precio) -
                            IFNULL((SELECT SUM(monto) FROM pagos_cliente pc WHERE pc.venta_id = v.id), 0)
                        ), 2)
                        FROM ventas v
                        WHERE LOWER(IFNULL(v.tipo_venta,''))='credito'
                        AND v.cliente_id = ?
                        AND UPPER(IFNULL(v.estado,'')) <> 'CANCELADA'
                    """, (cid,)).fetchone()
                    deuda = float(row[0] or 0.0)
                elif self._tabla_pagos == "pagos_credito":
                    tot = cur.execute("""
                        SELECT IFNULL(SUM(IFNULL(v.total, v.kilos * v.precio)), 0)
                        FROM ventas v
                        WHERE LOWER(IFNULL(v.tipo_venta,''))='credito'
                        AND v.cliente_id = ?
                        AND UPPER(IFNULL(v.estado,'')) <> 'CANCELADA'
                    """, (cid,)).fetchone()[0] or 0.0
                    pags = cur.execute("""
                        SELECT IFNULL(SUM(monto), 0) FROM pagos_credito WHERE cliente_id = ?
                    """, (cid,)).fetchone()[0] or 0.0
                    deuda = round(float(tot) - float(pags), 2)
                    if deuda < 0: deuda = 0.0
                else:
                    # Sin tabla de pagos: usa el valor guardado (no tocar)
                    return
                cur.execute("UPDATE clientes SET deuda_total = ? WHERE id = ?", (deuda, cid))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo recalcular la deuda del cliente.\n{e}")

        
# ---------- Gestión por VENTA (UI estilo panel proveedor) ----------

    def _build_ui_gestion_por_venta(self):
        wrapper = tk.LabelFrame(self._scroll_body, text="Gestión de Créditos por Venta", bg=PALETTE["panel"], fg=PALETTE["text"], bd=0)
        wrapper.grid(row=4, column=0, sticky="nsew", padx=10, pady=(4, 10))
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(2, weight=1)

        # Fila de filtros
        filt = tk.Frame(wrapper, bg=PALETTE["panel"])
        filt.grid(row=0, column=0, sticky="ew", pady=(6, 2))

        # Aumentamos columnas para alojar dos botones 📅 y el botón Recargar al final
        for c in range(10):
            # damos peso a columnas de combobox, a las entradas y al final
            filt.grid_columnconfigure(c, weight=(1 if c in (1, 4, 7, 9) else 0))

        tk.Label(filt, text="Cliente:", bg=PALETTE["panel"], fg=PALETTE["text"])\
        .grid(row=0, column=0, padx=6, pady=4, sticky="e")

        self.cb_cliente = ttk.Combobox(filt, state="readonly", width=28)
        self.cb_cliente.grid(row=0, column=1, padx=4, pady=4, sticky="we")
        self.cb_cliente.bind("<<ComboboxSelected>>", lambda _e: self._recargar_panel_creditos())

        def _dlabel(p, t, r, c):
            tk.Label(p, text=t, bg=PALETTE["panel"], fg=PALETTE["text"])\
            .grid(row=r, column=c, padx=6, pady=4, sticky="e")

        _dlabel(filt, "Desde:", 0, 3)
        self.desde_entry = ttk.Entry(filt, width=12)
        self.desde_entry.grid(row=0, column=4, padx=4, pady=4, sticky="we")

        # Botón calendario para "Desde"
        ttk.Button(
            filt, text="📅", width=3, style="TButton",
            command=lambda: self._popup_calendario(self.desde_entry, fuentes=("all",))
        ).grid(row=0, column=5, padx=(2, 8), pady=4, sticky="w")

        _dlabel(filt, "Hasta:", 0, 6)
        self.hasta_entry = ttk.Entry(filt, width=12)
        self.hasta_entry.grid(row=0, column=7, padx=4, pady=4, sticky="we")

        # Botón calendario para "Hasta"
        ttk.Button(
            filt, text="📅", width=3, style="TButton",
            command=lambda: self._popup_calendario(self.hasta_entry, fuentes=("all",))
        ).grid(row=0, column=8, padx=(2, 8), pady=4, sticky="w")

        ttk.Button(filt, text="Recargar", style="TButton", command=self._recargar_panel_creditos)\
        .grid(row=0, column=9, padx=8, pady=4, sticky="e")


        # Quick ranges
        q = tk.Frame(wrapper, bg=PALETTE["panel"])
        q.grid(row=1, column=0, sticky="w", pady=(0, 6))
        ttk.Button(q, text="Hoy",    command=self._rango_hoy,    style="TButton").pack(side="left", padx=4)
        ttk.Button(q, text="Semana", command=self._rango_semana, style="TButton").pack(side="left", padx=4)
        ttk.Button(q, text="Mes",    command=self._rango_mes,    style="TButton").pack(side="left", padx=4)

        # Split en dos tablas
        split = tk.Frame(wrapper, bg=PALETTE["panel"])
        split.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)

        # Ambas columnas con el mismo "uniform" para 50/50 real
        split.grid_columnconfigure(0, weight=1, uniform="splitcols")
        split.grid_columnconfigure(1, weight=1, uniform="splitcols")
        split.grid_rowconfigure(0, weight=1)

        # Ventas (izquierda)
        left = tk.LabelFrame(split, text="Ventas a crédito", bg=PALETTE["panel"], fg=PALETTE["text"], bd=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
        left.grid_rowconfigure(0, weight=1)     # <- estira el tree
        left.grid_columnconfigure(0, weight=1)  # <- estira el tree

        cols_v = ("Fecha", "Producto", "Cantidad", "Total", "Saldo", "Estatus", "VentaID")
        self.tree_compras = self._tree_with_scrolls(left, cols_v, height=10)
        for col, w, anchor in (
            ("Fecha", 110, "center"),
            ("Producto", 210, "w"),
            ("Cantidad", 100, "e"),
            ("Total", 110, "e"),
            ("Saldo", 110, "e"),
            ("Estatus", 100, "center"),
            ("VentaID", 70, "center"),
        ):
            self.tree_compras.heading(col, text=col)
            # Permite que "Producto" estire para ocupar sobrante
            self.tree_compras.column(col, width=w, anchor=anchor, stretch=(col in ("Producto",)))

        # Pagos (derecha)
        right = tk.LabelFrame(split, text="Pagos / Abonos", bg=PALETTE["panel"], fg=PALETTE["text"], bd=0)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)
        right.grid_rowconfigure(0, weight=1)     # <- estira el tree
        right.grid_columnconfigure(0, weight=1)  # <- estira el tree

        cols_p = ("Fecha", "VentaID", "Descripción", "Monto")
        self.tree_pagos = self._tree_with_scrolls(right, cols_p, height=10)
        for col, w, anchor in (
            ("Fecha", 110, "center"),
            ("VentaID", 70, "center"),
            ("Descripción", 240, "w"),
            ("Monto", 110, "e"),
        ):
            self.tree_pagos.heading(col, text=col)
            # Permite que "Descripción" estire para ocupar sobrante
            self.tree_pagos.column(col, width=w, anchor=anchor, stretch=(col in ("Descripción",)))


        # Acciones
        actions = tk.Frame(wrapper, bg=PALETTE["panel"])
        actions.grid(row=3, column=0, sticky="ew", pady=(6, 4))
        actions.grid_columnconfigure(0, weight=1)
        ttk.Button(actions, text="Abonar a venta seleccionada…", style="Success.TButton", command=self._abonar_a_venta)\
            .pack(side="left", padx=4)
        ttk.Button(actions, text="Ver pagos de la venta", style="TButton", command=self._ver_pagos_de_venta)\
            .pack(side="left", padx=4)
            
        

    def _cargar_clientes_combo_creditos(self):
        try:
            with get_connection() as conn:
                rows = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre COLLATE NOCASE").fetchall()
            self._clientes_combo_map = {r[1]: r[0] for r in rows}
            self.cb_cliente["values"] = list(self._clientes_combo_map.keys())
            if self.cb_cliente["values"]:
                self.cb_cliente.current(0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar clientes para gestión por venta.\n{e}")

    # Rango rápido
    def _rango_hoy(self):
        from datetime import datetime
        hoy = datetime.now().strftime("%Y-%m-%d")
        self.desde_entry.delete(0, tk.END); self.desde_entry.insert(0, hoy)
        self.hasta_entry.delete(0, tk.END); self.hasta_entry.insert(0, hoy)
        self._recargar_panel_creditos()

    def _rango_semana(self):
        from datetime import datetime, timedelta
        fin = datetime.now().date()
        ini = fin - timedelta(days=6)
        self.desde_entry.delete(0, tk.END); self.desde_entry.insert(0, ini.strftime("%Y-%m-%d"))
        self.hasta_entry.delete(0, tk.END); self.hasta_entry.insert(0, fin.strftime("%Y-%m-%d"))
        self._recargar_panel_creditos()

    def _rango_mes(self):
        from datetime import date
        d = date.today()
        ini = date(d.year, d.month, 1).strftime("%Y-%m-%d")
        self.desde_entry.delete(0, tk.END); self.desde_entry.insert(0, ini)
        self.hasta_entry.delete(0, tk.END); self.hasta_entry.insert(0, d.strftime("%Y-%m-%d"))
        self._recargar_panel_creditos()
        
    def _popup_calendario(self, target_entry: ttk.Entry, fuentes=("all",)):
        """
        Abre un popup con el CalendarioWidget y, al seleccionar fecha,
        inserta 'YYYY-MM-DD' en el Entry destino y refresca el panel.
        """
        # callback que escribe la fecha en el entry y refresca
        def _on_date(fecha: str):
            try:
                target_entry.delete(0, tk.END)
                target_entry.insert(0, fecha)
            except Exception:
                pass
            # Actualizar listados automáticamente al elegir fecha
            self._recargar_panel_creditos()

        top = tk.Toplevel(self)
        top.title("Selecciona una fecha")
        try:
            top.configure(bg=PALETTE["bg"])
        except Exception:
            pass

        # Construir el widget
        cal = CalendarioWidget(top, _on_date, fuentes=fuentes)

        # Si el entry ya tiene una fecha válida, abrir ese mes/año
        import datetime as _dt
        txt = (target_entry.get() or "").strip()
        try:
            d = _dt.datetime.strptime(txt, "%Y-%m-%d")
            cal.current_year = d.year
            cal.current_month = d.month
            cal.build_calendar()
        except Exception:
            pass

        # Asegurar modal suave
        try:
            top.transient(self.winfo_toplevel())
            top.grab_set()
            top.focus_set()
        except Exception:
            pass


    def _recargar_panel_creditos(self):
        self._load_ventas_cliente()
        self._load_pagos_cliente()

    def _get_cliente_sel_combo(self):
        nombre = self.cb_cliente.get()
        return self._clientes_combo_map.get(nombre, None)

    def _load_ventas_cliente(self):
        for it in self.tree_compras.get_children():
            self.tree_compras.delete(it)
        cid = self._get_cliente_sel_combo()
        if not cid:
            return
        d1 = (self.desde_entry.get() or "0001-01-01")
        d2 = (self.hasta_entry.get() or "9999-12-31")

        try:
            with get_connection() as conn:
                if self._tabla_pagos == "pagos_cliente" and self._pagos_has_venta_id:
                    # Podemos sumar pagos por venta
                    sql = """
                        SELECT v.fecha,
                               IFNULL(p.nombre,'') AS producto,
                               CASE
                                 WHEN IFNULL(v.unidades,0)>0 THEN CAST(v.unidades AS TEXT)
                                 WHEN IFNULL(v.kilos,0)>0 THEN printf('%.2f kg', v.kilos)
                                 ELSE ''
                               END AS cantidad,
                               IFNULL(v.total, v.kilos * v.precio) AS total_venta,
                               ROUND(
                                 IFNULL(v.total, v.kilos * v.precio) -
                                 IFNULL((SELECT SUM(monto) FROM pagos_cliente pc WHERE pc.venta_id = v.id), 0), 2
                               ) AS saldo,
                               CASE
                                 WHEN UPPER(IFNULL(v.estado,''))='CANCELADA' THEN 'CANCELADA'
                                 WHEN ROUND(
                                   IFNULL(v.total, v.kilos * v.precio) -
                                   IFNULL((SELECT SUM(monto) FROM pagos_cliente pc WHERE pc.venta_id = v.id), 0), 2
                                 ) <= 0 THEN 'PAGADA'
                                 ELSE 'PENDIENTE'
                               END AS estatus,
                               v.id
                        FROM ventas v
                        LEFT JOIN productos p ON p.id = v.producto_id
                        WHERE LOWER(IFNULL(v.tipo_venta,''))='credito'
                          AND v.cliente_id = ?
                          AND DATE(v.fecha) BETWEEN DATE(?) AND DATE(?)
                        ORDER BY v.fecha DESC
                    """
                    rows = conn.execute(sql, (cid, d1, d2)).fetchall()
                else:
                    # NO hay venta_id -> no se puede calcular saldo por venta
                    # Saldo = total_venta (informativo). Estatus = 'PENDIENTE' si total>0 y no cancelada.
                    sql = """
                        SELECT v.fecha,
                               IFNULL(p.nombre,'') AS producto,
                               CASE
                                 WHEN IFNULL(v.unidades,0)>0 THEN CAST(v.unidades AS TEXT)
                                 WHEN IFNULL(v.kilos,0)>0 THEN printf('%.2f kg', v.kilos)
                                 ELSE ''
                               END AS cantidad,
                               IFNULL(v.total, v.kilos * v.precio) AS total_venta,
                               IFNULL(v.total, v.kilos * v.precio) AS saldo,
                               CASE
                                 WHEN UPPER(IFNULL(v.estado,''))='CANCELADA' THEN 'CANCELADA'
                                 ELSE 'PENDIENTE'
                               END AS estatus,
                               v.id
                        FROM ventas v
                        LEFT JOIN productos p ON p.id = v.producto_id
                        WHERE LOWER(IFNULL(v.tipo_venta,''))='credito'
                          AND v.cliente_id = ?
                          AND DATE(v.fecha) BETWEEN DATE(?) AND DATE(?)
                        ORDER BY v.fecha DESC
                    """
                    rows = conn.execute(sql, (cid, d1, d2)).fetchall()

            for (fecha, prod, cant, total, saldo, est, vid) in rows:
                self.tree_compras.insert(
                    "", "end",
                    values=(
                        str(fecha).split(" ")[0],
                        prod,
                        str(cant),
                        formato_moneda(float(total or 0)),
                        formato_moneda(float(saldo or 0)),
                        est,
                        int(vid),
                    )
                )
            set_treeview_stripes(self.tree_compras, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar ventas del cliente.\n{e}")

    def _load_pagos_cliente(self, venta_id: int | None = None):
        for it in self.tree_pagos.get_children():
            self.tree_pagos.delete(it)
        cid = self._get_cliente_sel_combo()
        if not cid:
            return
        d1 = (self.desde_entry.get() or "0001-01-01")
        d2 = (self.hasta_entry.get() or "9999-12-31")

        try:
            with get_connection() as conn:
                if self._tabla_pagos == "pagos_cliente":
                    if self._pagos_has_venta_id:
                        if venta_id:
                            sql = """
                              SELECT fecha, venta_id, IFNULL(nota,''), monto
                              FROM pagos_cliente
                              WHERE cliente_id=? AND venta_id=? AND DATE(fecha) BETWEEN DATE(?) AND DATE(?)
                              ORDER BY fecha DESC
                            """
                            rows = conn.execute(sql, (cid, venta_id, d1, d2)).fetchall()
                        else:
                            sql = """
                              SELECT fecha, venta_id, IFNULL(nota,''), monto
                              FROM pagos_cliente
                              WHERE cliente_id=? AND DATE(fecha) BETWEEN DATE(?) AND DATE(?)
                              ORDER BY fecha DESC
                            """
                            rows = conn.execute(sql, (cid, d1, d2)).fetchall()
                    else:
                        # pagos_cliente sin venta_id -> mostrar pagos sin asociar venta
                        sql = """
                          SELECT fecha, NULL AS venta_id, IFNULL(nota,''), monto
                          FROM pagos_cliente
                          WHERE cliente_id=? AND DATE(fecha) BETWEEN DATE(?) AND DATE(?)
                          ORDER BY fecha DESC
                        """
                        rows = conn.execute(sql, (cid, d1, d2)).fetchall()

                elif self._tabla_pagos == "pagos_credito":
                    # Legacy, no hay venta_id
                    sql = """
                      SELECT NULL AS fecha, NULL AS venta_id, IFNULL(descripcion,''), monto
                      FROM pagos_credito
                      WHERE cliente_id=?
                      ORDER BY ROWID DESC
                    """
                    # Nota: pagos_credito no siempre tiene fecha. Si la tiene, ajústalo a tu esquema.
                    rows = conn.execute(sql, (cid,)).fetchall()
                else:
                    rows = []

            for (fecha, vid, nota, monto) in rows:
                fecha_txt = (str(fecha).split(" ")[0]) if fecha else ""
                self.tree_pagos.insert(
                    "", "end",
                    values=(fecha_txt, ("" if vid is None else int(vid)), nota or "", formato_moneda(float(monto or 0)))
                )
            set_treeview_stripes(self.tree_pagos, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los pagos.\n{e}")


    def _venta_sel(self):
        item = self.tree_compras.focus()
        if not item:
            return None
        vals = self.tree_compras.item(item, "values")
        if not vals:
            return None
        # Índices según columnas definidas: Fecha, Producto, Cantidad, Total, Saldo, Estatus, VentaID
        venta_id = int(vals[6])
        saldo_txt = vals[4]
        try:
            saldo = to_float(saldo_txt, permitir_cero=True)
        except Exception:
            saldo = 0.0
        return venta_id, saldo

    def _abonar_a_venta(self):
        sel = self._venta_sel()
        if not sel:
            messagebox.showinfo("Abono", "Selecciona una venta en la tabla de la izquierda.")
            return

        # Verificar estado de la venta seleccionada de forma segura
        vals_sel = self.tree_compras.item(self.tree_compras.focus(), "values") or ()
        estado = (vals_sel[5].upper() if len(vals_sel) > 5 and vals_sel[5] else "")
        if estado == "CANCELADA":
            messagebox.showwarning("Abono", "No se puede abonar a una venta cancelada.")
            return

        venta_id, saldo_actual = sel
        if saldo_actual <= 0:
            messagebox.showinfo("Abono", "Esta venta ya no tiene saldo pendiente.")
            return
        if not (self._tabla_pagos == "pagos_cliente" and self._pagos_has_venta_id):
            messagebox.showinfo(
                "Abono",
                "Tu base de datos no tiene pagos por venta (pagos_cliente.venta_id). "
                "Primero aplica la migración para habilitar esta función."
            )
            return

        # Modal de monto
        win = tk.Toplevel(self); win.title("Abonar a venta")
        try: win.configure(bg=PALETTE["bg"])
        except Exception: pass
        tk.Label(win, text=f"Saldo actual: {formato_moneda(saldo_actual)}", bg=PALETTE["bg"], fg=PALETTE["text"])\
            .grid(row=0, column=0, columnspan=2, padx=10, pady=(10,6), sticky="w")
        tk.Label(win, text="Monto a abonar:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=10, pady=6, sticky="e")
        ent_monto = ttk.Entry(win, width=14); ent_monto.grid(row=1, column=1, padx=10, pady=6, sticky="w")
        adjuntar_validador_2_decimales(ent_monto, permitir_vacio=False)
        ent_monto.focus_set()

        def confirmar(_=None):
            txt = (ent_monto.get() or "").strip()
            try:
                monto = to_float(txt, permitir_cero=False)  # debe ser > 0
            except Exception:
                messagebox.showerror("Error", "Monto inválido.", parent=win)
                return

            aplicado = min(monto, saldo_actual)
            aplicado_red = redondear_dos_decimales(aplicado)
            if aplicado_red <= 0:
                messagebox.showerror("Error", "El abono debe ser mayor a 0.", parent=win)
                return

            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cid = self._get_cliente_sel_combo()

                    # 1) Insertar abono ligado a la venta (monto POSITIVO)
                    cur.execute(
                        "INSERT INTO pagos_cliente (cliente_id, venta_id, monto, fecha, nota) "
                        "VALUES (?, ?, ?, datetime('now','localtime'), ?)",
                        (cid, venta_id, aplicado_red, "Abono a venta")
                    )
                    # 2) Ajuste rápido del acumulado mostrado
                    cur.execute(
                        "UPDATE clientes SET deuda_total = MAX(0, deuda_total - ?) WHERE id = ?",
                        (aplicado_red, cid)
                    )

                # Recalcular global desde ventas/pagos para asegurar sincronía con el panel de clientes
                try:
                    self._recalcular_deuda_global_cliente(cid)
                except Exception:
                    pass

                # Refrescar paneles
                self._recargar_panel_creditos()
                self.cargar_clientes()

                messagebox.showinfo("Éxito", "Abono registrado.", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo registrar el abono.\n{e}", parent=win)

        ttk.Button(win, text="Abonar", command=confirmar, style="Success.TButton")\
            .grid(row=2, column=0, columnspan=2, pady=10)
        win.bind("<Return>", confirmar)


    def _ver_pagos_de_venta(self):
        sel = self._venta_sel()
        if not sel:
            return
        venta_id, _ = sel
        self._load_pagos_cliente(venta_id=venta_id)

    # -------------------------------------------------------
    # Ordenamiento por columnas (Treeview)
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


# -----------------------------------------------------------
# Punto de entrada desde main.py
# -----------------------------------------------------------
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