"""Add local DOCX knowledge storage with pgvector embeddings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = '0002_knowledge_rag'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

VECTOR_DIMENSIONS = 1024  # Verified from the configured local bge-m3:latest embedding model.

def upgrade():
    try:
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    except Exception as exc:
        raise RuntimeError(
            'PostgreSQL pgvector is unavailable. Install the pgvector server extension for this PostgreSQL version '
            '(for example, use the project Compose image pgvector/pgvector:pg16), then rerun alembic upgrade head.'
        ) from exc
    op.create_table(
        'knowledge_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('filename', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('source_type', sa.String(32), nullable=False, server_default='docx'),
        sa.Column('total_pages', sa.Integer(), nullable=True),
        sa.Column('total_chunks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_knowledge_documents_file_hash', 'knowledge_documents', ['file_hash'], unique=True)
    op.create_index('ix_knowledge_documents_is_active', 'knowledge_documents', ['is_active'])
    op.create_table(
        'knowledge_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(VECTOR_DIMENSIONS), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('section_title', sa.Text(), nullable=True),
        sa.Column('subsection_title', sa.Text(), nullable=True),
        sa.Column('language', sa.String(24), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('document_id', 'chunk_index', name='uq_knowledge_chunks_document_index'),
    )
    op.create_index('ix_knowledge_chunks_document_id', 'knowledge_chunks', ['document_id'])
    op.create_index('ix_knowledge_chunks_chunk_index', 'knowledge_chunks', ['chunk_index'])
    op.create_index('ix_knowledge_chunks_page_number', 'knowledge_chunks', ['page_number'])
    op.create_index('ix_knowledge_chunks_section_title', 'knowledge_chunks', ['section_title'])
    op.create_index('ix_knowledge_chunks_embedding_hnsw', 'knowledge_chunks', ['embedding'], postgresql_using='hnsw', postgresql_ops={'embedding':'vector_cosine_ops'})

def downgrade():
    op.drop_index('ix_knowledge_chunks_embedding_hnsw', table_name='knowledge_chunks')
    op.drop_table('knowledge_chunks')
    op.drop_table('knowledge_documents')
    # Keep the shared vector extension installed; other database objects may use it.
