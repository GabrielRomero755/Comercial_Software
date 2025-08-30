Aplicación de escritorio para gestión de Productos, Inventario, Ventas, Créditos, Mermas, Gastos y Reportes con SQLite y UI en Tkinter. Incluye tickets (PDF/TXT), impresión directa (CUPS/Windows) y respaldo nativo de la base de datos.

✨ Características

UI unificada con tema de marca (Tkinter + ttk).

Ventas por KILOS o UNIDADES (CAJAS opcional/referencial).

Carrito multiproducto (detalle en venta_items).

Precios por modo: Manual / Mayoreo / Menudeo.

Crédito con ajuste automático de deuda_total (si la columna existe).

Tickets:

PDF A4 o Rollo térmico 80/58 mm (alto dinámico).

Fallback a TXT general y TXT térmico.

Impresión directa (CUPS en Linux/macOS, mecanismo por defecto en Windows).

Respaldos de la BD con un clic (SQLite backup API).

Búsquedas, ordenamiento por encabezados, validadores (2 decimales), atajos de teclado.

🧰 Requisitos

Python 3.10+ (recomendado).

Tkinter (viene con Python; en algunas distros Linux instalar python3-tk).

SQLite (incluido en Python).

Opcional para PDF: reportlab

Opcional impresión directa (Linux/macOS): CUPS (lp)

Debian/Ubuntu: sudo apt-get install cups-bsd

Fedora: sudo dnf install cups

Arch: sudo pacman -S cups

Windows: sin CUPS; impresión mediante app asociada a PDF/TXT.

🚀 Instalación rápida