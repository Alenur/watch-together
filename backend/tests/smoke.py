"""Verify the running Compose project through its Nginx HTTP and WebSocket proxy."""

import json
import os
from contextlib import closing
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

BASE = os.getenv("SMOKE_URL", "http://frontend:8080")
ORIGIN = os.getenv("SMOKE_ORIGIN", "http://localhost:8080")
PASSWORD = "smoke-test-password"
YOUTUBE_ID = "M7lc1UVf-VE"


class Client:
    def __init__(self):
        self.cookie = None

    def request(self, path, expected=200, method="GET", data=None, origin=ORIGIN):
        headers = {"Origin": origin}
        if self.cookie:
            headers["Cookie"] = self.cookie
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        request = Request(f"{BASE}{path}", data=body, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=8)
        except HTTPError as error:
            response = error
        with closing(response):
            assert response.code == expected, (method, path, expected, response.code, response.read())
            if cookie := response.headers.get("Set-Cookie"):
                self.cookie = cookie.partition(";")[0]
            content = response.read()
            if content and response.headers.get_content_type() == "application/json":
                return json.loads(content)
            return content

    def socket(self, room_id):
        base = BASE.replace("http", "ws", 1)
        return connect(f"{base}/ws/rooms/{room_id}", origin=ORIGIN,
                       additional_headers={"Cookie": self.cookie}, open_timeout=8)


def receive(socket, kind):
    deadline = monotonic() + 8
    while (remaining := deadline - monotonic()) > 0:
        event = json.loads(socket.recv(timeout=remaining))
        if event["type"] == kind:
            return event
    raise AssertionError(f"Missing event {kind}")


def send(socket, **event):
    socket.send(json.dumps(event))


def expect_close(socket, code):
    try:
        socket.recv(timeout=8)
    except ConnectionClosed as error:
        assert error.rcvd and error.rcvd.code == code, error
    else:
        raise AssertionError(f"WebSocket should close with {code}")


def run():
    owner, guest, other = Client(), Client(), Client()
    assert owner.request("/api/health") == {"status": "ok"}
    owner.request("/api/rooms", 401)
    token = uuid4().hex[:10]
    host_credentials = {"username": f"host_{token}", "password": PASSWORD}
    guest_credentials = {"username": f"guest_{token}", "password": PASSWORD}
    owner.request("/api/auth/register", 403, "POST", host_credentials, origin="https://other.example")
    me = owner.request("/api/auth/register", 201, "POST", host_credentials)
    other.request("/api/auth/register", 409, "POST", host_credentials)
    other.request("/api/auth/login", 401, "POST", {**host_credentials, "password": "incorrect-password"})
    assert other.request("/api/auth/login", 200, "POST", host_credentials) == me
    other.request("/api/auth/logout", 204, "POST")
    other.request("/api/auth/me", 401)
    assert owner.request("/api/auth/me") == me

    room = owner.request("/api/rooms", 201, "POST", {"name": "Проверка совместного просмотра"})
    room_id = room["id"]
    base = f"/api/rooms/{room_id}"
    assert room["playback"]["video_id"] is None
    invite_page = guest.request(f"/room/{room_id}")
    assert b'id="root"' in invite_page and b'src="/assets/' in invite_page
    guest_user = guest.request("/api/auth/register", 201, "POST", guest_credentials)

    def verify_video(event, playing, revision):
        state = event["playback"]
        assert (state["video_id"], state["playing"], state["revision"]) == (YOUTUBE_ID, playing, revision)
        return state

    with guest.socket(room_id) as unjoined:
        expect_close(unjoined, 4403)
    with owner.socket(room_id) as host_socket:
        assert receive(host_socket, "snapshot")["members"] == [me]
        owner.request(f"{base}/video", 422, "PUT", {"url": f"https://example.com/watch?v={YOUTUBE_ID}"})
        owner.request(f"{base}/video", 200, "PUT", {"url": f"https://youtu.be/{YOUTUBE_ID}?si=sample"})
        verify_video(receive(host_socket, "playback"), False, 1)
        guest.request(f"{base}/join", 200, "POST")
        assert receive(host_socket, "member_joined")["user"] == guest_user
        guest.request(f"{base}/join", 200, "POST")
        with guest.socket(room_id) as guest_socket, guest.socket(room_id) as guest_tab:
            snapshot = receive(guest_socket, "snapshot")
            receive(guest_tab, "snapshot")
            verify_video(snapshot["room"], False, 1)
            assert {user["id"] for user in snapshot["members"]} == {me["id"], guest_user["id"]}

            send(guest_socket, type="playback", action="play", revision=1)
            verify_video(receive(host_socket, "playback"), True, 2)
            verify_video(receive(guest_socket, "playback"), True, 2)
            send(host_socket, type="playback", action="seek", position=37.5, revision=2)
            assert verify_video(receive(guest_socket, "playback"), True, 3)["position"] == 37.5
            verify_video(receive(host_socket, "playback"), True, 3)
            send(guest_socket, type="playback", action="pause", revision=2)
            verify_video(receive(guest_socket, "playback"), True, 3)
            send(guest_socket, type="playback", action="pause", revision=3)
            verify_video(receive(host_socket, "playback"), False, 4)
            verify_video(receive(guest_socket, "playback"), False, 4)

            text = "Написано из браузера гостя 🎬"
            send(guest_socket, type="chat", text=text)
            assert receive(host_socket, "chat")["message"]["text"] == text
            assert receive(guest_socket, "chat")["message"]["user"] == guest_user
            with guest.socket(room_id) as reopened:
                assert receive(reopened, "snapshot")["messages"][-1]["text"] == text

            guest.request(f"{base}/members/{me['id']}", 403, "DELETE")
            guest.request(f"{base}/video", 403, "PUT", {"url": f"https://youtu.be/{YOUTUBE_ID}"})
            owner.request(f"{base}/members/{me['id']}", 422, "DELETE")
            owner.request(f"{base}/members/{guest_user['id']}", 204, "DELETE")
            assert receive(host_socket, "member_removed")["user_id"] == guest_user["id"]
            receive(guest_tab, "chat")
            expect_close(guest_socket, 4403)
            expect_close(guest_tab, 4403)
            guest.request(f"{base}/join", 403, "POST")
            assert guest.request("/api/rooms") == []
            with guest.socket(room_id) as rejected:
                expect_close(rejected, 4403)
    print("PASS: auth, invitation, synchronized play/pause/seek, chat, permissions and removal")


if __name__ == "__main__":
    run()
