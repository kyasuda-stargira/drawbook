"""AI providers.

- LocalProvider (default): any OpenAI-compatible server on this machine (mlx_lm.server, Ollama,
  llama.cpp, LM Studio). It refuses any URL that is not localhost, so documents never leave the machine.
- OutsideProvider (opt-in): the user's own provider and key (Anthropic, or any OpenAI-compatible API).
  Used only when switched on for a document or folder. Before each send it shows a warning, can redact
  LP names (and optionally figures), and appends a line to a send log.
- MockProvider: canned answers for tests.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str, *, doc: str = "") -> str: ...


def _is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def _post_json(url: str, body: dict, headers: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class LocalProvider:
    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = (base_url or os.environ.get("DRAWBOOK_LOCAL_URL") or "http://127.0.0.1:8080/v1").rstrip("/")
        if not _is_local(self.base_url):
            raise ValueError(f"local provider must point at this machine, not {self.base_url}")
        self.model = model or os.environ.get("DRAWBOOK_LOCAL_MODEL") or "default"
        self.name = f"local:{self.model}"

    def complete(self, system: str, user: str, *, doc: str = "") -> str:
        out = _post_json(f"{self.base_url}/chat/completions",
                         {"model": self.model, "temperature": 0, "max_tokens": 4000,
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, {})
        return out["choices"][0]["message"]["content"]


class MockProvider:
    def __init__(self, answer: str | Callable[[str, str], str]):
        self.answer = answer
        self.name = "mock"
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, doc: str = "") -> str:
        self.calls.append((system, user))
        return self.answer(system, user) if callable(self.answer) else self.answer


_FIG = re.compile(r"\d[\d,.  ]*\d")


def redact(text: str, names: list[str], figures: bool = False) -> str:
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(re.escape(n), "[LP]", text, flags=re.I)
    if figures:
        text = _FIG.sub("[FIGURE]", text)
    return text


WARNING = ("Drawbook is about to send text from {doc} to {provider}, outside this machine. "
           "Side letters and LPAs often limit sharing fund documents with outside processors. "
           "Check yours before you continue.")


class OutsideProvider:
    """The user's own AI provider. Never used unless the caller passes it in explicitly."""

    def __init__(self, kind: str, api_key: str, model: str, *, base_url: str | None = None,
                 log_path: Path, confirm: Callable[[str], bool], redact_names: list[str] | None = None,
                 redact_figures: bool = False, transport: Callable[[str, dict, dict], dict] | None = None):
        if kind not in ("anthropic", "openai-compatible"):
            raise ValueError("kind must be 'anthropic' or 'openai-compatible'")
        if not api_key:
            raise ValueError("an API key is required for an outside provider")
        self.kind, self.api_key, self.model = kind, api_key, model
        self.base_url = (base_url or ("https://api.anthropic.com/v1" if kind == "anthropic" else "")).rstrip("/")
        if not self.base_url:
            raise ValueError("base_url is required for an openai-compatible provider")
        self.log_path, self.confirm = Path(log_path), confirm
        self.redact_names, self.redact_figures = redact_names or [], redact_figures
        self.transport = transport or _post_json
        self.name = f"{kind}:{model}"

    def complete(self, system: str, user: str, *, doc: str = "") -> str:
        if not self.confirm(WARNING.format(doc=doc or "this document", provider=self.name)):
            raise PermissionError("user declined sending to outside provider")
        sent = redact(user, self.redact_names, self.redact_figures)
        if self.kind == "anthropic":
            out = self.transport(f"{self.base_url}/messages",
                                 {"model": self.model, "max_tokens": 4000, "system": system,
                                  "messages": [{"role": "user", "content": sent}]},
                                 {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
            text = "".join(b.get("text", "") for b in out.get("content", []))
        else:
            out = self.transport(f"{self.base_url}/chat/completions",
                                 {"model": self.model, "temperature": 0,
                                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": sent}]},
                                 {"Authorization": f"Bearer {self.api_key}"})
            text = out["choices"][0]["message"]["content"]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as f:
            f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "doc": doc, "provider": self.name,
                                "url": self.base_url, "chars_sent": len(sent),
                                "names_redacted": bool(self.redact_names), "figures_redacted": self.redact_figures}) + "\n")
        return text
