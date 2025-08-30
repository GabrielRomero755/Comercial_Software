# modules/gastos.py
# -----------------------------------------------------------
# Sistema de Comercio — Módulo de Gastos
#
# Funcionalidad:
#   - Catálogo de tipos de gasto (alta simple desde modal).
#   - Registro de gastos: tipo, monto, descripción, fecha (auto u opcional).
#   - Asociación opcional a Empleado y/o Cliente (si el esquema lo soporta).
#   - Búsqueda dinámica (tipo/descr./empleado/cliente).
#   - Edición y eliminación de gastos.
#   - Listado con monto formateado y ordenamiento por encabezados.
#
# UX:
#   - Validador 2 decimales (coma/punto), calendario libre, ESC cierra/ENTER confirma.
#   - Supr elimina seleccionado, doble clic edita.
#   - Regla: si tipo == 'Salarios' -> empleado requerido.
#
# Integración dinámica con BD (según migraciones):
#   - Tabla empleados(id, nombre, telefono ...).
#   - gastos.empleado_id  (NULL) → empleados.id
#   - gastos.cliente_id   (NULL) → clientes.id
#   - Si columnas/tablas no existen, la UI se oculta y el módulo opera en modo básico.
# -----------------------------------------------------------

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional
from datetime import datetime

from db.database import get_connection
from modules.calendar_widget import CalendarioWidget
from ui.helpers import (
    to_float,
    formato_moneda,
    es_fecha_ok,
    normalizar_fecha,
    adjuntar_validador_2_decimales,
)
from ui.theme import (
    apply_brand_ttk_theme,
    stylize_combobox_dropdown,
    set_treeview_stripes,
    BRAND_PALETTE,
)

PALETTE = BRAND_PALETTE


class GastosFrame(tk.Frame):
    # Flags de esquema (dinámicos)
    _has_proveedores: bool = False
    _has_compras: bool = False
    _has_empleados: bool = False
    _gastos_has_proveedor_fk: bool = False
    _gastos_has_compra_fk: bool = False
    _gastos_has_empleado_fk: bool = False
    _gastos_has_cliente_fk: bool = False

    def __init__(self, master=None):
        super().__init__(master, bg=PALETTE["bg"])

        # Tema / estilos unificados
        self._style = apply_brand_ttk_theme(self)
        self._tree_style_name = "Brand.Treeview"

        # Layout raíz (grid): 0=form, 1=busqueda, 2=tabla, 3=acciones
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)
        self.grid_columnconfigure(0, weight=1)

        # Detectar esquema y construir UI
        self._detectar_esquema()
        self._build_ui()

        # Carga de catálogos y listado
        self._cargar_tipos_gasto()
        self._cargar_empleados()
        self._cargar_clientes()
        self.cargar_gastos()

        # Atajos generales
        try:
            for w in (self.tipo_combo, self.monto_entry, self.descripcion_entry, self.fecha_entry):
                w.bind("<Return>", lambda _: self.registrar_gasto())
            if self._empleado_combo is not None:
                self._empleado_combo.bind("<Return>", lambda _: self.registrar_gasto())
            if self._cliente_combo is not None:
                self._cliente_combo.bind("<Return>", lambda _: self.registrar_gasto())
            self.tree.bind("<Delete>", lambda _: self.eliminar_gasto())
            self.tree.bind("<Double-1>", lambda _: self.editar_gasto())
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
                r = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='empleados' LIMIT 1"
                ).fetchone()
                self._has_empleados = bool(r)

                # ---- NUEVO: proveedores/compras ----
                r = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='proveedores' LIMIT 1"
                ).fetchone()
                self._has_proveedores = bool(r)

                r = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compras' LIMIT 1"
                ).fetchone()
                self._has_compras = bool(r)

                # Columnas opcionales en gastos
                cols = {row[1] for row in conn.execute("PRAGMA table_info(gastos)").fetchall()}
                self._gastos_has_empleado_fk = "empleado_id" in cols
                self._gastos_has_cliente_fk = "cliente_id" in cols
                # ---- NUEVO: FKs opcionales en gastos ----
                self._gastos_has_proveedor_fk = "proveedor_id" in cols
                self._gastos_has_compra_fk = "compra_id" in cols

        except Exception:
                self._has_empleados = False
                self._has_proveedores = False
                self._has_compras = False
                self._gastos_has_empleado_fk = False
                self._gastos_has_cliente_fk = False
                self._gastos_has_proveedor_fk = False
                self._gastos_has_compra_fk = False

    # -------------------------------------------------------
    # UI helpers (¡sin pack implícito!)
    # -------------------------------------------------------
    def _panel(self, parent):
        """Crea un contenedor sin gestionar geometría (el llamador usa grid)."""
        return tk.Frame(parent, bg=PALETTE["panel"], bd=0, highlightthickness=0)

    def _lbl(self, parent, text, **grid):
        w = tk.Label(parent, text=text, bg=parent["bg"], fg=PALETTE["text"])
        if grid:
            w.grid(**grid)
        return w

    def _entry(self, parent, width=16, **grid):
        e = ttk.Entry(parent, width=width, style="TEntry")
        if grid:
            e.grid(**grid)
        return e

    def _btn(self, parent, text, style, cmd, **grid):
        """Crea un botón; el llamador SIEMPRE debe pasar parámetros de grid."""
        b = ttk.Button(parent, text=text, command=cmd, style=style)
        if grid:
            b.grid(**grid)
        return b

    def _combobox(self, parent, width=24, **grid):
        cb = ttk.Combobox(parent, state="readonly", width=width, style="TCombobox")
        if grid:
            cb.grid(**grid)
        # Colorear dropdown
        cb.configure(postcommand=lambda c=cb: stylize_combobox_dropdown(c, PALETTE))
        return cb

    def _tree_with_scrolls(self, parent, columnas, height=12):
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
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        scroll_y.config(command=tree.yview)
        scroll_x.config(command=tree.xview)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        return tree

    # -------------------------------------------------------
    # Construcción de interfaz
    # -------------------------------------------------------
    def _build_ui(self):
        # ---------- Formulario ----------
        form = self._panel(self)
        form.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        for c in range(8):
            form.grid_columnconfigure(c, weight=(1 if c in (1, 3, 5, 7) else 0))

        # Tipo
        self._lbl(form, "Tipo de Gasto:", row=0, column=0, sticky="e", padx=8, pady=6)
        self.tipo_combo = self._combobox(form, width=28, row=0, column=1, sticky="we", padx=4, pady=6)
        self._btn(form, "Añadir tipo", "TButton", self._abrir_modal_nuevo_tipo, row=0, column=2, padx=8, pady=6, sticky="w")

        # Monto + Descripción
        self._lbl(form, "Monto:", row=1, column=0, sticky="e", padx=8, pady=6)
        self.monto_entry = self._entry(form, width=16, row=1, column=1, sticky="we", padx=4, pady=6)
        adjuntar_validador_2_decimales(self.monto_entry, permitir_vacio=False)

        self._lbl(form, "Descripción (opcional):", row=1, column=2, sticky="e", padx=8, pady=6)
        self.descripcion_entry = self._entry(form, width=42, row=1, column=3, padx=4, pady=6, sticky="we")

        # Fecha
        self._lbl(form, "Fecha (YYYY-MM-DD):", row=0, column=3, sticky="e", padx=8, pady=6)

        # Contenedor para entrada + botón calendario
        fecha_frame = tk.Frame(form, bg=PALETTE["panel"])
        fecha_frame.grid(row=0, column=4, padx=4, pady=6, sticky="w")

        self.fecha_entry = ttk.Entry(fecha_frame, width=14, style="TEntry")
        self.fecha_entry.pack(side="left", fill="x")

        btn_cal = ttk.Button(fecha_frame, text="📅", style="TButton", command=lambda: self._abrir_calendario(self.fecha_entry))
        btn_cal.pack(side="left", padx=(2, 0))  # separadito con 2px


        # Empleado (opcional / requerido si tipo == Salarios)
        self._empleado_combo: Optional[ttk.Combobox] = None
        self._cliente_combo: Optional[ttk.Combobox] = None

        col_base = 0
        if self._has_empleados and self._gastos_has_empleado_fk:
            self._lbl(form, "Empleado:", row=2, column=0, sticky="e", padx=8, pady=6)
            self._empleado_combo = self._combobox(form, width=28, row=2, column=1, sticky="we", padx=4, pady=6)
            self._btn(form, "Gestionar Empleados", "TButton", self._abrir_crud_empleados, row=2, column=2, padx=8, pady=6, sticky="w")
            col_base = 3  # desplaza cliente a la derecha

        # Cliente (opcional)
        if self._gastos_has_cliente_fk:
            self._lbl(form, "Cliente:", row=2, column=col_base, sticky="e", padx=8, pady=6)
            self._cliente_combo = self._combobox(form, width=28, row=2, column=col_base + 1, sticky="we", padx=4, pady=6)
            self._btn(form, "Gestionar Clientes", "TButton", self._abrir_crud_clientes, row=2, column=col_base + 2, padx=8, pady=6, sticky="w")


        self._btn(form, "Registrar Gasto", "Success.TButton", self.registrar_gasto, row=3, column=0, columnspan=8, pady=10)

        # ---- Abono a compra (proveedor) ----
        if self._has_proveedores and self._has_compras:
            self._btn(
                form,
                "Abonar compra (proveedor)",
                "TButton",
                self._abrir_modal_abono_compra,
                row=4, column=0, columnspan=8, pady=(0, 12)
            )

        # ---------- Búsqueda ----------
        search = self._panel(self)
        search.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 0))
        search.grid_columnconfigure(1, weight=1)
        self._lbl(search, "Buscar (tipo/descr./empleado/cliente):", row=0, column=0, sticky="e", padx=8, pady=6)
        self.buscar_entry = self._entry(search, width=36, row=0, column=1, padx=4, pady=6, sticky="we")
        self.buscar_entry.bind("<KeyRelease>", self._on_buscar_changed)

        # ---------- Tabla ----------
        tabla = self._panel(self)
        tabla.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)

        # 1) Definir las columnas base y condicionales
        columnas = ["ID", "Tipo", "Monto", "Descripción", "Fecha"]
        if self._gastos_has_empleado_fk:
            columnas.append("Empleado")
        if self._gastos_has_cliente_fk:
            columnas.append("Cliente")
        if self._gastos_has_proveedor_fk:
            columnas.append("Proveedor")
        columnas = tuple(columnas)

        # 2) Crear el Treeview
        self.tree = self._tree_with_scrolls(tabla, columnas, height=12)

        # 3) Anchos / Alineaciones (agrega ‘Proveedor’)
        widths = {
            "ID": 70, "Tipo": 170, "Monto": 110, "Descripción": 360, "Fecha": 150,
            "Empleado": 200, "Cliente": 220, "Proveedor": 220
        }
        anchors = {
            "ID": "center", "Tipo": "w", "Monto": "e", "Descripción": "w", "Fecha": "center",
            "Empleado": "w", "Cliente": "w", "Proveedor": "w"
        }

        for col in columnas:
            self.tree.heading(col, text=col)
            self.tree.column(
                col,
                width=widths.get(col, 120),
                anchor=anchors.get(col, "w"),
                # que sea “stretch” si es de texto largo
                stretch=(col in ("Tipo", "Descripción", "Empleado", "Cliente", "Proveedor"))
            )

        # 4) Tipos para ordenamiento (agrega ‘Proveedor’)
        tipos_sort = {"ID": "int", "Tipo": "str", "Monto": "money", "Descripción": "str", "Fecha": "date"}
        if self._gastos_has_empleado_fk:
            tipos_sort["Empleado"] = "str"
        if self._gastos_has_cliente_fk:
            tipos_sort["Cliente"] = "str"
        if self._gastos_has_proveedor_fk:
            tipos_sort["Proveedor"] = "str"

        self._setup_sorting(self.tree, columnas, tipos_sort)


        # ---------- Acciones ----------
        acciones = self._panel(self)
        acciones.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
        for c in range(3):
            acciones.grid_columnconfigure(c, weight=1, uniform="btns")

        self._btn(acciones, "Editar seleccionado", "TButton", self.editar_gasto, row=0, column=0, padx=5, pady=4, sticky="ew")
        self._btn(acciones, "Eliminar seleccionado", "Danger.TButton", self.eliminar_gasto, row=0, column=1, padx=5, pady=4, sticky="ew")
        self._btn(acciones, "Refrescar", "TButton", self.cargar_gastos, row=0, column=2, padx=5, pady=4, sticky="ew")

    # -------------------------------------------------------
    # Calendario (modo libre)
    # -------------------------------------------------------
    def _abrir_calendario(self, entry_widget: tk.Entry):
        top = tk.Toplevel(self)
        top.title("Seleccionar fecha")
        try:
            top.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        top.transient(self.winfo_toplevel())
        top.grab_set()
        CalendarioWidget(top, entry_widget, fuentes=("all",))

    # -------------------------------------------------------
    # Catálogos
    # -------------------------------------------------------
    def _cargar_tipos_gasto(self):
        try:
            with get_connection() as conn:
                rows = conn.execute("SELECT nombre FROM tipos_gasto ORDER BY nombre COLLATE NOCASE").fetchall()
            tipos = [r[0] if isinstance(r, tuple) else r["nombre"] for r in rows]
            self.tipo_combo["values"] = tipos
            if tipos and not self.tipo_combo.get():
                self.tipo_combo.current(0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los tipos de gasto.\n{e}")

    def _cargar_empleados(self):
        if not (self._has_empleados and self._gastos_has_empleado_fk and self._empleado_combo):
            return
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, nombre FROM empleados ORDER BY nombre COLLATE NOCASE"
                ).fetchall()
            self._empleados_map = {
                (r[1] if isinstance(r, tuple) else r["nombre"]): (r[0] if isinstance(r, tuple) else r["id"])
                for r in rows
            }
            self._empleado_combo["values"] = list(self._empleados_map.keys())
            # ⬇️ Dejar SIEMPRE vacío por defecto, como el de cliente
            self._empleado_combo.set("")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los empleados.\n{e}")


    def _cargar_clientes(self):
        if not (self._gastos_has_cliente_fk and self._cliente_combo):
            return
        try:
            with get_connection() as conn:
                rows = conn.execute("SELECT id, nombre FROM clientes ORDER BY nombre COLLATE NOCASE").fetchall()
            self._clientes_map = {
                (r[1] if isinstance(r, tuple) else r["nombre"]): (r[0] if isinstance(r, tuple) else r["id"])
                for r in rows
            }
            self._cliente_combo["values"] = list(self._clientes_map.keys())
            self._cliente_combo.set("")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los clientes.\n{e}")


    def _abrir_modal_nuevo_tipo(self):
        """Modal para agregar un nuevo tipo al catálogo."""
        win = tk.Toplevel(self)
        win.title("Nuevo tipo de gasto")
        try:
            win.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.bind("<Escape>", lambda _: win.destroy())

        tk.Label(win, text="Nombre del nuevo tipo:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=10, pady=10, sticky="e")
        ent_tipo = ttk.Entry(win, width=28, style="TEntry")
        ent_tipo.grid(row=0, column=1, padx=10, pady=10)
        ent_tipo.focus()

        def guardar(_=None):
            nombre = (ent_tipo.get() or "").strip()
            if not nombre:
                messagebox.showerror("Error", "El nombre no puede estar vacío.", parent=win)
                return
            try:
                with get_connection() as conn:
                    conn.execute("INSERT INTO tipos_gasto (nombre) VALUES (?)", (nombre,))
                self._cargar_tipos_gasto()
                messagebox.showinfo("Éxito", f"Tipo '{nombre}' agregado.", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo agregar el tipo.\n{e}", parent=win)

        ttk.Button(win, text="Guardar", command=guardar, style="Success.TButton").grid(row=1, column=0, columnspan=2, pady=10)
        win.bind("<Return>", guardar)

    def _abrir_modal_abono_compra(self):
        """Modal para registrar un abono a una compra a crédito (proveedor)."""
        if not (self._has_proveedores and self._has_compras):
            messagebox.showwarning("No disponible", "No existen tablas 'proveedores' y/o 'compras' en la base de datos.")
            return

        win = tk.Toplevel(self)
        win.title("Abonar compra (proveedor)")
        try:
            win.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.bind("<Escape>", lambda _: win.destroy())

        # ---- Proveedor ----
        tk.Label(win, text="Proveedor:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=10, pady=8, sticky="e")
        cb_prov = self._combobox(win, width=36, row=0, column=1, padx=10, pady=8, sticky="we")

        # ---- Compra ----
        tk.Label(win, text="Compra:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=10, pady=8, sticky="e")
        cb_compra = self._combobox(win, width=36, row=1, column=1, padx=10, pady=8, sticky="we")

        # ---- Info saldo ----
        lbl_saldo = tk.Label(win, text="Saldo: $0.00", bg=PALETTE["bg"], fg=PALETTE["text"])
        lbl_saldo.grid(row=1, column=2, padx=8, pady=8, sticky="w")

        # ---- Monto / Fecha / Desc ----
        tk.Label(win, text="Monto abono:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=2, column=0, padx=10, pady=8, sticky="e")
        ent_monto = ttk.Entry(win, width=16, style="TEntry"); ent_monto.grid(row=2, column=1, padx=10, pady=8, sticky="w")
        adjuntar_validador_2_decimales(ent_monto, permitir_vacio=False)

        tk.Label(win, text="Fecha (YYYY-MM-DD):", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=3, column=0, padx=10, pady=8, sticky="e")
        ent_fecha = ttk.Entry(win, width=16, style="TEntry"); ent_fecha.grid(row=3, column=1, padx=(10,0), pady=8, sticky="w")
        ttk.Button(win, text="📅", command=lambda: self._abrir_calendario(ent_fecha), style="TButton").grid(row=3, column=1, padx=(180,0), pady=8, sticky="w")

        tk.Label(win, text="Descripción (opcional):", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=4, column=0, padx=10, pady=8, sticky="e")
        ent_desc = ttk.Entry(win, width=40, style="TEntry"); ent_desc.grid(row=4, column=1, padx=10, pady=8, sticky="we")

        win.grid_columnconfigure(1, weight=1)

        # ---- Cargar proveedores ----
        proveedores_map = {}
        compras_map = {}      # texto -> (compra_id, saldo, total, fecha)

        try:
            with get_connection() as conn:
                rows = conn.execute("SELECT id, nombre FROM proveedores ORDER BY nombre COLLATE NOCASE").fetchall()
            proveedores_map = { (r[1] if isinstance(r, tuple) else r["nombre"]) : (r[0] if isinstance(r, tuple) else r["id"]) for r in rows }
            cb_prov["values"] = list(proveedores_map.keys())
            if cb_prov["values"]:
                cb_prov.current(0)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar proveedores.\n{e}", parent=win)
            win.destroy()
            return

        def cargar_compras_del_proveedor(_=None):
            cb_compra.set("")
            cb_compra["values"] = ()
            lbl_saldo.config(text="Saldo: $0.00")
            compras_map.clear()
            prov_name = (cb_prov.get() or "").strip()
            if not prov_name or prov_name not in proveedores_map:
                return
            prov_id = proveedores_map[prov_name]

            try:
                with get_connection() as conn:
                    cur = conn.cursor()

                    # ¿Existe deudas_proveedores? -> usarla como fuente principal
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deudas_proveedores'")
                    has_deudas = (cur.fetchone() is not None)

                    if has_deudas:
                        # Traer SOLO deudas con saldo > 0 del proveedor
                        cur.execute("""
                            SELECT d.id, d.fecha, d.monto, d.saldo, IFNULL(p.nombre,'(s/n)') AS producto
                            FROM deudas_proveedores d
                            LEFT JOIN productos p ON p.id = d.producto_id
                            WHERE d.proveedor_id = ? AND d.saldo > 0
                            ORDER BY d.fecha DESC, d.id DESC
                        """, (int(prov_id),))
                        rows = cur.fetchall()
                        for did, fecha, total, saldo, prod in rows:
                            texto = f"#D{did} — {fecha.split(' ')[0] if fecha else 's/f'} — {prod or ''} — Total {formato_moneda(total or 0)} — Saldo {formato_moneda(saldo or 0)}"
                            compras_map[texto] = (int(did), float(saldo or 0.0), float(total or 0.0), fecha or "", "DEUDA")
                    else:
                        # Fallback: esquema anterior basado en 'compras'
                        cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(compras)").fetchall()}
                        has_prov_fk = "proveedor_id" in cols
                        total_col = "total" if "total" in cols else ("monto_total" if "monto_total" in cols else None)
                        saldo_col = "saldo_pendiente" if "saldo_pendiente" in cols else ("deuda_restante" if "deuda_restante" in cols else None)
                        fecha_col = "fecha" if "fecha" in cols else None

                        where = "WHERE proveedor_id = ?" if has_prov_fk else ""
                        params = [prov_id] if has_prov_fk else []

                        credito_filter = ""
                        if saldo_col:
                            credito_filter = f"{' AND' if where else 'WHERE'} {saldo_col} > 0"

                        select_cols = ["id"]
                        if total_col: select_cols.append(total_col)
                        if saldo_col: select_cols.append(saldo_col)
                        if fecha_col: select_cols.append(fecha_col)

                        sql = f"SELECT {', '.join(select_cols)} FROM compras {where} {credito_filter} ORDER BY id DESC"
                        rows = conn.execute(sql, tuple(params)).fetchall()

                        for r in rows:
                            rid = r[0]
                            idx = 1
                            total = r[idx] if total_col else 0.0; idx += (1 if total_col else 0)
                            saldo = r[idx] if saldo_col else 0.0;  idx += (1 if saldo_col else 0)
                            fecha = r[idx] if fecha_col else ""
                            texto = f"#{rid} — { (fecha or 's/f') } — Total {formato_moneda(total or 0)} — Saldo {formato_moneda(saldo or 0)}"
                            compras_map[texto] = (int(rid), float(saldo or 0.0), float(total or 0.0), fecha or "", "COMPRA")

                cb_compra["values"] = list(compras_map.keys())
                if cb_compra["values"]:
                    cb_compra.current(0)
                    on_compra_sel()
                else:
                    cb_compra["values"] = ("(Sin deudas/compras pendientes para este proveedor)",)
                    cb_compra.current(0)
                    lbl_saldo.config(text="Saldo: $0.00")

            except Exception as e:
                messagebox.showerror("Error", f"No se pudieron cargar deudas/compras del proveedor.\n{e}", parent=win)


        def on_compra_sel(_=None):
            txt = (cb_compra.get() or "").strip()
            if txt and txt in compras_map:
                _, saldo, *_ = compras_map[txt]
                lbl_saldo.config(text=f"Saldo: {formato_moneda(saldo)}")
            else:
                lbl_saldo.config(text="Saldo: $0.00")

        cb_prov.bind("<<ComboboxSelected>>", cargar_compras_del_proveedor)
        cb_compra.bind("<<ComboboxSelected>>", on_compra_sel)
        cargar_compras_del_proveedor()

        def guardar(_=None):
            prov_name = (cb_prov.get() or "").strip()
            comp_txt  = (cb_compra.get() or "").strip()
            monto_txt = (ent_monto.get() or "").strip()
            fecha_txt = (ent_fecha.get() or "").strip()
            desc_txt  = (ent_desc.get() or "").strip()

            if not prov_name or prov_name not in proveedores_map:
                messagebox.showerror("Error", "Selecciona un proveedor.", parent=win); return
            if not comp_txt or comp_txt not in compras_map:
                messagebox.showerror("Error", "Selecciona una deuda/compra.", parent=win); return

            try:
                monto = to_float(monto_txt, permitir_cero=False)
                if monto <= 0: raise ValueError
            except Exception:
                messagebox.showerror("Error", "Monto de abono inválido.", parent=win); return

            # Fecha
            fecha_val = None
            if fecha_txt:
                f = normalizar_fecha(fecha_txt)
                if not es_fecha_ok(f):
                    messagebox.showerror("Error", "Fecha inválida. Usa YYYY-MM-DD.", parent=win); return
                fecha_val = f + " 00:00:00"
            else:
                fecha_val = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            compra_id, saldo_actual, total_compra, _fecha, fuente = compras_map[comp_txt]
            if saldo_actual > 0 and monto > saldo_actual:
                if not messagebox.askyesno("Confirmar", f"El monto ({formato_moneda(monto)}) excede el saldo ({formato_moneda(saldo_actual)}). ¿Continuar?", parent=win):
                    return

            try:
                with get_connection() as conn:
                    cur = conn.cursor()

                    # ¿Tenemos deudas_proveedores (nuevo flujo)?
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deudas_proveedores'")
                    has_deudas = (cur.fetchone() is not None)

                    # 1) Insertar GASTO (si tenemos proveedor_id en gastos, lo enlazamos)
                    cols_g = ["tipo", "monto", "descripcion", "fecha"]
                    vals_g = ["Abono compra", float(monto), (desc_txt or f"Abono a {'deuda' if has_deudas else 'compra'} #{compra_id} — Proveedor {prov_name}"), fecha_val]
                    # enlazar proveedor si existe la columna
                    g_cols = {r[1] for r in conn.execute("PRAGMA table_info(gastos)").fetchall()}
                    if "proveedor_id" in g_cols:
                        cols_g.append("proveedor_id"); vals_g.append(int(proveedores_map[prov_name]))
                    # si quisieras enlazar compra_id cuando fuente = 'COMPRA' y existe la columna:
                    if (fuente == "COMPRA") and ("compra_id" in g_cols):
                        cols_g.append("compra_id"); vals_g.append(int(compra_id))

                    cur.execute(f"INSERT INTO gastos ({', '.join(cols_g)}) VALUES ({', '.join('?' for _ in cols_g)})", tuple(vals_g))

                    if has_deudas:
                        # 2) Registrar el PAGO y actualizar saldo de la deuda
                        aplica = min(float(monto), float(saldo_actual))
                        # asegurar pagos_proveedores
                        conn.execute("""
                            CREATE TABLE IF NOT EXISTS pagos_proveedores (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                proveedor_id INTEGER,
                                monto REAL NOT NULL,
                                fecha TEXT NOT NULL,
                                descripcion TEXT,
                                deuda_proveedor_id INTEGER
                            )
                        """)
                        cur.execute("""
                            INSERT INTO pagos_proveedores (proveedor_id, deuda_proveedor_id, monto, fecha, descripcion)
                            VALUES (?, ?, ?, ?, ?)
                        """, (int(proveedores_map[prov_name]), int(compra_id), float(aplica), fecha_val, desc_txt or "Abono a compra"))
                        cur.execute("UPDATE deudas_proveedores SET saldo = MAX(saldo - ?, 0) WHERE id = ?",
                                    (float(aplica), int(compra_id)))
                    else:
                        # 3) Flujo viejo con 'compras' (si tienes saldo_col/estado_col)
                        cols_c = {r[1] for r in conn.execute("PRAGMA table_info(compras)").fetchall()}
                        saldo_col = "saldo_pendiente" if "saldo_pendiente" in cols_c else ("deuda_restante" if "deuda_restante" in cols_c else None)
                        estado_col = "estado" if "estado" in cols_c else None
                        total_col  = "total" if "total" in cols_c else ("monto_total" if "monto_total" in cols_c else None)
                        if saldo_col:
                            cur.execute(f"UPDATE compras SET {saldo_col} = MAX({saldo_col} - ?, 0) WHERE id = ?", (float(monto), int(compra_id)))
                            if estado_col:
                                cur.execute(f"UPDATE compras SET {estado_col} = 'PAGADA' WHERE id = ? AND ({saldo_col} <= 0.000001)", (int(compra_id),))
                        elif total_col and estado_col:
                            cur.execute(f"UPDATE compras SET {estado_col} = CASE WHEN ? >= {total_col} THEN 'PAGADA' ELSE {estado_col} END WHERE id = ?", (float(monto), int(compra_id)))

                self.cargar_gastos((self.buscar_entry.get() or "").strip())
                messagebox.showinfo("Éxito", "Abono registrado.", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo registrar el abono.\n{e}", parent=win)


        ttk.Button(win, text="Guardar", command=guardar, style="Success.TButton").grid(row=5, column=0, columnspan=3, pady=10)
        win.bind("<Return>", guardar)


    # -------------------------------------------------------
    # Registro / listado
    # -------------------------------------------------------
    def registrar_gasto(self):
        """Valida y registra un gasto."""
        tipo = (self.tipo_combo.get() or "").strip()
        monto_txt = (self.monto_entry.get() or "").strip()
        descripcion = (self.descripcion_entry.get() or "").strip()
        fecha_txt = (self.fecha_entry.get() or "").strip()

        if not tipo:
            messagebox.showerror("Error", "Selecciona un tipo de gasto.")
            return

        try:
            monto = to_float(monto_txt, permitir_cero=False)
            if monto <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Monto inválido. Ejemplos: 100, 100.50, 1.234,56, $1,234.56")
            return

        # Empleado requerido si tipo == 'Salarios'
        empleado_id = None
        if self._has_empleados and self._gastos_has_empleado_fk and self._empleado_combo:
            emp_name = (self._empleado_combo.get() or "").strip()
            if tipo.lower() in ("salarios", "salario") and not emp_name:
                messagebox.showerror("Error", "Para 'Salarios' debes seleccionar un empleado.")
                return
            if emp_name and emp_name in getattr(self, "_empleados_map", {}):
                empleado_id = self._empleados_map[emp_name]

        cliente_id = None
        if self._gastos_has_cliente_fk and self._cliente_combo:
            cli_name = (self._cliente_combo.get() or "").strip()
            if cli_name and cli_name in getattr(self, "_clientes_map", {}):
                cliente_id = self._clientes_map[cli_name]

        # Fecha
        fecha_val = None
        if fecha_txt:
            fecha_n = normalizar_fecha(fecha_txt)
            if not es_fecha_ok(fecha_n):
                messagebox.showerror("Error", "Fecha inválida. Usa YYYY-MM-DD (o deja vacío).")
                return
            fecha_val = f"{fecha_n} 00:00:00"

        try:
            with get_connection() as conn:
                cur = conn.cursor()
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
                if self._gastos_has_empleado_fk or self._gastos_has_cliente_fk or self._gastos_has_proveedor_fk:
                    emp_sel = ", e.nombre AS empleado" if self._gastos_has_empleado_fk else ""
                    cli_sel = ", c.nombre AS cliente" if self._gastos_has_cliente_fk else ""
                    prv_sel = ", pr.nombre AS proveedor" if self._gastos_has_proveedor_fk else ""

                    emp_join = "LEFT JOIN empleados e ON e.id = g.empleado_id" if self._gastos_has_empleado_fk else ""
                    cli_join = "LEFT JOIN clientes  c ON c.id = g.cliente_id"  if self._gastos_has_cliente_fk else ""
                    prv_join = "LEFT JOIN proveedores pr ON pr.id = g.proveedor_id" if self._gastos_has_proveedor_fk else ""

                    base_sql = f"""
                        SELECT g.id, g.tipo, g.monto, g.descripcion, g.fecha
                            {emp_sel}{cli_sel}{prv_sel}
                        FROM gastos g
                        {emp_join} {cli_join} {prv_join}
                    """

                    if filtro:
                        like = f"%{filtro}%"
                        parts = ["(g.tipo LIKE ? OR g.descripcion LIKE ?)"]
                        params = [like, like]
                        if self._gastos_has_empleado_fk:
                            parts.append("e.nombre LIKE ?"); params.append(like)
                        if self._gastos_has_cliente_fk:
                            parts.append("c.nombre LIKE ?"); params.append(like)
                        if self._gastos_has_proveedor_fk:
                            parts.append("pr.nombre LIKE ?"); params.append(like)
                        sql = base_sql + f" WHERE {' OR '.join(parts)} ORDER BY g.fecha DESC"
                        rows = conn.execute(sql, tuple(params)).fetchall()
                    else:
                        rows = conn.execute(base_sql + " ORDER BY g.fecha DESC").fetchall()
                else:
                    # modo básico sin joins
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
                    rid   = r[0]
                    tipo  = r[1]
                    monto = r[2]
                    descr = r[3]
                    fecha = r[4]

                    vals = [rid, tipo, formato_moneda(monto or 0), (descr or ""), fecha]

                    idx = 5  # después de las 5 columnas base
                    if self._gastos_has_empleado_fk:
                        emp = r[idx] if len(r) > idx else ""
                        vals.append(emp or "")
                        idx += 1
                    if self._gastos_has_cliente_fk:
                        cli = r[idx] if len(r) > idx else ""
                        vals.append(cli or "")
                        idx += 1
                    if self._gastos_has_proveedor_fk:
                        prv = r[idx] if len(r) > idx else ""
                        vals.append(prv or "")

                    self.tree.insert("", "end", values=tuple(vals))



            set_treeview_stripes(self.tree, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los gastos.\n{e}")

    def _on_buscar_changed(self, _e=None):
        self.cargar_gastos((self.buscar_entry.get() or "").strip())

    # -------------------------------------------------------
    # Edición / Eliminación
    # -------------------------------------------------------
    def _gasto_sel(self):
        item = self.tree.focus()
        if not item:
            return None
        vals = self.tree.item(item, "values")
        if not vals:
            return None
        # vals: (ID, Tipo, MontoFmt, Descripción, Fecha [, Empleado] [, Cliente])
        gid = int(vals[0])
        tipo = vals[1]
        monto_fmt = vals[2]
        desc = vals[3]
        fecha = vals[4]
        emp_name = vals[5] if self._gastos_has_empleado_fk else None
        cli_name = (
            vals[6] if (self._gastos_has_empleado_fk and self._gastos_has_cliente_fk) else
            (vals[5] if (not self._gastos_has_empleado_fk and self._gastos_has_cliente_fk) else None)
        )
        try:
            monto = to_float(monto_fmt, permitir_cero=False)
        except ValueError:
            monto = 0.0
        return gid, tipo, monto, desc, fecha, emp_name, cli_name

    def eliminar_gasto(self):
        sel = self._gasto_sel()
        if not sel:
            messagebox.showerror("Error", "Selecciona un gasto de la tabla.")
            return
        gid, tipo, monto, _desc, _fecha, *_ = sel
        if not messagebox.askyesno("Confirmar", f"¿Eliminar el gasto '{tipo}' de {formato_moneda(monto)}?"):
            return
        try:
            with get_connection() as conn:
                conn.execute("DELETE FROM gastos WHERE id = ?", (gid,))
            self.cargar_gastos((self.buscar_entry.get() or "").strip())
            messagebox.showinfo("Éxito", "Gasto eliminado.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo eliminar el gasto.\n{e}")

    def editar_gasto(self):
        sel = self._gasto_sel()
        if not sel:
            messagebox.showerror("Error", "Selecciona un gasto de la tabla.")
            return
        gid, tipo_act, monto_act, desc_act, fecha_act, emp_act, cli_act = sel

        win = tk.Toplevel(self)
        win.title("Editar gasto")
        try:
            win.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.bind("<Escape>", lambda _: win.destroy())

        # Tipo
        tk.Label(win, text="Tipo:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=10, pady=8, sticky="e")
        cb_tipo = self._combobox(win, width=28, row=0, column=1, padx=10, pady=8, sticky="we")
        cb_tipo["values"] = self.tipo_combo["values"]
        try:
            idx = list(cb_tipo["values"]).index(tipo_act)
            cb_tipo.current(idx)
        except Exception:
            if cb_tipo["values"]:
                cb_tipo.current(0)

        # Monto
        tk.Label(win, text="Monto:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=10, pady=8, sticky="e")
        ent_monto = ttk.Entry(win, width=16, style="TEntry")
        ent_monto.grid(row=1, column=1, padx=10, pady=8, sticky="w")
        ent_monto.insert(0, f"{monto_act:.2f}")
        adjuntar_validador_2_decimales(ent_monto, permitir_vacio=False)

        # Descripción
        tk.Label(win, text="Descripción:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=2, column=0, padx=10, pady=8, sticky="e")
        ent_desc = ttk.Entry(win, width=40, style="TEntry")
        ent_desc.grid(row=2, column=1, padx=10, pady=8, sticky="we")
        ent_desc.insert(0, desc_act or "")

        # Fecha
        tk.Label(win, text="Fecha (YYYY-MM-DD):", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=3, column=0, padx=10, pady=8, sticky="e")
        ent_fecha = ttk.Entry(win, width=16, style="TEntry")
        ent_fecha.grid(row=3, column=1, padx=(10, 0), pady=8, sticky="w")
        ent_fecha.insert(0, normalizar_fecha(fecha_act))
        ttk.Button(win, text="📅", command=lambda: self._abrir_calendario(ent_fecha), style="TButton").grid(row=3, column=1, padx=(180, 0), pady=8, sticky="w")

        # Empleado / Cliente
        row_next = 4
        cb_emp = None
        cb_cli = None

        if self._gastos_has_empleado_fk and self._has_empleados:
            tk.Label(win, text="Empleado:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=row_next, column=0, padx=10, pady=8, sticky="e")
            cb_emp = self._combobox(win, width=28, row=row_next, column=1, padx=10, pady=8, sticky="we")
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
            tk.Label(win, text="Cliente:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=row_next, column=0, padx=10, pady=8, sticky="e")
            cb_cli = self._combobox(win, width=28, row=row_next, column=1, padx=10, pady=8, sticky="we")
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

        def guardar(_=None):
            tipo_new = (cb_tipo.get() or "").strip()
            monto_txt = (ent_monto.get() or "").strip()
            desc_new = (ent_desc.get() or "").strip()
            fecha_txt = (ent_fecha.get() or "").strip()
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

                self.cargar_gastos((self.buscar_entry.get() or "").strip())
                messagebox.showinfo("Éxito", "Gasto actualizado.", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo actualizar el gasto.\n{e}", parent=win)

        ttk.Button(win, text="Guardar", command=guardar, style="Success.TButton").grid(row=row_next, column=0, columnspan=2, pady=8)
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
            top.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        top.transient(self.winfo_toplevel())
        top.grab_set()
        top.bind("<Escape>", lambda _: top.destroy())

        for c in range(3):
            top.grid_columnconfigure(c, weight=(1 if c == 1 else 0))

        tk.Label(top, text="Nombre:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=8, pady=6, sticky="e")
        ent_nombre = ttk.Entry(top, width=26, style="TEntry"); ent_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we")

        tk.Label(top, text="Teléfono:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=8, pady=6, sticky="e")
        ent_tel = ttk.Entry(top, width=20, style="TEntry"); ent_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we")

        def add_emp(_=None):
            nombre = (ent_nombre.get() or "").strip()
            tel = (ent_tel.get() or "").strip()
            if not nombre:
                messagebox.showerror("Error", "El nombre es obligatorio.", parent=top)
                return
            try:
                with get_connection() as conn:
                    conn.execute("INSERT INTO empleados (nombre, telefono) VALUES (?, ?)", (nombre, tel))
                ent_nombre.delete(0, tk.END); ent_tel.delete(0, tk.END)
                cargar_lista(); self._cargar_empleados()
                messagebox.showinfo("Éxito", "Empleado agregado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo agregar el empleado.\n{e}", parent=top)

        ttk.Button(top, text="Agregar", command=add_emp, style="Success.TButton").grid(row=2, column=0, columnspan=2, padx=8, pady=(4, 8))
        top.bind("<Return>", add_emp)

        cols = ("ID", "Nombre", "Teléfono")
        tree = ttk.Treeview(top, columns=cols, show="headings", style=self._tree_style_name, height=10)
        for c, w in (("ID", 70), ("Nombre", 220), ("Teléfono", 160)):
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
                    rid  = r[0] if isinstance(r, tuple) else r["id"]
                    nom  = r[1] if isinstance(r, tuple) else r["nombre"]
                    tel_ = r[2] if isinstance(r, tuple) else r["telefono"]
                    tree.insert("", "end", values=(rid, nom, tel_ or ""))
                set_treeview_stripes(tree, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))
            except Exception:
                pass

        def editar():
            item = tree.focus()
            if not item:
                messagebox.showerror("Error", "Selecciona un empleado.", parent=top)
                return
            vals = tree.item(item, "values")
            emp_id = int(vals[0]); nombre = vals[1]; tel = vals[2]

            w = tk.Toplevel(top)
            w.title("Editar empleado")
            try:
                w.configure(bg=PALETTE["bg"])
            except Exception:
                pass
            w.transient(top); w.grab_set()
            w.bind("<Escape>", lambda _: w.destroy())

            tk.Label(w, text="Nombre:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=8, pady=6, sticky="e")
            e_nombre = ttk.Entry(w, width=26, style="TEntry"); e_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we"); e_nombre.insert(0, nombre)

            tk.Label(w, text="Teléfono:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=8, pady=6, sticky="e")
            e_tel = ttk.Entry(w, width=20, style="TEntry"); e_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we"); e_tel.insert(0, tel)

            w.grid_columnconfigure(1, weight=1)

            def save(_=None):
                n = (e_nombre.get() or "").strip()
                t = (e_tel.get() or "").strip()
                if not n:
                    messagebox.showerror("Error", "El nombre es obligatorio.", parent=w)
                    return
                try:
                    with get_connection() as conn:
                        conn.execute("UPDATE empleados SET nombre = ?, telefono = ? WHERE id = ?", (n, t, emp_id))
                    cargar_lista(); self._cargar_empleados()
                    messagebox.showinfo("Éxito", "Empleado actualizado.", parent=w)
                    w.destroy()
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo actualizar el empleado.\n{e}", parent=w)

            ttk.Button(w, text="Guardar", command=save, style="Success.TButton").grid(row=2, column=0, columnspan=2, pady=8)
            w.bind("<Return>", save)

        def eliminar():
            item = tree.focus()
            if not item:
                messagebox.showerror("Error", "Selecciona un empleado.", parent=top)
                return
            vals = tree.item(item, "values")
            emp_id = int(vals[0]); nombre = vals[1]
            if not messagebox.askyesno("Confirmar", f"¿Eliminar empleado '{nombre}'?", parent=top):
                return
            try:
                with get_connection() as conn:
                    cnt = conn.execute("SELECT COUNT(*) FROM gastos WHERE empleado_id = ?", (emp_id,)).fetchone()[0]
                    if cnt > 0:
                        messagebox.showwarning("No permitido", "No se puede eliminar: está referenciado en gastos.", parent=top)
                        return
                    conn.execute("DELETE FROM empleados WHERE id = ?", (emp_id,))
                cargar_lista(); self._cargar_empleados()
                messagebox.showinfo("Éxito", "Empleado eliminado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el empleado.\n{e}", parent=top)

        ttk.Button(top, text="Editar", command=editar, style="TButton").grid(row=4, column=0, padx=8, pady=(0, 8), sticky="ew")
        ttk.Button(top, text="Eliminar", command=eliminar, style="Danger.TButton").grid(row=4, column=1, padx=8, pady=(0, 8), sticky="ew")
        ttk.Button(top, text="Cerrar", command=top.destroy, style="TButton").grid(row=4, column=2, padx=8, pady=(0, 8), sticky="ew")

        cargar_lista()

    # -------------------------------------------------------
    # CRUD rápido de Clientes
    # -------------------------------------------------------
    def _abrir_crud_clientes(self):
        top = tk.Toplevel(self)
        top.title("Clientes")
        try:
            top.configure(bg=PALETTE["bg"])
        except Exception:
            pass
        top.transient(self.winfo_toplevel())
        top.grab_set()
        top.bind("<Escape>", lambda _: top.destroy())

        for c in range(3):
            top.grid_columnconfigure(c, weight=(1 if c == 1 else 0))

        tk.Label(top, text="Nombre:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=8, pady=6, sticky="e")
        ent_nombre = ttk.Entry(top, width=26, style="TEntry"); ent_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we")

        tk.Label(top, text="Teléfono:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=8, pady=6, sticky="e")
        ent_tel = ttk.Entry(top, width=20, style="TEntry"); ent_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we")

        def add_cli(_=None):
            nombre = (ent_nombre.get() or "").strip()
            tel = (ent_tel.get() or "").strip()
            if not nombre:
                messagebox.showerror("Error", "El nombre es obligatorio.", parent=top)
                return
            try:
                with get_connection() as conn:
                    conn.execute(
                        "INSERT INTO clientes (nombre, telefono, deuda_total) VALUES (?, ?, 0.0)",
                        (nombre, tel),
                    )
                ent_nombre.delete(0, tk.END); ent_tel.delete(0, tk.END)
                cargar_lista(); self._cargar_clientes()
                messagebox.showinfo("Éxito", "Cliente agregado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo agregar el cliente.\n{e}", parent=top)

        ttk.Button(top, text="Agregar", command=add_cli, style="Success.TButton").grid(row=2, column=0, columnspan=2, padx=8, pady=(4, 8))
        top.bind("<Return>", add_cli)

        cols = ("ID", "Nombre", "Teléfono", "Deuda")
        tree = ttk.Treeview(top, columns=cols, show="headings", style=self._tree_style_name, height=10)
        for c, w, a in (("ID", 70, "center"), ("Nombre", 220, "w"), ("Teléfono", 160, "w"), ("Deuda", 110, "e")):
            tree.heading(c, text=c); tree.column(c, width=w, anchor=a)
        tree.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=8, pady=(6, 6))

        def cargar_lista():
            """Recarga la tabla de clientes (con formateo de deuda)."""
            tree.delete(*tree.get_children())
            try:
                with get_connection() as conn:
                    rows = conn.execute(
                        "SELECT id, nombre, telefono, deuda_total FROM clientes ORDER BY nombre COLLATE NOCASE"
                    ).fetchall()
                for r in rows:
                    rid   = r[0] if isinstance(r, tuple) else r["id"]
                    nom   = r[1] if isinstance(r, tuple) else r["nombre"]
                    tel_  = r[2] if isinstance(r, tuple) else r["telefono"]
                    deuda = r[3] if isinstance(r, tuple) else r["deuda_total"]
                    tree.insert(
                        "",
                        "end",
                        values=(rid, nom, tel_ or "", formato_moneda(deuda or 0)),
                    )
                set_treeview_stripes(tree, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))
            except Exception:
                pass

        def editar():
            """Editar cliente seleccionado (nombre/teléfono)."""
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
                w.configure(bg=PALETTE["bg"])
            except Exception:
                pass
            w.transient(top)
            w.grab_set()
            w.bind("<Escape>", lambda _: w.destroy())

            tk.Label(w, text="Nombre:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=8, pady=6, sticky="e")
            e_nombre = ttk.Entry(w, width=26, style="TEntry")
            e_nombre.grid(row=0, column=1, padx=8, pady=6, sticky="we")
            e_nombre.insert(0, nombre)

            tk.Label(w, text="Teléfono:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=8, pady=6, sticky="e")
            e_tel = ttk.Entry(w, width=20, style="TEntry")
            e_tel.grid(row=1, column=1, padx=8, pady=6, sticky="we")
            e_tel.insert(0, tel)

            w.grid_columnconfigure(1, weight=1)

            def save(_=None):
                n = (e_nombre.get() or "").strip()
                t = (e_tel.get() or "").strip()
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

            ttk.Button(w, text="Guardar", command=save, style="Success.TButton").grid(row=2, column=0, columnspan=2, pady=8)
            w.bind("<Return>", save)

        def eliminar():
            """Eliminar cliente (si no tiene referencias en ventas/pagos/gastos)."""
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
                    # Compatibilidad con distintos esquemas de pagos
                    refs = 0
                    try:
                        refs += conn.execute("SELECT COUNT(*) FROM ventas WHERE cliente_id = ?", (cid,)).fetchone()[0]
                    except Exception:
                        pass
                    # pagos_cliente (nuevo) o pagos_credito (legacy)
                    try:
                        refs += conn.execute("SELECT COUNT(*) FROM pagos_cliente WHERE cliente_id = ?", (cid,)).fetchone()[0]
                    except Exception:
                        try:
                            refs += conn.execute("SELECT COUNT(*) FROM pagos_credito WHERE cliente_id = ?", (cid,)).fetchone()[0]
                        except Exception:
                            pass
                    # gastos.cliente_id si la columna existe
                    try:
                        cols = {r[1] for r in conn.execute("PRAGMA table_info(gastos)").fetchall()}
                        if "cliente_id" in cols:
                            refs += conn.execute("SELECT COUNT(*) FROM gastos WHERE cliente_id = ?", (cid,)).fetchone()[0]
                    except Exception:
                        pass

                    if refs > 0:
                        messagebox.showwarning(
                            "No permitido",
                            "No se puede eliminar el cliente: tiene registros asociados.",
                            parent=top,
                        )
                        return

                    conn.execute("DELETE FROM clientes WHERE id = ?", (cid,))
                cargar_lista()
                self._cargar_clientes()
                messagebox.showinfo("Éxito", "Cliente eliminado.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el cliente.\n{e}", parent=top)

        ttk.Button(top, text="Editar", command=editar, style="TButton").grid(row=4, column=0, padx=8, pady=(0, 8), sticky="ew")
        ttk.Button(top, text="Eliminar", command=eliminar, style="Danger.TButton").grid(row=4, column=1, padx=8, pady=(0, 8), sticky="ew")
        ttk.Button(top, text="Cerrar", command=top.destroy, style="TButton").grid(row=4, column=2, padx=8, pady=(0, 8), sticky="ew")

        cargar_lista()

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
    """Monta el frame de Gastos en el contenedor principal."""
    for widget in frame_contenido.winfo_children():
        widget.destroy()
    frame = GastosFrame(frame_contenido)
    # Compatibilidad: si main usa grid, intentamos grid; si no, pack.
    try:
        frame.grid(row=0, column=0, sticky="nsew")
    except Exception:
        frame.pack(fill="both", expand=True)
