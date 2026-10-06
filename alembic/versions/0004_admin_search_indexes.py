"""Add trigram indexes for admin substring searches."""
from alembic import op

revision = '0004_admin_search_indexes'
down_revision = '0003_admin_observability'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    op.execute('CREATE INDEX ix_chat_messages_content_trgm ON chat_messages USING gin (content gin_trgm_ops)')
    op.execute('CREATE INDEX ix_chat_sessions_user_email_trgm ON chat_sessions USING gin (user_email gin_trgm_ops)')
    op.execute('CREATE INDEX ix_chat_sessions_user_name_trgm ON chat_sessions USING gin (user_name gin_trgm_ops)')
    op.execute('CREATE INDEX ix_chat_sessions_user_id_trgm ON chat_sessions USING gin (user_id gin_trgm_ops)')

def downgrade():
    op.drop_index('ix_chat_sessions_user_id_trgm', table_name='chat_sessions')
    op.drop_index('ix_chat_sessions_user_name_trgm', table_name='chat_sessions')
    op.drop_index('ix_chat_sessions_user_email_trgm', table_name='chat_sessions')
    op.drop_index('ix_chat_messages_content_trgm', table_name='chat_messages')
    # pg_trgm is shared and is intentionally not removed.
