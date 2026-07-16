import uuid

from datetime import datetime
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import relationship

from models.database import Base


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_PUBLIC_ID = "00000000-0000-0000-0000-0000000000a1"


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled', 'archived')", name="ck_tenants_status"),
        UniqueConstraint("public_id", name="ux_tenants_public_id"),
        UniqueConstraint("slug", name="ux_tenants_slug"),
        Index("ix_tenants_slug", "slug"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    public_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    slug = Column(String(120), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    memberships = relationship("TenantMembership", back_populates="tenant", foreign_keys="TenantMembership.tenant_id")


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('tenant_admin', 'analyst', 'viewer')",
            name="ck_tenant_memberships_role",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'pending')",
            name="ck_tenant_memberships_status",
        ),
        UniqueConstraint("public_id", name="ux_tenant_memberships_public_id"),
        Index("ix_tenant_memberships_tenant_id", "tenant_id"),
        Index("ix_tenant_memberships_user_id", "user_id"),
        Index("ix_tenant_memberships_created_by_user_id", "created_by_user_id"),
        Index(
            "ux_tenant_memberships_tenant_user_active",
            "tenant_id",
            "user_id",
            unique=True,
            sqlite_where=text("deleted_at IS NULL AND status = 'active'"),
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    public_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(32), nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="memberships", foreign_keys=[tenant_id])
    user = relationship("User", back_populates="tenant_memberships", foreign_keys=[user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('super_admin', 'admin', 'analyst', 'viewer')", name="ck_users_role"),
        CheckConstraint("status IN ('active', 'disabled', 'pending')", name="ck_users_status"),
        CheckConstraint("email = trim(email)", name="ck_users_email_trimmed"),
        CheckConstraint("email_normalized = lower(trim(email_normalized))", name="ck_users_email_normalized"),
        UniqueConstraint("public_id", name="ux_users_public_id"),
        UniqueConstraint("email_normalized", name="ux_users_email_normalized"),
        Index("ix_users_email_normalized", "email_normalized"),
        Index("ix_users_default_tenant_id", "default_tenant_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    public_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    email = Column(String(320), nullable=False)
    email_normalized = Column(String(320), nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String(120), nullable=False, default="User")
    role = Column(String(20), nullable=False, default="viewer")
    status = Column(String(20), nullable=False, default="active")
    default_tenant_id = Column(
        String,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_TENANT_ID,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
    )

    email_verified_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    default_tenant = relationship("Tenant", foreign_keys=[default_tenant_id])
    auth_sessions = relationship("AuthSession", back_populates="user")
    account_tokens = relationship("AccountToken", back_populates="user", foreign_keys="AccountToken.user_id")
    tenant_memberships = relationship("TenantMembership", back_populates="user", foreign_keys="TenantMembership.user_id")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="ck_auth_sessions_status"),
        UniqueConstraint("public_id", name="ux_auth_sessions_public_id"),
        UniqueConstraint("token_hash", name="ux_auth_sessions_token_hash"),
        Index("ix_auth_sessions_user_id", "user_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    public_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    token_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="active")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="auth_sessions")


class AccountToken(Base):
    __tablename__ = "account_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('setup_password', 'password_reset')",
            name="ck_account_tokens_purpose",
        ),
        CheckConstraint(
            "status IN ('active', 'used', 'revoked', 'expired')",
            name="ck_account_tokens_status",
        ),
        UniqueConstraint("public_id", name="ux_account_tokens_public_id"),
        UniqueConstraint("token_hash", name="ux_account_tokens_token_hash"),
        Index("ix_account_tokens_user_id", "user_id"),
        Index("ix_account_tokens_purpose", "purpose"),
        Index("ix_account_tokens_expires_at", "expires_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    public_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    token_hash = Column(String(64), nullable=False)
    purpose = Column(String(32), nullable=False)
    status = Column(String(20), nullable=False, default="active")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="account_tokens", foreign_keys=[user_id])
