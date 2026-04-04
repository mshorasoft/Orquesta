"""
Orquesta File Generator — Premium corporate document engine.
Excel, Word, PDF with professional design.
"""
import io, re, json
from datetime import datetime

BRAND = {
    "primary":    "0D3D2E",
    "accent":     "1D9E75",
    "accent_mid": "0F6E56",
    "accent_lt":  "5DCAA5",
    "bg_tint":    "F0FAF6",
    "gray_dark":  "1A1A2E",
    "gray_mid":   "4A5568",
    "gray_lt":    "E2E8F0",
    "white":      "FFFFFF",
}

# ═══════════════════════════════════════════════
# EXCEL
# ═══════════════════════════════════════════════
def generate_excel(ai_content: str, title: str = "Orquesta") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    sheets_data = _parse_excel_content(ai_content, title)

    def F(hex_c): return PatternFill("solid", start_color=hex_c, fgColor=hex_c)
    def Fnt(bold=False, size=11, color="1A1A2E", italic=False):
        return Font(name="Calibri", bold=bold, size=size, color=color, italic=italic)
    def Al(h="left", v="center", wrap=False, indent=0):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap, indent=indent)
    def Bdr(color="E2E8F0", style="thin"):
        s = Side(style=style, color=color)
        return Border(left=s, right=s, top=s, bottom=s)

    for sheet_info in sheets_data:
        ws = wb.create_sheet(title=sheet_info["name"][:31])
        ws.sheet_view.showGridLines = False

        rows    = sheet_info.get("rows", [])
        headers = sheet_info.get("headers", [])
        stitle  = sheet_info.get("title", sheet_info["name"])
        desc    = sheet_info.get("description", "")
        ncols   = max(len(headers), max((len(r) for r in rows), default=1), 1)

        # Row 1 — thin accent bar
        for c in range(1, ncols+3): ws.cell(1,c).fill = F(BRAND["accent"])
        ws.row_dimensions[1].height = 4

        # Row 2 — dark title
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols+1)
        tc = ws.cell(2, 1, value=stitle)
        tc.font = Fnt(True, 20, BRAND["white"])
        tc.fill = F(BRAND["gray_dark"])
        tc.alignment = Al("left","center", indent=1)
        for c in range(1, ncols+3): ws.cell(2,c).fill = F(BRAND["gray_dark"])
        ws.cell(2,1).font = Fnt(True, 20, BRAND["white"])
        ws.row_dimensions[2].height = 38

        # Row 3 — subtitle
        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=ncols+1)
        sc = ws.cell(3, 1, value=desc or f"Orquesta AI · {datetime.now().strftime('%d/%m/%Y')}")
        sc.font = Fnt(False, 10, BRAND["accent_lt"], True)
        sc.fill = F(BRAND["gray_dark"])
        sc.alignment = Al("left","center", indent=1)
        for c in range(1, ncols+3): ws.cell(3,c).fill = F(BRAND["gray_dark"])
        ws.row_dimensions[3].height = 20

        # Row 4 — accent bottom bar
        for c in range(1, ncols+3): ws.cell(4,c).fill = F(BRAND["accent"])
        ws.row_dimensions[4].height = 3

        # Row 5 — spacer
        ws.row_dimensions[5].height = 10

        # Row 6 — headers
        HR = 6
        for ci, hdr in enumerate(headers, 1):
            cell = ws.cell(HR, ci, value=hdr)
            cell.font = Fnt(True, 10.5, BRAND["white"])
            cell.fill = F(BRAND["accent_mid"])
            cell.alignment = Al("center","center", wrap=True)
            cell.border = Border(
                bottom=Side(style="medium", color=BRAND["accent"]),
                left=Side(style="thin", color=BRAND["primary"]),
                right=Side(style="thin", color=BRAND["primary"]),
            )
        ws.row_dimensions[HR].height = 24

        # Data rows
        for ri, row_data in enumerate(rows, 1):
            er = HR + ri
            even = ri % 2 == 0
            rfill = F(BRAND["bg_tint"]) if even else F(BRAND["white"])
            for ci in range(1, ncols+1):
                val = row_data[ci-1] if ci <= len(row_data) else ""
                pval = _parse_value(val)
                cell = ws.cell(er, ci, value=pval)
                cell.fill = rfill
                cell.font = Fnt(False, 10, BRAND["gray_mid"])
                cell.border = Bdr()
                if isinstance(pval, (int,float)):
                    cell.alignment = Al("right","center")
                    cell.number_format = '#,##0.00' if isinstance(pval,float) else '#,##0'
                else:
                    cell.alignment = Al("left","center", wrap=True)
            ws.row_dimensions[er].height = 20

        # Totals row
        if rows and headers:
            tr = HR + len(rows) + 1
            ws.cell(tr, 1, value="TOTAL").font = Fnt(True, 10, BRAND["white"])
            ws.cell(tr, 1).fill = F(BRAND["accent"])
            ws.cell(tr, 1).alignment = Al("center","center")
            ws.cell(tr, 1).border = Bdr(BRAND["accent_mid"], "medium")
            for ci in range(2, len(headers)+1):
                cl = get_column_letter(ci)
                has_nums = any(isinstance(_parse_value(r[ci-1] if ci<=len(r) else ""), (int,float)) for r in rows)
                if has_nums:
                    cell = ws.cell(tr, ci, value=f"=SUM({cl}{HR+1}:{cl}{HR+len(rows)})")
                    cell.font = Fnt(True, 10, BRAND["white"])
                    cell.fill = F(BRAND["accent"])
                    cell.number_format = '#,##0'
                    cell.alignment = Al("right","center")
                    cell.border = Bdr(BRAND["accent_mid"], "medium")
                else:
                    cell = ws.cell(tr, ci, value="")
                    cell.fill = F(BRAND["accent"])
                    cell.border = Bdr(BRAND["accent_mid"], "medium")
            ws.row_dimensions[tr].height = 22

        # Conditional formatting — color scale on numeric cols
        for ci, hdr in enumerate(headers, 1):
            cl = get_column_letter(ci)
            if rows and any(isinstance(_parse_value(r[ci-1] if ci<=len(r) else ""), (int,float)) for r in rows):
                try:
                    ws.conditional_formatting.add(
                        f"{cl}{HR+1}:{cl}{HR+len(rows)}",
                        ColorScaleRule(
                            start_type="min", start_color="FFFFFF",
                            mid_type="percentile", mid_value=50, mid_color="C6EFCE",
                            end_type="max", end_color="1D9E75"
                        )
                    )
                except Exception: pass

        # Column widths
        for ci in range(1, ncols+1):
            cl = get_column_letter(ci)
            mx = len(str(headers[ci-1])) if ci <= len(headers) else 8
            for r in rows:
                if ci <= len(r): mx = max(mx, len(str(r[ci-1] or "")))
            ws.column_dimensions[cl].width = min(max(mx, 8)+4, 42)

        ws.freeze_panes = ws.cell(HR+1, 1)
        if headers:
            ws.auto_filter.ref = f"A{HR}:{get_column_letter(len(headers))}{HR+len(rows)}"

    # Cover sheet
    cov = wb.create_sheet("🏠 Inicio", 0)
    cov.sheet_view.showGridLines = False
    cov.sheet_view.showRowColHeaders = False
    for r in range(1,10):
        cov.row_dimensions[r].height = 18
        for c in range(1,12): cov.cell(r,c).fill = F(BRAND["gray_dark"])
    cov.row_dimensions[1].height = 8
    cov.row_dimensions[9].height = 8
    cov.merge_cells("B2:K4")
    tc2 = cov.cell(2, 2, value=title)
    tc2.font = Font(name="Calibri", bold=True, size=24, color=BRAND["white"])
    tc2.alignment = Alignment(horizontal="left", vertical="center")
    cov.merge_cells("B5:K6")
    sc2 = cov.cell(5, 2, value=f"Generado por Orquesta AI · {datetime.now().strftime('%d de %B de %Y, %H:%M')}")
    sc2.font = Font(name="Calibri", size=11, color=BRAND["accent_lt"], italic=True)
    sc2.alignment = Alignment(horizontal="left", vertical="center")
    for c in range(1,12): cov.cell(9,c).fill = F(BRAND["accent"])
    cov.row_dimensions[9].height = 4
    cov.row_dimensions[11].height = 22
    cov.merge_cells("B11:K11")
    ih = cov.cell(11, 2, value="CONTENIDO")
    ih.font = Font(name="Calibri", bold=True, size=10, color=BRAND["accent_mid"])
    for i, s in enumerate(sheets_data, 13):
        cov.row_dimensions[i].height = 20
        nc = cov.cell(i, 2, value=f"→   {s['name']}")
        nc.font = Font(name="Calibri", size=11, color=BRAND["gray_dark"])
        dc = cov.cell(i, 4, value=s.get("description",""))
        dc.font = Font(name="Calibri", size=10, color=BRAND["gray_mid"], italic=True)
        try: cov.merge_cells(f"D{i}:K{i}")
        except: pass
    for c in range(1,12): cov.column_dimensions[get_column_letter(c)].width = 14
    cov.column_dimensions["A"].width = 3

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _parse_value(val):
    if isinstance(val, (int, float)): return val
    s = str(val).strip().replace(",","").replace("%","").replace("$","")
    try:
        return float(s) if "." in s else int(s)
    except: return val


def _parse_excel_content(content, fallback_title):
    try:
        m = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if m:
            data = json.loads(m.group(1))
            if isinstance(data, list): return data
            if isinstance(data, dict) and "sheets" in data: return data["sheets"]
    except: pass
    try:
        data = json.loads(content.strip())
        if isinstance(data, list): return data
        if isinstance(data, dict) and "sheets" in data: return data["sheets"]
    except: pass
    return _md_to_sheets(content, fallback_title)


def _md_to_sheets(content, title):
    sheets = []
    for section in re.split(r'\n#{1,3}\s+', content):
        if not section.strip(): continue
        lines = section.strip().split('\n')
        stitle = lines[0].strip().strip('#').strip() or title
        headers, rows, desc = [], [], ""
        for i, line in enumerate(lines[1:], 1):
            if i==1 and '|' not in line and not line.startswith('-'):
                desc = line.strip(); continue
            if '|' in line:
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if not cells or re.match(r'^[-:]+$', cells[0]): continue
                if not headers: headers = cells
                else: rows.append(cells)
        if headers or rows:
            sheets.append({"name":stitle[:31],"title":stitle,"description":desc,"headers":headers,"rows":rows,"formulas":{}})
    if not sheets:
        lines = [l for l in content.split('\n') if l.strip()]
        sheets.append({"name":title[:31],"title":title,"description":"","headers":["Contenido"],"rows":[[l.strip()] for l in lines[:50]],"formulas":{}})
    return sheets


# ═══════════════════════════════════════════════
# WORD
# ═══════════════════════════════════════════════
def generate_docx(ai_content: str, title: str = "Documento") -> bytes:
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    def rgb(h):
        h = h.lstrip('#')
        return RGBColor(int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))

    doc = Document()
    for sec in doc.sections:
        sec.page_width=Cm(21.59); sec.page_height=Cm(27.94)
        sec.left_margin=Cm(3.0); sec.right_margin=Cm(2.5)
        sec.top_margin=Cm(2.8); sec.bottom_margin=Cm(2.5)

    _setup_docx_styles(doc, rgb)

    # Header
    hp = doc.sections[0].header.paragraphs[0]
    hp.clear()
    _para_border(hp, "bottom", BRAND["accent"], 4)
    for text, color, bold in [("ORQUESTA AI", BRAND["accent"], True), ("    ·    ", BRAND["gray_lt"], False), (title[:60], BRAND["gray_mid"], False)]:
        run = hp.add_run(text)
        run.font.name="Calibri"; run.font.size=Pt(7.5)
        run.font.bold=bold; run.font.color.rgb=rgb(color)
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # Footer
    fp = doc.sections[0].footer.paragraphs[0]
    fp.clear()
    _para_border(fp, "top", BRAND["gray_lt"], 4)
    fr = fp.add_run(f"Orquesta AI  ·  {datetime.now().strftime('%d de %B de %Y')}")
    fr.font.name="Calibri"; fr.font.size=Pt(8); fr.font.color.rgb=rgb(BRAND["gray_mid"])
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Cover
    _docx_cover(doc, title, rgb)
    _docx_render(doc, ai_content, rgb)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _setup_docx_styles(doc, rgb):
    from docx.shared import Pt
    s = doc.styles
    n = s['Normal']
    n.font.name="Calibri"; n.font.size=Pt(11)
    n.font.color.rgb=rgb(BRAND["gray_mid"])
    n.paragraph_format.space_after=Pt(8); n.paragraph_format.line_spacing=Pt(16)

    for lvl, size, color, before, after in [
        (1, 24, BRAND["primary"], 24, 10),
        (2, 15, BRAND["accent_mid"], 18, 6),
        (3, 12, BRAND["gray_dark"], 12, 4),
    ]:
        h = s[f'Heading {lvl}']
        h.font.name="Calibri"; h.font.size=Pt(size); h.font.bold=True; h.font.italic=False
        h.font.color.rgb=rgb(color)
        h.paragraph_format.space_before=Pt(before); h.paragraph_format.space_after=Pt(after)


def _para_border(para, side, color, sz):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    pPr = para._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    b = OxmlElement(f'w:{side}')
    b.set(qn('w:val'), 'single'); b.set(qn('w:sz'), str(sz))
    b.set(qn('w:space'), '4'); b.set(qn('w:color'), color)
    pBdr.append(b); pPr.append(pBdr)


def _set_shading(para, color):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    pPr = para._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), color)
    pPr.append(shd)


def _set_cell_bg(cell, color):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), color)
    tcPr.append(shd)


def _docx_cover(doc, title, rgb):
    from docx.shared import Pt, Cm, RGBColor

    for color, height, is_title in [
        (BRAND["accent"], Pt(4), False),
        (BRAND["primary"], Pt(52), True),
        (BRAND["gray_dark"], Pt(26), False),
        (BRAND["accent"], Pt(4), False),
    ]:
        p = doc.add_paragraph()
        _set_shading(p, color)
        p.paragraph_format.space_before=Pt(0); p.paragraph_format.space_after=Pt(0)
        p.paragraph_format.line_spacing=height
        if is_title:
            p.paragraph_format.left_indent=Cm(0.5)
            run = p.add_run(title)
            run.font.name="Calibri"; run.font.size=Pt(30); run.font.bold=True
            run.font.color.rgb=RGBColor(255,255,255)
        elif color == BRAND["gray_dark"]:
            p.paragraph_format.left_indent=Cm(0.5)
            run = p.add_run(f"Orquesta AI  ·  {datetime.now().strftime('%d de %B de %Y')}")
            run.font.name="Calibri"; run.font.size=Pt(10); run.font.italic=True
            run.font.color.rgb=rgb(BRAND["accent_lt"])

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after=Pt(20)


def _docx_render(doc, content, rgb):
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line: i+=1; continue

        if line.startswith('# '): doc.add_heading(line[2:].strip(), 1); i+=1; continue
        if line.startswith('## '): doc.add_heading(line[3:].strip(), 2); i+=1; continue
        if line.startswith('### '): doc.add_heading(line[4:].strip(), 3); i+=1; continue
        if line.startswith('**') and line.endswith('**') and len(line)>4:
            doc.add_heading(line.strip('*'), 2); i+=1; continue
        if line.startswith('---'):
            _add_hr(doc, BRAND["gray_lt"]); i+=1; continue

        # Table
        if '|' in line and i+1 < len(lines) and re.match(r'\|[-: |]+\|', lines[i+1]):
            trows = []
            while i < len(lines) and '|' in lines[i]:
                row = [c.strip() for c in lines[i].split('|') if c.strip()]
                if row and not re.match(r'^[-:]+$', row[0]): trows.append(row)
                i+=1
            if trows: _docx_table(doc, trows, rgb)
            continue

        # Blockquote
        if line.startswith('> '):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent=Cm(1.2); p.paragraph_format.right_indent=Cm(1.2)
            p.paragraph_format.space_before=Pt(10); p.paragraph_format.space_after=Pt(10)
            _set_shading(p, BRAND["bg_tint"])
            _para_border(p, "left", BRAND["accent"], 18)
            run = p.add_run(line[2:])
            run.font.name="Calibri"; run.font.size=Pt(11); run.font.italic=True
            run.font.color.rgb=rgb(BRAND["accent_mid"])
            i+=1; continue

        # Code
        if line.startswith('```'):
            code_lines = []
            i+=1
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(lines[i]); i+=1
            i+=1
            if code_lines:
                p = doc.add_paragraph()
                _set_shading(p, "F1F5F9")
                p.paragraph_format.left_indent=Cm(0.8); p.paragraph_format.right_indent=Cm(0.8)
                p.paragraph_format.space_before=Pt(6); p.paragraph_format.space_after=Pt(6)
                run = p.add_run('\n'.join(code_lines))
                run.font.name="Courier New"; run.font.size=Pt(9.5)
                run.font.color.rgb=rgb(BRAND["gray_dark"])
            continue

        if line.startswith('- ') or line.startswith('* '):
            p = doc.add_paragraph(style='List Bullet'); _fmt_run(p, line[2:], rgb); i+=1; continue

        m = re.match(r'^(\d+)\.\s(.+)', line)
        if m:
            p = doc.add_paragraph(style='List Number'); _fmt_run(p, m.group(2), rgb); i+=1; continue

        p = doc.add_paragraph(); _fmt_run(p, line, rgb); i+=1


def _fmt_run(para, text, rgb):
    from docx.shared import Pt, RGBColor
    for part in re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)', text):
        if part.startswith('**') and part.endswith('**') and len(part)>4:
            r = para.add_run(part[2:-2]); r.bold=True; r.font.name="Calibri"
            r.font.color.rgb=rgb(BRAND["primary"])
        elif part.startswith('*') and part.endswith('*') and len(part)>2:
            r = para.add_run(part[1:-1]); r.italic=True; r.font.name="Calibri"
        elif part.startswith('`') and part.endswith('`') and len(part)>2:
            r = para.add_run(part[1:-1]); r.font.name="Courier New"; r.font.size=Pt(10)
            r.font.color.rgb=rgb(BRAND["accent_mid"])
        elif part:
            r = para.add_run(part); r.font.name="Calibri"


def _add_hr(doc, color):
    from docx.shared import Pt
    p = doc.add_paragraph()
    p.paragraph_format.space_before=Pt(4); p.paragraph_format.space_after=Pt(4)
    _para_border(p, "bottom", color, 4)


def _docx_table(doc, rows_data, rgb):
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    if not rows_data: return
    ncols = max(len(r) for r in rows_data)
    table = doc.add_table(rows=len(rows_data), cols=ncols)
    table.style = 'Table Grid'
    for ri, row_data in enumerate(rows_data):
        row = table.rows[ri]
        is_hdr = ri == 0
        is_even = ri % 2 == 0 and not is_hdr
        for ci in range(ncols):
            cell = row.cells[ci]
            text = row_data[ci] if ci < len(row_data) else ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_before=Pt(2); para.paragraph_format.space_after=Pt(2)
            run = para.add_run(text)
            run.font.name="Calibri"
            if is_hdr:
                run.bold=True; run.font.size=Pt(10); run.font.color.rgb=RGBColor(255,255,255)
                _set_cell_bg(cell, BRAND["primary"])
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif is_even:
                run.font.size=Pt(10); run.font.color.rgb=rgb(BRAND["gray_mid"])
                _set_cell_bg(cell, BRAND["bg_tint"])
            else:
                run.font.size=Pt(10); run.font.color.rgb=rgb(BRAND["gray_mid"])
                _set_cell_bg(cell, BRAND["white"])
    doc.add_paragraph()


# ═══════════════════════════════════════════════
# PDF
# ═══════════════════════════════════════════════
def generate_pdf(ai_content: str, title: str = "Documento", doc_type: str = "general") -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether
    )
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

    C = {k: colors.HexColor(f"#{v}") for k,v in BRAND.items()}
    PW, PH = letter

    buf = io.BytesIO()

    def draw_page(canvas, doc, first=False):
        canvas.saveState()
        # Top dark bar
        canvas.setFillColor(C["gray_dark"])
        canvas.rect(0, PH-22*mm, PW, 22*mm, fill=1, stroke=0)
        # Accent left stripe in header
        canvas.setFillColor(C["accent"])
        canvas.rect(0, PH-22*mm, 8*mm, 22*mm, fill=1, stroke=0)
        # Accent bottom line of header
        canvas.setFillColor(C["accent"])
        canvas.rect(0, PH-22*mm, PW, 1.5*mm, fill=1, stroke=0)
        # Header text
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(C["accent_lt"])
        canvas.drawString(12*mm, PH-13*mm, "ORQUESTA AI")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawRightString(PW-10*mm, PH-13*mm, title[:72])
        # Bottom bar
        canvas.setFillColor(C["gray_dark"])
        canvas.rect(0, 0, PW, 12*mm, fill=1, stroke=0)
        canvas.setFillColor(C["accent"])
        canvas.rect(PW-8*mm, 0, 8*mm, 12*mm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(10*mm, 4*mm, f"Orquesta AI  ·  {datetime.now().strftime('%d de %B de %Y')}")
        if not first:
            canvas.setFont("Helvetica-Bold", 8)
            canvas.setFillColor(C["accent_lt"])
            canvas.drawRightString(PW-12*mm, 4*mm, f"Pág. {doc.page}")
        canvas.restoreState()

    doc_obj = SimpleDocTemplate(buf, pagesize=letter,
        leftMargin=18*mm, rightMargin=18*mm, topMargin=28*mm, bottomMargin=18*mm,
        title=title, author="Orquesta AI")

    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    s_title = S("OT", fontName="Helvetica-Bold", fontSize=28, textColor=C["primary"],
        spaceAfter=4, leading=34)
    s_tsub  = S("OTS", fontName="Helvetica-Oblique", fontSize=11, textColor=C["accent_mid"],
        spaceAfter=16, leading=15)
    s_h1    = S("OH1", fontName="Helvetica-Bold", fontSize=18, textColor=C["primary"],
        spaceBefore=20, spaceAfter=8, leading=22)
    s_h2    = S("OH2", fontName="Helvetica-Bold", fontSize=13, textColor=C["accent_mid"],
        spaceBefore=14, spaceAfter=5, leading=17)
    s_h3    = S("OH3", fontName="Helvetica-BoldOblique", fontSize=11, textColor=C["gray_dark"],
        spaceBefore=10, spaceAfter=3, leading=14)
    s_body  = S("OB", fontName="Helvetica", fontSize=10.5, textColor=C["gray_mid"],
        spaceAfter=7, leading=16, alignment=TA_JUSTIFY)
    s_bullet= S("OBul", fontName="Helvetica", fontSize=10.5, textColor=C["gray_mid"],
        spaceAfter=3, leading=15, leftIndent=16, firstLineIndent=-12)
    s_num   = S("ONum", fontName="Helvetica", fontSize=10.5, textColor=C["gray_mid"],
        spaceAfter=3, leading=15, leftIndent=20, firstLineIndent=-14)
    s_code  = S("OCd", fontName="Courier", fontSize=9, textColor=C["gray_dark"],
        spaceAfter=8, leading=13, backColor=colors.HexColor("#F1F5F9"),
        leftIndent=10, rightIndent=10, borderPadding=8)
    s_quote = S("OQ", fontName="Helvetica-Oblique", fontSize=11, textColor=C["accent_mid"],
        spaceAfter=8, leading=16, leftIndent=20, rightIndent=20,
        backColor=C["bg_tint"], borderPadding=(10,10,10,14),
        borderLeftColor=C["accent"], borderLeftWidth=4, borderLeftPadding=10)
    s_meta  = S("OM", fontName="Helvetica-Oblique", fontSize=8,
        textColor=colors.HexColor("#AAAAAA"), alignment=TA_CENTER, spaceBefore=16)

    story = []

    # Cover block
    cover = Table([[Paragraph(title, s_title)], [Paragraph(f"Generado por Orquesta AI · {datetime.now().strftime('%d de %B de %Y')}", s_tsub)]],
        colWidths=[PW - 36*mm])
    cover.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C["bg_tint"]),
        ('LEFTPADDING', (0,0), (-1,-1), 18), ('RIGHTPADDING', (0,0), (-1,-1), 18),
        ('TOPPADDING', (0,0), (-1,-1), 18), ('BOTTOMPADDING', (0,0), (-1,-1), 14),
        ('LINEABOVE', (0,0), (-1,0), 4, C["accent"]),
        ('LINEBELOW', (0,-1), (-1,-1), 1, C["gray_lt"]),
    ]))
    story.append(cover)
    story.append(Spacer(1, 16))

    lines = ai_content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line: story.append(Spacer(1, 4)); i+=1; continue

        if line.startswith('# '):
            story.append(Paragraph(_mi(line[2:].strip()), s_h1))
            story.append(HRFlowable(width="100%", thickness=2, color=C["accent"], spaceAfter=6))
            i+=1; continue
        if line.startswith('## '):
            story.append(Paragraph(_mi(line[3:].strip()), s_h2))
            story.append(HRFlowable(width="40%", thickness=1, color=C["bg_tint"], spaceAfter=4, hAlign='LEFT'))
            i+=1; continue
        if line.startswith('### '):
            story.append(Paragraph(_mi(line[4:].strip()), s_h3)); i+=1; continue
        if line.startswith('**') and line.endswith('**') and len(line)>4:
            story.append(Paragraph(f"<b>{_esc(line[2:-2])}</b>", s_h2)); i+=1; continue
        if line.startswith('---'):
            story.append(HRFlowable(width="100%", thickness=1, color=C["gray_lt"], spaceBefore=6, spaceAfter=6)); i+=1; continue

        if line.startswith('```'):
            code_lines=[]
            i+=1
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(_esc(lines[i])); i+=1
            i+=1
            if code_lines: story.append(Paragraph('<br/>'.join(code_lines), s_code))
            continue

        if line.startswith('> '):
            story.append(Paragraph(_mi(line[2:]), s_quote)); i+=1; continue

        # Table
        if '|' in line and i+1 < len(lines) and re.match(r'\|[-: |]+\|', lines[i+1]):
            trows=[]
            while i < len(lines) and '|' in lines[i]:
                row=[c.strip() for c in lines[i].split('|') if c.strip()]
                if row and not re.match(r'^[-:]+$', row[0]): trows.append(row)
                i+=1
            if trows:
                story.append(_pdf_table(trows, C, PW))
                story.append(Spacer(1,10))
            continue

        if line.startswith('- ') or line.startswith('* '):
            story.append(Paragraph(f"<bullet>•</bullet> {_mi(line[2:])}", s_bullet)); i+=1; continue

        nm = re.match(r'^(\d+)\.\s(.+)', line)
        if nm:
            story.append(Paragraph(f"<b>{nm.group(1)}.</b>  {_mi(nm.group(2))}", s_num)); i+=1; continue

        story.append(Paragraph(_mi(line), s_body)); i+=1

    story.append(Spacer(1,24))
    story.append(HRFlowable(width="100%", thickness=1, color=C["gray_lt"]))
    story.append(Paragraph("Documento generado automáticamente · Orquesta AI", s_meta))

    doc_obj.build(story,
        onFirstPage=lambda c,d: draw_page(c,d,True),
        onLaterPages=lambda c,d: draw_page(c,d,False))
    return buf.getvalue()


def _esc(t):
    return t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def _mi(t):
    t = _esc(t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'\*(.+?)\*', r'<i>\1</i>', t)
    t = re.sub(r'`(.+?)`', r'<font name="Courier">\1</font>', t)
    return t

def _pdf_table(rows, C, PW):
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    if not rows: return Spacer(1,0)
    ncols = max(len(r) for r in rows)
    norm = [r + ['']*(ncols-len(r)) for r in rows]
    sh = ParagraphStyle("TH", fontName="Helvetica-Bold", fontSize=9.5, textColor=__import__('reportlab').lib.colors.white, alignment=TA_CENTER)
    sc = ParagraphStyle("TD", fontName="Helvetica", fontSize=9.5, textColor=C["gray_mid"], alignment=TA_LEFT, leading=13)
    styled = []
    for ri, row in enumerate(norm):
        styled.append([Paragraph(_mi(str(c)), sh if ri==0 else sc) for c in row])
    cw = (PW - 36*mm) / ncols
    t = Table(styled, colWidths=[cw]*ncols, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C["primary"]),
        ('LINEABOVE', (0,0), (-1,0), 3, C["accent"]),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [__import__('reportlab').lib.colors.white, C["bg_tint"]]),
        ('GRID', (0,0), (-1,-1), 0.5, C["gray_lt"]),
        ('TOPPADDING', (0,0), (-1,-1), 7), ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LINEABOVE', (0,-1), (-1,-1), 1.5, C["accent"]),
    ]))
    return t


# ── FILE TYPE DETECTION ──────────────────────────────────────────────────────
def detect_file_type(prompt: str):
    p = prompt.lower()
    CV_KW = ["curriculum","currículum","cv ","resume","hoja de vida"]
    FILE_KW = {
        "xlsx": ["excel","planilla","spreadsheet","hoja de calculo","hoja de cálculo",".xlsx","tabla excel","presupuesto excel","reporte excel","plantilla excel","generar excel","crea excel","haceme un excel","haceme una planilla","plantilla de excel","crea una planilla","generá una planilla","creá un excel"],
        "docx": ["word",".docx","documento word","informe word","cv en word","curriculum en word","carta word","contrato word","memo word","plantilla word","generar word","crea un word","haceme un word","documento de texto","redacta un documento","crea un documento"],
        "pdf":  ["pdf",".pdf","en pdf","como pdf","generar pdf","crea un pdf","haceme un pdf","informe pdf","reporte pdf","cv pdf","curriculum pdf","documento pdf","carta pdf","reporte en pdf"],
    }
    if any(k in p for k in CV_KW):
        if any(k in p for k in FILE_KW["docx"]): return "docx"
        if any(k in p for k in FILE_KW["xlsx"]): return "xlsx"
        return "pdf"
    for ftype, kws in FILE_KW.items():
        if any(k in p for k in kws): return ftype
    return None


# ── AI SYSTEM PROMPTS ────────────────────────────────────────────────────────
FILE_SYSTEM_PROMPTS = {
    "xlsx": """Sos un experto en planillas Excel profesionales. Generá el contenido en JSON exacto:

```json
[
  {
    "name": "Nombre Hoja",
    "title": "Título completo",
    "description": "Descripción breve",
    "headers": ["Col1", "Col2", "Col3"],
    "rows": [
      ["dato1", 1000, 500],
      ["dato2", 2000, 800]
    ],
    "formulas": {}
  }
]
```

REGLAS: múltiples hojas si corresponde (máx 5), al menos 10-15 filas por hoja, números reales (no strings), datos coherentes y específicos. Respondé SOLO con el JSON.""",

    "docx": """Sos un experto redactor profesional. Generá el documento en Markdown:
- # Título, ## Sección, ### Subsección
- **negrita**, *cursiva*, `código`
- - bullets, 1. numerados
- | tablas | con | separador |-|-|
- > destacados, --- separadores

Documento COMPLETO (mínimo 500 palabras), profesional, específico al pedido. CVs con todas las secciones. Contratos con cláusulas completas. Sin texto introductorio — solo el markdown.""",

    "pdf": """Sos un experto en documentos PDF profesionales. Generá el contenido en Markdown:
- # Título, ## Sección, ### Subsección
- **negrita**, *cursiva*
- - bullets, 1. numerados
- | tablas markdown |
- > destacados, --- divisores

Contenido COMPLETO (mínimo 300 palabras), profesional y específico. Sin texto introductorio — solo el markdown.""",
}
