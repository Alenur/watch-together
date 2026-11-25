from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from ..schemas import PlaybackView, RoomCreate, RoomView, VideoChange
from ..services.rooms import RoomService
from .dependencies import CurrentUser, Database, check_origin

router = APIRouter(prefix="/api/rooms", tags=["Комнаты"])
same_origin = [Depends(check_origin)]


@router.get("")
async def rooms(user: CurrentUser, db: Database) -> list[RoomView]:
    return await RoomService(db).list_for(user)


@router.post("", status_code=201, dependencies=same_origin)
async def create(data: RoomCreate, request: Request, user: CurrentUser, db: Database) -> RoomView:
    room = await RoomService(db).create(data.name, user, request.app.state.settings.room_owner_timeout)
    await db.commit()
    return room


@router.delete("/{room_id}", status_code=204, dependencies=same_origin)
async def close(room_id: UUID, user: CurrentUser, db: Database) -> Response:
    await RoomService(db).delete(room_id, user)
    await db.commit()
    return Response(status_code=204)


@router.post("/{room_id}/join", dependencies=same_origin)
async def join(room_id: UUID, user: CurrentUser, db: Database) -> RoomView:
    room = await RoomService(db).join(room_id, user)
    await db.commit()
    return room


@router.put("/{room_id}/video", dependencies=same_origin)
async def video(room_id: UUID, data: VideoChange, user: CurrentUser, db: Database) -> PlaybackView:
    playback = await RoomService(db).set_video(room_id, user, data.url)
    await db.commit()
    return playback


@router.delete("/{room_id}/members/{user_id}", status_code=204, dependencies=same_origin)
async def kick(room_id: UUID, user_id: int, user: CurrentUser, db: Database) -> Response:
    await RoomService(db).kick(room_id, user, user_id)
    await db.commit()
    return Response(status_code=204)
