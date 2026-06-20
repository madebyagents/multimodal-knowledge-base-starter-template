from __future__ import annotations

import subprocess
from pathlib import Path

from app.providers import ClaudeOAuthChatClient, CodexOAuthChatClient


def test_codex_oauth_client_uses_safe_exec_command(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_text("Grounded answer", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-should-not-leak")

    client = CodexOAuthChatClient(codex_bin="codex", model="gpt-5.5", timeout_s=12)
    chunks = list(
        client.stream_chat(
            [
                {"role": "system", "content": "Use sources only."},
                {"role": "user", "content": "Question"},
            ]
        )
    )

    cmd = seen["cmd"]
    assert chunks == ["Grounded answer"]
    assert cmd[:3] == ["codex", "exec", "--ignore-user-config"]
    assert "--ephemeral" in cmd
    assert ["-s", "read-only"] == cmd[cmd.index("-s") : cmd.index("-s") + 2]
    assert "approval_policy=never" in cmd
    assert "gpt-5.5" in cmd
    assert seen["kwargs"]["stdin"] == subprocess.DEVNULL
    assert "OPENAI_API_KEY" not in seen["kwargs"]["env"]


def test_claude_oauth_client_uses_noninteractive_oauth_command(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="Grounded answer [1]\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")

    client = ClaudeOAuthChatClient(
        claude_bin="claude",
        model="claude-sonnet-4-6",
        effort="medium",
        timeout_s=12,
    )
    chunks = list(
        client.stream_chat(
            [
                {"role": "system", "content": "Use sources only."},
                {"role": "user", "content": "Question"},
            ]
        )
    )

    cmd = seen["cmd"]
    assert chunks == ["Grounded answer [1]"]
    assert cmd[:2] == ["claude", "--print"]
    assert ["--model", "claude-sonnet-4-6"] == cmd[cmd.index("--model") : cmd.index("--model") + 2]
    assert ["--effort", "medium"] == cmd[cmd.index("--effort") : cmd.index("--effort") + 2]
    assert ["--tools", ""] == cmd[cmd.index("--tools") : cmd.index("--tools") + 2]
    assert ["--permission-mode", "dontAsk"] == cmd[
        cmd.index("--permission-mode") : cmd.index("--permission-mode") + 2
    ]
    assert "--no-session-persistence" in cmd
    assert "--bare" not in cmd
    assert not any("budget_tokens" in str(part) for part in cmd)
    assert seen["kwargs"]["stdin"] == subprocess.DEVNULL
    assert "ANTHROPIC_API_KEY" not in seen["kwargs"]["env"]


def test_claude_oauth_client_maps_xhigh_effort_to_oauth_high(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    client = ClaudeOAuthChatClient(model="claude-opus-4-8", effort="xhigh")
    assert client.complete_chat([{"role": "user", "content": "ok"}]) == "ok"

    cmd = seen["cmd"]
    assert ["--effort", "high"] == cmd[cmd.index("--effort") : cmd.index("--effort") + 2]
    assert "--bare" not in cmd
    assert not any("budget_tokens" in str(part) for part in cmd)
