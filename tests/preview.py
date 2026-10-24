"""The preview's window, recording its messages without opening a display."""

import json
import queue
import struct
import threading
import time
from types import TracebackType
from typing import Self

from manimgx import _engine
from manimgx.rendering.film import Cut

START, NOTE, END = 14, 9, 12


class Viewer:
    """A window as `manimgx preview` uses one: what it is sent, read as messages (op, fields);
    a scene its viewer asks for; its viewer closing it."""

    def __init__(self, title: str, *, time: float = 0.0) -> None:
        self.buffer = b""
        self.seen: list[tuple[int, bytes]] = []
        self.wants: queue.Queue[str] = queue.Queue()
        self.closed = threading.Event()
        self.failure: str | None = None
        self.lock = threading.Lock()

    def __call__(self, data: bytes) -> None:
        if self.closed.is_set():
            raise Cut
        with self.lock:
            self.buffer += data
            while len(self.buffer) >= 4:
                (n,) = struct.unpack_from("<I", self.buffer)
                if len(self.buffer) < 4 + n:
                    break
                self.seen.append((self.buffer[4], self.buffer[5 : 4 + n]))
                self.buffer = self.buffer[4 + n :]

    def scenes(self, names: list[str], playing: str) -> None:
        self(_engine.note(json.dumps({"scenes": names, "scene": playing})))

    def failed(self, error: BaseException, trace: str, line: int | None = None) -> None:
        fault = {"type": type(error).__name__, "trace": trace, "line": line}
        self(_engine.note(json.dumps({"error": fault})))

    @property
    def open(self) -> bool:
        return not self.closed.is_set()

    def asked(self) -> str | None:
        return None if self.wants.empty() else self.wants.get()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.closed.set()

    def notes(self) -> list[dict[str, object]]:
        with self.lock:
            return [json.loads(fields[4:]) for op, fields in self.seen if op == NOTE]

    def until(
        self, wanted: str, count: int = 1, timeout: float = 60.0
    ) -> dict[str, object]:
        """Wait until the `count`th note with key `wanted`; return it."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = [n for n in self.notes() if wanted in n]
            if len(found) >= count:
                return found[count - 1]
            time.sleep(0.01)
        raise TimeoutError(f"no {wanted!r} note #{count}")

    def ended(self, count: int = 1, timeout: float = 60.0) -> None:
        """Wait until the `count`th take ends (its END message)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if sum(op == END for op, _ in self.seen) >= count:
                    return
            time.sleep(0.01)
        raise TimeoutError(f"take #{count} never ended")

    def starts(self) -> int:
        with self.lock:
            return sum(op == START for op, _ in self.seen)
