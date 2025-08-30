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
# - Montaje compatible con grid o pack desde main.mostrar().
#
# TEMA / PALETA
# -----------------------------------------------------------
# - Usa el tema de marca unificado (ui.theme) en lugar de colores fijos:
#     * apply_brand_ttk_theme() para estilos TTK coherentes.
#     * BRAND_PALETTE para colores (bg, panel, text, primary, accent, etc.).
#     * set_treeview_stripes() para rayado alterno de filas.
#     * stylize_combobox_dropdown() para el popup del combobox.
# -----------------------------------------------------------

from __future__ import annotations

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
from ui.theme import (
    apply_brand_ttk_theme,
    BRAND_PALETTE,
    set_treeview_stripes,
    stylize_combobox_dropdown,
)

PALETTE = BRAND_PALETTE


class MermasFrame(tk.Frame):
    def __init__(self, master=None):
        super().__init__(master, bg=PALETTE["bg"])
        self.productos: dict[str, int] = {}  # nombre -> id
        self._producto_seleccionado_id: int | None = None

        # Tema / estilos
        self._style = apply_brand_ttk_theme(self)
        self._tree_style_name = "Brand.Treeview"

        # UI
        self.crear_interfaz()
        self.cargar_productos()
        self.cargar_mermas()

        # Esc: limpiar formulario
        self.bind("<Escape>", self._limpiar_formulario)
        # Foco inicial
        self.after_idle(lambda: self.producto_combo.focus_set())

    # ---------------------------
    # Helpers UI (paleta)
    # ---------------------------
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

    def _entry(self, parent, width=12, **grid):
        e = ttk.Entry(parent, width=width, style="TEntry")
        if grid:
            e.grid(**grid)
        return e

    def _btn(self, parent, text, style, cmd, **grid):
        b = ttk.Button(parent, text=text, command=cmd, style=style)
        if grid:
            b.grid(**grid)
        return b

    def _combobox(self, parent, width=28, **grid):
        cb = ttk.Combobox(parent, state="readonly", width=width, style="TCombobox")
        if grid:
            cb.grid(**grid)
        cb.configure(postcommand=lambda c=cb: stylize_combobox_dropdown(c, PALETTE))
        return cb

    # ---------------------------
    # UI
    # ---------------------------
    def crear_interfaz(self):
        form_panel = self._panel(self, pady=8, padx=8, fill="x")
        grid = tk.Frame(form_panel, bg=PALETTE["panel"])
        grid.pack(fill="x", padx=8, pady=6)

        # Producto
        self._lbl(grid, "Producto:", row=0, column=0, sticky="e", padx=4, pady=2)
        self.producto_combo = self._combobox(grid, width=36)
        self.producto_combo.grid(row=0, column=1, sticky="we", padx=4, pady=2)
        grid.grid_columnconfigure(1, weight=1)
        self.producto_combo.bind("<<ComboboxSelected>>", self._on_producto_change)
        # Enter en combobox también registra la merma
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
        grid.grid_columnconfigure(1, weight=1)

        # Validadores de 2 decimales (coma/punto) para kilos/cajas
        for e in (self.kilos_entry, self.cajas_entry):
            adjuntar_validador_2_decimales(e, permitir_vacio=True)

        # Atajos Enter
        self.kilos_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.cajas_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.unidades_entry.bind("<Return>", lambda e: self.registrar_merma())
        self.motivo_entry.bind("<Return>", lambda e: self.registrar_merma())

        # Botón
        self._btn(grid, "Registrar Merma", "TButton", self.registrar_merma,
                  row=3, column=0, columnspan=6, pady=10)

        # Info stock / peso
        self.info_label = tk.Label(
            form_panel,
            text="Kilos: 0.00 | Cajas: 0.00 | Unidades: 0 | Peso/caja: 0.00 kg",
            bg=PALETTE["panel"], fg=PALETTE["text"], anchor="w"
        )
        self.info_label.pack(fill="x", padx=16, pady=(0, 6))

        # --- Tabla de mermas ---
        tabla_panel = self._panel(self, pady=6, padx=8, fill="both", expand=True)
        tabla_panel.grid_columnconfigure(0, weight=1)
        tabla_panel.grid_rowconfigure(0, weight=1)

        # ⬇️ ANTES: ("Producto", "Kilos", "Cajas", "Unidades", "Motivo", "Fecha")
        columnas = ("ID", "Producto", "Kilos", "Cajas", "Unidades", "Motivo", "Fecha")

        # Scrollbars
        scroll_y = ttk.Scrollbar(tabla_panel, orient="vertical", style="Vertical.TScrollbar")
        scroll_x = ttk.Scrollbar(tabla_panel, orient="horizontal", style="Horizontal.TScrollbar")

        self.tree = ttk.Treeview(
            tabla_panel, columns=columnas, show="headings", height=14, style=self._tree_style_name,
            yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set
        )
        scroll_y.config(command=self.tree.yview)
        scroll_x.config(command=self.tree.xview)

        for col, width, anchor in (
            ("ID", 0, "center"),               # ⬅️ Oculta ID
            ("Producto", 200, "w"),
            ("Kilos", 100, "e"),
            ("Cajas", 100, "e"),
            ("Unidades", 100, "e"),
            ("Motivo", 320, "w"),
            ("Fecha", 150, "center"),
        ):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col in ("Producto", "Motivo")))

        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        # Ordenamiento por encabezados (agregamos ID:int)
        self._setup_sorting(
            tree=self.tree,
            columnas=columnas,
            tipos={
                "ID": "int",
                "Producto": "str",
                "Kilos": "float",
                "Cajas": "float",
                "Unidades": "int",
                "Motivo": "str",
                "Fecha": "date",
            },
        )

        # ⬇️ Doble click = editar
        self.tree.bind("<Double-1>", lambda _e: self.modificar_merma())

        # ⬇️ Barra de acciones simple
        actions = tk.Frame(tabla_panel, bg=PALETTE["panel"])
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(actions, text="Modificar merma", command=self.modificar_merma).pack(side="left", padx=(0, 8))


    # ---------------------------
    # Datos / DB
    # ---------------------------
    def cargar_productos(self):
        """Carga productos en el combobox, guardando mapa nombre→id."""
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT id, nombre FROM productos ORDER BY nombre COLLATE NOCASE"
                ).fetchall()
            self.productos = {r[1]: int(r[0]) for r in rows}
            self.producto_combo["values"] = list(self.productos.keys())
            if self.productos and not self.producto_combo.get():
                self.producto_combo.current(0)
                self._on_producto_change()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar los productos.\n{e}")

    def _on_producto_change(self, _e=None):
        """Actualiza etiqueta info con stock y peso/caja del producto actual."""
        nombre = (self.producto_combo.get() or "").strip()
        self._producto_seleccionado_id = self.productos.get(nombre)
        if not self._producto_seleccionado_id:
            self.info_label.config(text="Kilos: 0.00 | Cajas: 0.00 | Unidades: 0 | Peso/caja: 0.00 kg")
            return
        try:
            with get_connection() as conn:
                r = conn.execute(
                    "SELECT kilos, num_cajas, unidades, peso_caja FROM productos WHERE id = ?",
                    (self._producto_seleccionado_id,),
                ).fetchone()
            if r:
                kilos = float(r[0] or 0)
                cajas = float(r[1] or 0)
                unids = int(r[2] or 0)
                peso = float(r[3] or 0)
                self.info_label.config(
                    text=f"Kilos: {kilos:.2f} | Cajas: {cajas:.2f} | Unidades: {unids} | Peso/caja: {peso:.2f} kg"
                )
        except Exception:
            pass

    def cargar_mermas(self):
        """Llena la tabla de mermas (más recientes primero)."""
        try:
            self.tree.delete(*self.tree.get_children())
        except Exception:
            pass
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT m.id, p.nombre AS producto, m.kilos, m.num_cajas, m.unidades, m.motivo, m.fecha
                    FROM mermas m
                    JOIN productos p ON p.id = m.producto_id
                ORDER BY m.fecha DESC
                    """
                ).fetchall()

            for r in rows:
                self.tree.insert(
                    "", "end",
                    values=(
                        int(r[0]),                                   # ⬅️ ID
                        r[1],                                        # Producto
                        f"{redondear_dos_decimales(r[2] or 0):.2f}", # Kilos
                        f"{redondear_dos_decimales(r[3] or 0):.2f}", # Cajas
                        int(r[4] or 0),                              # Unidades
                        r[5] or "",                                  # Motivo
                        formatear_fecha(str(r[6])),                  # Fecha
                    ),
                )

            set_treeview_stripes(self.tree, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron cargar las mermas.\n{e}")

    # ---------------------------
    # Registro de merma
    # ---------------------------
    def registrar_merma(self):
        """Valida entradas, autocálculo según peso_caja, verifica stock y registra merma."""
        nombre = (self.producto_combo.get() or "").strip()
        if not nombre or nombre not in self.productos:
            messagebox.showerror("Error", "Selecciona un producto.")
            return
        producto_id = self.productos[nombre]

        # Leer entradas
        kilos_txt = (self.kilos_entry.get() or "").strip()
        cajas_txt = (self.cajas_entry.get() or "").strip()
        unid_txt  = (self.unidades_entry.get() or "").strip()
        motivo    = (self.motivo_entry.get() or "").strip()

        try:
            kilos = to_float(kilos_txt, permitir_cero=True)
            cajas = to_float(cajas_txt, permitir_cero=True)
            unidades = to_int(unid_txt, permitir_cero=True)
        except ValueError:
            messagebox.showerror("Error", "Valores numéricos inválidos.")
            return

        if kilos < 0 or cajas < 0 or unidades < 0:
            messagebox.showerror("Error", "Los valores no pueden ser negativos.")
            return

        # Leer stock actual y peso/caja
        try:
            with get_connection() as conn:
                r = conn.execute(
                    "SELECT kilos, num_cajas, unidades, peso_caja FROM productos WHERE id = ?",
                    (producto_id,),
                ).fetchone()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo consultar el producto.\n{e}")
            return

        if not r:
            messagebox.showerror("Error", "Producto no encontrado.")
            return

        kilos_stock, cajas_stock, unid_stock, peso_caja = (
            float(r[0] or 0),
            float(r[1] or 0),
            int(r[2] or 0),
            float(r[3] or 0),
        )

        # Autocálculo (si peso_caja > 0)
        if peso_caja > 0:
            if kilos > 0 and (cajas == 0):
                cajas = redondear_dos_decimales(kilos / peso_caja)
            elif cajas > 0 and (kilos == 0):
                kilos = redondear_dos_decimales(cajas * peso_caja)

        # Si todo cero, nada que hacer
        if kilos == 0 and cajas == 0 and unidades == 0:
            messagebox.showwarning("Atención", "Ingresa al menos uno de: kilos, cajas o unidades.")
            return

        # Verificar stock suficiente
        if kilos > kilos_stock + 1e-9:
            messagebox.showerror("Stock insuficiente", "No hay suficientes kilos.")
            return
        if cajas > cajas_stock + 1e-9:
            messagebox.showerror("Stock insuficiente", "No hay suficientes cajas.")
            return
        if unidades > unid_stock:
            messagebox.showerror("Stock insuficiente", "No hay suficientes unidades.")
            return

        # Registrar en DB (merma + actualización de producto)
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                # Insert en mermas
                cur.execute(
                    """
                    INSERT INTO mermas (producto_id, kilos, num_cajas, unidades, motivo, fecha)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        producto_id,
                        float(kilos),
                        float(cajas),
                        int(unidades),
                        motivo,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                # Update stock producto
                cur.execute(
                    """
                    UPDATE productos
                       SET kilos = ?, num_cajas = ?, unidades = ?
                     WHERE id = ?
                    """,
                    (
                        redondear_dos_decimales(kilos_stock - kilos),
                        redondear_dos_decimales(cajas_stock - cajas),
                        max(0, int(unid_stock - unidades)),
                        producto_id,
                    ),
                )

            self.cargar_mermas()
            self._on_producto_change()
            messagebox.showinfo("Éxito", "Merma registrada correctamente.")
            self._limpiar_formulario()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo registrar la merma.\n{e}")

    def _selected_merma_id(self) -> int | None:
        item = self.tree.focus()
        if not item:
            return None
        vals = self.tree.item(item, "values")
        if not vals or len(vals) < 1:
            return None
        try:
            return int(vals[0])  # ID está en la primera columna
        except Exception:
            return None

    
    def modificar_merma(self):
        merma_id = self._selected_merma_id()
        if not merma_id:
            messagebox.showwarning("Editar", "Selecciona una merma en la tabla.")
            return

        # Leer registro actual
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT m.producto_id, p.nombre, m.kilos, m.num_cajas, m.unidades,
                        IFNULL(m.motivo,''), m.fecha
                    FROM mermas m
                    JOIN productos p ON p.id = m.producto_id
                    WHERE m.id = ?
                """, (int(merma_id),))
                row = cur.fetchone()
            if not row:
                raise ValueError("Merma no encontrada.")
            (prod_id_old, prod_nom_old, k_old, c_old, u_old,
            motivo_old, fecha_old) = row
            k_old = float(k_old or 0)
            c_old = float(c_old or 0)
            u_old = int(u_old or 0)
        except Exception as e:
            messagebox.showerror("Editar", f"No se pudo leer la merma.\n{e}")
            return

        # --- Diálogo de edición ---
        win = tk.Toplevel(self)
        win.title(f"Editar merma #{merma_id}")
        try: win.configure(bg=PALETTE["bg"])
        except Exception: pass
        win.transient(self.winfo_toplevel())

        # Producto
        tk.Label(win, text="Producto:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=0, column=0, padx=10, pady=6, sticky="e")
        cb_prod = self._combobox(win, width=30, row=0, column=1, padx=10, pady=6, sticky="we")
        cb_prod["values"] = list(self.productos.keys())
        cb_prod.set(prod_nom_old)
        win.grid_columnconfigure(1, weight=1)

        # Kilos / Cajas / Unidades
        tk.Label(win, text="Kilos (-):", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=1, column=0, padx=10, pady=6, sticky="e")
        e_kilos = ttk.Entry(win, width=14); e_kilos.grid(row=1, column=1, padx=10, pady=6, sticky="w")
        e_kilos.insert(0, f"{k_old:.2f}")
        adjuntar_validador_2_decimales(e_kilos, permitir_vacio=True)

        tk.Label(win, text="Cajas (-):", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=2, column=0, padx=10, pady=6, sticky="e")
        e_cajas = ttk.Entry(win, width=14); e_cajas.grid(row=2, column=1, padx=10, pady=6, sticky="w")
        e_cajas.insert(0, f"{c_old:.2f}")
        adjuntar_validador_2_decimales(e_cajas, permitir_vacio=True)

        tk.Label(win, text="Unidades (-):", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=3, column=0, padx=10, pady=6, sticky="e")
        e_unid = ttk.Entry(win, width=14); e_unid.grid(row=3, column=1, padx=10, pady=6, sticky="w")
        e_unid.insert(0, str(u_old))

        # Motivo
        tk.Label(win, text="Motivo:", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=4, column=0, padx=10, pady=6, sticky="e")
        e_motivo = ttk.Entry(win, width=48); e_motivo.grid(row=4, column=1, padx=10, pady=6, sticky="we")
        e_motivo.insert(0, motivo_old or "")

        # Fecha
        tk.Label(win, text="Fecha (YYYY-MM-DD HH:MM:SS):", bg=PALETTE["bg"], fg=PALETTE["text"]).grid(row=5, column=0, padx=10, pady=6, sticky="e")
        e_fecha = ttk.Entry(win, width=22); e_fecha.grid(row=5, column=1, padx=10, pady=6, sticky="w")
        e_fecha.insert(0, fecha_old or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        def guardar():
            nuevo_prod_nom = (cb_prod.get() or "").strip()
            nuevo_prod_id = self.productos.get(nuevo_prod_nom)
            if not nuevo_prod_id:
                messagebox.showerror("Editar", "Selecciona un producto válido.", parent=win); return

            # Leer y validar números
            try:
                k_new = to_float(e_kilos.get() or 0, permitir_cero=True)
                c_new = to_float(e_cajas.get() or 0, permitir_cero=True)
                u_new = to_int(e_unid.get()  or 0, permitir_cero=True)
            except Exception:
                messagebox.showerror("Editar", "Valores inválidos para kilos/cajas/unidades.", parent=win); return
            if any(x < 0 for x in (k_new, c_new, u_new)):
                messagebox.showerror("Editar", "No se permiten valores negativos.", parent=win); return
            if (k_new <= 0) and (c_new <= 0) and (u_new <= 0):
                messagebox.showerror("Editar", "Ingresa al menos un valor mayor a 0.", parent=win); return

            nuevo_motivo = (e_motivo.get() or "").strip()
            nueva_fecha  = (e_fecha.get()  or datetime.now().strftime("%Y-%m-%d %H:%M:%S")).strip()

            # Verificar stock suficiente "reponiendo" primero la merma anterior en memoria
            try:
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT kilos, num_cajas, unidades FROM productos WHERE id = ?", (int(nuevo_prod_id),))
                    srow = cur.fetchone()
                    if not srow:
                        raise ValueError("Producto no encontrado.")

                    sk, sc, su = (float(srow[0] or 0), float(srow[1] or 0), int(srow[2] or 0))

                    # Si es el mismo producto, al reponer la merma anterior aumenta el stock disponible
                    sk_repuesto = sk + (k_old if nuevo_prod_id == prod_id_old else 0.0)
                    sc_repuesto = sc + (c_old if nuevo_prod_id == prod_id_old else 0.0)
                    su_repuesto = su + (u_old if nuevo_prod_id == prod_id_old else 0)

                    if (k_new > sk_repuesto) or (c_new > sc_repuesto) or (u_new > su_repuesto):
                        messagebox.showerror(
                            "Stock insuficiente",
                            "La merma nueva excede el stock disponible tras reponer la merma anterior.",
                            parent=win
                        )
                        return

                    # Transacción de actualización: reponer viejo -> aplicar nuevo -> actualizar merma
                    cur.execute("""
                        UPDATE productos
                        SET kilos = kilos + ?, num_cajas = num_cajas + ?, unidades = unidades + ?
                        WHERE id = ?
                    """, (float(k_old), float(c_old), int(u_old), int(prod_id_old)))

                    cur.execute("""
                        UPDATE productos
                        SET kilos = kilos - ?, num_cajas = num_cajas - ?, unidades = unidades - ?
                        WHERE id = ?
                    """, (float(k_new), float(c_new), int(u_new), int(nuevo_prod_id)))

                    cur.execute("""
                        UPDATE mermas
                        SET producto_id = ?, kilos = ?, num_cajas = ?, unidades = ?,
                            motivo = ?, fecha = ?
                        WHERE id = ?
                    """, (int(nuevo_prod_id), float(k_new), float(c_new), int(u_new),
                        nuevo_motivo, nueva_fecha, int(merma_id)))

                messagebox.showinfo("Éxito", "Merma actualizada.", parent=win)
                win.destroy()
                self.cargar_mermas()
                self._on_producto_change()  # refresca ficha del producto actual del formulario

            except Exception as e:
                messagebox.showerror("Error", f"No se pudo guardar la merma.\n{e}", parent=win)

        ttk.Button(win, text="Guardar cambios", command=guardar, style="Success.TButton")\
            .grid(row=6, column=0, columnspan=2, padx=10, pady=(8, 10), sticky="ew")

        # atajos y modal
        win.bind("<Return>", lambda _e: guardar())
        win.bind("<Escape>", lambda _e: win.destroy())
        try: win.grab_set()
        except Exception: pass
        try: win.focus_force()
        except Exception: pass

    # ---------------------------
    # Utilidades
    # ---------------------------
    def _limpiar_formulario(self, _e=None):
        for w in (self.kilos_entry, self.cajas_entry, self.unidades_entry, self.motivo_entry):
            try:
                w.delete(0, tk.END)
            except Exception:
                pass
        self.producto_combo.focus_set()

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
    frame = MermasFrame(frame_contenido)
    # Montaje flexible (grid/pack)
    try:
        frame.grid(row=0, column=0, sticky="nsew")
    except Exception:
        frame.pack(fill="both", expand=True)
