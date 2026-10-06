"""Add admin sessions and identity/RAG audit metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003_admin_observability'
down_revision = '0002_knowledge_rag'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('chat_sessions', sa.Column('user_email', sa.String(length=320), nullable=True))
    op.add_column('chat_sessions', sa.Column('user_name', sa.String(length=200), nullable=True))
    op.create_index('ix_chat_sessions_user_created', 'chat_sessions', ['user_id', 'created_at'])
    op.add_column('chat_messages', sa.Column('rag_used', sa.Boolean(), nullable=True))
    op.add_column('chat_messages', sa.Column('retrieved_chunks', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_chat_messages_role_created', 'chat_messages', ['role', 'created_at'])
    op.create_table(
        'admin_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('username', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('token_hash', name='uq_admin_sessions_token_hash'),
    )
    op.create_index('ix_admin_sessions_expires_at', 'admin_sessions', ['expires_at'])
    op.create_index('ix_admin_sessions_validity', 'admin_sessions', ['token_hash', 'expires_at', 'revoked_at'])

def downgrade():
    op.drop_index('ix_admin_sessions_validity', table_name='admin_sessions')
    op.drop_index('ix_admin_sessions_expires_at', table_name='admin_sessions')
    op.drop_table('admin_sessions')
    op.drop_index('ix_chat_messages_role_created', table_name='chat_messages')
    op.drop_column('chat_messages', 'retrieved_chunks')
    op.drop_column('chat_messages', 'rag_used')
    op.drop_index('ix_chat_sessions_user_created', table_name='chat_sessions')
    op.drop_column('chat_sessions', 'user_name')
    op.drop_column('chat_sessions', 'user_email')
