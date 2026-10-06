from __future__ import annotations

import re
from dataclasses import dataclass
from app.rag.parser import DocumentBlock

DEVANAGARI = re.compile(r'[\u0900-\u097f]')
LATIN = re.compile(r'[A-Za-z]')
SENTENCE_SPLIT = re.compile(r'(?<=[.!?।])\s+')

@dataclass(frozen=True)
class KnowledgeChunkData:
    chunk_index: int
    content: str
    section_title: str | None
    subsection_title: str | None
    page_number: int | None
    language: str
    metadata: dict

def detect_language(text: str) -> str:
    devanagari = len(DEVANAGARI.findall(text))
    latin = len(LATIN.findall(text))
    if devanagari and latin:
        return 'bilingual'
    if devanagari:
        return 'Hindi'
    if latin:
        return 'English'
    return 'unknown'

def _split_long(text: str, size: int) -> list[str]:
    pieces: list[str] = []
    for paragraph in text.splitlines() or [text]:
        if len(paragraph) <= size:
            pieces.append(paragraph)
            continue
        sentences = SENTENCE_SPLIT.split(paragraph)
        current = ''
        for sentence in sentences:
            if len(sentence) > size:
                words = sentence.split()
                for word in words:
                    candidate = f'{current} {word}'.strip()
                    if len(candidate) > size and current:
                        pieces.append(current)
                        current = word
                    else:
                        current = candidate
                continue
            candidate = f'{current} {sentence}'.strip()
            if len(candidate) > size and current:
                pieces.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            pieces.append(current)
    return [piece for piece in pieces if piece.strip()]

def chunk_document(blocks: list[DocumentBlock], *, size: int = 1800, overlap: int = 240) -> list[KnowledgeChunkData]:
    if size < 300:
        raise ValueError('RAG_CHUNK_SIZE must be at least 300 characters.')
    if overlap < 0 or overlap >= size:
        raise ValueError('RAG_CHUNK_OVERLAP must be non-negative and smaller than RAG_CHUNK_SIZE.')
    section: str | None = None
    subsection: str | None = None
    current: list[str] = []
    current_chars = 0
    current_page: int | None = None
    chunks: list[KnowledgeChunkData] = []

    def emit(*, carry: bool = False) -> str:
        nonlocal current, current_chars
        if not current:
            return ''
        content = '\n'.join(current).strip()
        chunks.append(KnowledgeChunkData(
            chunk_index=len(chunks), content=content, section_title=section,
            subsection_title=subsection, page_number=current_page,
            language=detect_language(content),
            metadata={'source_kind':'manual', 'contains_table_rows': any(line.startswith('Column ') or ': ' in line for line in current)},
        ))
        tail = content[-overlap:] if carry and overlap else ''
        current = [tail] if tail else []
        current_chars = len(tail)
        return content

    for block in blocks:
        text = re.sub(r'\s+', ' ', block.text).strip() if block.kind == 'paragraph' else block.text.strip()
        if not text:
            continue
        style = block.style.lower()
        if style.endswith('heading1'):
            if current:
                emit()
            if text.upper().startswith(('PART ', 'भाग ')):
                section, subsection = text, None
            elif section is None:
                section = text
        elif style.endswith('heading2'):
            if current:
                emit()
            section, subsection = text, None
        elif style.endswith(('heading3', 'heading4')):
            if current:
                emit()
            subsection = text

        segments = _split_long(text, size)
        for segment in segments:
            if current and current_chars + len(segment) + 1 > size:
                emit(carry=True)
            if block.page_number is not None and not current:
                current_page = block.page_number
            elif not current:
                current_page = None
            current.append(segment)
            current_chars += len(segment) + 1
    if current:
        emit()
    return chunks
