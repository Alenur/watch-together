from dataclasses import dataclass
from os import environ


@dataclass(frozen=True)
class Settings:
    database_url: str
    origins: frozenset[str]
    cookie_secure: bool
    session_seconds: int
    room_owner_timeout: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=environ["DATABASE_URL"],
            origins=frozenset(
                origin.strip().rstrip("/")
                for origin in environ["APP_ORIGINS"].split(",")
                if origin.strip()
            ),
            cookie_secure=environ.get("COOKIE_SECURE", "false").lower() == "true",
            session_seconds=int(environ.get("SESSION_SECONDS", "604800")),
            room_owner_timeout=int(environ.get("ROOM_OWNER_TIMEOUT", "120")),
        )
