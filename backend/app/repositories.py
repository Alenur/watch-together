from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LoginSession, Membership, Message, Room, User


class AuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_username(self, username: str) -> User | None:
        return await self.db.scalar(select(User).where(User.username == username))

    async def user_for_session(self, token_hash: str, now: datetime) -> User | None:
        return await self.db.scalar(
            select(User).join(LoginSession).where(
                LoginSession.token_hash == token_hash, LoginSession.expires_at > now
            )
        )

    def add_user(self, user: User) -> None:
        self.db.add(user)

    def add_session(self, session: LoginSession) -> None:
        self.db.add(session)

    async def revoke_session(self, token_hash: str) -> None:
        await self.db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash))

    async def clean_expired(self, now: datetime) -> None:
        await self.db.execute(delete(LoginSession).where(LoginSession.expires_at <= now))


class RoomRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for(self, user_id: int, now: datetime) -> list[Room]:
        rooms = await self.db.scalars(
            select(Room).join(Membership).where(
                Membership.user_id == user_id, Membership.removed.is_(False),
                or_(Room.owner_deadline_at.is_(None), Room.owner_deadline_at > now),
            ).order_by(Room.created_at.desc())
        )
        return list(rooms)

    async def expired(self, now: datetime) -> list[Room]:
        rooms = await self.db.scalars(
            select(Room).where(Room.owner_deadline_at <= now).order_by(Room.owner_deadline_at)
            .limit(100).with_for_update(skip_locked=True)
        )
        return list(rooms)

    async def delete(self, room: Room) -> None:
        await self.db.delete(room)

    async def lock(self, room_id: UUID) -> Room | None:
        return await self.db.scalar(select(Room).where(Room.id == room_id).with_for_update())

    async def membership(self, room_id: UUID, user_id: int) -> Membership | None:
        return await self.db.get(Membership, (room_id, user_id))

    async def members(self, room_id: UUID) -> list[User]:
        users = await self.db.scalars(
            select(User).join(Membership).where(
                Membership.room_id == room_id, Membership.removed.is_(False)
            ).order_by(User.username)
        )
        return list(users)

    async def history(self, room_id: UUID) -> list[tuple[Message, User]]:
        rows = await self.db.execute(
            select(Message, User).join(User).where(Message.room_id == room_id)
            .order_by(Message.id.desc()).limit(100)
        )
        return [(message, user) for message, user in reversed(rows.all())]

    def add_room(self, room: Room) -> None:
        self.db.add(room)

    def add_member(self, room_id: UUID, user_id: int) -> None:
        self.db.add(Membership(room_id=room_id, user_id=user_id, removed=False))

    def add_message(self, message: Message) -> None:
        self.db.add(message)
