# transport.py #3.4
from __future__ import annotations
import abc, json, queue, subprocess, sys, urllib.request            #A
from dataclasses import dataclass                                    #A

@dataclass
class Message:                                                        #B
    obj: dict

class Transport(abc.ABC):                                            #C
    @abc.abstractmethod
    def send(self, msg: Message) -> None: ...
    @abc.abstractmethod
    def recv(self, timeout: float | None = None) -> Message: ...
    @abc.abstractmethod
    def close(self) -> None: ...

class StdioTransport(Transport):                                     #D
    def __init__(self, cmd: list[str]):
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        self._q: "queue.Queue[str]" = queue.Queue()
        self._pump()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self._q.put(line.rstrip("\n"))

    def send(self, msg: Message) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg.obj, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float | None = None) -> Message:
        raw = self._q.get(timeout=timeout)
        return Message(json.loads(raw))

    def close(self) -> None:
        try:
            if self.proc.stdin: self.proc.stdin.close()
        finally:
            self.proc.wait(timeout=3.0)

class HttpTransport(Transport):                                      #E
    def __init__(self, url: str):
        self.url = url

    def send(self, msg: Message) -> None:
        data = json.dumps(msg.obj).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST")
        self._last = urllib.request.urlopen(req)                     #F

    def recv(self, timeout: float | None = None) -> Message:
        payload = self._last.read().decode("utf-8")
        return Message(json.loads(payload))

    def close(self) -> None:
        pass
