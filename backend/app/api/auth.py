from fastapi import APIRouter, Depends, Request, Response

from ..config import Settings
from ..schemas import Credentials, UserView
from ..services.auth import COOKIE_NAME, AuthService, token_from_cookie
from .dependencies import CurrentUser, Database, check_origin

router = APIRouter(prefix="/api/auth", tags=["Аккаунт"])
same_origin = [Depends(check_origin)]


def set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_seconds,
                        httponly=True, samesite="strict", secure=settings.cookie_secure)


@router.post("/register", status_code=201, dependencies=same_origin)
async def register(data: Credentials, request: Request, response: Response, db: Database) -> UserView:
    settings = request.app.state.settings
    service = AuthService(db)
    user = await service.register(data)
    await service.end_session(token_from_cookie(request.cookies.get(COOKIE_NAME)))
    token = await service.start_session(user, settings.session_seconds)
    await db.commit()
    set_cookie(response, token, settings)
    return UserView.model_validate(user)


@router.post("/login", dependencies=same_origin)
async def login(data: Credentials, request: Request, response: Response, db: Database) -> UserView:
    settings = request.app.state.settings
    service = AuthService(db)
    user = await service.login(data)
    await service.end_session(token_from_cookie(request.cookies.get(COOKIE_NAME)))
    token = await service.start_session(user, settings.session_seconds)
    await db.commit()
    set_cookie(response, token, settings)
    return UserView.model_validate(user)


@router.get("/me")
async def me(user: CurrentUser) -> UserView:
    return UserView.model_validate(user)


@router.post("/logout", status_code=204, dependencies=same_origin)
async def logout(request: Request, db: Database) -> Response:
    await AuthService(db).end_session(token_from_cookie(request.cookies.get(COOKIE_NAME)))
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="strict",
                           secure=request.app.state.settings.cookie_secure)
    return response
