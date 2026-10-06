"""Create chat sessions and messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None
def upgrade():
    op.create_table('chat_sessions', sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True), sa.Column('user_id', sa.String(), nullable=True), sa.Column('title', sa.Text(), nullable=True), sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_chat_sessions_user_id','chat_sessions',['user_id']); op.create_index('ix_chat_sessions_created_at','chat_sessions',['created_at'])
    op.create_table('chat_messages', sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True), sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False), sa.Column('role', sa.String(16), nullable=False), sa.Column('content', sa.Text(), nullable=False), sa.Column('model', sa.Text(), nullable=True), sa.Column('response_time_ms', sa.Integer(), nullable=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_chat_messages_session_id','chat_messages',['session_id']); op.create_index('ix_chat_messages_created_at','chat_messages',['created_at']); op.create_index('ix_chat_messages_session_created','chat_messages',['session_id','created_at'])
def downgrade():
    op.drop_table('chat_messages'); op.drop_table('chat_sessions')
