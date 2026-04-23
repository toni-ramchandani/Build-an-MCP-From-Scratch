"""Small transport abstraction used by the Chapter 3 examples.

This module is intentionally narrow. It demonstrates how the rest of a client or
host harness can stay transport-agnostic while swapping between stdio and a
minimal JSON-response HTTP adapter. It is not part of the official MCP Python
SDK and it does not implement custom transports such as WebSocket or message
queues.
"""

from __future__ import annotations

import abc
import json
import queue
import subprocess
import sys
import threading
import urllib.request
from typing import Any


class Transport(abc.ABC):
    """Minimal transport interface used in the Chapter 3 examples."""

    @abc.abstractmethod
    def send(self, msg: dict[str, Any]) -> None:
        ...

    @abc.abstractmethod
    def recv(self, timeout: float | None = None) -> dict[str, Any]:
        ...

    @abc.abstractmethod
    def close(self) -> None:
        ...


class StdioTransport(Transport):
    """Exchange newline-delimited JSON-RPC messages with a child process."""

    def __init__(
        self,
        cmd: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._q: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        try:
            for line in self.proc.stdout:
                self._q.put(line.rstrip("\n"))
        finally:
            self._q.put(None)

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()

    def send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float | None = None) -> dict[str, Any]:
        while True:
            try:
                raw = self._q.get(timeout=timeout)
            except queue.Empty as e:
                raise TimeoutError("timed out waiting for stdio message") from e

            if raw is None:
                raise EOFError("stdio transport closed")

            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                print(
                    f"transport warning: ignoring malformed stdout line {raw!r} ({e})",
                    file=sys.stderr,
                )
                continue

            if isinstance(obj, dict):
                return obj

            print(
                f"transport warning: ignoring non-object stdout message {raw!r}",
                file=sys.stderr,
            )

    def close(self) -> None:
        self._close_stream(self.proc.stdin)
        try:
            self.proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        finally:
            self._close_stream(self.proc.stdout, warn=True)
            self._close_stream(self.proc.stderr, warn=True)

    @staticmethod
    def _close_stream(stream, warn: bool = False) -> None:
        if stream is None or stream.closed:
            return
        try:
            stream.close()
        except OSError as exc:
            if warn:
                print(f"transport shutdown warning: {exc}", file=sys.stderr)


class HttpTransport(Transport):
    """Minimal JSON-response HTTP adapter.

    This teaching stub handles only the JSON-response branch of Streamable HTTP.
    If the server responds with text/event-stream, recv() raises
    NotImplementedError so the limitation stays explicit on the page.
    """

    def __init__(self, url: str):
        self.url = url
        self._resp = None

    def send(self, msg: dict[str, Any]) -> None:
        if self._resp is not None:
            self._resp.close()
            self._resp = None

        data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            method="POST",
        )
        self._resp = urllib.request.urlopen(req)

    def recv(self, timeout: float | None = None) -> dict[str, Any]:
        del timeout  # Unused in this minimal synchronous example.
        assert self._resp is not None

        resp = self._resp
        self._resp = None
        with resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8")

        if content_type.startswith("text/event-stream"):
            raise NotImplementedError(
                "This teaching stub handles only the JSON-response branch."
            )

        obj = json.loads(body)
        if not isinstance(obj, dict):
            raise ValueError("expected one JSON-RPC object in the HTTP response body")
        return obj

    def close(self) -> None:
        if self._resp is not None:
            self._resp.close()
            self._resp = None
