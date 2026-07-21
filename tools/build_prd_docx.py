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
from docx.shared import Cm, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "PRD-v1.1.md"
TARGET = ROOT / "docs" / "出海方舟OverseaArk-PRD-v1.1.docx"

FONT_EAST_ASIA = "Noto Sans CJK SC"
FONT_FALLBACK = "Microsoft YaHei"
FONT_LATIN = "Aptos"


def set_run_font(run, size: int | None = None, bold: bool | None = None, color: str | None = None):
    font = run.font
    font.name = FONT_LATIN
    if size:
        font.size = Pt(size)
    if bold is not None:
        font.bold = bold
    if color:
        font.color.rgb = RGBColor.from_string(color)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_EAST_ASIA)
    run._element.rPr.rFonts.set(qn("w:asciiTheme"), "minorHAnsi")
    run._element.rPr.rFonts.set(qn("w:hAnsiTheme"), "minorHAnsi")


def set_style_font(style, size: int, bold: bool = False, color: str = "111827"):
    font = style.font
    font.name = FONT_LATIN
    font.size = Pt(size)
    font.bold = bold
    font.color.rgb = RGBColor.from_string(color)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), FONT_EAST_ASIA)
    style.element.rPr.rFonts.set(qn("w:ascii"), FONT_LATIN)
    style.element.rPr.rFonts.set(qn("w:hAnsi"), FONT_LATIN)


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


def add_toc(document: Document):
    p = document.add_paragraph(style="TOC Instruction")
    p.add_run("目录").bold = True
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    toc = document.add_paragraph()
    add_field(toc, 'TOC \\o "1-3" \\h \\z \\u')
    note = document.add_paragraph(style="Caption")
    note.add_run("提示：在 Microsoft Word 中右键目录区域并选择「更新域」以生成页码。")


def configure_styles(document: Document):
    styles = document.styles
    normal = styles["Normal"]
    set_style_font(normal, 9, False, "111827")
    normal.paragraph_format.line_spacing = 1.08
    normal.paragraph_format.space_after = Pt(3)

    for name, size, color in [
        ("Title", 22, "0F172A"),
        ("Heading 1", 15, "0F172A"),
        ("Heading 2", 11, "1F2937"),
        ("Heading 3", 10, "374151"),
    ]:
        set_style_font(styles[name], size, True, color)
        styles[name].paragraph_format.space_before = Pt(7)
        styles[name].paragraph_format.space_after = Pt(3)

    set_style_font(styles["List Number"], 9, False, "111827")
    set_style_font(styles["List Bullet"], 9, False, "111827")
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
    section.top_margin = Cm(1.35)
    section.bottom_margin = Cm(1.25)
    section.left_margin = Cm(1.45)
    section.right_margin = Cm(1.45)
    section.header_distance = Cm(0.55)
    section.footer_distance = Cm(0.55)

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
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.style = "Table Grid"
    set_table_borders(table)

    available_twips = 9600
    first_col = 1900 if max_cols > 2 else 2600
    remaining = available_twips - first_col
    widths = [first_col] + [max(1200, remaining // max(1, max_cols - 1))] * (max_cols - 1)

    for r_idx, row in enumerate(rows):
        for c_idx in range(max_cols):
            cell = table.cell(r_idx, c_idx)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_width(cell, widths[c_idx])
            value = row[c_idx] if c_idx < len(row) else ""
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(0)
            run = para.add_run(value)
            set_run_font(run, 7 if max_cols >= 5 else 8, r_idx == 0, "111827")
            if r_idx == 0:
                shade_cell(cell, "E5E7EB")
            elif r_idx % 2 == 0:
                shade_cell(cell, "F9FAFB")


def add_code_block(document: Document, code: list[str]):
    table = document.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_borders(table)
    cell = table.cell(0, 0)
    shade_cell(cell, "F3F4F6")
    set_cell_width(cell, 9600)
    para = cell.paragraphs[0]
    for idx, line in enumerate(code):
        if idx:
            para.add_run().add_break()
        run = para.add_run(line)
        run.font.name = "Menlo"
        run.font.size = Pt(8)
        run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_FALLBACK)


def add_cover(document: Document):
    table = document.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_borders(table)
    cell = table.cell(0, 0)
    shade_cell(cell, "111827")
    set_cell_width(cell, 9600)
    p = cell.paragraphs[0]
    p.style = "Memo Masthead"
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("NVIDIA DGX Spark Hackathon · Local Multimodal Agent Product Brief")

    title = document.add_paragraph()
    title.style = "Title"
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("出海方舟 OverseaArk")
    set_run_font(r, 24, True, "0F172A")
    sub = document.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("产品需求文档 v1.1")
    set_run_font(r, 15, True, "374151")
    tagline = document.add_paragraph()
    tagline.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = tagline.add_run("本地多模态外贸营销作战室")
    set_run_font(r, 11, False, "4B5563")
    document.add_paragraph()


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
            set_run_font(r, 9)
        elif line.startswith("- "):
            p = document.add_paragraph(style="List Bullet")
            r = p.add_run(line[2:])
            set_run_font(r, 9)
        else:
            p = document.add_paragraph()
            r = p.add_run(line)
            set_run_font(r, 9)
        i += 1


def main():
    markdown = SOURCE.read_text(encoding="utf-8")
    document = Document()
    configure_styles(document)
    configure_document(document)
    add_cover(document)
    add_toc(document)
    add_markdown(document, markdown)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    document.save(TARGET)
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
