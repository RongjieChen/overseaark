#!/usr/bin/env python3
"""Build the OverseaArk PRD v1.1 DOCX from markdown.

The script intentionally uses python-docx and Word-native styles/fields rather
than rendering a fake visual document. It is scoped to the PRD artifact only.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor, Twips


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "PRD-v1.1.md"
TARGET = ROOT / "docs" / "出海方舟OverseaArk-PRD-v1.1.docx"

FONT_EAST_ASIA = "Noto Sans CJK SC"
FONT_FALLBACK = "Noto Sans CJK SC"
FONT_LATIN = "Noto Sans CJK SC"
CONTENT_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120
CELL_MARGINS_DXA = {"top": 80, "bottom": 80, "start": 120, "end": 120}


def set_run_font(run, size: int | None = None, bold: bool | None = None, color: str | None = None):
    font = run.font
    font.name = FONT_LATIN
    if size:
        font.size = Pt(size)
    if bold is not None:
        font.bold = bold
    if color:
        font.color.rgb = RGBColor.from_string(color)
    for script in ("ascii", "hAnsi", "eastAsia", "cs"):
        run._element.rPr.rFonts.set(qn(f"w:{script}"), FONT_EAST_ASIA)
    for theme_attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        run._element.rPr.rFonts.attrib.pop(qn(f"w:{theme_attr}"), None)


def set_style_font(style, size: int, bold: bool = False, color: str = "111827"):
    font = style.font
    font.name = FONT_LATIN
    font.size = Pt(size)
    font.bold = bold
    font.color.rgb = RGBColor.from_string(color)
    for script in ("ascii", "hAnsi", "eastAsia", "cs"):
        style.element.rPr.rFonts.set(qn(f"w:{script}"), FONT_EAST_ASIA)
    for theme_attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        style.element.rPr.rFonts.attrib.pop(qn(f"w:{theme_attr}"), None)


def shade_cell(cell, fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_width(cell, width_twips: int):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_twips))
    tc_w.set(qn("w:type"), "dxa")


def ensure_child(parent, tag: str):
    child = parent.find(qn(tag))
    if child is None:
        child = OxmlElement(tag)
        parent.append(child)
    return child


def apply_table_geometry(table, widths: list[int]):
    if sum(widths) != CONTENT_WIDTH_DXA:
        raise ValueError(f"table widths must sum to {CONTENT_WIDTH_DXA}: {widths}")
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = ensure_child(tbl_pr, "w:tblW")
    tbl_w.set(qn("w:type"), "dxa")
    tbl_w.set(qn("w:w"), str(CONTENT_WIDTH_DXA))
    tbl_ind = ensure_child(tbl_pr, "w:tblInd")
    tbl_ind.set(qn("w:type"), "dxa")
    tbl_ind.set(qn("w:w"), str(TABLE_INDENT_DXA))
    layout = ensure_child(tbl_pr, "w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        grid_col = OxmlElement("w:gridCol")
        grid_col.set(qn("w:w"), str(width))
        grid.append(grid_col)
    for col_idx, width in enumerate(widths):
        table.columns[col_idx].width = Twips(width)
    for row in table.rows:
        row.height = None
        for col_idx, cell in enumerate(row.cells):
            cell.width = Twips(widths[col_idx])
            set_cell_width(cell, widths[col_idx])
            tc_mar = ensure_child(cell._tc.get_or_add_tcPr(), "w:tcMar")
            for side, margin in CELL_MARGINS_DXA.items():
                node = ensure_child(tc_mar, f"w:{side}")
                node.set(qn("w:w"), str(margin))
                node.set(qn("w:type"), "dxa")


def set_table_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), "D1D5DB")


def add_field(paragraph, instruction: str):
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    paragraph._p.append(begin)
    paragraph._p.append(instr)
    paragraph._p.append(separate)
    paragraph._p.append(end)


def add_page_number(paragraph):
    add_field(paragraph, "PAGE")


def add_toc(document: Document, markdown: str):
    p = document.add_paragraph(style="TOC Instruction")
    p.add_run("目录").bold = True
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for line in markdown.splitlines():
        if not line.startswith("## ") and not line.startswith("### "):
            continue
        level = 1 if line.startswith("## ") else 2
        text = line[3:].strip() if level == 1 else line[4:].strip()
        if text == "目录":
            continue
        toc_line = document.add_paragraph()
        toc_line.paragraph_format.left_indent = Inches(0 if level == 1 else 0.28)
        toc_line.paragraph_format.space_before = Pt(0)
        toc_line.paragraph_format.space_after = Pt(3 if level == 1 else 1)
        set_run_font(toc_line.add_run(text), 10 if level == 1 else 9, level == 1, "374151")
    document.add_page_break()


def configure_styles(document: Document):
    styles = document.styles
    normal = styles["Normal"]
    set_style_font(normal, 11, False, "111827")
    normal.paragraph_format.line_spacing = 1.10
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)

    for name, size, color in [
        ("Title", 23, "0F172A"),
        ("Heading 1", 16, "2E74B5"),
        ("Heading 2", 13, "2E74B5"),
        ("Heading 3", 12, "1F4D78"),
    ]:
        set_style_font(styles[name], size, True, color)
    styles["Title"].paragraph_format.space_before = Pt(0)
    styles["Title"].paragraph_format.space_after = Pt(4)
    styles["Heading 1"].paragraph_format.space_before = Pt(16)
    styles["Heading 1"].paragraph_format.space_after = Pt(8)
    styles["Heading 2"].paragraph_format.space_before = Pt(12)
    styles["Heading 2"].paragraph_format.space_after = Pt(6)
    styles["Heading 3"].paragraph_format.space_before = Pt(8)
    styles["Heading 3"].paragraph_format.space_after = Pt(4)

    set_style_font(styles["List Number"], 11, False, "111827")
    set_style_font(styles["List Bullet"], 11, False, "111827")
    for list_name in ("List Number", "List Bullet"):
        list_format = styles[list_name].paragraph_format
        list_format.left_indent = Inches(0.5)
        list_format.first_line_indent = Inches(-0.25)
        list_format.space_after = Pt(8)
        list_format.line_spacing = 1.167
    set_style_font(styles["Caption"], 8, False, "6B7280")

    if "Memo Masthead" not in styles:
        masthead = styles.add_style("Memo Masthead", WD_STYLE_TYPE.PARAGRAPH)
    else:
        masthead = styles["Memo Masthead"]
    set_style_font(masthead, 9, True, "FFFFFF")
    masthead.paragraph_format.space_after = Pt(0)

    if "TOC Instruction" not in styles:
        toc_style = styles.add_style("TOC Instruction", WD_STYLE_TYPE.PARAGRAPH)
    else:
        toc_style = styles["TOC Instruction"]
    set_style_font(toc_style, 12, True, "0F172A")


def configure_document(document: Document):
    section = document.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    header = section.header.paragraphs[0]
    header.text = ""
    header.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = header.add_run("出海方舟 OverseaArk PRD v1.1")
    set_run_font(run, 8, True, "4B5563")

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number(footer)


def parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
        rows.append(cells)
        i += 1
    if len(rows) >= 2 and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in rows[1]):
        rows.pop(1)
    return rows, i


def add_table(document: Document, rows: list[list[str]]):
    if not rows:
        return
    max_cols = max(len(r) for r in rows)
    table = document.add_table(rows=len(rows), cols=max_cols)
    table.style = "Table Grid"
    set_table_borders(table)
    header_row_pr = table.rows[0]._tr.get_or_add_trPr()
    header_marker = OxmlElement("w:tblHeader")
    header_marker.set(qn("w:val"), "true")
    header_row_pr.append(header_marker)

    available_twips = CONTENT_WIDTH_DXA
    first_col = 1900 if max_cols > 2 else 2600
    remaining = available_twips - first_col
    widths = [first_col] + [max(1200, remaining // max(1, max_cols - 1))] * (max_cols - 1)
    widths[-1] += available_twips - sum(widths)

    for r_idx, row in enumerate(rows):
        for c_idx in range(max_cols):
            cell = table.cell(r_idx, c_idx)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            value = row[c_idx] if c_idx < len(row) else ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_before = Pt(0)
            para.paragraph_format.space_after = Pt(2)
            para.paragraph_format.line_spacing = 1.10
            run = para.add_run(value)
            set_run_font(run, 8 if max_cols >= 5 else 9, r_idx == 0, "111827")
            if r_idx == 0:
                shade_cell(cell, "E5E7EB")
            elif r_idx % 2 == 0:
                shade_cell(cell, "F9FAFB")
    apply_table_geometry(table, widths)


def add_code_block(document: Document, code: list[str]):
    para = document.add_paragraph()
    para.paragraph_format.left_indent = Inches(0.18)
    para.paragraph_format.right_indent = Inches(0.18)
    para.paragraph_format.space_before = Pt(4)
    para.paragraph_format.space_after = Pt(8)
    para.paragraph_format.line_spacing = 1.0
    p_pr = para._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), "F3F4F6")
    p_pr.append(shd)
    for idx, line in enumerate(code):
        if idx:
            para.add_run().add_break()
        run = para.add_run(line)
        run.font.name = "Menlo"
        run.font.size = Pt(8)
        run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_FALLBACK)


def add_cover(document: Document):
    p = document.add_paragraph(style="Memo Masthead")
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    masthead = p.add_run("NVIDIA DGX Spark Hackathon  ·  Product Requirements Document")
    set_run_font(masthead, 10, True, "2E74B5")

    title = document.add_paragraph()
    title.style = "Title"
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("出海方舟 OverseaArk")
    set_run_font(r, 26, True, "0F172A")
    sub = document.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("产品需求文档 v1.1")
    set_run_font(r, 15, True, "374151")
    tagline = document.add_paragraph()
    tagline.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = tagline.add_run("本地多模态外贸营销作战室")
    set_run_font(r, 11, False, "4B5563")
    metadata = document.add_paragraph()
    metadata.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run_font(metadata.add_run("v1.1  |  DGX Spark / Ubuntu 24.04 / CUDA 13  |  2026-07-22"), 9, False, "6B7280")
    rule = document.add_paragraph()
    rule.paragraph_format.space_before = Pt(12)
    rule.paragraph_format.space_after = Pt(0)
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "10")
    bottom.set(qn("w:color"), "2E74B5")
    p_bdr.append(bottom)
    rule._p.get_or_add_pPr().append(p_bdr)
    document.add_page_break()


def add_markdown(document: Document, markdown: str):
    lines = markdown.splitlines()
    i = 0
    in_code = False
    code: list[str] = []
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                add_code_block(document, code)
                code = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code.append(raw)
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        if line.strip().startswith("|"):
            rows, i = parse_table(lines, i)
            add_table(document, rows)
            continue
        if line.startswith("# "):
            if "出海方舟" in line:
                i += 1
                continue
            document.add_heading(line[2:].strip(), level=1)
        elif line.startswith("## "):
            document.add_heading(line[3:].strip(), level=1)
        elif line.startswith("### "):
            document.add_heading(line[4:].strip(), level=2)
        elif re.match(r"^\d+\.\s+", line):
            p = document.add_paragraph(style="List Number")
            r = p.add_run(re.sub(r"^\d+\.\s+", "", line))
            set_run_font(r, 11)
        elif line.startswith("- "):
            p = document.add_paragraph(style="List Bullet")
            r = p.add_run(line[2:])
            set_run_font(r, 11)
        else:
            p = document.add_paragraph()
            r = p.add_run(line)
            set_run_font(r, 11)
        i += 1


def main():
    markdown = SOURCE.read_text(encoding="utf-8")
    document = Document()
    configure_styles(document)
    configure_document(document)
    add_cover(document)
    add_toc(document, markdown)
    add_markdown(document, markdown)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    document.save(TARGET)
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
