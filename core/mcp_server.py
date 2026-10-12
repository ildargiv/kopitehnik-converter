"""MCP server over stdio: lets AI agents use the converter through text tools (no screen, no mouse).

Run:  Converter.exe --mcp      (or: python app.py --mcp)

Protocol: JSON-RPC 2.0, one JSON message per line on stdin / stdout (the standard MCP stdio transport).
Written by hand, no external packages. Everything that is not a protocol message goes to stderr, because
a stray print on stdout would break the connection."""
from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from typing import Any, Callable

from .version import VERSION

SERVER_NAME = "kopitehnik-converter"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "КопиТехник Конвертор: конвертация фото и документов (JPG, PNG, TIFF, PDF), цвет и кадр, несколько фото на "
    "листе, правка PDF и печать. Все пути к файлам указывайте полностью. Начните с app_info: там форматы, "
    "раскладки листов, форматы бумаги и найденные принтеры. Результат работы проверяйте инструментами preview "
    "(картинка, размеры и яркость числами), pdf_get_text и inspect_file. Исходные файлы не меняются."
)


class ToolError(Exception):
    """A problem the agent can fix by changing the arguments; shown to it as the tool result."""


class Tool:
    def __init__(self, name: str, description: str, schema: dict, handler: Callable, read_only: bool = False):
        self.name, self.description, self.schema, self.handler, self.read_only = name, description, schema, handler, read_only

    def listing(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema,
                "annotations": {"readOnlyHint": self.read_only, "openWorldHint": False}}


class Context:
    """Passed to every tool: progress reports for the client."""

    def __init__(self, server: "Server", token):
        self._server, self._token = server, token

    def progress(self, done: float, total: float, message: str = "") -> None:
        if self._token is None:
            return
        params = {"progressToken": self._token, "progress": done, "total": total}
        if message:
            params["message"] = message
        self._server.notify("notifications/progress", params)


class Server:
    def __init__(self, tools: list[Tool]):
        self.tools = {t.name: t for t in tools}
        self._out_fd = -1
        self._lock = threading.Lock()
        self._buf = b""

    # ------------------------------------------------------------------ transport
    def _claim_stdio(self) -> None:
        """Keep the real stdout for protocol messages; anything else that prints goes to stderr."""
        try:
            self._out_fd = os.dup(1)
            os.dup2(2, 1)
        except OSError:
            self._out_fd = 1
        sys.stdout = sys.stderr = open(2, "w", encoding="utf-8", errors="replace", closefd=False)

    def _send(self, message: dict) -> None:
        data = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            view = memoryview(data)
            while view:
                n = os.write(self._out_fd, view)
                view = view[n:]

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _readline(self) -> bytes | None:
        while b"\n" not in self._buf:
            chunk = os.read(0, 65536)
            if not chunk:
                rest, self._buf = self._buf, b""
                return rest or None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line

    # ------------------------------------------------------------------ requests
    def _result(self, rid, result: dict) -> None:
        self._send({"jsonrpc": "2.0", "id": rid, "result": result})

    def _error(self, rid, code: int, message: str) -> None:
        self._send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})

    def handle(self, msg: dict) -> None:
        method = msg.get("method")
        rid = msg.get("id")
        params = msg.get("params") or {}
        if method is None:        # a response to something we never asked
            return
        if rid is None:           # notification: nothing to answer
            return
        if method == "initialize":
            wanted = params.get("protocolVersion")
            version = wanted if wanted in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
            self._result(rid, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                               "serverInfo": {"name": SERVER_NAME, "version": VERSION},
                               "instructions": INSTRUCTIONS})
        elif method == "ping":
            self._result(rid, {})
        elif method == "tools/list":
            self._result(rid, {"tools": [t.listing() for t in self.tools.values()]})
        elif method == "tools/call":
            self._call(rid, params)
        elif method in ("resources/list", "resources/templates/list", "prompts/list"):
            key = "prompts" if method.startswith("prompts") else "resources"
            self._result(rid, {key if method != "resources/templates/list" else "resourceTemplates": []})
        else:
            self._error(rid, -32601, f"метод {method} не поддерживается")

    def _call(self, rid, params: dict) -> None:
        tool = self.tools.get(params.get("name", ""))
        if tool is None:
            self._error(rid, -32602, f"нет инструмента {params.get('name')}")
            return
        token = (params.get("_meta") or {}).get("progressToken")
        try:
            out = tool.handler(params.get("arguments") or {}, Context(self, token))
            extra: list[dict] = []
            if isinstance(out, tuple):
                out, extra = out
            text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, separators=(",", ":"))
            self._result(rid, {"content": [{"type": "text", "text": text}, *extra], "isError": False})
        except Exception as exc:   # the agent reads the reason and tries again
            if not isinstance(exc, (ToolError, ValueError, FileNotFoundError, PermissionError)) and \
                    exc.__class__.__name__ not in ("PdfToolError", "LoadError", "OfficeError"):
                print(traceback.format_exc(), file=sys.stderr)
            msg = str(exc) or exc.__class__.__name__
            self._result(rid, {"content": [{"type": "text", "text": msg}], "isError": True})

    # ------------------------------------------------------------------ loop
    def serve(self) -> int:
        self._claim_stdio()
        while True:
            try:
                line = self._readline()
            except OSError:
                return 0
            if line is None:
                return 0
            line = line.strip()
            if not line:
                continue
            try:
                msg: Any = json.loads(line.decode("utf-8-sig"))
            except ValueError:
                self._error(None, -32700, "не разобрал JSON")
                continue
            batch = msg if isinstance(msg, list) else [msg]
            for item in batch:
                if isinstance(item, dict):
                    try:
                        self.handle(item)
                    except Exception:
                        print(traceback.format_exc(), file=sys.stderr)
                        if item.get("id") is not None:
                            self._error(item["id"], -32603, "внутренняя ошибка сервера")


def run() -> int:
    """Entry point for ``--mcp``."""
    from PySide6.QtGui import QGuiApplication   # Qt renders PDF, SVG, text and prints

    from .mcp_tools import build_tools

    app = QGuiApplication(sys.argv[:1])
    code = Server(build_tools()).serve()
    del app
    return code
