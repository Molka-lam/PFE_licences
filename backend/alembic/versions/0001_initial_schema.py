"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('role', sa.String(20), nullable=False, server_default='client'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('email_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('email_verify_token', sa.String(255), nullable=True),
        sa.Column('email_verify_token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('password_reset_token', sa.String(255), nullable=True),
        sa.Column('password_reset_token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('email_opt_in', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('in_app_opt_in', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # 2. refresh_tokens
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # 3. plans
    op.create_table(
        'plans',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price_monthly', sa.Numeric(10, 2), nullable=True),
        sa.Column('features', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('limits', postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_plans_name', 'plans', ['name'], unique=True)

    # 4. applications (FK -> users)
    op.create_table(
        'applications',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('app_code', sa.String(100), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('environment', sa.String(20), nullable=False, server_default='development'),
        sa.Column('api_key_hash', sa.String(64), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_applications_app_code', 'applications', ['app_code'], unique=True)

    # 5. licenses (FK -> applications, plans, users)
    op.create_table(
        'licenses',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('plan_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('plans.id'), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='requested'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('custom_limits', postgresql.JSONB(), nullable=True),
        sa.Column('custom_features', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # 6. license_transitions (FK -> licenses, users)
    op.create_table(
        'license_transitions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('license_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('licenses.id'), nullable=False),
        sa.Column('from_status', sa.String(20), nullable=True),
        sa.Column('to_status', sa.String(20), nullable=False),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # 7. license_keys (FK -> licenses, users)
    op.create_table(
        'license_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('license_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('licenses.id'), nullable=False),
        sa.Column('public_key', sa.Text(), nullable=False),
        sa.Column('private_key_encrypted', sa.Text(), nullable=False),
        sa.Column('encryption_iv', sa.String(32), nullable=False),
        sa.Column('generated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('private_key_first_downloaded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('private_key_first_downloaded_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('license_id', name='uq_license_keys_license_id'),
    )

    # 8. notifications (FK -> users, licenses)
    op.create_table(
        'notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False, server_default='in_app'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('related_license_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('licenses.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # 9. usage_records (FK -> licenses)
    op.create_table(
        'usage_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('license_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('licenses.id'), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('api_calls_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('active_users_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('storage_used_mb', sa.Numeric(10, 2), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('license_id', 'year', 'month', name='uq_usage_license_year_month'),
    )

    # 10. audit_logs (FK -> users)
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=True),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # 11. webhooks (FK -> users)
    op.create_table(
        'webhooks',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('secret_hash', sa.String(64), nullable=False),
        sa.Column('events', postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # 12. webhook_deliveries (FK -> webhooks)
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('webhook_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('webhooks.id'), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('webhook_deliveries')
    op.drop_table('webhooks')
    op.drop_table('audit_logs')
    op.drop_table('usage_records')
    op.drop_table('notifications')
    op.drop_table('license_keys')
    op.drop_table('license_transitions')
    op.drop_table('licenses')
    op.drop_index('ix_applications_app_code', 'applications')
    op.drop_table('applications')
    op.drop_index('ix_plans_name', 'plans')
    op.drop_table('plans')
    op.drop_table('refresh_tokens')
    op.drop_index('ix_users_email', 'users')
    op.drop_table('users')
