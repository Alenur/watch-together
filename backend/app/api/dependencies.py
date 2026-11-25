from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import AppError
from ..models import User
from ..services.auth import COOKIE_NAME, AuthService, token_from_cookie


async def database(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as db:
        yield db


Database = Annotated[AsyncSession, Depends(database)]


async def current_user(request: Request, db: Database) -> User:
    return await AuthService(db).current_user(token_from_cookie(request.cookies.get(COOKIE_NAME)))


CurrentUser = Annotated[User, Depends(current_user)]


async def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in request.app.state.settings.origins:
        raise AppError(403, "origin_denied", "Источник запроса не разрешён.")
