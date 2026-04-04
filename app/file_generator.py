"""
Orquesta File Generator — Professional document generation engine.
Supports: XLSX, DOCX, PDF with AI-powered content.
"""

import io
import re
import json
from datetime import datetime

# ── EXCEL GENERATOR ──────────────────────────────────────────────────────────

def generate_excel(ai_content: str, title: str = "Orquesta") -> bytes:
    """Generate a professional Excel file from AI-structured content."""
    from openpyxl import Workbook
    from openpyxl.styles import (
        Font, PatternFill, Alignment, Border, Side, GradientFill
    )
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)

    # Parse the AI content into sheets
    sheets_data = _parse_excel_content(ai_content, title)

    # Color palette — professional dark header style
    HEADER_COLOR = "1D9E75"   # Orquesta green
    SUBHEADER_COLOR = "0F6E56"
    ALT_ROW_COLOR = "F0FAF6"
    BORDER_COLOR = "C8E6D5"
    TITLE_COLOR = "0D3D2E"

    thin = Side(style="thin", color=BORDER_COLOR)
    full_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    bottom_only = Border(bottom=Side(style="medium", color=HEADER_COLOR))

    for sheet_info in sheets_data:
        ws = wb.create_sheet(title=sheet_info["name"][:31])

        rows = sheet_info.get("rows", [])
        headers = sheet_info.get("headers", [])
        sheet_title = sheet_info.get("title", sheet_info["name"])
        description = sheet_info.get("description", "")
        formulas = sheet_info.get("formulas", {})

        col_count = max(len(headers), max((len(r) for r in rows), default=1), 1)

        # ── Sheet title row ──
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(col_count, 2))
        title_cell = ws.cell(row=1, column=1, value=sheet_title)
        title_cell.font = Font(name="Arial", bold=True, size=16, color="FFFFFF")
        title_cell.fill = PatternFill("solid", start_color=TITLE_COLOR)
        title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.row_dimensions[1].height = 30

        # ── Description row (if any) ──
        data_start = 3
        if description:
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(col_count, 2))
            desc_cell = ws.cell(row=2, column=1, value=description)
            desc_cell.font = Font(name="Arial", italic=True, size=10, color="555555")
            desc_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
            ws.row_dimensions[2].height = 18
            data_start = 3

        # ── Empty row separator ──
        ws.row_dimensions[data_start].height = 8
        data_start += 1

        # ── Headers ──
        header_row = data_start
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=header_row, column=col_idx, value=header)
            cell.font = Font(name="Arial", bold=True, size=11, color="FFFFFF")
            cell.fill = PatternFill("solid", start_color=HEADER_COLOR)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = full_border
        ws.row_dimensions[header_row].height = 22

        # ── Data rows ──
        for r_idx, row_data in enumerate(rows, 1):
            excel_row = header_row + r_idx
            is_alt = r_idx % 2 == 0
            for c_idx, val in enumerate(row_data, 1):
                col_letter = get_column_letter(c_idx)
                cell_addr = f"{col_letter}{excel_row}"
                # Check if this cell has a formula
                if cell_addr in formulas:
                    cell = ws.cell(row=excel_row, column=c_idx, value=formulas[cell_addr])
                else:
                    cell = ws.cell(row=excel_row, column=c_idx, value=_parse_value(val))
                cell.font = Font(name="Arial", size=10)
                if is_alt:
                    cell.fill = PatternFill("solid", start_color=ALT_ROW_COLOR)
                cell.border = full_border
                cell.alignment = Alignment(vertical="center", wrap_text=False)
            ws.row_dimensions[excel_row].height = 18

        # ── Totals row (if formulas present for totals) ──
        if rows and headers:
            total_row = header_row + len(rows) + 1
            has_total = False
            for c_idx, header in enumerate(headers, 1):
                col_letter = get_column_letter(c_idx)
                total_key = f"TOTAL_{col_letter}"
                if total_key in formulas:
                    has_total = True
                    cell = ws.cell(row=total_row, column=c_idx, value=formulas[total_key].replace("COL", col_letter).replace("START", str(header_row + 1)).replace("END", str(header_row + len(rows))))
                    cell.font = Font(name="Arial", bold=True, size=10, color="FFFFFF")
                    cell.fill = PatternFill("solid", start_color=SUBHEADER_COLOR)
                    cell.border = full_border
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif c_idx == 1 and has_total is False:
                    cell = ws.cell(row=total_row, column=c_idx, value="TOTAL")
                    cell.font = Font(name="Arial", bold=True, size=10, color="FFFFFF")
                    cell.fill = PatternFill("solid", start_color=SUBHEADER_COLOR)
                    cell.border = full_border

        # ── Column widths (auto-fit) ──
        for col_idx in range(1, col_count + 1):
            col_letter = get_column_letter(col_idx)
            max_len = 0
            for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
                for cell in row:
                    if cell.value and not isinstance(cell.value, str) or (isinstance(cell.value, str) and not cell.value.startswith("=")):
                        max_len = max(max_len, len(str(cell.value or "")))
            header_len = len(str(headers[col_idx - 1])) if col_idx <= len(headers) else 0
            ws.column_dimensions[col_letter].width = min(max(max_len, header_len, 8) + 4, 40)

        # ── Freeze panes below header ──
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

        # ── Auto-filter ──
        if headers:
            last_col = get_column_letter(len(headers))
            last_data_row = header_row + len(rows)
            ws.auto_filter.ref = f"A{header_row}:{last_col}{last_data_row}"

    # ── Summary / cover sheet ──
    cover = wb.create_sheet("📋 Resumen", 0)
    cover.sheet_view.showGridLines = False

    cover.merge_cells("A1:F1")
    c = cover.cell(row=1, column=1, value="ORQUESTA · DOCUMENTO GENERADO CON IA")
    c.font = Font(name="Arial", bold=True, size=18, color="FFFFFF")
    c.fill = PatternFill("solid", start_color=TITLE_COLOR)
    c.alignment = Alignment(horizontal="center", vertical="center")
    cover.row_dimensions[1].height = 45

    cover.merge_cells("A2:F2")
    c2 = cover.cell(row=2, column=1, value=f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')}")
    c2.font = Font(name="Arial", size=11, color="555555", italic=True)
    c2.alignment = Alignment(horizontal="center")
    cover.row_dimensions[2].height = 22

    cover.merge_cells("A3:F3")
    cover.row_dimensions[3].height = 12

    cover.cell(row=4, column=1, value="Hojas en este documento:").font = Font(name="Arial", bold=True, size=11, color=TITLE_COLOR)
    for i, s in enumerate(sheets_data, 5):
        cell = cover.cell(row=i, column=1, value=f"  ▸  {s['name']}")
        cell.font = Font(name="Arial", size=11, color="1D9E75")

    for col in range(1, 7):
        cover.column_dimensions[get_column_letter(col)].width = 20

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _parse_value(val):
    """Try to parse strings as numbers."""
    if isinstance(val, (int, float)):
        return val
    s = str(val).strip().replace(",", "").replace("%", "").replace("$", "")
    try:
        if "." in s:
            return float(s)
        return int(s)
    except (ValueError, TypeError):
        return val


def _parse_excel_content(content: str, fallback_title: str) -> list:
    """Parse AI-generated text into sheet definitions."""
    # Try JSON first
    try:
        # Look for JSON block in the content
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', content)
        if json_match:
            data = json.loads(json_match.group(1))
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "sheets" in data:
                return data["sheets"]
    except Exception:
        pass

    # Try plain JSON
    try:
        data = json.loads(content.strip())
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "sheets" in data:
            return data["sheets"]
    except Exception:
        pass

    # Fallback: parse markdown-style tables
    return _parse_markdown_to_sheets(content, fallback_title)


def _parse_markdown_to_sheets(content: str, title: str) -> list:
    """Convert markdown table content into sheet definitions."""
    sheets = []
    sections = re.split(r'\n#{1,3}\s+', content)

    for section in sections:
        if not section.strip():
            continue
        lines = section.strip().split('\n')
        sheet_title = lines[0].strip().strip('#').strip() or title
        headers = []
        rows = []
        description = ""

        for i, line in enumerate(lines[1:], 1):
            # Description line
            if i == 1 and not line.startswith('|') and not line.startswith('-'):
                description = line.strip()
                continue
            # Table row
            if '|' in line:
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if not cells:
                    continue
                if re.match(r'^[-:]+$', cells[0]):
                    continue  # separator row
                if not headers:
                    headers = cells
                else:
                    rows.append(cells)

        if headers or rows:
            sheets.append({
                "name": sheet_title[:31],
                "title": sheet_title,
                "description": description,
                "headers": headers,
                "rows": rows,
                "formulas": {}
            })

    if not sheets:
        # Create a single sheet with raw content lines
        lines = [l for l in content.split('\n') if l.strip()]
        rows = [[l.strip()] for l in lines[:50]]
        sheets.append({
            "name": title[:31],
            "title": title,
            "description": "",
            "headers": ["Contenido"],
            "rows": rows,
            "formulas": {}
        })

    return sheets


# ── WORD GENERATOR ───────────────────────────────────────────────────────────

def generate_docx(ai_content: str, title: str = "Documento") -> bytes:
    """Generate a professional Word document from AI content."""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    doc = Document()

    # ── Page setup ──
    section = doc.sections[0]
    section.page_width = Cm(21.59)    # Letter
    section.page_height = Cm(27.94)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)

    # ── Styles ──
    _setup_docx_styles(doc)

    # ── Header ──
    header = doc.sections[0].header
    header_para = header.paragraphs[0]
    header_para.clear()
    run = header_para.add_run("ORQUESTA AI")
    run.font.name = "Arial"
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x1D, 0x9E, 0x75)
    run.font.bold = True
    header_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    # ── Footer ──
    footer = doc.sections[0].footer
    footer_para = footer.paragraphs[0]
    footer_para.clear()
    run_f = footer_para.add_run(f"Generado por Orquesta AI · {datetime.now().strftime('%d/%m/%Y')}")
    run_f.font.name = "Arial"
    run_f.font.size = Pt(8)
    run_f.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # ── Content ──
    _render_docx_content(doc, ai_content, title)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _setup_docx_styles(doc):
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    GREEN = RGBColor(0x0F, 0x6E, 0x56)
    DARK = RGBColor(0x0D, 0x3D, 0x2E)
    GRAY = RGBColor(0x44, 0x44, 0x44)

    styles = doc.styles

    # Normal
    normal = styles['Normal']
    normal.font.name = "Arial"
    normal.font.size = Pt(11)
    normal.font.color.rgb = GRAY
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = Pt(14)

    # Heading 1
    h1 = styles['Heading 1']
    h1.font.name = "Arial"
    h1.font.size = Pt(22)
    h1.font.color.rgb = DARK
    h1.font.bold = True
    h1.paragraph_format.space_before = Pt(18)
    h1.paragraph_format.space_after = Pt(8)

    # Heading 2
    h2 = styles['Heading 2']
    h2.font.name = "Arial"
    h2.font.size = Pt(15)
    h2.font.color.rgb = GREEN
    h2.font.bold = True
    h2.paragraph_format.space_before = Pt(14)
    h2.paragraph_format.space_after = Pt(5)

    # Heading 3
    h3 = styles['Heading 3']
    h3.font.name = "Arial"
    h3.font.size = Pt(12)
    h3.font.color.rgb = GREEN
    h3.font.bold = True
    h3.font.italic = True
    h3.paragraph_format.space_before = Pt(10)
    h3.paragraph_format.space_after = Pt(4)


def _render_docx_content(doc, content: str, title: str):
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    # ── Cover title ──
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_para.add_run(title)
    title_run.font.name = "Arial"
    title_run.font.size = Pt(28)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(0x0D, 0x3D, 0x2E)

    # Decorative line under title
    _add_colored_rule(doc, "1D9E75")
    doc.add_paragraph()  # spacer

    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Skip empty
        if not line:
            i += 1
            continue

        # H1
        if line.startswith('# '):
            p = doc.add_heading(line[2:].strip(), level=1)
            i += 1
            continue

        # H2
        if line.startswith('## '):
            p = doc.add_heading(line[3:].strip(), level=2)
            i += 1
            continue

        # H3
        if line.startswith('### '):
            p = doc.add_heading(line[4:].strip(), level=3)
            i += 1
            continue

        # Bold header without #
        if line.startswith('**') and line.endswith('**') and len(line) > 4:
            p = doc.add_heading(line.strip('*'), level=2)
            i += 1
            continue

        # Table detection
        if '|' in line and i + 1 < len(lines) and '|-' in lines[i + 1]:
            rows_data = []
            while i < len(lines) and '|' in lines[i]:
                row = [c.strip() for c in lines[i].split('|') if c.strip()]
                if row and not re.match(r'^[-:]+$', row[0]):
                    rows_data.append(row)
                i += 1
            if rows_data:
                _add_docx_table(doc, rows_data)
            continue

        # Bullet list
        if line.startswith('- ') or line.startswith('* '):
            p = doc.add_paragraph(style='List Bullet')
            _add_formatted_run(p, line[2:])
            i += 1
            continue

        # Numbered list
        if re.match(r'^\d+\.\s', line):
            p = doc.add_paragraph(style='List Number')
            _add_formatted_run(p, re.sub(r'^\d+\.\s', '', line))
            i += 1
            continue

        # Blockquote / callout
        if line.startswith('> '):
            p = doc.add_paragraph()
            from docx.shared import Cm
            p.paragraph_format.left_indent = Cm(1)
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(line[2:])
            run.font.italic = True
            run.font.color.rgb = RGBColor(0x1D, 0x9E, 0x75)
            i += 1
            continue

        # Code block
        if line.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1
            if code_lines:
                p = doc.add_paragraph()
                run = p.add_run('\n'.join(code_lines))
                run.font.name = "Courier New"
                run.font.size = Pt(9)
                from docx.shared import Cm
                p.paragraph_format.left_indent = Cm(1)
                p.paragraph_format.right_indent = Cm(1)
            continue

        # Horizontal rule
        if line.startswith('---'):
            _add_colored_rule(doc, "CCCCCC")
            i += 1
            continue

        # Normal paragraph
        p = doc.add_paragraph()
        _add_formatted_run(p, line)
        i += 1


def _add_formatted_run(para, text: str):
    """Add text with inline bold/italic formatting."""
    from docx.shared import Pt, RGBColor
    # Split on bold/italic markers
    parts = re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`)', text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            run = para.add_run(part[2:-2])
            run.bold = True
            run.font.color.rgb = RGBColor(0x0F, 0x6E, 0x56)
        elif part.startswith('*') and part.endswith('*'):
            run = para.add_run(part[1:-1])
            run.italic = True
        elif part.startswith('`') and part.endswith('`'):
            run = para.add_run(part[1:-1])
            run.font.name = "Courier New"
            run.font.size = Pt(10)
        else:
            para.add_run(part)


def _add_colored_rule(doc, hex_color: str):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), hex_color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _add_docx_table(doc, rows_data: list):
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    if not rows_data:
        return

    num_cols = max(len(r) for r in rows_data)
    table = doc.add_table(rows=len(rows_data), cols=num_cols)
    table.style = 'Table Grid'

    GREEN_FILL = "1D9E75"
    ALT_FILL = "F0FAF6"

    for r_idx, row_data in enumerate(rows_data):
        row = table.rows[r_idx]
        is_header = r_idx == 0
        is_alt = r_idx % 2 == 0 and not is_header
        for c_idx in range(num_cols):
            cell = row.cells[c_idx]
            text = row_data[c_idx] if c_idx < len(row_data) else ""
            para = cell.paragraphs[0]
            run = para.add_run(text)
            run.font.name = "Arial"
            run.font.size = Pt(10)
            if is_header:
                run.bold = True
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                _set_cell_background(cell, GREEN_FILL)
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif is_alt:
                _set_cell_background(cell, ALT_FILL)

    doc.add_paragraph()  # spacer after table


def _set_cell_background(cell, hex_color: str):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


# ── PDF GENERATOR ─────────────────────────────────────────────────────────────

def generate_pdf(ai_content: str, title: str = "Documento", doc_type: str = "general") -> bytes:
    """Generate a professional PDF from AI content."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm, inch
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether, PageBreak
    )
    from reportlab.platypus import BalancedColumns
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY

    GREEN = colors.HexColor("#1D9E75")
    DARK_GREEN = colors.HexColor("#0D3D2E")
    MID_GREEN = colors.HexColor("#0F6E56")
    LIGHT_GREEN = colors.HexColor("#F0FAF6")
    GRAY = colors.HexColor("#444444")
    LIGHT_GRAY = colors.HexColor("#F5F5F5")
    BORDER_GRAY = colors.HexColor("#DDDDDD")

    buf = io.BytesIO()

    # ── Canvas callbacks for header/footer ──
    def on_first_page(canvas, doc):
        canvas.saveState()
        # Top color bar
        canvas.setFillColor(DARK_GREEN)
        canvas.rect(0, letter[1] - 0.6 * cm, letter[0], 0.6 * cm, fill=1, stroke=0)
        canvas.setFillColor(GREEN)
        canvas.rect(0, letter[1] - 1.2 * cm, letter[0] * 0.3, 0.6 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(colors.white)
        canvas.drawRightString(letter[0] - cm, letter[1] - 0.95 * cm, "ORQUESTA AI")
        # Footer
        canvas.setFillColor(DARK_GREEN)
        canvas.rect(0, 0, letter[0], 0.8 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.white)
        canvas.drawCentredString(letter[0] / 2, 0.25 * cm,
            f"Generado por Orquesta AI · {datetime.now().strftime('%d/%m/%Y')}")
        canvas.restoreState()

    def on_later_pages(canvas, doc):
        on_first_page(canvas, doc)
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GRAY)
        canvas.drawRightString(letter[0] - cm, 1.1 * cm, f"Pág. {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2 * cm,
        title=title,
        author="Orquesta AI",
    )

    # ── Styles ──
    styles = getSampleStyleSheet()

    style_title = ParagraphStyle("OTitle", fontName="Helvetica-Bold", fontSize=26,
        textColor=DARK_GREEN, spaceAfter=6, leading=30, alignment=TA_LEFT)
    style_subtitle = ParagraphStyle("OSubtitle", fontName="Helvetica-Oblique", fontSize=13,
        textColor=MID_GREEN, spaceAfter=16, leading=16, alignment=TA_LEFT)
    style_h1 = ParagraphStyle("OH1", fontName="Helvetica-Bold", fontSize=16,
        textColor=DARK_GREEN, spaceBefore=16, spaceAfter=6, leading=20)
    style_h2 = ParagraphStyle("OH2", fontName="Helvetica-Bold", fontSize=13,
        textColor=MID_GREEN, spaceBefore=12, spaceAfter=4, leading=16)
    style_h3 = ParagraphStyle("OH3", fontName="Helvetica-BoldOblique", fontSize=11,
        textColor=MID_GREEN, spaceBefore=8, spaceAfter=3, leading=14)
    style_body = ParagraphStyle("OBody", fontName="Helvetica", fontSize=10.5,
        textColor=GRAY, spaceAfter=6, leading=15, alignment=TA_JUSTIFY)
    style_bullet = ParagraphStyle("OBullet", fontName="Helvetica", fontSize=10.5,
        textColor=GRAY, spaceAfter=3, leading=14, leftIndent=18, firstLineIndent=-12)
    style_code = ParagraphStyle("OCode", fontName="Courier", fontSize=9,
        textColor=colors.HexColor("#333333"), spaceAfter=6, leading=13,
        backColor=LIGHT_GRAY, leftIndent=12, rightIndent=12, borderPadding=6)
    style_quote = ParagraphStyle("OQuote", fontName="Helvetica-Oblique", fontSize=10.5,
        textColor=MID_GREEN, spaceAfter=6, leading=14, leftIndent=24,
        borderLeftColor=GREEN, borderLeftWidth=3, borderLeftPadding=8)

    story = []

    # ── Title block ──
    story.append(Paragraph(title, style_title))
    story.append(HRFlowable(width="100%", thickness=3, color=GREEN, spaceAfter=12))

    # ── Parse and render content ──
    lines = ai_content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line:
            story.append(Spacer(1, 4))
            i += 1
            continue

        # H1
        if line.startswith('# '):
            story.append(Paragraph(line[2:].strip(), style_h1))
            story.append(HRFlowable(width="100%", thickness=1, color=LIGHT_GREEN, spaceAfter=4))
            i += 1
            continue

        # H2
        if line.startswith('## '):
            story.append(Paragraph(line[3:].strip(), style_h2))
            i += 1
            continue

        # H3
        if line.startswith('### '):
            story.append(Paragraph(line[4:].strip(), style_h3))
            i += 1
            continue

        # Bold standalone
        if line.startswith('**') and line.endswith('**') and len(line) > 4:
            story.append(Paragraph(f"<b>{line[2:-2]}</b>", style_h2))
            i += 1
            continue

        # Horizontal rule
        if line.startswith('---'):
            story.append(HRFlowable(width="100%", thickness=1, color=BORDER_GRAY, spaceAfter=6))
            i += 1
            continue

        # Code block
        if line.startswith('```'):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code_lines.append(lines[i].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
                i += 1
            i += 1
            if code_lines:
                story.append(Paragraph('<br/>'.join(code_lines), style_code))
            continue

        # Blockquote
        if line.startswith('> '):
            story.append(Paragraph(_md_to_pdf(line[2:]), style_quote))
            i += 1
            continue

        # Table detection
        if '|' in line and i + 1 < len(lines) and '|-' in lines[i + 1]:
            table_rows = []
            while i < len(lines) and '|' in lines[i]:
                row = [c.strip() for c in lines[i].split('|') if c.strip()]
                if row and not re.match(r'^[-:]+$', row[0]):
                    table_rows.append(row)
                i += 1
            if table_rows:
                story.append(_build_pdf_table(table_rows, GREEN, DARK_GREEN, LIGHT_GREEN))
                story.append(Spacer(1, 8))
            continue

        # Bullet
        if line.startswith('- ') or line.startswith('* '):
            story.append(Paragraph(f"• {_md_to_pdf(line[2:])}", style_bullet))
            i += 1
            continue

        # Numbered list
        m = re.match(r'^(\d+)\.\s(.+)', line)
        if m:
            story.append(Paragraph(f"<b>{m.group(1)}.</b> {_md_to_pdf(m.group(2))}", style_bullet))
            i += 1
            continue

        # Normal
        story.append(Paragraph(_md_to_pdf(line), style_body))
        i += 1

    # ── Date & metadata footer ──
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER_GRAY))
    meta_style = ParagraphStyle("Meta", fontName="Helvetica-Oblique", fontSize=8,
        textColor=colors.HexColor("#888888"), alignment=TA_CENTER, spaceAfter=0)
    story.append(Paragraph(
        f"Documento generado automáticamente por Orquesta AI · {datetime.now().strftime('%d de %B de %Y')}",
        meta_style
    ))

    doc.build(story, onFirstPage=on_first_page, onLaterPages=on_later_pages)
    return buf.getvalue()


def _md_to_pdf(text: str) -> str:
    """Convert basic markdown inline to ReportLab XML."""
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Code inline
    text = re.sub(r'`(.+?)`', r'<font name="Courier">\1</font>', text)
    return text


def _build_pdf_table(rows: list, green, dark_green, light_green):
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter as ltr
    from reportlab.lib.units import cm

    BORDER = colors.HexColor("#C8E6D5")

    if not rows:
        return Spacer(1, 0)

    num_cols = max(len(r) for r in rows)
    # Normalize rows
    norm = [r + [''] * (num_cols - len(r)) for r in rows]

    col_width = (ltr[0] - 4 * cm) / num_cols if num_cols else 100

    style = TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), dark_green),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9.5),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor("#444444")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, light_green]),
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ])

    from reportlab.lib.pagesizes import letter as ltr
    t = Table(norm, colWidths=[col_width] * num_cols)
    t.setStyle(style)
    return t


# ── DETECT FILE TYPE FROM PROMPT ────────────────────────────────────────────

def detect_file_type(prompt: str) -> str | None:
    """Detect if the user wants a file generated."""
    p = prompt.lower()

    excel_kw = [
        "excel", "planilla", "spreadsheet", "hoja de calculo", "hoja de cálculo",
        ".xlsx", "tabla excel", "cuadro excel", "presupuesto excel",
        "reporte excel", "plantilla excel", "generar excel", "crea excel",
        "haceme un excel", "haceme una planilla", "plantilla de excel",
    ]
    word_kw = [
        "word", ".docx", "documento word", "informe word", "cv en word",
        "curriculum en word", "carta word", "contrato word", "memo word",
        "plantilla word", "generar word", "crea un word", "haceme un word",
        "documento de texto", "redacta un documento",
    ]
    pdf_kw = [
        "pdf", ".pdf", "en pdf", "como pdf", "generar pdf", "crea un pdf",
        "haceme un pdf", "informe pdf", "reporte pdf", "cv pdf",
        "curriculum pdf", "documento pdf", "carta pdf",
    ]

    # CV / resume detection — default to PDF
    cv_kw = ["curriculum", "currículum", "cv ", " cv", "resume", "hoja de vida"]
    if any(k in p for k in cv_kw):
        if any(k in p for k in word_kw):
            return "docx"
        if any(k in p for k in excel_kw):
            return "xlsx"
        return "pdf"

    if any(k in p for k in excel_kw):
        return "xlsx"
    if any(k in p for k in word_kw):
        return "docx"
    if any(k in p for k in pdf_kw):
        return "pdf"
    return None


# ── FILE SYSTEM PROMPTS ──────────────────────────────────────────────────────

FILE_SYSTEM_PROMPTS = {
    "xlsx": """Sos un experto en creación de planillas Excel profesionales.
El usuario quiere un Excel. Generá el contenido estructurado en formato JSON con esta estructura exacta:

```json
[
  {
    "name": "Nombre Hoja",
    "title": "Título completo de la hoja",
    "description": "Descripción breve opcional",
    "headers": ["Col1", "Col2", "Col3", "Col4"],
    "rows": [
      ["dato1", "dato2", "dato3", "dato4"],
      ["dato5", "dato6", "dato7", "dato8"]
    ],
    "formulas": {}
  }
]
```

REGLAS CRÍTICAS:
- Generá MÚLTIPLES hojas si es apropiado (máximo 5)
- Los datos deben ser REALES, coherentes y profesionales
- Incluí al menos 8-15 filas de datos por hoja
- Para columnas numéricas, usá números reales (no strings)
- El JSON debe ser válido y estar entre ```json y ```
- NO incluyas texto fuera del bloque JSON
- Respondé SOLO con el JSON, nada más""",

    "docx": """Sos un experto en redacción de documentos profesionales en español.
El usuario quiere un documento Word. Generá el contenido en Markdown profesional.

FORMATO A USAR:
- # Título Principal
- ## Sección
- ### Subsección
- **texto en negrita**
- *texto en cursiva*
- - bullet points
- 1. listas numeradas
- | col1 | col2 | (tablas markdown)
- > citas o destacados
- --- separadores

REGLAS:
- El documento debe ser COMPLETO, PROFESIONAL y EXTENSO (mínimo 400 palabras)
- Usá estructura lógica con secciones bien definidas
- Incluí contenido específico y detallado, no genérico
- Si es un CV, incluí todas las secciones estándar con datos ficticios pero coherentes
- Si es un contrato, incluí cláusulas reales y completas
- Respondé con el contenido markdown directamente, sin envoltorio""",

    "pdf": """Sos un experto en redacción de documentos profesionales en español.
El usuario quiere un PDF. Generá el contenido en Markdown profesional.

FORMATO A USAR:
- # Título Principal
- ## Sección  
- ### Subsección
- **negrita**
- *cursiva*
- - bullets
- 1. numerados
- | tablas |
- > destacados
- --- separadores

REGLAS:
- El documento debe ser COMPLETO y PROFESIONAL (mínimo 300 palabras)
- Usá diseño limpio con buena estructura
- Incluí contenido real, específico y valioso
- Para informes: incluí resumen ejecutivo, análisis, conclusiones
- Para CVs: todas las secciones con datos coherentes
- Respondé con el markdown directamente""",
}
