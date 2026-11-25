from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe

from anyio import to_thread
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError, unauthenticated
from ..events import publish
from ..models import LoginSession, User
from ..repositories import AuthRepository
from ..schemas import Credentials

COOKIE_NAME = "watch_session"
hasher = PasswordHasher()
# Use the same verification work for a login with an unknown username.
dummy_hash = hasher.hash(token_urlsafe(32))


def hash_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def token_from_cookie(token: str | None) -> str | None:
    return hash_token(token) if token and len(token) == 43 else None


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuthRepository(db)

    async def register(self, credentials: Credentials) -> User:
        password_hash = await to_thread.run_sync(hasher.hash, credentials.password)
        user = User(username=credentials.username, password_hash=password_hash)
        self.repo.add_user(user)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise AppError(409, "username_taken", "Это имя пользователя уже занято.") from exc
        return user

    async def login(self, credentials: Credentials) -> User:
        user = await self.repo.by_username(credentials.username)
        try:
            await to_thread.run_sync(hasher.verify, user.password_hash if user else dummy_hash, credentials.password)
        except VerifyMismatchError as exc:
            raise AppError(401, "wrong_credentials", "Неверное имя пользователя или пароль.") from exc
        if user is None:
            raise AppError(401, "wrong_credentials", "Неверное имя пользователя или пароль.")
        if hasher.check_needs_rehash(user.password_hash):
            user.password_hash = await to_thread.run_sync(hasher.hash, credentials.password)
        return user

    async def start_session(self, user: User, lifetime: int) -> str:
        token = token_urlsafe(32)
        now = datetime.now(UTC)
        await self.repo.clean_expired(now)
        self.repo.add_session(
            LoginSession(token_hash=hash_token(token), user_id=user.id, expires_at=now + timedelta(seconds=lifetime))
        )
        return token

    async def current_user(self, token_hash: str | None) -> User:
        user = await self.repo.user_for_session(token_hash, datetime.now(UTC)) if token_hash else None
        if user is None:
            raise unauthenticated()
        return user

    async def end_session(self, token_hash: str | None) -> None:
        if token_hash:
            await self.repo.revoke_session(token_hash)
            await publish(self.db, f"session:{token_hash}", {"type": "session_ended"})
