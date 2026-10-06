from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{%s}' % NS['w']

class DocumentParseError(ValueError):
    """A DOCX is corrupt, unsupported, or contains no usable text."""

@dataclass(frozen=True)
class DocumentBlock:
    text: str
    style: str
    kind: str = 'paragraph'
    page_number: int | None = None

@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    title: str
    blocks: list[DocumentBlock]
    total_pages: int | None
    metadata: dict

def _paragraph_text(element: ET.Element) -> tuple[str, int]:
    pieces: list[str] = []
    page_breaks = 0
    for node in element.iter():
        if node.tag == W + 't':
            pieces.append(node.text or '')
        elif node.tag == W + 'tab':
            pieces.append(' ')
        elif node.tag == W + 'br':
            if node.get(W + 'type') == 'page':
                page_breaks += 1
                pieces.append(' ')
            else:
                pieces.append(' ')
        elif node.tag == W + 'lastRenderedPageBreak':
            page_breaks += 1
            pieces.append(' ')
    text = re.sub(r'[\t\xa0 ]+', ' ', ''.join(pieces)).strip()
    return text, page_breaks

def _table_text(table: ET.Element) -> str:
    rows: list[list[str]] = []
    for row in table.findall('w:tr', NS):
        cells = []
        for cell in row.findall('w:tc', NS):
            value = ' '.join(filter(None, (_paragraph_text(p)[0] for p in cell.findall('.//w:p', NS))))
            cells.append(value)
        if any(cells):
            rows.append(cells)
    if not rows:
        return ''
    headers = rows[0]
    output = []
    for row_index, row in enumerate(rows[1:] or rows):
        pairs = []
        for column, value in enumerate(row):
            if not value:
                continue
            heading = headers[column] if rows[1:] and column < len(headers) and headers[column] else f'Column {column + 1}'
            pairs.append(f'{heading}: {value}')
        if pairs:
            output.append(' | '.join(pairs))
    return '\n'.join(output)

def parse_docx(path: str | Path) -> ParsedDocument:
    source = Path(path)
    if source.suffix.lower() != '.docx' or not source.is_file():
        raise DocumentParseError('Input must be an existing .docx file.')
    if not zipfile.is_zipfile(source):
        raise DocumentParseError('The file is not a valid DOCX archive.')
    try:
        with zipfile.ZipFile(source) as archive:
            names = set(archive.namelist())
            if 'word/document.xml' not in names:
                raise DocumentParseError('DOCX is missing word/document.xml.')
            root = ET.fromstring(archive.read('word/document.xml'))
            app_props = ET.fromstring(archive.read('docProps/app.xml')) if 'docProps/app.xml' in names else None
            core_props = ET.fromstring(archive.read('docProps/core.xml')) if 'docProps/core.xml' in names else None
            page_break_count = len(root.findall('.//w:br[@w:type="page"]', NS)) + len(root.findall('.//w:lastRenderedPageBreak', NS))
            page_text = None
            if app_props is not None:
                page_node = next((node for node in app_props if node.tag.rsplit('}', 1)[-1] == 'Pages'), None)
                if page_node is not None and page_node.text:
                    try:
                        declared = int(page_node.text)
                        if declared > 1:
                            page_text = declared
                    except ValueError:
                        pass
            title = None
            if core_props is not None:
                title_node = next((node for node in core_props if node.tag.rsplit('}', 1)[-1] == 'title'), None)
                title = (title_node.text or '').strip() if title_node is not None else None
            body = root.find('w:body', NS)
            if body is None:
                raise DocumentParseError('DOCX has no document body.')
            blocks: list[DocumentBlock] = []
            page = 1 if page_break_count else None
            for child in body:
                if child.tag == W + 'p':
                    text, breaks = _paragraph_text(child)
                    if not text:
                        if breaks and page is not None:
                            page += breaks
                        continue
                    style_node = child.find('w:pPr/w:pStyle', NS)
                    style = style_node.get(W + 'val', '') if style_node is not None else ''
                    blocks.append(DocumentBlock(text=text, style=style, page_number=page))
                    if breaks and page is not None:
                        page += breaks
                elif child.tag == W + 'tbl':
                    text = _table_text(child)
                    if text:
                        blocks.append(DocumentBlock(text=text, style='', kind='table', page_number=page))
            if not any(block.text for block in blocks):
                raise DocumentParseError('No readable paragraphs or tables were found in the DOCX.')
            pictures = sum(1 for name in names if name.startswith('word/media/'))
            return ParsedDocument(
                filename=source.name,
                title=title or blocks[0].text[:240],
                blocks=blocks,
                total_pages=page_text or (page if page_break_count else None),
                metadata={'paragraph_and_table_blocks':len(blocks), 'embedded_image_count':pictures,
                          'page_numbers_available':bool(page_break_count), 'declared_page_metadata':page_text},
            )
    except DocumentParseError:
        raise
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        raise DocumentParseError(f'Could not read DOCX content: {exc}') from exc
