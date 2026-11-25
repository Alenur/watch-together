from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator

Username = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True,
                                           pattern=r"^[A-Za-z0-9_]{3,24}$")]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
Position = Annotated[float, Field(ge=0, le=172800, allow_inf_nan=False)]
PlaybackRate = Annotated[float, Field(ge=0.25, le=4, allow_inf_nan=False)]


class Credentials(BaseModel):
    username: Username
    password: Password


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class RoomCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]

    @field_validator("name")
    @classmethod
    def reject_null(cls, name: str) -> str:
        if "\0" in name:
            raise ValueError("Недопустимый символ")
        return name


class VideoChange(BaseModel):
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]


class PlaybackView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    video_id: str | None
    position: float
    playing: bool
    rate: float
    updated_at: datetime
    revision: int


class RoomView(BaseModel):
    id: UUID
    name: str
    owner_id: int
    playback: PlaybackView


class MessageView(BaseModel):
    id: int
    user: UserView
    text: str
    created_at: datetime


class RoomSnapshot(BaseModel):
    room: RoomView
    members: list[UserView]
    messages: list[MessageView]
    server_time: datetime


class ChatCommand(BaseModel):
    type: Literal["chat"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]

    @field_validator("text")
    @classmethod
    def reject_null(cls, text: str) -> str:
        if "\0" in text:
            raise ValueError("Недопустимый символ")
        return text


class PlaybackCommand(BaseModel):
    type: Literal["playback"]
    action: Literal["play", "pause", "seek", "end"]
    revision: Annotated[int, Field(ge=0)]
    position: Position | None = None


class PingCommand(BaseModel):
    type: Literal["ping"]
    sent_at: Annotated[int, Field(ge=0)]


class PlayerCommand(BaseModel):
    type: Literal["player"]
    request_id: Annotated[int, Field(gt=0)]
    revision: Annotated[int, Field(ge=0)]
    position: Position
    playing: bool
    rate: PlaybackRate


socket_command = TypeAdapter(Annotated[
    ChatCommand | PlaybackCommand | PlayerCommand | PingCommand, Field(discriminator="type")
])
