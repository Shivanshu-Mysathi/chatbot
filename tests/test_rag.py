import asyncio
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from app.rag.chunker import chunk_document, detect_language
from app.rag.context import RAGResult, build_context, build_user_prompt
from app.rag.embeddings import embed_texts, EmbeddingDimensionMismatch
from app.rag.ingestion import ingest_document
from app.rag.parser import DocumentBlock, DocumentParseError, parse_docx
from app.rag import retriever

WNS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

def _p(text, style=''):
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    return f'<w:p>{style_xml}<w:r><w:t>{text}</w:t></w:r></w:p>'

def _cell(text):
    return f'<w:tc>{_p(text)}</w:tc>'

def _write_docx(path: Path, *, duplicate_content='Training content.'):
    body = (
        _p('MySathi Training Manual', 'Title')
        + _p('7. Luggage Booking', 'Heading2')
        + _p(duplicate_content)
        + '<w:tbl><w:tr>' + _cell('Booking Type') + _cell('Payment') + '</w:tr>'
        + '<w:tr>' + _cell('Immediate') + _cell('After coolie accepts') + '</w:tr></w:tbl>'
    )
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="{WNS}"><w:body>{body}<w:sectPr/></w:body></w:document>'''
    app = '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Pages>2</Pages></Properties>'
    core = '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>MySathi Training Manual</dc:title></cp:coreProperties>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('word/document.xml', xml)
        archive.writestr('docProps/app.xml', app)
        archive.writestr('docProps/core.xml', core)

def test_docx_parser_preserves_headings_tables_and_metadata(tmp_path):
    path = tmp_path / 'manual.docx'
    _write_docx(path)
    parsed = parse_docx(path)
    assert parsed.title == 'MySathi Training Manual'
    assert parsed.total_pages == 2
    assert parsed.blocks[1].style == 'Heading2'
    table = next(block.text for block in parsed.blocks if block.kind == 'table')
    assert 'Booking Type: Immediate' in table
    assert 'Payment: After coolie accepts' in table

def test_docx_parser_rejects_invalid_input(tmp_path):
    path = tmp_path / 'broken.docx'
    path.write_text('not a docx')
    with pytest.raises(DocumentParseError):
        parse_docx(path)

def test_section_chunking_and_bilingual_detection():
    blocks = [
        DocumentBlock('7. Luggage Booking', 'Heading2'),
        DocumentBlock('Immediate booking searches for a porter first. तत्काळ बुकिंग में पहले कुली खोजा जाता है।', ''),
        DocumentBlock('7.1 Payment Rules', 'Heading3'),
        DocumentBlock('Payment follows acceptance.', ''),
    ]
    chunks = chunk_document(blocks, size=400, overlap=60)
    assert len(chunks) == 2
    assert chunks[0].section_title == '7. Luggage Booking'
    assert chunks[0].language == 'bilingual'
    assert chunks[1].subsection_title == '7.1 Payment Rules'
    assert detect_language('केवल हिंदी') == 'Hindi'

def test_chunking_splits_long_content_with_overlap():
    blocks = [DocumentBlock(('The rule is important. ' * 35).strip(), '')]
    chunks = chunk_document(blocks, size=400, overlap=80)
    assert len(chunks) > 1
    assert all(len(item.content) <= 480 for item in chunks)
    assert chunks[0].content[-50:] in chunks[1].content

def test_embedding_generation_batches_requests_and_checks_dimension(monkeypatch):
    seen = []
    async def handler(request):
        body = __import__('json').loads(request.content)
        seen.append(body['input'])
        return httpx.Response(200, json={'embeddings':[[0.1] * 1024 for _ in body['input']]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    vectors = asyncio.run(embed_texts(['one', 'two', 'three'], batch_size=2))
    assert len(vectors) == 3 and len(vectors[0]) == 1024
    assert [len(batch) for batch in seen] == [2, 1]

def test_embedding_generation_rejects_wrong_dimension(monkeypatch):
    async def handler(request):
        return httpx.Response(200, json={'embeddings':[[0.1] * 3]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(EmbeddingDimensionMismatch):
        asyncio.run(embed_texts(['one'], batch_size=1))

def test_ingestion_is_idempotent_for_duplicate_hash(tmp_path):
    path = tmp_path / 'manual.docx'
    _write_docx(path)
    existing = SimpleNamespace(id=uuid.uuid4(), total_pages=2)
    class FakeDB:
        async def scalar(self, statement): return existing
        async def rollback(self): pass
    embedder = AsyncMock()
    outcome = asyncio.run(ingest_document(FakeDB(), path, embedder=embedder))
    assert outcome['skipped_duplicates'] == 1
    assert outcome['chunks_created'] == outcome['embeddings_created'] == 0
    embedder.assert_not_awaited()

def test_full_docx_ingestion_stores_chunks_and_vectors(tmp_path):
    path = tmp_path / 'manual.docx'
    _write_docx(path)
    class Tx:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    class Rows:
        def all(self): return []
    class FakeDB:
        def __init__(self): self.document=None; self.rows=[]
        async def scalar(self, statement): return None
        async def rollback(self): pass
        def begin(self): return Tx()
        async def scalars(self, statement): return Rows()
        def add(self, item): self.document=item
        async def flush(self): self.document.id=uuid.uuid4()
        def add_all(self, rows): self.rows.extend(rows)
    db=FakeDB()
    async def embeddings(texts, batch_size=None): return [[0.0]*1024 for _ in texts]
    outcome=asyncio.run(ingest_document(db, path, embedder=embeddings))
    assert outcome['chunks_created'] == len(db.rows) > 0
    assert outcome['embeddings_created'] == len(db.rows)
    assert all(len(row.embedding) == 1024 for row in db.rows)

def test_retrieval_returns_ranked_results_and_enforces_threshold(monkeypatch):
    doc=SimpleNamespace(id=uuid.uuid4(), filename='manual.docx')
    chunk=SimpleNamespace(content='Coolie assignment uses the booking time.', page_number=19,
                          section_title='Luggage Booking', subsection_title='15-minute rule')
    class Rows:
        def all(self): return [(chunk, doc, 0.91)]
    class FakeDB:
        def __init__(self): self.statement=None
        async def execute(self, statement): self.statement=statement; return Rows()
    async def embedding(texts, batch_size=None): return [[0.0]*1024]
    monkeypatch.setattr(retriever, 'embed_texts', embedding)
    db=FakeDB()
    results=asyncio.run(retriever.retrieve(db, 'How do bookings work?', top_k=4))
    compiled=str(db.statement.compile(dialect=postgresql.dialect()))
    assert 'knowledge_chunks.embedding <=>' in compiled
    assert 'knowledge_documents.is_active IS true' in compiled
    assert any(value == 0.50 for value in db.statement.compile(dialect=postgresql.dialect()).params.values())
    assert len(results) == 1 and results[0].similarity == 0.91
    assert results[0].page_number == 19

def test_context_builder_has_source_metadata_and_no_context_fallback():
    result=RAGResult('Immediate bookings match porters first.', uuid.uuid4(), 'manual.docx', 19,
                     'Luggage Booking', '15-minute rule', 0.91)
    context=build_context([result])
    assert 'SOURCE: manual.docx' in context and 'PAGE: 19' in context
    prompt=build_user_prompt('How does immediate booking work?', [result])
    assert 'quoted product knowledge' in prompt and 'Immediate bookings' in prompt
    assert '[No relevant MySathi training-manual information was retrieved.]' in build_user_prompt('Who won?', [])

def test_chat_service_injects_retrieved_context(monkeypatch):
    from app.services import chat_service
    session_id=uuid.uuid4()
    class FakeDB:
        def __init__(self): self.pending=[]
        async def get(self, *args): return None
        def add(self, item): self.pending.append(item)
        async def flush(self):
            for item in self.pending:
                if getattr(item, 'id', None) is None: item.id=session_id
        async def commit(self):
            for item in self.pending:
                if getattr(item, 'id', None) is None: item.id=uuid.uuid4()
        async def scalars(self, statement):
            class Result:
                def all(inner): return [item for item in self.pending if getattr(item, 'role', None)]
            return Result()
        async def refresh(self, item):
            if item.id is None: item.id=uuid.uuid4()
    source=RAGResult('Login uses SMS OTP for verification.', uuid.uuid4(), 'manual.docx', 3,
                     'Authentication', 'OTP', 0.9)
    class FakeRAG:
        async def retrieve(self, db, query): return [source]
    captured={}
    class FakeOllama:
        async def chat(self, messages): captured['messages']=messages; return 'OTP verification is required.'
    settings=SimpleNamespace(rag_enabled=True, rag_system_prompt='Use only MySathi training excerpts.',
                             system_prompt='general', max_context_messages=20, ollama_model='qwen3:14b')
    monkeypatch.setattr(chat_service, 'get_settings', lambda: settings)
    monkeypatch.setattr(chat_service, 'RAGService', FakeRAG)
    monkeypatch.setattr(chat_service, 'OllamaService', FakeOllama)
    sid, _, response, _=asyncio.run(chat_service.send_message(FakeDB(), 'How does OTP work?', None))
    assert sid == session_id and response == 'OTP verification is required.'
    assert captured['messages'][0]['content'] == settings.rag_system_prompt
    assert 'Login uses SMS OTP' in captured['messages'][-1]['content']
    assert 'How does OTP work?' in captured['messages'][-1]['content']

def test_authenticated_chat_endpoint_uses_rag(client, monkeypatch):
    from app.db.database import get_db
    from app.services import chat_service

    class FakeDB:
        def __init__(self): self.pending=[]; self.history=[]
        async def get(self, *args): return None
        def add(self, item):
            self.pending.append(item)
            if getattr(item, 'role', None) == 'user': self.history.append(item)
        async def flush(self):
            for item in self.pending:
                if item.__class__.__name__ == 'ChatSession' and item.id is None: item.id=uuid.uuid4()
        async def commit(self):
            for item in self.pending:
                if getattr(item, 'id', None) is None: item.id=uuid.uuid4()
        async def scalars(self, statement):
            class Result:
                def all(inner): return self.history
            return Result()
        async def refresh(self, item): pass

    db=FakeDB()
    async def override_db(): yield db
    client.app.dependency_overrides[get_db]=override_db
    source=RAGResult('The passenger enters a 10-digit PNR to start a wheelchair booking.',
                     uuid.uuid4(), 'manual.docx', 18, 'Wheelchair Booking', 'PNR search', 0.88)
    class FakeRAG:
        async def retrieve(self, session, query): return [source]
    observed={}
    class FakeOllama:
        async def chat(self, messages):
            observed['messages']=messages
            return 'Enter the PNR to start the wheelchair booking flow.'
    monkeypatch.setattr(chat_service, 'RAGService', FakeRAG)
    monkeypatch.setattr(chat_service, 'OllamaService', FakeOllama)
    response=client.post('/api/v1/chat', headers={'Authorization':'Bearer test-secret'}, json={'message':'How do I book a wheelchair?'})
    client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()['response'].startswith('Enter the PNR')
    assert '10-digit PNR' in observed['messages'][-1]['content']
