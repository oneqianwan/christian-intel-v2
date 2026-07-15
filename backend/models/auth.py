import uuid

from datetime import datetime
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import relationship

from models.database import Base


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
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    public_id = Column(String, nullable=False, default=lambda: str(uuid.uuid4()))
    email = Column(String(320), nullable=False)
    email_normalized = Column(String(320), nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String(120), nullable=False, default="User")
    role = Column(String(20), nullable=False, default="viewer")
    status = Column(String(20), nullable=False, default="active")

    email_verified_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    auth_sessions = relationship("AuthSession", back_populates="user")
    account_tokens = relationship("AccountToken", back_populates="user", foreign_keys="AccountToken.user_id")


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
