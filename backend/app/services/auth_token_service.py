"""Database-backed refresh rotation, revocation, and password resets."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ValidationError
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    hash_password,
    hash_token,
    validate_password_strength,
    validate_refresh_token,
)
from app.models.auth_session import AuthSession, PasswordResetToken
from app.models.user import User


class AuthTokenService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    async def create_session(self, user: User, commit: bool = True) -> tuple[str, str]:
        claims = {"role": user.role.value, "email": user.email}
        refresh_token = create_refresh_token(subject=user.id, additional_claims=claims)
        payload = validate_refresh_token(refresh_token)
        session_id = payload["jti"]
        access_token = create_access_token(
            subject=user.id,
            additional_claims={**claims, "sid": session_id},
        )
        self.db.add(AuthSession(
            id=session_id,
            user_id=user.id,
            refresh_token_hash=hash_token(refresh_token),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        ))
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return access_token, refresh_token

    async def rotate(self, refresh_token: str, user: User) -> tuple[str, str]:
        payload = validate_refresh_token(refresh_token)
        session_id = payload.get("jti")
        if not session_id or payload.get("sub") != user.id:
            raise AuthenticationError(message="Invalid refresh token")

        result = await self.db.execute(
            select(AuthSession).where(AuthSession.id == session_id).with_for_update()
        )
        session = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if (
            not session
            or session.revoked_at is not None
            or self._as_utc(session.expires_at) <= now
            or session.refresh_token_hash != hash_token(refresh_token)
        ):
            await self.revoke_all(user.id, commit=True)
            raise AuthenticationError(message="Refresh token has expired or was already used")

        session.revoked_at = now
        access_token, new_refresh_token = await self.create_session(user, commit=False)
        new_payload = validate_refresh_token(new_refresh_token)
        session.replaced_by_id = new_payload["jti"]
        await self.db.commit()
        return access_token, new_refresh_token

    async def revoke_session(self, session_id: str, user_id: str, commit: bool = True) -> None:
        await self.db.execute(
            update(AuthSession)
            .where(
                AuthSession.id == session_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        if commit:
            await self.db.commit()

    async def revoke_all(self, user_id: str, commit: bool = True) -> None:
        await self.db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        if commit:
            await self.db.commit()

    async def is_session_active(self, session_id: str, user_id: str) -> bool:
        result = await self.db.execute(select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(timezone.utc),
        ))
        return result.scalar_one_or_none() is not None

    async def issue_password_reset(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
            .values(used_at=now)
        )
        raw_token = create_password_reset_token()
        self.db.add(PasswordResetToken(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=hash_token(raw_token),
            expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        ))
        await self.db.commit()
        return raw_token

    async def consume_password_reset(self, token: str, new_password: str) -> User:
        result = await self.db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == hash_token(token))
            .with_for_update()
        )
        reset = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if not reset or reset.used_at is not None or self._as_utc(reset.expires_at) <= now:
            raise AuthenticationError(message="Password reset link is invalid, expired, or already used")
        valid, message = validate_password_strength(new_password)
        if not valid:
            raise ValidationError(message=message)
        user = await self.db.get(User, reset.user_id)
        if not user or not user.is_active:
            raise AuthenticationError(message="Password reset link is invalid, expired, or already used")
        user.password_hash = hash_password(new_password)
        user.failed_login_attempts = 0
        user.locked_until = None
        reset.used_at = now
        await self.revoke_all(user.id, commit=False)
        await self.db.commit()
        return user
