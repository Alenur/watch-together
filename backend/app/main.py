import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .api import auth, live, rooms
from .config import Settings
from .db import make_database
from .errors import AppError
from .events import EventListener
from .services.rooms import RoomService

logger = logging.getLogger(__name__)


async def remove_expired_rooms(sessions) -> None:
    while True:
        try:
            async with sessions.begin() as db:
                await RoomService(db).remove_expired()
        except SQLAlchemyError:
            logger.warning("Could not remove expired rooms. Retrying.", exc_info=True)
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    engine, sessions = make_database(settings.database_url)
    listener = EventListener(engine.url)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.listener = listener
    task = asyncio.create_task(listener.run())
    cleanup = asyncio.create_task(remove_expired_rooms(sessions))
    try:
        await asyncio.wait_for(listener.ready.wait(), timeout=12)
        yield
    finally:
        task.cancel()
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await task
        with suppress(asyncio.CancelledError):
            await cleanup
        await engine.dispose()


app = FastAPI(title="Вместе", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json",
              redoc_url=None, swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect")
app.include_router(auth.router)
app.include_router(rooms.router)
app.include_router(live.router)


@app.exception_handler(AppError)
async def application_error(_: Request, error: AppError) -> JSONResponse:
    return JSONResponse({"code": error.code, "detail": error.detail}, status_code=error.status)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    descriptions = {
        "username": "Имя должно содержать от 3 до 24 латинских букв, цифр или знаков подчёркивания.",
        "password": "Пароль должен содержать от 8 до 128 символов.",
        "name": "Введите название комнаты длиной от 2 до 80 символов.",
        "url": "Вставьте ссылку на видео YouTube.",
    }
    field = error.errors()[0]["loc"][-1] if error.errors()[0]["loc"] else None
    detail = descriptions.get(field, "Проверьте данные запроса.")
    return JSONResponse({"code": "invalid_request", "detail": detail}, status_code=422)


@app.get("/api/health", include_in_schema=False)
async def health(request: Request):
    try:
        async with request.app.state.sessions() as db:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=2)
        if request.app.state.listener.ready.is_set():
            return {"status": "ok"}
    except (SQLAlchemyError, TimeoutError):
        pass
    return JSONResponse({"status": "unavailable"}, status_code=503)
