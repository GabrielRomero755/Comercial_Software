# Comercial_Software
Sistema de Gestión para Comerciante
# Sistema de Comercio (Tkinter + SQLite)

Aplicación de escritorio para punto de venta e inventario con interfaz oscura, base de datos SQLite y reportes en PDF/CSV. Optimizada para Windows 10+, pero funciona en Linux.

---

## 🚀 Características principales

* **Módulos**: Inicio, Productos, Inventario, Ventas, Créditos, Mermas, Gastos, Reportes.
* **Ventas**: modalidades *Unidades / Cajas / Kilos* (excluyentes) y modo de precio *Manual / Mayoreo / Menudeo*.
* **Inventario**: actualizaciones con redondeo a 2 decimales, impacto cruzado por peso de caja.
* **Créditos**: manejo de `deuda_total` por cliente y reporte dedicado.
* **Gastos**: registro y reportes por rango.
* **Reportes**: filtros por fecha, atajos, ordenamiento por columnas y exportación a **PDF** (opcional con ReportLab) y **CSV**.
* **Tema oscuro** consistente en toda la UI.
* **Respaldo** de la base de datos desde un botón que permite elegir carpeta de destino.
* **Compatibilidad Windows**: rutas escribibles y corrección del error `usedforsecurity` (ReportLab/OpenSSL).

---

## 🧩 Requisitos

* **Python 3.10+**
* Paquetes:

  * Obligatorios: `tkinter` (viene con Python estándar)
  * Recomendados: `reportlab` (para exportar PDF)
* (Opcional) `PyInstaller` para crear ejecutable en Windows.

Instalación de dependencias:

```bash
# Crear entorno (opcional)
python -m venv .venv
# Activar
#   Windows: .venv\Scripts\activate
#   Linux/macOS: source .venv/bin/activate

# Instalar ReportLab para exportar PDF
pip install reportlab
```

> Si no instalas ReportLab, los botones “Exportar PDF” aparecerán deshabilitados; siempre puedes exportar **CSV**.

---

## ▶️ Ejecutar

```bash
python main.py
```

---

## 🗂️ Estructura del proyecto (resumen)

```
.
├─ main.py
├─ db/
│  ├─ database.py          # Conexión SQLite + init_db()
│  └─ init_db.sql          # Esquema (usar IF NOT EXISTS)
├─ modules/
│  ├─ productos.py
│  ├─ inventario.py
│  ├─ ventas.py
│  ├─ creditos.py
│  ├─ mermas.py
│  ├─ gastos.py
│  ├─ reportes.py          # Exportar PDF/CSV; fix MD5 para Windows
│  └─ calendar_widget.py
├─ ui/
│  └─ helpers.py           # resource_path, validadores, formateo, etc.
└─ assets/
   ├─ icon.ico (Windows)
   └─ logo.png (fallback)
```

---

## 🗄️ Base de datos (SQLite)

La app guarda la BD en una **carpeta de datos del usuario** (evita problemas de permisos):

* **Windows**: `%APPDATA%\SistemaComercio\datos_comercio.db`
* **Linux**: `~/.local/share/SistemaComercio/datos_comercio.db`

> `init_db()` ejecuta `db/init_db.sql` (incluye `IF NOT EXISTS`) y es idempotente.

### Respaldo de BD

* Botón **“Respaldar BD”** en la barra superior.
* Siempre **pide carpeta** y crea un archivo `backup_YYYYmmdd_HHMMSS.sqlite3`.

> Evita rutas protegidas como `C:\Program Files\...` para no chocar con *Acceso denegado*; usa “Documentos” u otra carpeta del usuario.

---

## 🧾 Reportes (Ventas / Gastos / Créditos)

* Filtrado por **rango de fechas** (+ atajos: Hoy / Semana / Mes).
* **Ordenamiento** clicando encabezados.
* **Exportar PDF** (si `reportlab` está instalado) y **CSV**.
* Mensaje de “Sin datos” cuando no hay resultados.

### Compatibilidad PDF en Windows

Se incluye un *shim* para `hashlib.md5` que ignora el argumento `usedforsecurity` cuando tu build de OpenSSL no lo soporta. Esto corrige el error:

```
'usedforsecurity' is an invalid keyword argument for openssl_md5()
```

No afecta la seguridad de la app; sólo evita el `TypeError` generado internamente por ReportLab en algunos entornos.

---

## ⌨️ Atajos y navegación

### Globales

* **Alt+0..7**: cambiar de módulo rápidamente (Inicio=0, …, Reportes=7)
* **F5**: recargar vista activa
* **F11**: pantalla completa
* **Esc**: salir de pantalla completa

### Reportes

* **Enter** en campos de fecha: **Generar**
* **Esc**: cerrar calendario (si está abierto)

### Ventas

* **Enter** en cualquier campo del formulario: **agrega o actualiza** (según selección)
* **Enter** en la caja de búsqueda: aplica el filtro (además del filtrado en vivo)
* **Esc**:

  * Si está abierto en **Toplevel**: cierra la ventana
  * En la ventana principal: **limpia** formulario y búsqueda
* **Ctrl+F**: enfoca la búsqueda
* **Supr**: elimina desde la tabla
* **Doble clic / Enter** en la tabla: carga al formulario

> Los validadores existentes se mantienen (decimales a 2 dígitos; unidades ≥ 1 entero, etc.).

---

## 🛠️ Empaquetado (Windows • opcional)

Con PyInstaller:

```bash
pyinstaller ^
  --noconfirm --windowed --name "Sistema de Gestión" ^
  --add-data "db/init_db.sql;db" ^
  --add-data "assets/icon.ico;assets" ^
  main.py
```

Notas:

* `resource_path` hace que `init_db.sql` e iconos funcionen empaquetados.
* La BD **no** se guarda junto al ejecutable; va al directorio de datos del usuario.

---

## 🧪 Solución de problemas

* **No genera PDF / botón no responde**
  Instala `reportlab` (`pip install reportlab`). Si aparece el error de `usedforsecurity`, ya está cubierto por el *shim* incluido en `reportes.py`.

* **Respaldo falla con “Acceso denegado”**
  No elijas carpetas del sistema como `C:\Program Files\`. Guarda en “Documentos” u otra carpeta del usuario.

* **Permisos / rutas**
  Toda escritura (BD, exportaciones, respaldos) debe ir a rutas **del usuario** (Documentos, Escritorio, etc.).

---

## 📄 Licencia

Uso interno. Puedes adaptar esta sección a la licencia que prefieras (por ejemplo, MIT).

---🙌 Créditos

* GUI: **Tkinter**
* PDF: **ReportLab** (opcional)
* DB: **SQLite**