"""In-process registry of live reply streams so "Stop generating" can reach them.

Per process only: with several web workers a stop request may land on a process that
isn't streaming; the client also aborts its fetch, and the disconnect ends the stream
there, so both paths converge on the same `cancelled` status."""

import threading

_active: dict[str, threading.Event] = {}
_lock = threading.Lock()


def register(message_id: str) -> threading.Event:
    event = threading.Event()
    with _lock:
        _active[message_id] = event
    return event


def unregister(message_id: str) -> None:
    with _lock:
        _active.pop(message_id, None)


def request_stop(message_id: str) -> bool:
    with _lock:
        event = _active.get(message_id)
    if event is None:
        return False
    event.set()
    return True
