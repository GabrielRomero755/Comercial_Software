# ui/tickets.py
# -----------------------------------------------------------
# Generación de tickets (PDF / TXT / Térmico 58/80mm)
#
# Puntos clave:
# - REPORTLAB_OK: bandera de disponibilidad de ReportLab.
# - imprimir_ticket(venta_id, reimpresion=False, prefer_pdf=True, abrir_archivo=True, output_dir=None)
#   1) Lee la venta desde la BD.
#   2) Construye el dict de ticket.
#   3) Genera PDF si ReportLab está disponible (o TXT como fallback).
#   4) (Opcional) abre el archivo resultante.
#
# - generate_ticket(): elige PDF si hay ReportLab y prefer_pdf=True; si no, TXT.
# - generate_ticket_pdf() / generate_ticket_txt(): salidas generales (A4 / texto ancho fijo).
# - render_receipt_text(): forma un string optimizado para rollo térmico (58/80mm).
# - generate_ticket_txt_thermal(): guarda la versión térmica en .txt (útil para impresoras genéricas).
#
# Estructura esperada de ticket:
# {
#   "company_name": "Ajos La Misión",
#   "sale_id": 123,
#   "items": [
#       {"producto":"Ajo morado", "kilos": 12.5, "unidades": 0, "precio": 45.0, "importe": 562.5},
#       {"producto":"Malla ajo",  "kilos": 0.0,  "unidades": 10, "precio": 12.0, "importe": 120.0},
#   ],
#   "total_kilos": 12.5,
#   "total_unidades": 10,
#   "total_venta": 682.5,
#   "fecha": "YYYY-MM-DD HH:MM:SS",
#   "nota": "COPIA"   # opcional; se imprime si reimpresión
# }
# -----------------------------------------------------------

from __future__ import annotations

import os
import sys
import platform
from datetime import datetime
from typing import Tuple, Dict, Any, Optional

from .helpers import redondear_dos_decimales, formato_moneda
from db.database import get_connection, get_db_path

# ---- Shim ReportLab (Windows md5 usedforsecurity) ----
try:
    import hashlib as _hashlib
    _orig_md5 = _hashlib.md5
    try:
        _orig_md5(b"", usedforsecurity=False)  # type: ignore[arg-type]
    except TypeError:
        def _md5_compat(*args, **kwargs):
            kwargs.pop("usedforsecurity", None)
            return _orig_md5(*args, **kwargs)
        _hashlib.md5 = _md5_compat  # type: ignore[assignment]
except Exception:
    pass

# ---- Carga condicional de ReportLab ----
try:
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False


# ===========================================================
# Utilidades
# ===========================================================
def _ticket_defaults(ticket: dict) -> dict:
    t = dict(ticket or {})
    t.setdefault("company_name", "Ajos La Misión")
    t.setdefault("sale_id", "")
    t.setdefault("items", [])
    t.setdefault("total_kilos", 0.0)
    t.setdefault("total_unidades", 0)
    t.setdefault("total_venta", 0.0)
    t.setdefault("fecha", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return t


def _tickets_output_dir(default_folder: Optional[str] = None) -> str:
    """
    Directorio de salida por defecto:
    <carpeta_datos_usuario>/SistemaComercio/tickets/
    """
    if default_folder:
        os.makedirs(default_folder, exist_ok=True)
        return default_folder
    db_dir = get_db_path().parent
    out = os.path.join(str(db_dir), "tickets")
    os.makedirs(out, exist_ok=True)
    return out


def _open_file(path: str) -> None:
    """Intenta abrir el archivo con la app por defecto del SO."""
    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            os.system(f"open '{path}'")
        else:
            os.system(f"xdg-open '{path}'")
    except Exception:
        # Si no se puede abrir, lo ignoramos silenciosamente.
        pass


# ===========================================================
# Generación de archivos
# ===========================================================
def generate_ticket(ticket: dict, output_dir: str, prefer_pdf: bool = True) -> str:
    """
    Genera un ticket en output_dir. Si ReportLab está disponible y prefer_pdf=True,
    crea un PDF; si no, genera un .txt. Devuelve la ruta generada.
    """
    os.makedirs(output_dir, exist_ok=True)
    base = f"ticket_venta_{ticket.get('sale_id','')}".strip("_")
    if prefer_pdf and REPORTLAB_OK:
        path = os.path.join(output_dir, f"{base}.pdf")
        return generate_ticket_pdf(ticket, path)
    path = os.path.join(output_dir, f"{base}.txt")
    return generate_ticket_txt(ticket, path)


def generate_ticket_pdf(ticket: dict, output_path: str) -> str:
    """
    Genera ticket en PDF (A4). Sencillo, legible e imprimible en cualquier impresora.
    """
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab no está disponible")
    t = _ticket_defaults(ticket)

    doc = SimpleDocTemplate(output_path, pagesize=A4)
    elementos = []
    estilos = getSampleStyleSheet()

    # Encabezado
    titulo = t["company_name"]
    if t.get("nota"):
        titulo = f"{titulo} — {t['nota']}"
    elementos.append(Paragraph(str(titulo), estilos["Title"]))
    elementos.append(Paragraph("Ticket de Venta", estilos["Heading2"]))
    elementos.append(Paragraph(f"ID Venta: {t['sale_id']} &nbsp;&nbsp;&nbsp; Fecha: {t['fecha']}", estilos["Normal"]))
    elementos.append(Spacer(1, 6))

    # Tabla
    encabezado = ["Producto", "Kilos", "Unidades", "Precio", "Importe"]
    datos = [encabezado]
    for it in (t["items"] or []):
        datos.append([
            str(it.get("producto","")),
            f"{redondear_dos_decimales(it.get('kilos',0.0)):.2f}",
            str(int(it.get('unidades',0) or 0)),
            f"{redondear_dos_decimales(it.get('precio',0.0)):.2f}",
            f"{redondear_dos_decimales(it.get('importe',0.0)):.2f}",
        ])

    tabla = Table(datos)
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 6))

    # Totales
    elementos.append(Paragraph(
        f"Total kilos: {redondear_dos_decimales(t['total_kilos']):.2f} &nbsp;&nbsp; "
        f"Total unidades: {int(t['total_unidades'] or 0)}",
        estilos["Normal"])
    )
    elementos.append(Paragraph(f"Total a pagar: {formato_moneda(t['total_venta'])}", estilos["Heading3"]))
    elementos.append(Spacer(1, 8))
    elementos.append(Paragraph("¡Gracias por su compra!", estilos["Italic"]))

    doc.build(elementos)
    return output_path


def generate_ticket_txt(ticket: dict, output_path: str) -> str:
    """
    Genera ticket en texto plano ancho fijo (apto para impresión general).
    """
    t = _ticket_defaults(ticket)
    lines = []
    header = t['company_name']
    if t.get("nota"):
        header = f"{header} - {t['nota']}"
    lines.append(f"{header}\n")
    lines.append("TICKET DE VENTA\n")
    lines.append(f"ID Venta: {t['sale_id']}   Fecha: {t['fecha']}\n")
    lines.append("-" * 54 + "\n")
    lines.append(f"{'Producto':25} {'Kg':>7} {'Unid':>7} {'Precio':>12} {'Importe':>12}\n")
    lines.append("-" * 54 + "\n")
    for it in (t["items"] or []):
        prod = str(it.get("producto",""))[:25].ljust(25)
        kg   = f"{redondear_dos_decimales(it.get('kilos',0.0)):.2f}".rjust(7)
        uni  = f"{int(it.get('unidades',0) or 0)}".rjust(7)
        pre  = f"{redondear_dos_decimales(it.get('precio',0.0)):.2f}".rjust(12)
        imp  = f"{redondear_dos_decimales(it.get('importe',0.0)):.2f}".rjust(12)
        lines.append(f"{prod}{kg}{uni}{pre}{imp}\n")

    lines.append("-" * 54 + "\n")
    lines.append(f"Total kilos:    {redondear_dos_decimales(t['total_kilos']):.2f}\n")
    lines.append(f"Total unidades: {int(t['total_unidades'] or 0)}\n")
    lines.append(f"TOTAL A PAGAR:  {formato_moneda(t['total_venta'])}\n")
    lines.append("\nGracias por su compra.\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return output_path


# ---------- Formato térmico (58/80 mm) ----------
def render_receipt_text(ticket: dict, width: int = 42) -> str:
    """
    Renderiza un ticket en texto adecuado para rollo térmico.
    width típico: 32 (58mm) o 42 (80mm).
    """
    t = _ticket_defaults(ticket)
    w = max(24, int(width))

    def line(txt: str = "", fill: str = " ") -> str:
        return (txt[:w]).ljust(w, fill) + "\n"

    def right(txt: str) -> str:
        s = str(txt)
        if len(s) > w:
            s = s[:w]
        return " " * (w - len(s)) + s + "\n"

    out = []
    header = t["company_name"]
    if t.get("nota"):
        header = f"{header} - {t['nota']}"
    out.append(line(header.center(w)))
    out.append(line("TICKET DE VENTA".center(w)))
    out.append(line(f"ID: {t['sale_id']}  FECHA: {t['fecha']}"))
    out.append(line("-" * w, fill="-"))

    # Encabezados columnas
    # Producto (w-26) | Kg (6) | Unid (6) | Importe (14)
    col_prod = max(10, w - 26)
    out.append(f"{'Producto'.ljust(col_prod)}{'Kg'.rjust(6)}{'Unid'.rjust(6)}{'Importe'.rjust(14)}\n")
    out.append(line("-" * w, fill="-"))

    for it in (t["items"] or []):
        prod = str(it.get("producto",""))
        kg   = f"{redondear_dos_decimales(it.get('kilos',0.0)):.2f}"
        uni  = f"{int(it.get('unidades',0) or 0)}"
        imp  = f"{redondear_dos_decimales(it.get('importe',0.0)):.2f}"

        # Puede ocupar varias líneas si el producto es largo
        first = True
        while prod:
            p_chunk, prod = prod[:col_prod], prod[col_prod:]
            if first:
                out.append(f"{p_chunk.ljust(col_prod)}{kg.rjust(6)}{uni.rjust(6)}{imp.rjust(14)}\n")
                first = False
            else:
                out.append(f"{p_chunk}\n")

    out.append(line("-" * w, fill="-"))
    out.append(line(f"Total kilos: {redondear_dos_decimales(t['total_kilos']):.2f}"))
    out.append(line(f"Total unidades: {int(t['total_unidades'] or 0)}"))
    out.append(right(f"TOTAL: {formato_moneda(t['total_venta'])}"))
    out.append("\n")
    out.append(line("¡Gracias por su compra!".center(w)))
    return "".join(out)


def generate_ticket_txt_thermal(ticket: dict, output_path: str, width: int = 42) -> str:
    """
    Guarda el ticket en formato térmico como .txt.
    (Útil para impresoras USB genéricas o compartir al driver de impresión.)
    """
    content = render_receipt_text(ticket, width=width)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


# ===========================================================
# Integración con la BD y punto de entrada público
# ===========================================================
def _load_sale_from_db(venta_id: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Lee venta + producto (+ cliente si existe). Devuelve:
      - venta: dict con campos crudos (kilos, unidades, precio, total, etc.)
      - meta:  dict auxiliar (nombre_producto, nombre_cliente, peso_caja opcional)
    """
    with get_connection() as conn:
        cur = conn.cursor()
        # Venta y producto
        cur.execute("""
            SELECT v.id, v.producto_id, v.kilos, v.num_cajas, v.unidades, v.precio, v.total,
                   v.tipo_venta, v.cliente_id, v.fecha
            FROM ventas v
            WHERE v.id = ?
        """, (venta_id,))
        v = cur.fetchone()
        if not v:
            raise ValueError(f"Venta #{venta_id} no encontrada.")

        venta = {
            "id": int(v[0]),
            "producto_id": int(v[1]),
            "kilos": float(v[2] or 0.0),
            "num_cajas": float(v[3] or 0.0),
            "unidades": int(v[4] or 0),
            "precio": float(v[5] or 0.0),
            "total": float(v[6] or 0.0),
            "tipo_venta": (v[7] or "contado"),
            "cliente_id": (int(v[8]) if v[8] is not None else None),
            "fecha": v[9],
        }

        cur.execute("""
            SELECT nombre, peso_caja FROM productos WHERE id = ?
        """, (venta["producto_id"],))
        p = cur.fetchone()
        if not p:
            raise ValueError("Producto de la venta no encontrado.")
        nombre_producto = p[0] or "Producto"
        peso_caja = float(p[1] or 0.0)

        nombre_cliente = ""
        # Cliente puede no existir o no tener campo nombre en esquemas antiguos
        try:
            if venta["cliente_id"] is not None:
                cur.execute("SELECT nombre FROM clientes WHERE id = ?", (venta["cliente_id"],))
                c = cur.fetchone()
                if c and c[0]:
                    nombre_cliente = c[0]
        except Exception:
            nombre_cliente = ""

        meta = {
            "nombre_producto": nombre_producto,
            "nombre_cliente": nombre_cliente,
            "peso_caja": peso_caja,
        }
        return venta, meta


def _build_ticket_dict(venta: Dict[str, Any], meta: Dict[str, Any], reimpresion: bool) -> Dict[str, Any]:
    """
    Transforma la venta cruda en el dict de ticket esperado por los generadores.
    """
    kilos = float(venta.get("kilos") or 0.0)
    unidades = int(venta.get("unidades") or 0)
    precio = float(venta.get("precio") or 0.0)
    total = float(venta.get("total") or (kilos * precio if kilos > 0 else unidades * precio))

    items = [{
        "producto": meta["nombre_producto"],
        "kilos": kilos,
        "unidades": unidades,
        "precio": precio,
        "importe": total,
    }]

    ticket = {
        "company_name": "Ajos La Misión",
        "sale_id": venta["id"],
        "items": items,
        "total_kilos": kilos,
        "total_unidades": unidades,
        "total_venta": total,
        "fecha": venta.get("fecha") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if reimpresion:
        ticket["nota"] = "COPIA"
    return ticket


def imprimir_ticket(
    venta_id: int,
    reimpresion: bool = False,
    prefer_pdf: bool = True,
    abrir_archivo: bool = True,
    output_dir: Optional[str] = None,
    thermal_txt_also: bool = False,
    thermal_width: int = 42,
) -> str:
    """
    Genera (y opcionalmente abre) el ticket de una venta.
    - venta_id: ID de ventas.id a imprimir.
    - reimpresion: si True, añade leyenda "COPIA".
    - prefer_pdf: si ReportLab está disponible y True, genera PDF; si no, TXT.
    - abrir_archivo: si True, intentará abrir el archivo generado.
    - output_dir: carpeta donde guardar el ticket (por defecto: …/tickets/).
    - thermal_txt_also: además del PDF/TXT general, guarda un TXT térmico aparte.
    - thermal_width: ancho del recibo térmico (32 para 58mm, 42 para 80mm).

    Devuelve la ruta del archivo principal generado.
    """
    # 1) Leer venta y armar estructura
    venta, meta = _load_sale_from_db(int(venta_id))
    ticket = _build_ticket_dict(venta, meta, reimpresion=reimpresion)

    # 2) Determinar carpeta de salida y nombres
    out_dir = _tickets_output_dir(output_dir)

    # 3) Generar archivo principal (PDF o TXT)
    main_path = generate_ticket(ticket, out_dir, prefer_pdf=prefer_pdf)

    # 4) Opcional: generar también versión térmica
    if thermal_txt_also:
        base = f"ticket_venta_{ticket.get('sale_id','')}".strip("_")
        thermal_path = os.path.join(out_dir, f"{base}_thermal.txt")
        try:
            generate_ticket_txt_thermal(ticket, thermal_path, width=int(thermal_width))
        except Exception:
            # No interrumpimos si falla la versión térmica
            pass

    # 5) Abrir archivo si procede
    if abrir_archivo:
        _open_file(main_path)

    return main_path
