# ui/tickets.py
# -----------------------------------------------------------
# Generación de tickets (PDF/TXT)
# - REPORTLAB_OK: bandera de disponibilidad de ReportLab.
# - generate_ticket(): elige PDF si hay ReportLab, de lo contrario TXT.
# - generate_ticket_pdf() / generate_ticket_txt()
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
#   "fecha": "YYYY-MM-DD HH:MM:SS"
# }
# -----------------------------------------------------------

from __future__ import annotations

import os
from datetime import datetime

from .helpers import redondear_dos_decimales, formato_moneda

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
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab no está disponible")
    t = _ticket_defaults(ticket)

    doc = SimpleDocTemplate(output_path, pagesize=A4)
    elementos = []
    estilos = getSampleStyleSheet()

    elementos.append(Paragraph(str(t["company_name"]), estilos["Title"]))
    elementos.append(Paragraph("Ticket de Venta", estilos["Heading2"]))
    elementos.append(Paragraph(f"ID Venta: {t['sale_id']} &nbsp;&nbsp;&nbsp; Fecha: {t['fecha']}", estilos["Normal"]))
    elementos.append(Spacer(1, 6))

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
    elementos.append(Paragraph(
        f"Total kilos: {redondear_dos_decimales(t['total_kilos']):.2f} &nbsp;&nbsp; "
        f"Total unidades: {int(t['total_unidades'] or 0)}",
        estilos["Normal"])
    )
    elementos.append(Paragraph(f"Total a pagar: {formato_moneda(t['total_venta'])}", estilos["Heading3"]))

    doc.build(elementos)
    return output_path


def generate_ticket_txt(ticket: dict, output_path: str) -> str:
    t = _ticket_defaults(ticket)
    lines = []
    lines.append(f"{t['company_name']}\n")
    lines.append("TICKET DE VENTA\n")
    lines.append(f"ID Venta: {t['sale_id']}   Fecha: {t['fecha']}\n")
    lines.append("-" * 48 + "\n")
    lines.append(f"{'Producto':22} {'Kg':>6} {'Unid':>6} {'Precio':>10} {'Importe':>10}\n")
    lines.append("-" * 48 + "\n")
    for it in (t["items"] or []):
        prod = str(it.get("producto",""))[:22].ljust(22)
        kg   = f"{redondear_dos_decimales(it.get('kilos',0.0)):.2f}".rjust(6)
        uni  = f"{int(it.get('unidades',0) or 0)}".rjust(6)
        pre  = f"{redondear_dos_decimales(it.get('precio',0.0)):.2f}".rjust(10)
        imp  = f"{redondear_dos_decimales(it.get('importe',0.0)):.2f}".rjust(10)
        lines.append(f"{prod}{kg}{uni}{pre}{imp}\n")

    lines.append("-" * 48 + "\n")
    lines.append(f"Total kilos:    {redondear_dos_decimales(t['total_kilos']):.2f}\n")
    lines.append(f"Total unidades: {int(t['total_unidades'] or 0)}\n")
    lines.append(f"TOTAL A PAGAR:  {formato_moneda(t['total_venta'])}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return output_path
