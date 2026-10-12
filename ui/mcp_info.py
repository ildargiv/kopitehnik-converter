"""Window with the settings for connecting AI agents (MCP clients) to this program."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from .widgets import AnimatedButton


def server_command() -> tuple[str, list[str]]:
    """Command that starts the MCP server: the installed program, or Python with app.py when run from source."""
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp"]
    return sys.executable, [str(Path(__file__).resolve().parent.parent / "app.py"), "--mcp"]


def client_config() -> str:
    """JSON that most MCP clients (Claude Desktop, Cursor, Cline, Hermes through its MCP settings) accept."""
    command, args = server_command()
    return json.dumps({"mcpServers": {"kopitehnik-converter": {"command": command, "args": args}}},
                      ensure_ascii=False, indent=2)


class McpDialog(QDialog):
    def __init__(self, parent, t):
        super().__init__(parent)
        self.setWindowTitle(t("mcp_title"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(10)
        text = QLabel(t("mcp_intro"))
        text.setWordWrap(True)
        v.addWidget(text)
        self.box = QPlainTextEdit(client_config())
        self.box.setReadOnly(True)
        self.box.setMinimumHeight(150)
        v.addWidget(self.box)
        hint = QLabel(t("mcp_hint"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        copy = AnimatedButton(t("mcp_copy"))
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(self.box.toPlainText()),
                                      copy.setText(t("mcp_copied"))))
        row.addWidget(copy)
        ok = AnimatedButton(t("close"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        v.addLayout(row)
