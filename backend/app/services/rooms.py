import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError
from ..events import publish
from ..models import Message, Room, User
from ..repositories import RoomRepository
from ..schemas import MessageView, PlaybackCommand, PlaybackView, PlayerCommand, RoomSnapshot, RoomView, UserView

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
MAX_POSITION = 172800


def extract_video_id(url: str) -> str:
    invalid = AppError(422, "invalid_video", "Вставьте ссылку на видео YouTube.")
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.port:
            raise invalid
        segments = parts.path.strip("/").split("/")
        video_id = ""
        if parts.hostname == "youtu.be" and len(segments) == 1:
            video_id = segments[0]
        elif parts.hostname in YOUTUBE_HOSTS:
            if segments == ["watch"]:
                video_id = parse_qs(parts.query).get("v", [""])[0]
            elif len(segments) == 2 and segments[0] in {"shorts", "embed", "live"}:
                video_id = segments[1]
        elif parts.hostname in {"www.youtube-nocookie.com", "youtube-nocookie.com"}:
            if len(segments) == 2 and segments[0] == "embed":
                video_id = segments[1]
    except ValueError as exc:
        raise invalid from exc
    if not VIDEO_ID.fullmatch(video_id):
        raise invalid
    return video_id


def room_view(room: Room) -> RoomView:
    return RoomView(id=room.id, name=room.name, owner_id=room.owner_id, playback=PlaybackView.model_validate(room))


def message_view(message: Message, user: User) -> MessageView:
    return MessageView(id=message.id, text=message.text, created_at=message.created_at,
                       user=UserView.model_validate(user))


class RoomService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = RoomRepository(db)

    async def list_for(self, user: User) -> list[RoomView]:
        return [room_view(room) for room in await self.repo.list_for(user.id, datetime.now(UTC))]

    async def create(self, name: str, user: User, owner_timeout: int) -> RoomView:
        now = datetime.now(UTC)
        room = Room(id=uuid4(), name=name, owner_id=user.id, created_at=now, video_id=None,
                    position=0, playing=False, rate=1, updated_at=now, revision=0,
                    owner_deadline_at=now + timedelta(seconds=owner_timeout))
        self.repo.add_room(room)
        await self.db.flush()
        self.repo.add_member(room.id, user.id)
        return room_view(room)

    async def get_room(self, room_id: UUID) -> Room:
        room = await self.repo.lock(room_id)
        if room is None or (room.owner_deadline_at and room.owner_deadline_at <= datetime.now(UTC)):
            raise AppError(404, "room_missing", "Комната закрыта или не найдена.")
        return room

    def mark_owner_present(self, room: Room, user: User, timeout: int) -> None:
        if user.id == room.owner_id:
            room.owner_deadline_at = datetime.now(UTC) + timedelta(seconds=timeout)

    async def delete(self, room_id: UUID, user: User) -> None:
        await self.remove(await self.require_owner(room_id, user))

    async def remove(self, room: Room) -> None:
        await self.repo.delete(room)
        await publish(self.db, str(room.id), {"type": "room_closed"})

    async def remove_expired(self) -> None:
        for room in await self.repo.expired(datetime.now(UTC)):
            await self.remove(room)

    async def require_member(self, room_id: UUID, user: User) -> Room:
        room = await self.get_room(room_id)
        membership = await self.repo.membership(room.id, user.id)
        if membership is None:
            raise AppError(403, "join_required", "Присоединитесь к комнате по приглашению.")
        if membership.removed:
            raise AppError(403, "room_removed", "Организатор исключил вас из комнаты.")
        return room

    async def require_owner(self, room_id: UUID, user: User) -> Room:
        room = await self.require_member(room_id, user)
        if room.owner_id != user.id:
            raise AppError(403, "owner_required", "Это действие доступно организатору.")
        return room

    async def join(self, room_id: UUID, user: User) -> RoomView:
        room = await self.get_room(room_id)
        membership = await self.repo.membership(room.id, user.id)
        if membership is not None and membership.removed:
            raise AppError(403, "room_removed", "Организатор исключил вас из комнаты.")
        if membership is None:
            self.repo.add_member(room.id, user.id)
            await publish(self.db, str(room.id), {
                "type": "member_joined", "user": UserView.model_validate(user).model_dump()
            })
        return room_view(room)

    async def snapshot(self, room_id: UUID, user: User, owner_timeout: int) -> RoomSnapshot:
        room = await self.require_member(room_id, user)
        self.mark_owner_present(room, user, owner_timeout)
        members = await self.repo.members(room.id)
        history = await self.repo.history(room.id)
        return RoomSnapshot(room=room_view(room), members=members,
                            messages=[message_view(message, author) for message, author in history],
                            server_time=datetime.now(UTC))

    async def set_video(self, room_id: UUID, user: User, url: str) -> PlaybackView:
        room = await self.require_owner(room_id, user)
        room.video_id = extract_video_id(url)
        room.rate = 1
        return await self.save_playback(room, 0, False)

    async def kick(self, room_id: UUID, owner: User, target_id: int) -> None:
        room = await self.require_owner(room_id, owner)
        if target_id == owner.id:
            raise AppError(422, "cannot_remove_owner", "Организатора нельзя исключить из комнаты.")
        membership = await self.repo.membership(room.id, target_id)
        if not membership or membership.removed:
            raise AppError(404, "member_missing", "Участник не найден.")
        membership.removed = True
        await publish(self.db, str(room.id), {"type": "member_removed", "user_id": target_id})

    async def chat(self, room: Room, user: User, text: str) -> None:
        message = Message(room_id=room.id, user_id=user.id, text=text, created_at=datetime.now(UTC))
        self.repo.add_message(message)
        await self.db.flush()
        await publish(self.db, str(room.id), {
            "type": "chat", "message": message_view(message, user).model_dump(mode="json")
        })

    async def player_update(self, room: Room, command: PlayerCommand) -> tuple[PlaybackView, bool]:
        if not room.video_id or command.revision != room.revision:
            return PlaybackView.model_validate(room), False
        room.rate = command.rate
        return await self.save_playback(room, command.position, command.playing), True

    async def playback(self, room: Room, command: PlaybackCommand) -> PlaybackView | None:
        if not room.video_id:
            raise AppError(422, "video_missing", "Сначала добавьте видео.")
        if command.revision != room.revision:
            return PlaybackView.model_validate(room)
        elapsed = (datetime.now(UTC) - room.updated_at).total_seconds() if room.playing else 0
        position = min(MAX_POSITION, room.position + max(0, elapsed) * room.rate)
        match command.action:
            case "play":
                await self.save_playback(room, command.position if command.position is not None else position, True)
            case "pause":
                await self.save_playback(room, position, False)
            case "seek" | "end":
                if command.position is None:
                    raise AppError(422, "position_missing", "Укажите позицию в видео.")
                if command.action == "seek" or room.playing:
                    await self.save_playback(room, command.position, room.playing and command.action == "seek")
        return None

    async def save_playback(self, room: Room, position: float, playing: bool) -> PlaybackView:
        room.position = position
        room.playing = playing
        room.updated_at = datetime.now(UTC)
        room.revision += 1
        view = PlaybackView.model_validate(room)
        await publish(self.db, str(room.id), {"type": "playback", "playback": view.model_dump(mode="json")})
        return view
