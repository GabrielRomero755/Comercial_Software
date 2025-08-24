# modules/productos.py
# -----------------------------------------------------------
# Sistema de Comercio — Catálogo de Productos
#
# Funcionalidad principal
# -----------------------------------------------------------
# - Alta / edición / eliminación.
# - Búsqueda dinámica por nombre.
# - Validación de decimales tolerante a coma/punto (helpers).
# - Prevención de duplicados por nombre (NOCASE): si existe, propone actualizar.
# - Atajos: Enter (agregar/actualizar), Supr (eliminar), Ctrl+L (limpiar), Ctrl+S (guardar/actualizar), Ctrl+F (buscar).
# - Menú contextual (clic derecho) sobre la tabla.
#
# Campos:
#   Nombre (obligatorio)
#   Precio Mayoreo (2 dec)
#   Precio Menudeo (2 dec)
#   Unidades (entero)
#   Kilos (2 dec)
#   # Cajas (2 dec, permite 0.5)
#   Peso x Caja (kg) (2 dec)
#
# Tema / Paleta
# -----------------------------------------------------------
# Aplica el tema de marca unificado (ui.theme):
#   - apply_brand_ttk_theme() para configurar estilos TTK.
#   - BRAND_PALETTE para colores (bg, panel, text, primary, accent, etc.).
#   - set_treeview_stripes() para filas alternas en tablas.
#   - stylize_combobox_dropdown() disponible si se agregan Combobox.
# -----------------------------------------------------------

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from db.database import get_connection
from ui.helpers import (
    redondear_dos_decimales,
    to_float,
    to_int,
    adjuntar_validador_2_decimales,
)
from ui.theme import (
    apply_brand_ttk_theme,
    set_treeview_stripes,
    stylize_combobox_dropdown,  # disponible por si más adelante se usa
    BRAND_PALETTE,
)

PALETTE = BRAND_PALETTE  # Paleta activa por defecto


# -----------------------------------------------------------
# Acceso a DB
# -----------------------------------------------------------
def _fetch_productos(nombre_filtro: str | None = None):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            if nombre_filtro:
                cur.execute(
                    """
                    SELECT id, nombre, precio_mayoreo, precio_menudeo, unidades, kilos, num_cajas, peso_caja
                      FROM productos
                     WHERE nombre LIKE ?
                  ORDER BY nombre COLLATE NOCASE
                    """,
                    (f"%{nombre_filtro}%",),
                )
            else:
                cur.execute(
                    """
                    SELECT id, nombre, precio_mayoreo, precio_menudeo, unidades, kilos, num_cajas, peso_caja
                      FROM productos
                  ORDER BY nombre COLLATE NOCASE
                    """
                )
            return cur.fetchall()
    except Exception as e:
        messagebox.showerror("Error", f"No se pudieron cargar los productos: {e}")
        return []


def _existe_producto_por_nombre(nombre: str):
    """Devuelve (True, id) si existe un producto con ese nombre (NOCASE)."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM productos WHERE lower(nombre)=lower(?) LIMIT 1",
                (nombre.strip(),),
            )
            row = cur.fetchone()
            return (True, int(row[0])) if row else (False, None)
    except Exception:
        return False, None


def _insert_producto(nombre, pmay, pmen, unidades, kilos, num_cajas, peso_caja):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO productos (nombre, precio_mayoreo, precio_menudeo, unidades, kilos, num_cajas, peso_caja)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nombre,
                    float(pmay),
                    float(pmen),
                    int(unidades),
                    float(kilos),
                    float(num_cajas),
                    float(peso_caja),
                ),
            )
        return True
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo agregar el producto: {e}")
        return False


def _update_producto(producto_id, nombre, pmay, pmen, unidades, kilos, num_cajas, peso_caja):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE productos
                   SET nombre = ?, precio_mayoreo = ?, precio_menudeo = ?,
                       unidades = ?, kilos = ?, num_cajas = ?, peso_caja = ?
                 WHERE id = ?
                """,
                (
                    nombre,
                    float(pmay),
                    float(pmen),
                    int(unidades),
                    float(kilos),
                    float(num_cajas),
                    float(peso_caja),
                    int(producto_id),
                ),
            )
        return True
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo actualizar el producto: {e}")
        return False


def _delete_producto(producto_id):
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM productos WHERE id = ?", (int(producto_id),))
        return True
    except Exception as e:
        # Tip amigable si hay FKs
        if "FOREIGN KEY" in str(e).upper():
            messagebox.showerror(
                "Error", "No se puede eliminar: existen ventas o movimientos vinculados."
            )
        else:
            messagebox.showerror("Error", f"No se pudo eliminar el producto: {e}")
        return False


# -----------------------------------------------------------
# Ordenamiento por columnas (utilidad local)
# -----------------------------------------------------------
def _setup_sorting(tree: ttk.Treeview, columnas: tuple[str, ...], tipos: dict[str, str]):
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
# UI
# -----------------------------------------------------------
def mostrar(parent_frame):
    """Monta la UI de productos dentro de un contenedor propio (tema de marca aplicado)."""
    for w in parent_frame.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass

    # Contenedor raíz del módulo
    root = tk.Frame(parent_frame, bg=PALETTE["bg"], bd=0, highlightthickness=0)
    try:
        root.grid(row=0, column=0, sticky="nsew")
        parent_frame.grid_rowconfigure(0, weight=1)
        parent_frame.grid_columnconfigure(0, weight=1)
    except Exception:
        root.pack(fill="both", expand=True)

    # Tema / estilos unificados (marca)
    style = apply_brand_ttk_theme(root)
    tree_style_name = "Brand.Treeview"  # definido en ui.theme

    # ---------- Helpers UI (colores desde paleta) ----------
    def _panel(parent, **pack):
        f = tk.Frame(parent, bg=PALETTE["panel"], bd=0, highlightthickness=0)
        if pack:
            f.pack(**pack)
        return f

    def _lbl(parent, text, **grid):
        w = tk.Label(parent, text=text, bg=parent["bg"], fg=PALETTE["text"])
        if grid:
            w.grid(**grid)
        return w

    def _entry(parent, width=16, **grid):
        e = ttk.Entry(parent, width=width, style="TEntry")
        if grid:
            e.grid(**grid)
        return e

    def _btn(parent, text, style_name, cmd):
        return ttk.Button(parent, text=text, style=style_name, command=cmd)

    # Estado para edición (mutable para clausuras)
    selected_id = {"id": None}

    # Validadores (helpers para decimales; int simple para unidades)
    def _entry_int(parent, width=10, **grid):
        e = _entry(parent, width=width, **grid)

        def _val(proposed: str) -> bool:
            return proposed == "" or proposed.isdigit()

        e.configure(validate="key", validatecommand=(root.register(_val), "%P"))
        return e

    # ---------- Top: Búsqueda ----------
    busc_panel = _panel(root, pady=6, padx=8, fill="x")
    busc_grid = tk.Frame(busc_panel, bg=PALETTE["panel"])
    busc_grid.pack(fill="x")
    _lbl(busc_grid, "Buscar producto:", row=0, column=0, sticky="e", padx=4)
    entry_busqueda = _entry(busc_grid, width=36, row=0, column=1, sticky="we", padx=4)
    busc_grid.grid_columnconfigure(1, weight=1)

    # ---------- Formulario ----------
    form_container = _panel(root, pady=8, padx=8, fill="x")
    form = tk.Frame(form_container, bg=PALETTE["panel"], bd=0, highlightthickness=0)
    form.pack(fill="x")

    etiquetas = [
        "Nombre",
        "Precio Mayoreo",
        "Precio Menudeo",
        "Unidades",
        "Kilos",
        "# Cajas",
        "Peso x Caja (kg)",
    ]
    widgets: dict[str, ttk.Entry] = {}

    # Encabezados
    for i, et in enumerate(etiquetas):
        _lbl(form, et, row=0, column=i, padx=2, pady=(0, 2))

    # Campos con validador de 2 decimales
    campos_decimales = {
        "Precio Mayoreo",
        "Precio Menudeo",
        "Kilos",
        "# Cajas",
        "Peso x Caja (kg)",
    }

    # Entradas
    for i, et in enumerate(etiquetas):
        if et == "Unidades":
            entry = _entry_int(form, width=10, row=1, column=i, padx=2, sticky="we")
        elif et in campos_decimales:
            entry = _entry(form, width=14, row=1, column=i, padx=2, sticky="we")
            adjuntar_validador_2_decimales(entry, permitir_vacio=True)
        else:
            entry = _entry(form, width=18, row=1, column=i, padx=2, sticky="we")
        widgets[et] = entry

    for col in range(len(etiquetas)):
        form.grid_columnconfigure(col, weight=1 if col in (0, 2, 4, 6) else 0)

    # ---------- Botones ----------
    btns = _panel(root, pady=6, padx=8, fill="x")
    btn_agregar = _btn(btns, "Agregar", "Success.TButton", lambda: guardar_producto())
    btn_actual = _btn(
        btns, "Actualizar", "TButton", lambda: actualizar_producto_seleccionado()
    )
    btn_elim = _btn(
        btns, "Eliminar", "Danger.TButton", lambda: eliminar_producto_seleccionado()
    )
    btn_limpf = _btn(
        btns, "Limp. formulario", "TButton", lambda: limpiar_formulario()
    )
    btn_limpflt = _btn(
        btns,
        "Limp. filtro",
        "TButton",
        lambda: (entry_busqueda.delete(0, tk.END), cargar_tabla()),
    )
    for b in (btn_agregar, btn_actual, btn_elim, btn_limpf, btn_limpflt):
        b.pack(side="left", padx=5)

    # ---------- Tabla ----------
    tabla_panel = _panel(root, pady=6, padx=8, fill="both", expand=True)
    columnas = (
        "ID",
        "Nombre",
        "PMayoreo",
        "PMenudeo",
        "Unidades",
        "Kilos",
        "Cajas",
        "PesoCaja",
    )

    scroll_y = ttk.Scrollbar(tabla_panel, orient="vertical", style="Vertical.TScrollbar")
    scroll_x = ttk.Scrollbar(tabla_panel, orient="horizontal", style="Horizontal.TScrollbar")

    tree = ttk.Treeview(
        tabla_panel,
        columns=columnas,
        show="headings",
        height=14,
        style=tree_style_name,
        yscrollcommand=scroll_y.set,
        xscrollcommand=scroll_x.set,
    )
    scroll_y.config(command=tree.yview)
    scroll_x.config(command=tree.xview)

    for col, width, anchor in (
        ("ID", 60, "center"),
        ("Nombre", 200, "w"),
        ("PMayoreo", 100, "e"),
        ("PMenudeo", 100, "e"),
        ("Unidades", 90, "e"),
        ("Kilos", 100, "e"),
        ("Cajas", 90, "e"),
        ("PesoCaja", 110, "e"),
    ):
        tree.heading(col, text=col)
        tree.column(
            col, width=width, anchor=anchor, stretch=(col in ("Nombre",))
        )

    tree.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")
    tabla_panel.grid_rowconfigure(0, weight=1)
    tabla_panel.grid_columnconfigure(0, weight=1)

    _setup_sorting(
        tree=tree,
        columnas=columnas,
        tipos={
            "ID": "int",
            "Nombre": "str",
            "PMayoreo": "float",
            "PMenudeo": "float",
            "Unidades": "int",
            "Kilos": "float",
            "Cajas": "float",
            "PesoCaja": "float",
        },
    )

    # ---------- Menú contextual ----------
    menu = tk.Menu(
        tree,
        tearoff=0,
        bg=PALETTE["panel"],
        fg=PALETTE["text"],
        activebackground=PALETTE["accent"],
        activeforeground=PALETTE["text"],
        bd=0,
    )
    menu.add_command(label="Editar", command=lambda: cargar_a_formulario())
    menu.add_command(label="Eliminar", command=lambda: eliminar_producto_seleccionado())

    def _show_menu(event):
        try:
            iid = tree.identify_row(event.y)
            if iid:
                tree.selection_set(iid)
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    tree.bind("<Button-3>", _show_menu)  # clic derecho

    # ---------- Helpers de UI / flujo ----------
    def limpiar_formulario():
        for e in widgets.values():
            e.delete(0, tk.END)
        selected_id["id"] = None
        widgets["Nombre"].focus_set()

    def limpiar_filtro():
        entry_busqueda.delete(0, tk.END)

    def limpiar_todo():
        limpiar_formulario()
        limpiar_filtro()
        cargar_tabla()

    def cargar_tabla(nombre_filtro: str | None = None):
        tree.delete(*tree.get_children())
        for p in _fetch_productos(nombre_filtro):
            tree.insert(
                "",
                tk.END,
                values=(
                    p[0],  # ID
                    p[1],  # Nombre
                    f"{redondear_dos_decimales(p[2]):.2f}",  # PMayoreo
                    f"{redondear_dos_decimales(p[3]):.2f}",  # PMenudeo
                    int(p[4] or 0),  # Unidades
                    f"{redondear_dos_decimales(p[5]):.2f}",  # Kilos
                    f"{redondear_dos_decimales(p[6]):.2f}",  # Cajas
                    f"{redondear_dos_decimales(p[7]):.2f}",  # PesoCaja
                ),
            )
        # Rayado alterno
        set_treeview_stripes(tree, even_bg=PALETTE.get("alt_row"), odd_bg=PALETTE.get("panel"))

    def _leer_formulario():
        nombre = widgets["Nombre"].get().strip()
        if not nombre:
            raise ValueError("El nombre es obligatorio.")

        pmay = to_float(widgets["Precio Mayoreo"].get() or 0, permitir_cero=True)
        pmen = to_float(widgets["Precio Menudeo"].get() or 0, permitir_cero=True)
        unidades = to_int(widgets["Unidades"].get() or 0, permitir_cero=True)
        kilos = to_float(widgets["Kilos"].get() or 0, permitir_cero=True)
        num_cajas = to_float(widgets["# Cajas"].get() or 0, permitir_cero=True)
        peso_caja = to_float(widgets["Peso x Caja (kg)"].get() or 0, permitir_cero=True)

        if (
            pmay < 0
            or pmen < 0
            or unidades < 0
            or kilos < 0
            or num_cajas < 0
            or peso_caja < 0
        ):
            raise ValueError("Los valores numéricos no pueden ser negativos.")

        return nombre, pmay, pmen, unidades, kilos, num_cajas, peso_caja

    # ---------- Acciones CRUD ----------
    def guardar_producto():
        """Si hay uno seleccionado: actualiza. Si no, intenta insertar (resuelve duplicado por nombre)."""
        if selected_id["id"]:
            return actualizar_producto_seleccionado()

        try:
            nombre, pmay, pmen, unidades, kilos, num_cajas, peso_caja = _leer_formulario()
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return

        # ¿Existe ya un producto con ese nombre?
        existe, prod_id = _existe_producto_por_nombre(nombre)
        if existe:
            if messagebox.askyesno(
                "Ya existe",
                f"Ya existe un producto llamado '{nombre}'.\n¿Deseas actualizarlo con los datos del formulario?",
            ):
                if _update_producto(
                    prod_id, nombre, pmay, pmen, unidades, kilos, num_cajas, peso_caja
                ):
                    messagebox.showinfo("Éxito", "Producto actualizado.")
                    limpiar_formulario()
                    cargar_tabla(entry_busqueda.get().strip() or None)
            return

        # Insertar nuevo
        if _insert_producto(nombre, pmay, pmen, unidades, kilos, num_cajas, peso_caja):
            messagebox.showinfo("Éxito", "Producto agregado correctamente.")
            limpiar_formulario()
            cargar_tabla(entry_busqueda.get().strip() or None)

    def cargar_a_formulario(event=None):
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0], "values")
        selected_id["id"] = vals[0]
        widgets["Nombre"].delete(0, tk.END)
        widgets["Nombre"].insert(0, vals[1])
        widgets["Precio Mayoreo"].delete(0, tk.END)
        widgets["Precio Mayoreo"].insert(0, vals[2])
        widgets["Precio Menudeo"].delete(0, tk.END)
        widgets["Precio Menudeo"].insert(0, vals[3])
        widgets["Unidades"].delete(0, tk.END)
        widgets["Unidades"].insert(0, vals[4])
        widgets["Kilos"].delete(0, tk.END)
        widgets["Kilos"].insert(0, vals[5])
        widgets["# Cajas"].delete(0, tk.END)
        widgets["# Cajas"].insert(0, vals[6])
        widgets["Peso x Caja (kg)"].delete(0, tk.END)
        widgets["Peso x Caja (kg)"].insert(0, vals[7])

    def actualizar_producto_seleccionado():
        if not selected_id["id"]:
            sel = tree.selection()
            if sel:
                selected_id["id"] = tree.item(sel[0], "values")[0]
        if not selected_id["id"]:
            messagebox.showwarning(
                "Atención",
                "Selecciona un producto para actualizar (o carga uno con doble clic).",
            )
            return
        try:
            nombre, pmay, pmen, unidades, kilos, num_cajas, peso_caja = _leer_formulario()
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return

        # Permitir cambiar nombre a uno que ya exista: si hay conflicto y NO es el mismo ID, pedir confirmación.
        existe, prod_id = _existe_producto_por_nombre(nombre)
        if existe and int(prod_id) != int(selected_id["id"]):
            if not messagebox.askyesno(
                "Nombre duplicado",
                f"Ya existe otro producto llamado '{nombre}'.\n¿Deseas usar el mismo nombre de todos modos?",
            ):
                return

        if _update_producto(
            selected_id["id"], nombre, pmay, pmen, unidades, kilos, num_cajas, peso_caja
        ):
            messagebox.showinfo("Éxito", "Producto actualizado correctamente.")
            limpiar_formulario()
            cargar_tabla(entry_busqueda.get().strip() or None)

    def eliminar_producto_seleccionado():
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("Atención", "Selecciona un producto para eliminar.")
            return
        producto_id, nombre = tree.item(sel[0], "values")[0], tree.item(sel[0], "values")[1]
        confirmar = messagebox.askyesno(
            "Confirmar eliminación",
            f"Esta acción no se puede deshacer.\n¿Eliminar '{nombre}' (ID {producto_id})?",
        )
        if confirmar and _delete_producto(producto_id):
            messagebox.showinfo("Éxito", "Producto eliminado correctamente.")
            limpiar_formulario()
            cargar_tabla(entry_busqueda.get().strip() or None)

    # ---------- Eventos / Atajos ----------
    # Búsqueda
    entry_busqueda.bind(
        "<KeyRelease>", lambda e: cargar_tabla(entry_busqueda.get().strip())
    )
    entry_busqueda.bind(
        "<Return>", lambda e: cargar_tabla(entry_busqueda.get().strip())
    )

    # Tabla
    tree.bind("<Double-1>", cargar_a_formulario)
    tree.bind("<Return>", cargar_a_formulario)  # Enter en tabla = editar
    tree.bind("<Delete>", lambda ev: eliminar_producto_seleccionado())

    # Atajos teclado en formulario
    for e in widgets.values():
        e.bind(
            "<Return>",
            lambda ev: (
                actualizar_producto_seleccionado()
                if selected_id["id"]
                else guardar_producto()
            ),
        )
        e.bind("<Control-l>", lambda ev: limpiar_formulario())
        e.bind(
            "<Control-s>",
            lambda ev: (
                actualizar_producto_seleccionado()
                if selected_id["id"]
                else guardar_producto()
            ),
        )

    # Atajos globales
    root.bind_all(
        "<Control-f>",
        lambda ev: (entry_busqueda.focus_set(), entry_busqueda.select_range(0, tk.END)),
    )

    def _on_escape(ev=None):
        top = root.winfo_toplevel()
        if isinstance(top, tk.Toplevel):
            try:
                top.destroy()
                return
            except Exception:
                pass
        limpiar_todo()

    root.bind_all("<Escape>", _on_escape)

    # ---------- Inicio ----------
    cargar_tabla()
    widgets["Nombre"].focus_set()

# -----------------------------------------------------------
# Ordenamiento por encabezados
# -----------------------------------------------------------
def _setup_sorting(tree: ttk.Treeview, columnas, tipos):
    tree._sort_state = {}
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
