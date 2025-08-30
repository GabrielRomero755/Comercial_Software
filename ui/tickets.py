# ui/tickets.py
# -----------------------------------------------------------
# Generación de tickets (PDF / TXT / Térmico 58/80mm)
#
# - Auto-detección de impresora por defecto (CUPS) y tipo (térmica vs normal).
# - PDF "responsivo":
#       * A4 para impresoras normales.
#       * Rollo 80/58 mm (alto dinámico) para térmicas.
# - Fallback: TXT general y TXT térmico (ancho fijo 32/42).
# - Arreglado: tickets multi-item (carrito) conservan TODOS los ítems.
# - Windows: intento de impresión con os.startfile(..., "print") si procede.
# -----------------------------------------------------------

from __future__ import annotations

import os
import shutil
import subprocess
import platform
from datetime import datetime
from typing import Tuple, Dict, Any, Optional, List

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
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False


# ===========================================================
# Utilidades de ruta / salida
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
    Directorio de salida por defecto: <carpeta_datos_bd>/tickets/
    """
    if default_folder:
        os.makedirs(default_folder, exist_ok=True)
        return default_folder
    db_dir = get_db_path().parent
    out = os.path.join(str(db_dir), "tickets")
    os.makedirs(out, exist_ok=True)
    return out


def _open_file(path: str) -> None:
    """Intenta abrir el archivo con la app por defecto del SO (vista previa)."""
    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            os.system(f"open '{path}'")
        else:
            os.system(f"xdg-open '{path}'")
    except Exception:
        pass


# ===========================================================
# CUPS / Impresoras
# ===========================================================
def _cups_available() -> bool:
    return shutil.which("lp") is not None


def _cups_get_default_printer() -> Optional[str]:
    """
    1) Variables de entorno: LPDEST / PRINTER
    2) lpstat -d
    3) primera impresora de lpstat -a
    """
    env = (os.getenv("LPDEST") or os.getenv("PRINTER") or "").strip()
    if env:
        return env
    try:
        out = subprocess.check_output(["lpstat", "-d"], text=True, stderr=subprocess.STDOUT).strip()
        if ":" in out:
            cand = out.split(":", 1)[1].strip()
            if cand:
                return cand.split()[0]
    except Exception:
        pass
    try:
        out = subprocess.check_output(["lpstat", "-a"], text=True, stderr=subprocess.STDOUT)
        for line in out.splitlines():
            name = (line.split() or [""])[0].strip()
            if name:
                return name
    except Exception:
        pass
    return None


def _cups_list_printers() -> List[str]:
    try:
        out = subprocess.check_output(["lpstat", "-a"], text=True, stderr=subprocess.STDOUT)
        names = []
        for line in out.splitlines():
            name = (line.split() or [""])[0].strip()
            if name:
                names.append(name)
        return names
    except Exception:
        return []


def _guess_printer_kind(printer_name: Optional[str]) -> str:
    """
    Devuelve 'thermal' o 'normal' con una heurística simple en base al nombre.
    Se puede forzar con env TICKET_THERMAL=1/0.
    """
    force = os.getenv("TICKET_THERMAL", "").strip().lower()
    if force in ("1", "true", "yes", "si"):
        return "thermal"
    if force in ("0", "false", "no"):
        return "normal"

    name = (printer_name or "").lower()
    # Palabras típicas de térmicas
    thermal_markers = [
        "tm", "epson tm", "epson-tm", "t20", "t88", "bixolon", "srp", "tsp", "star",
        "pos", "pos-80", "pos80", "pos-58", "pos58", "zj", "gp-", "sewoo", "rl", "printer_80",
        "80mm", "58mm"
    ]
    if any(m in name for m in thermal_markers):
        return "thermal"
    return "normal"


def print_with_lp(file_path: str,
                  printer_name: str | None = None,
                  copies: int = 1,
                  media: str | None = None,
                  fit_to_page: bool = True) -> bool:
    """
    Envía un archivo (PDF o TXT) a CUPS.
    Si no se especifica 'printer_name', intenta usar la predeterminada.
    """
    if platform.system() == "Windows":
        # En Windows no hay CUPS; devolver False para que se use otro método
        return False

    if not _cups_available():
        return False

    if not printer_name:
        printer_name = _cups_get_default_printer()

    cmd = ["lp"]
    if printer_name:
        cmd += ["-d", printer_name]
    if isinstance(copies, int) and copies > 1:
        cmd += ["-n", str(copies)]
    if media:
        cmd += ["-o", f"media={media}"]
    if fit_to_page:
        cmd += ["-o", "fit-to-page"]
    cmd += [file_path]

    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:
        try:
            detected = ", ".join(_cups_list_printers()) or "ninguna"
        except Exception:
            detected = "desconocidas"
        print(f"[tickets] lp falló: {e}. Impresora usada: {printer_name!r}. Detectadas: {detected}")
        return False


def print_with_windows(file_path: str) -> bool:
    """
    Intento simple de impresión en Windows con la app asociada (PDF/TXT).
    Imprime en la impresora predeterminada del sistema.
    """
    if platform.system() != "Windows":
        return False
    try:
        # Acción 'print' usa la impresora por defecto
        os.startfile(file_path, "print")  # type: ignore[attr-defined]
        return True
    except Exception as e:
        print(f"[tickets] Windows print falló: {e}")
        return False


# ===========================================================
# Generación de archivos (PDF/TXT)
# ===========================================================
def generate_ticket(ticket: dict,
                    output_dir: str,
                    prefer_pdf: bool = True,
                    pdf_layout: str = "auto",
                    thermal_char_width: int = 42,
                    roll_mm: int = 80) -> str:
    """
    Genera ticket y devuelve la ruta del archivo principal.
    - pdf_layout: "auto" | "a4" | "roll"
    - thermal_char_width: 42 (80mm) o 32 (58mm) para tablas compactas en PDF 'roll'
    - roll_mm: 80 o 58
    """
    os.makedirs(output_dir, exist_ok=True)
    base = f"ticket_venta_{ticket.get('sale_id','')}".strip("_")

    if prefer_pdf and REPORTLAB_OK:
        path = os.path.join(output_dir, f"{base}.pdf")
        return generate_ticket_pdf(ticket, path,
                                   layout=pdf_layout,
                                   thermal_char_width=thermal_char_width,
                                   roll_mm=roll_mm)
    # Fallback a TXT general
    path = os.path.join(output_dir, f"{base}.txt")
    return generate_ticket_txt(ticket, path)


def _calc_roll_height_pt(num_lines: int, line_h: float, top_bottom_margin: float) -> float:
    """
    Estima alto de página (en puntos) para rollo según líneas de contenido.
    """
    content = num_lines * line_h
    return content + (top_bottom_margin * 2)


def _build_table_data_for_pdf(ticket: dict) -> list[list[str]]:
    encabezado = ["Producto", "Kilos", "Unid.", "Precio", "Importe"]
    datos = [encabezado]
    for it in (ticket.get("items") or []):
        datos.append([
            str(it.get("producto", "")),
            f"{redondear_dos_decimales(it.get('kilos', 0.0)):.2f}",
            str(int(it.get("unidades", 0) or 0)),
            f"{redondear_dos_decimales(it.get('precio', 0.0)):.2f}",
            f"{redondear_dos_decimales(it.get('importe', 0.0)):.2f}",
        ])
    return datos


def generate_ticket_pdf(ticket: dict,
                        output_path: str,
                        layout: str = "auto",
                        thermal_char_width: int = 42,
                        roll_mm: int = 80) -> str:
    """
    Genera PDF 'responsivo':
    - layout="a4": A4 clásico.
    - layout="roll": ancho 80/58mm, alto dinámico.
    - layout="auto": decide según heurística (usa roll si el contenido es ideal para térmica).
    """
    if not REPORTLAB_OK:
        raise RuntimeError("ReportLab no está disponible")

    t = _ticket_defaults(ticket)

    # ¿Layout automático?
    if layout not in ("a4", "roll"):
        # Si hay pocos caracteres por línea (pensado para 42/32) usa roll
        layout = "roll" if thermal_char_width <= 42 else "a4"

    estilos = getSampleStyleSheet()
    # Estilos compactos para rollo
    tiny = ParagraphStyle("Tiny", parent=estilos["Normal"], fontSize=8, leading=10)
    tiny_b = ParagraphStyle("TinyB", parent=tiny, fontName="Helvetica-Bold")
    normal = estilos["Normal"]
    h2 = estilos["Heading2"]
    title_style = estilos["Title"]

    elementos = []

    titulo = t["company_name"]
    if t.get("nota"):
        titulo = f"{titulo} — {t['nota']}"

    if layout == "a4":
        # --------- A4 clásico ----------
        from reportlab.lib.pagesizes import A4
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        elementos.append(Paragraph(str(titulo), title_style))
        elementos.append(Paragraph("Ticket de Venta", h2))
        elementos.append(Paragraph(f"ID Venta: {t['sale_id']} &nbsp;&nbsp;&nbsp; Fecha: {t['fecha']}", normal))
        elementos.append(Spacer(1, 6))

        datos = _build_table_data_for_pdf(t)
        tabla = Table(datos, hAlign="LEFT")
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
            f"Total unidades: {int(t['total_unidades'] or 0)}", normal))
        elementos.append(Paragraph(f"Total a pagar: {formato_moneda(t['total_venta'])}", estilos["Heading3"]))
        elementos.append(Spacer(1, 8))
        elementos.append(Paragraph("¡Gracias por su compra!", estilos["Italic"]))
        doc.build(elementos)
        return output_path

    # --------- PDF de rollo (80/58 mm) ----------
    # Ancho en mm → puntos; alto dinámico según filas
    width_pt = (roll_mm * mm)
    # Estimación de líneas:
    num_items = len(t.get("items") or [])
    header_lines = 4  # título, subtítulo, id/fecha, separador
    total_lines = 3   # totales + gracias
    table_lines = max(1, num_items)  # al menos 1 línea (encabezado aparte)
    num_lines = header_lines + 1 + table_lines + total_lines  # +1 por encabezado de tabla
    line_h = 10  # puntos por línea
    margin = 6 * mm
    height_pt = _calc_roll_height_pt(num_lines, line_h, margin)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=(width_pt, height_pt),
        topMargin=margin, bottomMargin=margin,
        leftMargin=margin, rightMargin=margin
    )

    elementos.append(Paragraph(str(titulo), tiny_b))
    elementos.append(Paragraph("Ticket de Venta", tiny_b))
    elementos.append(Paragraph(f"ID: {t['sale_id']} &nbsp;&nbsp;&nbsp; Fecha: {t['fecha']}", tiny))
    elementos.append(Spacer(1, 2))

    # Tabla compacta
    datos = _build_table_data_for_pdf(t)
    # Columnas: Producto (flex) | Kilos | Unid | Importe
    # Para 80mm/58mm usamos fuentes pequeñas
    col_widths = [None, 22*mm, 16*mm, 24*mm, 28*mm]  # el primero se estira
    tabla = Table(datos, colWidths=col_widths, hAlign="LEFT")
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.black),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
    ]))
    elementos.append(tabla)
    elementos.append(Spacer(1, 2))
    elementos.append(Paragraph(
        f"Total kilos: {redondear_dos_decimales(t['total_kilos']):.2f} &nbsp;&nbsp; "
        f"Total unidades: {int(t['total_unidades'] or 0)}", tiny))
    elementos.append(Paragraph(f"TOTAL: {formato_moneda(t['total_venta'])}", tiny_b))
    elementos.append(Spacer(1, 2))
    elementos.append(Paragraph("¡Gracias por su compra!", tiny))

    doc.build(elementos)
    return output_path


def generate_ticket_txt(ticket: dict, output_path: str) -> str:
    """
    TXT general ancho fijo (también imprime en térmicas).
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
        prod = str(it.get("producto", ""))[:25].ljust(25)
        kg = f"{redondear_dos_decimales(it.get('kilos', 0.0)):.2f}".rjust(7)
        uni = f"{int(it.get('unidades', 0) or 0)}".rjust(7)
        pre = f"{redondear_dos_decimales(it.get('precio', 0.0)):.2f}".rjust(12)
        imp = f"{redondear_dos_decimales(it.get('importe', 0.0)):.2f}".rjust(12)
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
    Renderiza ticket en texto para rollo térmico.
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

    # Producto (w-26) | Kg (6) | Unid (6) | Importe (14)
    col_prod = max(10, w - 26)
    out.append(f"{'Producto'.ljust(col_prod)}{'Kg'.rjust(6)}{'Unid'.rjust(6)}{'Importe'.rjust(14)}\n")
    out.append(line("-" * w, fill="-"))

    for it in (t["items"] or []):
        prod = str(it.get("producto", ""))
        kg = f"{redondear_dos_decimales(it.get('kilos', 0.0)):.2f}"
        uni = f"{int(it.get('unidades', 0) or 0)}"
        imp = f"{redondear_dos_decimales(it.get('importe', 0.0)):.2f}"

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
    """
    content = render_receipt_text(ticket, width=width)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


# ===========================================================
# Integración con la BD y estructura de ticket
# ===========================================================
def _load_sale_from_db(venta_id: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        # Encabezado
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
            "producto_id": v[1] if v[1] is not None else None,
            "kilos": float(v[2] or 0.0),
            "num_cajas": float(v[3] or 0.0),
            "unidades": int(v[4] or 0),
            "precio": float(v[5] or 0.0),
            "total": float(v[6] or 0.0),
            "tipo_venta": (v[7] or "contado"),
            "cliente_id": (int(v[8]) if v[8] is not None else None),
            "fecha": v[9],
        }

        # ¿Existe tabla de detalle?
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='venta_items'")
        has_detalle = cur.fetchone() is not None

        items = []
        nombre_cliente = ""
        peso_caja = 0.0  # irrelevante en multi-item, compatibilidad

        if has_detalle:
            cur.execute("""
                SELECT vi.producto_id, IFNULL(p.nombre,''), 
                       IFNULL(vi.kilos,0), IFNULL(vi.unidades,0), IFNULL(vi.num_cajas,0),
                       IFNULL(vi.precio,0), IFNULL(vi.importe,0)
                FROM venta_items vi
                LEFT JOIN productos p ON p.id = vi.producto_id
                WHERE vi.venta_id = ?
                ORDER BY vi.id
            """, (venta_id,))
            for pid, pnom, k, u, nc, pre, imp in cur.fetchall():
                items.append({
                    "producto": pnom or "Producto",
                    "kilos": float(k or 0.0),
                    "unidades": int(u or 0),
                    "precio": float(pre or 0.0),
                    "importe": float(imp or 0.0),
                })
        else:
            # legacy: una sola línea en ventas
            cur.execute("SELECT nombre, peso_caja FROM productos WHERE id = ?", (venta["producto_id"],))
            p = cur.fetchone()
            nombre_producto = (p[0] if p and p[0] else "Producto")
            peso_caja = float(p[1] or 0.0) if p else 0.0
            items = [{
                "producto": nombre_producto,
                "kilos": float(venta.get("kilos") or 0.0),
                "unidades": int(venta.get("unidades") or 0),
                "precio": float(venta.get("precio") or 0.0),
                "importe": float(venta.get("total") or 0.0) or
                           (float(venta.get("kilos") or 0.0) * float(venta.get("precio") or 0.0)
                            if float(venta.get("kilos") or 0.0) > 0
                            else int(venta.get("unidades") or 0) * float(venta.get("precio") or 0.0)),
            }]

        # Cliente (opcional)
        try:
            if venta["cliente_id"] is not None:
                cur.execute("SELECT nombre FROM clientes WHERE id = ?", (venta["cliente_id"],))
                c = cur.fetchone()
                if c and c[0]:
                    nombre_cliente = c[0]
        except Exception:
            nombre_cliente = ""

        meta = {
            "nombre_producto": (items[0]["producto"] if items else "Producto"),
            "nombre_cliente": nombre_cliente,
            "peso_caja": peso_caja,
        }
        if not venta["total"]:
            venta["total"] = sum(float(i["importe"] or 0.0) for i in items)

        venta["_items"] = items
        return venta, meta


def _build_ticket_dict(venta: Dict[str, Any], meta: Dict[str, Any], reimpresion: bool) -> Dict[str, Any]:
    """
    Transforma la venta cruda en el dict del ticket (multi-item o simple).
    """
    if venta.get("_items"):
        items = list(venta["_items"])
        total = sum(float(i.get("importe") or 0.0) for i in items)
        kilos = sum(float(i.get("kilos") or 0.0) for i in items)
        unidades = sum(int(i.get("unidades") or 0) for i in items)
    else:
        kilos = float(venta.get("kilos") or 0.0)
        unidades = int(venta.get("unidades") or 0)
        precio = float(venta.get("precio") or 0.0)
        total = float(venta.get("total") or (kilos * precio if kilos > 0 else unidades * precio))
        items = [{
            "producto": meta.get("nombre_producto", "Producto"),
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


# ===========================================================
# Punto de entrada público
# ===========================================================
def imprimir_ticket(
    venta_id: int,
    reimpresion: bool = False,
    prefer_pdf: bool = True,
    abrir_archivo: bool = True,
    output_dir: Optional[str] = None,
    thermal_txt_also: bool = False,
    thermal_width: int = 42,            # 42 (80mm) o 32 (58mm)
    print_direct: bool = False,
    printer_name: Optional[str] = None, # si None, intentará predeterminada (CUPS)
) -> str:
    """
    Genera (y opcionalmente imprime) el ticket de una venta.
    - Si detecta impresora térmica, genera PDF de rollo (80/58mm) con alto dinámico.
    - En caso contrario, PDF A4.
    - Sin ReportLab, genera TXT.
    """
    # 1) Cargar venta
    venta, meta = _load_sale_from_db(int(venta_id))
    ticket = _build_ticket_dict(venta, meta, reimpresion=reimpresion)

    # 2) Heurística de impresora / layout
    target_printer = printer_name
    if not target_printer and _cups_available() and platform.system() != "Windows":
        target_printer = _cups_get_default_printer()

    kind = _guess_printer_kind(target_printer)
    roll_mm = 80 if int(thermal_width) >= 42 else 58
    pdf_layout = "roll" if kind == "thermal" else "a4"

    # 3) Carpeta de salida
    out_dir = _tickets_output_dir(output_dir)

    # 4) Generar archivo principal
    main_path = generate_ticket(
        ticket, out_dir,
        prefer_pdf=prefer_pdf and REPORTLAB_OK,
        pdf_layout=pdf_layout if REPORTLAB_OK else "a4",
        thermal_char_width=int(thermal_width),
        roll_mm=roll_mm
    )

    # 5) Opcional: generar versión térmica TXT (útil para drivers genéricos)
    if thermal_txt_also:
        base = f"ticket_venta_{ticket.get('sale_id','')}".strip("_")
        thermal_path = os.path.join(out_dir, f"{base}_thermal.txt")
        try:
            generate_ticket_txt_thermal(ticket, thermal_path, width=int(thermal_width))
        except Exception:
            pass  # no interrumpir

    # 6) Imprimir o abrir
    if print_direct:
        printed = False
        # Linux / macOS con CUPS
        media_opt = None
        if kind == "thermal":
            # Algunos drivers aceptan este tamaño personalizado; si no, el driver ignorará la opción
            media_opt = f"Custom.{roll_mm}x200mm"
        printed = print_with_lp(main_path, printer_name=target_printer, media=media_opt)

        if not printed:  # Windows u otros casos
            printed = print_with_windows(main_path)

        if not printed and abrir_archivo:
            _open_file(main_path)
    else:
        if abrir_archivo:
            _open_file(main_path)

    return main_path
