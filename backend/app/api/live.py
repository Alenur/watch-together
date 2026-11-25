import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..errors import AppError
from ..events import Subscription
from ..schemas import ChatCommand, PingCommand, PlayerCommand, socket_command
from ..services.auth import COOKIE_NAME, AuthService, token_from_cookie
from ..services.rooms import RoomService

router = APIRouter()


def close_code(error: AppError) -> int:
    return 4000 + error.status


async def connection_reader(ws: WebSocket, room_id: UUID, token_hash: str, sub: Subscription) -> int:
    owner_timeout = ws.app.state.settings.room_owner_timeout
    while sub.active:
        try:
            frame = await asyncio.wait_for(ws.receive(), timeout=90)
        except TimeoutError:
            return 1012
        if frame["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(frame["code"])
        if frame.get("text") is None:
            return 1003
        try:
            command = socket_command.validate_json(frame["text"])
        except ValidationError:
            sub.put({"type": "error", "detail": "Некорректная команда или сообщение длиннее 500 символов."})
            continue
        try:
            reply = None
            async with ws.app.state.sessions.begin() as db:
                user = await AuthService(db).current_user(token_hash)
                service = RoomService(db)
                room = await service.require_member(room_id, user)
                service.mark_owner_present(room, user, owner_timeout)
                if isinstance(command, ChatCommand):
                    await service.chat(room, user, command.text)
                elif isinstance(command, PingCommand):
                    reply = {"type": "pong", "sent_at": command.sent_at,
                             "server_time": datetime.now(UTC).isoformat()}
                elif isinstance(command, PlayerCommand):
                    state, accepted = await service.player_update(room, command)
                    reply = {"type": "player_ack", "request_id": command.request_id, "accepted": accepted,
                             "playback": state.model_dump(mode="json")}
                else:
                    latest = await service.playback(room, command)
                    if latest is not None:
                        reply = {"type": "playback", "playback": latest.model_dump(mode="json")}
            if reply is not None:
                sub.put(reply)
        except AppError as error:
            if error.status in {401, 403, 404}:
                return close_code(error)
            sub.put({"type": "error", "detail": error.detail})
    return 1012


async def connection_writer(ws: WebSocket, user_id: int, sub: Subscription) -> int:
    while True:
        event = await sub.queue.get()
        if event is None:
            return 1012
        if event["type"] == "session_ended":
            return 4401
        if event["type"] == "room_closed":
            return 4410
        if event["type"] == "member_removed" and event["user_id"] == user_id:
            return 4403
        try:
            await asyncio.wait_for(ws.send_json(event), timeout=8)
        except TimeoutError:
            return 1012


@router.websocket("/ws/rooms/{room_id}")
async def live(ws: WebSocket, room_id: UUID) -> None:
    if ws.headers.get("origin") not in ws.app.state.settings.origins:
        await ws.close(code=1008)
        return
    await ws.accept()
    token_hash = token_from_cookie(ws.cookies.get(COOKIE_NAME))
    listener = ws.app.state.listener
    if not listener.ready.is_set():
        await ws.close(code=1012)
        return
    if token_hash is None:
        await ws.close(code=4401)
        return

    topics = (str(room_id), f"session:{token_hash}")
    sub = listener.subscribe(*topics)
    tasks = []
    code = 1011
    try:
        async with ws.app.state.sessions.begin() as db:
            user = await AuthService(db).current_user(token_hash)
            snapshot = await RoomService(db).snapshot(room_id, user, ws.app.state.settings.room_owner_timeout)
        if sub.active:
            await asyncio.wait_for(ws.send_json({"type": "snapshot", **snapshot.model_dump(mode="json")}), timeout=8)
            tasks = [asyncio.create_task(connection_reader(ws, room_id, token_hash, sub)),
                     asyncio.create_task(connection_writer(ws, user.id, sub))]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            code = next(iter(done)).result()
        else:
            code = 1012
    except AppError as error:
        code = close_code(error)
    except TimeoutError:
        code = 1012
    except (WebSocketDisconnect, OSError):
        return
    finally:
        listener.unsubscribe(sub, *topics)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(WebSocketDisconnect, RuntimeError, OSError):
            await ws.close(code=code)
