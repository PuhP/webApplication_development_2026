from __future__ import annotations

import json
from collections import defaultdict
from queue import Empty, Queue
from threading import RLock
from typing import Any

from flask import current_app
from flask_login import current_user

from .models import QueueSession
from .queue_service import serialize_session

_clients: dict[int, set[Queue]] = defaultdict(set)
_lock = RLock()


def broadcast(session_id: int, payload: dict[str, Any]) -> None:
    with _lock:
        targets = list(_clients.get(session_id, set()))
    for client_queue in targets:
        client_queue.put(payload)


def broadcast_session_update(session_id: int) -> None:
    session = QueueSession.query.get(session_id)
    if session:
        broadcast(session_id, serialize_session(session))


def register_socket_routes(sock):
    @sock.route("/ws/session/<int:session_id>")
    def session_socket(ws, session_id: int):
        if not current_user.is_authenticated:
            ws.close()
            return

        client_queue: Queue = Queue()
        with _lock:
            _clients[session_id].add(client_queue)

        try:
            session = QueueSession.query.get(session_id)
            if session:
                ws.send(json.dumps(serialize_session(session), ensure_ascii=False, default=str))
            while True:
                try:
                    payload = client_queue.get(timeout=25)
                except Empty:
                    payload = {"type": "ping"}
                ws.send(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception as exc:
            current_app.logger.debug("WebSocket session %s closed: %s", session_id, exc)
        finally:
            with _lock:
                _clients[session_id].discard(client_queue)
