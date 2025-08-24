# main.py
# -----------------------------------------------------------
# Punto de entrada del Sistema de Comercio (GUI Tkinter)
# + Barra de estado (status bar) para mensajes contextuales.
# + Tema ttk unificado (ui.theme) y atajos globales.
# + Persistencia de última vista.
# + Respaldo de BD con diálogo de carpeta (backup nativo SQLite).
# -----------------------------------------------------------

import os
import sys
import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from modules import productos, inventario, ventas, reportes, creditos, mermas, gastos, home
from ui.helpers import centrar_ventana
from db.database import init_db, get_connection  # noqa: F401  (get_connection se usa indirectamente por módulos)
from ui.theme import apply_brand_ttk_theme, BRAND_PALETTE

PALETTE = BRAND_PALETTE  # paleta centralizada: {"bg","panel","text","primary","accent","border",...}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "app_state.json")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sistema de Gestión")
        self.geometry("1000x650")
        self.minsize(900, 560)
        self.configure(bg=PALETTE["bg"])
        centrar_ventana(self, 1000, 650)

        # Intentar establecer ícono (opcional)
        self._set_icon()

        # Aplicar tema ttk unificado (colores / estilos por marca)
        self._style = apply_brand_ttk_theme(self)

        # Estado UI
        self._botones_menu: dict[str, tk.Button] = {}
        self._boton_activo: str | None = None
        self._closing = False  # evita reentrancia al cerrar

        # Layout raíz con grid (navbar, contenido, status)
        self.grid_rowconfigure(1, weight=1)   # contenido
        self.grid_columnconfigure(0, weight=1)

        self._crear_widgets()
        self._configurar_atajos_teclado()
        self.protocol("WM_DELETE_WINDOW", self._confirmar_salida)

        # Cargar vista inicial -> última usada o "Inicio"
        last = (self._leer_estado().get("last_view") or "Inicio")
        self._activar_y_cargar(last, self._resolver_loader(last), persist=False)

    # -------------------------------------------------------
    # Icono de la ventana
    # -------------------------------------------------------
    def _set_icon(self):
        try:
            ico = os.path.join(BASE_DIR, "assets", "icon.ico")
            png = os.path.join(BASE_DIR, "assets", "logo.png")
            if os.path.exists(ico):
                self.iconbitmap(default=ico)
            elif os.path.exists(png):
                img = tk.PhotoImage(file=png)
                self.iconphoto(True, img)
                self._icon_img_ref = img  # mantener referencia
        except Exception:
            pass

    # -------------------------------------------------------
    # Construcción de UI
    # -------------------------------------------------------
    def _crear_widgets(self):
        # Navbar superior
        self.navbar = tk.Frame(self, bg=PALETTE["bg"], highlightthickness=0, bd=0)
        self.navbar.grid(row=0, column=0, sticky="nsew")

        self._boton_specs = [
            ("Inicio",     self.cargar_inicio,    "Alt+0"),
            ("Productos",  self.cargar_productos, "Alt+1"),
            ("Inventario", self.cargar_inventario,"Alt+2"),
            ("Ventas",     self.cargar_ventas,    "Alt+3"),
            ("Créditos",   self.cargar_creditos,  "Alt+4"),
            ("Mermas",     self.cargar_mermas,    "Alt+5"),
            ("Gastos",     self.cargar_gastos,    "Alt+6"),
            ("Reportes",   self.cargar_reportes,  "Alt+7"),
        ]

        # Columnas de la navbar con pesos iguales (+1 para botón de respaldo)
        total_cols = len(self._boton_specs) + 1
        for c in range(total_cols):
            self.navbar.grid_columnconfigure(c, weight=1, uniform="nav")

        # Crear botones
        for idx, (texto, comando, _atajo) in enumerate(self._boton_specs):
            b = self._nav_button(self.navbar, label=texto, command=lambda c=comando, ref=texto: self._activar_y_cargar(ref, c))
            b.grid(row=0, column=idx, sticky="nsew", padx=6, pady=8)
            self._botones_menu[texto] = b

        # Botón de respaldo BD (última columna)
        self.btn_backup = self._nav_button(self.navbar, label="Respaldar BD", command=self._respaldar_bd)
        self.btn_backup.grid(row=0, column=total_cols - 1, sticky="nsew", padx=(6, 12), pady=8)

        # Contenedor principal (los módulos insertan su propio frame dentro)
        self.contenido_frame = tk.Frame(self, bg=PALETTE["panel"], highlightthickness=0, bd=0)
        self.contenido_frame.grid(row=1, column=0, sticky="nsew")
        self.contenido_frame.grid_rowconfigure(0, weight=1)
        self.contenido_frame.grid_columnconfigure(0, weight=1)

        # Status bar
        status_frame = tk.Frame(self, bg=PALETTE["panel"], highlightthickness=0, bd=0)
        status_frame.grid(row=2, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="Listo.")
        self.status_label = tk.Label(
            status_frame, textvariable=self.status_var,
            anchor="w", padx=10, pady=6,
            bg=PALETTE["panel"], fg=PALETTE["text"]
        )
        self.status_label.pack(fill="x")

    def _nav_button(self, parent, label, command):
        btn = tk.Button(
            parent, text=label, command=command,
            bg=PALETTE["primary"], fg=PALETTE["text"],
            activebackground=PALETTE["accent"], activeforeground=PALETTE["text"],
            relief="raised", bd=1,
            padx=12, pady=8, cursor="hand2",
            highlightthickness=1, highlightbackground=PALETTE["border"], highlightcolor=PALETTE["accent"],
        )

        def _on_enter(_):
            if self._boton_activo and self._botones_menu.get(self._boton_activo) is btn:
                return
            btn.configure(bg=PALETTE["accent"])

        def _on_leave(_):
            if self._boton_activo and self._botones_menu.get(self._boton_activo) is btn:
                return
            btn.configure(bg=PALETTE["primary"])

        btn.bind("<Enter>", _on_enter)
        btn.bind("<Leave>", _on_leave)
        return btn

    def _configurar_atajos_teclado(self):
        # Navegación rápida (Alt+N)
        self.bind_all("<Alt-Key-0>", lambda _e: self._activar_y_cargar("Inicio", self.cargar_inicio))
        self.bind_all("<Alt-Key-1>", lambda _e: self._activar_y_cargar("Productos", self.cargar_productos))
        self.bind_all("<Alt-Key-2>", lambda _e: self._activar_y_cargar("Inventario", self.cargar_inventario))
        self.bind_all("<Alt-Key-3>", lambda _e: self._activar_y_cargar("Ventas", self.cargar_ventas))
        self.bind_all("<Alt-Key-4>", lambda _e: self._activar_y_cargar("Créditos", self.cargar_creditos))
        self.bind_all("<Alt-Key-5>", lambda _e: self._activar_y_cargar("Mermas", self.cargar_mermas))
        self.bind_all("<Alt-Key-6>", lambda _e: self._activar_y_cargar("Gastos", self.cargar_gastos))
        self.bind_all("<Alt-Key-7>", lambda _e: self._activar_y_cargar("Reportes", self.cargar_reportes))

        # Utilitarios
        self.bind_all("<Control-b>", lambda _e: self._respaldar_bd())  # backup
        self.bind_all("<F5>",        lambda _e: self._recargar_vista_activa())
        self.bind_all("<F11>",       lambda _e: self._toggle_fullscreen(True))
        self.bind_all("<Escape>",    lambda _e: self._toggle_fullscreen(False))

    # -------------------------------------------------------
    # Barra de estado
    # -------------------------------------------------------
    def set_status(self, texto: str):
        self.status_var.set(texto)
        self.status_label.update_idletasks()

    # -------------------------------------------------------
    # Navegación / Carga de vistas
    # -------------------------------------------------------
    def _activar_y_cargar(self, nombre_boton, cargar_callback, persist: bool = True):
        # Reset de botones
        for nombre, btn in self._botones_menu.items():
            if nombre == nombre_boton:
                btn.config(bg=PALETTE["accent"], relief="sunken")
            else:
                btn.config(bg=PALETTE["primary"], relief="raised")
        self._boton_activo = nombre_boton

        # Cargar vista
        self.set_status(f"Cargando módulo: {nombre_boton}…")
        self.limpiar_contenido()
        try:
            cargar_callback()  # cada módulo gestiona su layout
            self.set_status(f"Módulo activo: {nombre_boton}")
            if persist:
                self._guardar_estado({"last_view": nombre_boton})
        except Exception as e:
            self.set_status("Error al cargar módulo.")
            messagebox.showerror("Error", f"No se pudo cargar el módulo '{nombre_boton}'.\n{e}", parent=self)

    def limpiar_contenido(self):
        for widget in self.contenido_frame.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass

    # -------------------------------------------------------
    # Resolver callback desde el nombre (persistencia)
    # -------------------------------------------------------
    def _resolver_loader(self, nombre: str):
        mapping = {
            "Inicio":     self.cargar_inicio,
            "Productos":  self.cargar_productos,
            "Inventario": self.cargar_inventario,
            "Ventas":     self.cargar_ventas,
            "Créditos":   self.cargar_creditos,
            "Mermas":     self.cargar_mermas,
            "Gastos":     self.cargar_gastos,
            "Reportes":   self.cargar_reportes,
        }
        return mapping.get(nombre, self.cargar_inicio)

    # -------------------------------------------------------
    # Métodos para cargar módulos
    # -------------------------------------------------------
    def cargar_inicio(self):
        home.mostrar(self.contenido_frame)

    def cargar_productos(self):
        productos.mostrar(self.contenido_frame)

    def cargar_inventario(self):
        inventario.mostrar(self.contenido_frame)

    def cargar_ventas(self):
        ventas.mostrar(self.contenido_frame)

    def cargar_creditos(self):
        creditos.mostrar(self.contenido_frame)

    def cargar_mermas(self):
        mermas.mostrar(self.contenido_frame)

    def cargar_gastos(self):
        gastos.mostrar(self.contenido_frame)

    def cargar_reportes(self):
        reportes.mostrar(self.contenido_frame)

    # -------------------------------------------------------
    # Respaldo de Base de Datos (SQLite)
    # -------------------------------------------------------
    def _respaldar_bd(self):
        """
        Crea un archivo de respaldo usando la API nativa de SQLite.
        - Abre un diálogo para elegir carpeta de destino en cada ejecución.
        - Nombra el archivo con timestamp para evitar sobrescrituras.
        """
        try:
            self.btn_backup.config(state="disabled")

            # Carpeta sugerida (Documentos o HOME)
            home_dir = os.path.expanduser("~")
            docs_dir = os.path.join(home_dir, "Documents")
            initial_dir = docs_dir if os.path.isdir(docs_dir) else home_dir

            destino_dir = filedialog.askdirectory(
                parent=self,
                initialdir=initial_dir,
                title="Selecciona la carpeta donde se guardará el respaldo"
            )
            if not destino_dir:
                self.set_status("Respaldo cancelado.")
                return

            filename = f"backup_{self._timestamp()}.sqlite3"
            destino = os.path.join(destino_dir, filename)

            self.set_status("Creando respaldo de BD…")
            # Usar backup nativo de SQLite
            # Nota: get_connection() ya aplica PRAGMA foreign_keys=ON en la app.
            from db.database import get_connection as _gc  # import local para evitar ciclos
            with _gc() as src_conn:
                with sqlite3.connect(destino) as dst_conn:
                    src_conn.backup(dst_conn)

            self.set_status("Respaldo de BD creado.")
            if messagebox.askyesno(
                "Respaldo creado",
                f"Se generó el respaldo:\n{destino}\n\n¿Deseas abrir la carpeta?",
                parent=self
            ):
                self._abrir_carpeta(destino_dir)

        except Exception as e:
            messagebox.showerror("Error al respaldar", f"No se pudo crear el respaldo.\n{e}", parent=self)
            self.set_status("Error al crear respaldo de BD.")
        finally:
            self.btn_backup.config(state="normal")

    def _abrir_carpeta(self, ruta: str):
        try:
            if os.name == "nt":            # Windows
                os.startfile(ruta)
            elif sys.platform == "darwin": # macOS
                os.system(f'open "{ruta}"')
            else:                          # Linux/Unix
                os.system(f'xdg-open "{ruta}" >/dev/null 2>&1 &')
        except Exception:
            pass

    @staticmethod
    def _timestamp():
        import datetime as _dt
        return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    # -------------------------------------------------------
    # Persistencia de estado (última vista)
    # -------------------------------------------------------
    def _leer_estado(self) -> dict:
        try:
            if os.path.exists(STATE_PATH):
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _guardar_estado(self, data: dict):
        try:
            prev = self._leer_estado()
            prev.update(data or {})
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(prev, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # -------------------------------------------------------
    # Utilitarios UI
    # -------------------------------------------------------
    def _recargar_vista_activa(self):
        if not self._boton_activo:
            return
        self._activar_y_cargar(self._boton_activo, self._resolver_loader(self._boton_activo))

    def _toggle_fullscreen(self, on: bool):
        try:
            self.attributes("-fullscreen", bool(on))
            self.set_status("Pantalla completa" if on else "Ventana normal")
        except Exception:
            pass

    # -------------------------------------------------------
    # Ventana / ciclo
    # -------------------------------------------------------
    def _confirmar_salida(self, _event=None):
        """Confirma salida evitando errores si la app ya se está destruyendo."""
        if self._closing:
            return
        self._closing = True
        try:
            if not self.winfo_exists():
                return
            salir = messagebox.askyesno("Salir", "¿Deseas cerrar?", parent=self)
        except tk.TclError:
            return
        if salir:
            self.after_idle(self.destroy)  # Destruir al final del ciclo de eventos
        else:
            self._closing = False


if __name__ == "__main__":
    try:
        init_db()
    except Exception as e:
        try:
            messagebox.showerror("Error crítico", f"No se pudo inicializar la base de datos.\n{e}")
        except Exception:
            print(f"[ERROR] No se pudo inicializar la base de datos: {e}")

    app = App()
    app.mainloop()
