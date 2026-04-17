"""
Orquesta AI — Generador de archivos premium
"""
import io, re
from datetime import datetime

FILE_SYSTEM_PROMPTS = {
    "xlsx": """Sos un experto en Excel. Generá contenido para una planilla profesional.

FORMATO OBLIGATORIO — respondé SOLO con esto, sin texto adicional:

TITULO: [título real del documento, ej: "Gestión de Turnos - Peluquería Roma"]
COLUMNAS: col1|col2|col3|col4|col5
DATOS:
valor1|valor2|valor3|valor4|valor5
valor1|valor2|valor3|valor4|valor5
...

REGLAS:
- El TITULO debe ser descriptivo y real (no el prompt literal)
- Mínimo 20 filas de datos reales y concretos
- Datos coherentes con el tema pedido
- Sin texto extra fuera del formato""",

    "docx": """Sos un escritor profesional. Generá contenido para un documento Word.
Usá: # para título, ## para sección, ### para subsección, - para bullets, **texto** para negrita.
Contenido completo, profesional, mínimo 400 palabras.""",

    "pdf": """Sos un experto en documentos PDF. Generá contenido estructurado y completo.
Usá: # para título, ## para sección, - para bullets, **texto** para negrita.
Mínimo 300 palabras, estructura clara."""
}


def _extract_title_and_data(ai_content: str, fallback_title: str):
    """Extrae título y datos del contenido generado por la IA."""
    lines = ai_content.strip().split("\n")
    title = fallback_title
    headers = []
    data_rows = []
    in_data = False

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("TITULO:"):
            title = line.split(":", 1)[1].strip()
        elif line.upper().startswith("COLUMNAS:"):
            headers = [c.strip() for c in line.split(":", 1)[1].split("|") if c.strip()]
        elif line.upper().startswith("DATOS:"):
            in_data = True
        elif in_data and "|" in line:
            row = [c.strip() for c in line.split("|")]
            if row:
                data_rows.append(row)

    # Fallback: buscar pipes en cualquier parte
    if not headers:
        for line in lines:
            if "|" in line and not line.upper().startswith("TITULO") and not line.upper().startswith("COLUMNAS"):
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if len(cells) >= 2:
                    if not headers:
                        headers = cells
                    else:
                        data_rows.append(cells)

    if not headers:
        headers = ["Item", "Descripción", "Valor", "Estado", "Notas"]
        data_rows = [["1", "Sin datos", "", "", ""]]

    return title, headers, data_rows


def _to_number(val: str):
    """Convierte string a número si es posible."""
    if not val:
        return val
    clean = val.replace(",", "").replace("$", "").replace("%", "").replace(".", "", val.count(".")-1).strip()
    try:
        f = float(clean)
        return int(f) if f == int(f) else round(f, 2)
    except:
        return val


def generate_excel(ai_content: str, title: str) -> bytes:
    """Genera Excel premium sin errores XML."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise Exception("openpyxl no instalado — ejecutá: pip install openpyxl")

    # Extraer datos
    real_title, headers, data_rows = _extract_title_and_data(ai_content, title)
    num_cols = len(headers)
    if num_cols == 0:
        raise Exception("No se pudieron extraer columnas del contenido generado")

    # Colores
    C_GREEN      = "1D9E75"
    C_GREEN_MID  = "5DCAA5"
    C_GREEN_LITE = "E8F8F3"
    C_WHITE      = "FFFFFF"
    C_DARK       = "1A1F1A"
    C_GRAY_ROW   = "F5F7F5"

    def side(): return Side(style="thin", color="CCCCCC")
    def border(): return Border(left=side(), right=side(), top=side(), bottom=side())

    wb = openpyxl.Workbook()
    
    # ── Hoja principal ────────────────────────────────────────────────────────
    ws = wb.active
    ws.title = real_title[:28].strip() if real_title else "Datos"
    ws.sheet_view.showGridLines = False

    col_end = get_column_letter(num_cols)

    # Fila 1: título
    ws.merge_cells(f"A1:{col_end}1")
    c = ws["A1"]
    c.value = real_title
    c.font = Font(name="Calibri", size=14, bold=True, color=C_WHITE)
    c.fill = PatternFill("solid", fgColor=C_GREEN)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # Fila 2: subtítulo
    ws.merge_cells(f"A2:{col_end}2")
    c2 = ws["A2"]
    c2.value = f"Generado por Orquesta AI  ·  {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    c2.font = Font(name="Calibri", size=9, italic=True, color="555555")
    c2.fill = PatternFill("solid", fgColor=C_GREEN_LITE)
    c2.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 16

    # Fila 3: vacía
    ws.row_dimensions[3].height = 6

    # Fila 4: headers
    HDR_ROW = 4
    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=HDR_ROW, column=ci, value=h.upper())
        c.font = Font(name="Calibri", size=10, bold=True, color=C_WHITE)
        c.fill = PatternFill("solid", fgColor=C_GREEN)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border()
    ws.row_dimensions[HDR_ROW].height = 26

    # Datos
    for ri, row in enumerate(data_rows, HDR_ROW + 1):
        bg = C_GREEN_LITE if (ri - HDR_ROW) % 2 == 0 else C_WHITE
        for ci in range(1, num_cols + 1):
            raw = row[ci - 1] if ci <= len(row) else ""
            val = _to_number(raw)
            c = ws.cell(row=ri, column=ci, value=val)
            c.font = Font(name="Calibri", size=10, color=C_DARK)
            c.fill = PatternFill("solid", fgColor=bg)
            c.border = border()
            if isinstance(val, (int, float)):
                c.alignment = Alignment(horizontal="right", vertical="center")
                if isinstance(val, float):
                    c.number_format = "#,##0.00"
                else:
                    c.number_format = "#,##0"
            else:
                c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.row_dimensions[ri].height = 20

    # Fila de totales
    last_data_row = HDR_ROW + len(data_rows)
    total_row = last_data_row + 1
    has_totals = False
    for ci in range(1, num_cols + 1):
        c = ws.cell(row=total_row, column=ci)
        nums = []
        for ri in range(HDR_ROW + 1, total_row):
            v = ws.cell(row=ri, column=ci).value
            if isinstance(v, (int, float)):
                nums.append(v)
        if nums and len(nums) > 1:
            c.value = sum(nums)
            c.number_format = "#,##0.00" if any(isinstance(n, float) for n in nums) else "#,##0"
            c.alignment = Alignment(horizontal="right")
            has_totals = True
        elif ci == 1:
            c.value = "TOTAL"
            c.alignment = Alignment(horizontal="left")
        c.font = Font(name="Calibri", size=10, bold=True, color=C_WHITE)
        c.fill = PatternFill("solid", fgColor=C_GREEN_MID)
        c.border = border()
    if has_totals:
        ws.row_dimensions[total_row].height = 22

    # Anchos de columna
    for ci in range(1, num_cols + 1):
        cl = get_column_letter(ci)
        max_len = len(str(headers[ci - 1]))
        for ri in range(HDR_ROW + 1, min(HDR_ROW + 51, last_data_row + 1)):
            v = ws.cell(row=ri, column=ci).value
            max_len = max(max_len, min(len(str(v or "")), 40))
        ws.column_dimensions[cl].width = max(12, max_len + 3)

    # Freeze y filtro
    ws.freeze_panes = f"A{HDR_ROW + 1}"
    ws.auto_filter.ref = f"A{HDR_ROW}:{col_end}{HDR_ROW}"

    # ── Hoja Resumen SIMPLE (sin fórmulas complejas) ──────────────────────────
    if len(data_rows) >= 5:
        ws2 = wb.create_sheet("Resumen")
        ws2.sheet_view.showGridLines = False

        ws2.merge_cells("A1:D1")
        c = ws2["A1"]
        c.value = f"RESUMEN — {real_title.upper()}"
        c.font = Font(name="Calibri", size=13, bold=True, color=C_WHITE)
        c.fill = PatternFill("solid", fgColor=C_GREEN)
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws2.row_dimensions[1].height = 28

        ws2.merge_cells("A2:D2")
        c2 = ws2["A2"]
        c2.value = f"Total de registros: {len(data_rows)}  ·  Columnas: {num_cols}  ·  Generado: {datetime.now().strftime('%d/%m/%Y')}"
        c2.font = Font(name="Calibri", size=9, italic=True, color="555555")
        c2.fill = PatternFill("solid", fgColor=C_GREEN_LITE)
        c2.alignment = Alignment(horizontal="center")
        ws2.row_dimensions[2].height = 16

        # Stats simples (sin fórmulas Excel — solo valores calculados en Python)
        row = 4
        for label, col_w in [("Columna", 20), ("Mínimo", 14), ("Máximo", 14), ("Total", 14)]:
            c = ws2.cell(row=row, column=["Columna","Mínimo","Máximo","Total"].index(label)+1, value=label)
            c.font = Font(name="Calibri", size=10, bold=True, color=C_WHITE)
            c.fill = PatternFill("solid", fgColor=C_GREEN)
            c.alignment = Alignment(horizontal="center")

        row = 5
        for ci, h in enumerate(headers, 1):
            nums = []
            for rd in data_rows:
                if ci <= len(rd):
                    v = _to_number(rd[ci - 1])
                    if isinstance(v, (int, float)):
                        nums.append(v)
            if nums:
                bg = C_GREEN_LITE if row % 2 == 0 else C_WHITE
                for col_i, val in enumerate([h, min(nums), max(nums), sum(nums)], 1):
                    c = ws2.cell(row=row, column=col_i, value=round(val, 2) if isinstance(val, float) else val)
                    c.fill = PatternFill("solid", fgColor=bg)
                    c.font = Font(name="Calibri", size=10, bold=(col_i == 1))
                    c.alignment = Alignment(horizontal="right" if col_i > 1 else "left")
                    c.border = border()
                row += 1

        for ci, w in enumerate([22, 14, 14, 14], 1):
            ws2.column_dimensions[get_column_letter(ci)].width = w

    # Propiedades
    wb.properties.title = real_title
    wb.properties.creator = "Orquesta AI"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_docx(ai_content: str, title: str) -> bytes:
    """Genera Word premium."""
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Cm
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise Exception("python-docx no instalado")

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.5); section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(3);  section.right_margin  = Cm(2.5)

    GREEN = RGBColor(0x1D, 0x9E, 0x75)
    DARK  = RGBColor(0x1A, 0x1F, 0x1A)
    GRAY  = RGBColor(0x66, 0x66, 0x66)

    # Portada
    tp = doc.add_paragraph(); tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = tp.add_run(title.upper())
    tr.font.size = Pt(22); tr.font.bold = True; tr.font.color.rgb = GREEN

    doc.add_paragraph()
    lp = doc.add_paragraph("─" * 50); lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    lp.runs[0].font.color.rgb = GREEN

    sp = doc.add_paragraph(); sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sp.add_run(f"Orquesta AI  ·  {datetime.now().strftime('%d/%m/%Y')}")
    sr.font.size = Pt(9); sr.font.italic = True; sr.font.color.rgb = GRAY
    doc.add_paragraph()

    for line in ai_content.split("\n"):
        line = line.rstrip()
        if not line: doc.add_paragraph(); continue
        if line.startswith("# ") and not line.startswith("## "):
            h = doc.add_heading(line[2:], 1); h.runs[0].font.color.rgb = GREEN; continue
        if line.startswith("## ") and not line.startswith("### "):
            h = doc.add_heading(line[3:], 2); h.runs[0].font.color.rgb = GREEN; continue
        if line.startswith("### "):
            doc.add_heading(line[4:], 3); continue
        if line.strip() == "---":
            p = doc.add_paragraph("─" * 60); p.runs[0].font.color.rgb = RGBColor(0xCC,0xCC,0xCC); continue
        if line.startswith(("- ", "• ")):
            p = doc.add_paragraph(style="List Bullet"); _docx_run(p, line[2:], DARK); continue
        if re.match(r"^\d+\. ", line):
            p = doc.add_paragraph(style="List Number"); _docx_run(p, re.sub(r"^\d+\. ","",line), DARK); continue
        p = doc.add_paragraph(); _docx_run(p, line, DARK)

    buf = io.BytesIO(); doc.save(buf); return buf.getvalue()


def _docx_run(para, text, default_color):
    from docx.shared import Pt, RGBColor
    GREEN = RGBColor(0x1D, 0x9E, 0x75)
    for part in re.split(r"(\*\*[^*]+\*\*)", text):
        if part.startswith("**") and part.endswith("**"):
            r = para.add_run(part[2:-2]); r.bold = True; r.font.color.rgb = GREEN
        elif part:
            r = para.add_run(part); r.font.color.rgb = default_color; r.font.size = Pt(11)


def generate_pdf(ai_content: str, title: str) -> bytes:
    """Genera PDF premium."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    except ImportError:
        raise Exception("reportlab no instalado")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        rightMargin=2.5*cm, leftMargin=2.5*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
        title=title, author="Orquesta AI")

    GREEN = colors.HexColor("#1D9E75")
    DARK  = colors.HexColor("#1A1F1A")
    GRAY  = colors.HexColor("#666666")

    S = lambda **kw: ParagraphStyle("s", **kw)
    s_title  = S(fontSize=20, fontName="Helvetica-Bold", textColor=GREEN, alignment=TA_CENTER, spaceAfter=6)
    s_sub    = S(fontSize=9,  fontName="Helvetica-Oblique", textColor=GRAY, alignment=TA_CENTER, spaceAfter=16)
    s_h1     = S(fontSize=14, fontName="Helvetica-Bold", textColor=GREEN, spaceBefore=12, spaceAfter=4)
    s_h2     = S(fontSize=12, fontName="Helvetica-Bold", textColor=DARK,  spaceBefore=8,  spaceAfter=3)
    s_body   = S(fontSize=10, fontName="Helvetica", textColor=DARK, leading=15, spaceAfter=5, alignment=TA_JUSTIFY)
    s_bullet = S(fontSize=10, fontName="Helvetica", textColor=DARK, leading=14, leftIndent=18, spaceAfter=3)
    s_footer = S(fontSize=8,  fontName="Helvetica-Oblique", textColor=GRAY, alignment=TA_CENTER)

    story = [Spacer(1, 0.5*cm),
             Paragraph(title.upper(), s_title),
             HRFlowable(width="100%", thickness=1.5, color=GREEN, spaceAfter=4),
             Paragraph(f"Generado por <b>Orquesta AI</b>  ·  {datetime.now().strftime('%d/%m/%Y')}", s_sub),
             Spacer(1, 0.3*cm)]

    for line in ai_content.split("\n"):
        line = line.rstrip()
        if not line: story.append(Spacer(1, 0.15*cm)); continue
        if line.startswith("# ") and not line.startswith("## "):
            story.append(Paragraph(line[2:], s_h1))
            story.append(HRFlowable(width="35%", thickness=1, color=GREEN, spaceAfter=3)); continue
        if line.startswith("## "): story.append(Paragraph(line[3:], s_h2)); continue
        if line.strip() == "---":
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC"), spaceAfter=4)); continue
        if line.startswith(("- ","• ")):
            story.append(Paragraph(f"• {line[2:]}", s_bullet)); continue
        if re.match(r"^\d+\. ", line):
            story.append(Paragraph(line, s_bullet)); continue
        fmt = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", line)
        story.append(Paragraph(fmt, s_body))

    story += [Spacer(1, 0.8*cm),
              HRFlowable(width="100%", thickness=0.5, color=GREEN, spaceAfter=4),
              Paragraph("Orquesta AI  ·  La primera IA diseñada para todas las capacidades", s_footer)]

    def page_num(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GRAY)
        canvas.drawRightString(A4[0]-2.5*cm, 1.2*cm, f"Página {doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=page_num, onLaterPages=page_num)
    return buf.getvalue()
