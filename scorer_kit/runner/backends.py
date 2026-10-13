"""Where a model call actually goes.

A model is named by a spec string ``provider:model``:

- ``openrouter:<model>``  API via OpenRouter (env OPENROUTER_API_KEY)
- ``bailian:<model>``     API via Alibaba Cloud Bailian / DashScope (env DASHSCOPE_API_KEY)
- ``app:<label>``         no API: prompts are written to files for the user (or their AI app)
                          to run in a chat app; responses are pasted back into files
- ``mock:<label>``        offline deterministic fake, for trying the pipeline without keys
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from scorer_kit.schemas import CallResult, Job

PROVIDERS = ("openrouter", "bailian", "app", "mock")


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    name: str

    @classmethod
    def parse(cls, spec: str) -> ModelSpec:
        provider, sep, name = spec.partition(":")
        if not sep or not name or provider not in PROVIDERS:
            raise ValueError(f"model spec {spec!r} must look like <{'|'.join(PROVIDERS)}>:<model>")
        return cls(provider, name)

    def __str__(self) -> str:
        return f"{self.provider}:{self.name}"

    @property
    def slug(self) -> str:
        """Filesystem-safe name."""
        return re.sub(r"[^A-Za-z0-9._-]+", "_", str(self))


class Backend(Protocol):
    def call(self, job: Job) -> CallResult: ...


# ---------------------------------------------------------------- API (OpenAI-compatible)


class OpenAICompatBackend:
    """Chat Completions over HTTP. OpenRouter and Bailian both speak this dialect."""

    def __init__(self, name: str, base_url: str, api_key: str, extra_body: dict | None = None,
                 timeout: float = 300, max_retries: int = 3, client: httpx.Client | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.extra_body = extra_body or {}
        self.max_retries = max_retries
        self.client = client or httpx.Client(timeout=timeout)

    def call(self, job: Job) -> CallResult:
        model = ModelSpec.parse(job.model).name
        body = {
            "model": model,
            "messages": [m.model_dump() for m in job.messages],
            **self.extra_body,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last_error = ""
        for attempt in range(self.max_retries):
            start = time.perf_counter()
            try:
                resp = self.client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as e:
                last_error = f"{type(e).__name__}: {e}"
            else:
                latency = time.perf_counter() - start
                if resp.status_code == 200:
                    return self._parse(resp.json(), latency)
                last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
                if resp.status_code not in (408, 409, 429) and resp.status_code < 500:
                    break  # client error: retrying will not help
            time.sleep(2**attempt)
        return CallResult(status="error", error=last_error, backend=self.name)

    def _parse(self, data: dict, latency: float) -> CallResult:
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return CallResult(status="error", error=f"unexpected response: {str(data)[:500]}",
                              latency_s=latency, backend=self.name)
        usage = data.get("usage") or {}
        cost = usage.get("cost")
        return CallResult(
            text=text,
            latency_s=round(latency, 3),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cost_usd=float(cost) if cost is not None else None,
            backend=self.name,
        )


def _require_env(var: str, provider: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise RuntimeError(f"{provider}: set the {var} environment variable to use API mode")
    return value


def openrouter_backend() -> OpenAICompatBackend:
    return OpenAICompatBackend(
        "openrouter",
        os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        _require_env("OPENROUTER_API_KEY", "openrouter"),
        extra_body={"usage": {"include": True}},  # asks OpenRouter to report cost
    )


def bailian_backend() -> OpenAICompatBackend:
    # Mainland endpoint by default; international accounts set
    # BAILIAN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
    return OpenAICompatBackend(
        "bailian",
        os.environ.get("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        _require_env("DASHSCOPE_API_KEY", "bailian"),
    )


# ---------------------------------------------------------------- app handoff (no API)


def render_handoff(job: Job) -> str:
    """One paste-able block: chat apps take a single message, so system text goes first."""
    parts = []
    for m in job.messages:
        if m.role == "system":
            parts.append(m.content.strip())
        elif m.role == "user":
            parts.append(m.content.strip())
    return "\n\n---\n\n".join(parts) + "\n"


class HandoffBackend:
    """Writes each job as ``<id>.prompt.md``; the response is read from ``<id>.response.md``.

    Re-running picks up whatever responses have been filled in so far, so the user can work
    through the prompts at their own pace (or have their AI app do it).
    """

    name = "app"

    def __init__(self, folder: Path):
        self.folder = folder

    def paths(self, job: Job) -> tuple[Path, Path]:
        d = self.folder / ModelSpec.parse(job.model).slug
        return d / f"{job.id}.prompt.md", d / f"{job.id}.response.md"

    def call(self, job: Job) -> CallResult:
        prompt_path, response_path = self.paths(job)
        if response_path.is_file():
            text = response_path.read_text(encoding="utf-8").strip()
            if text:
                return CallResult(text=text, backend=self.name)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(render_handoff(job), encoding="utf-8")
        return CallResult(status="pending", backend=self.name)


# ---------------------------------------------------------------- mock (offline)


class MockBackend:
    """Deterministic fake model. Each mock label gets a stable 'skill' level, and the
    recipe's grader supplies plausible outputs/judgements, so the full pipeline (run,
    grade, calibrate, report) can be exercised without keys or cost."""

    name = "mock"

    def call(self, job: Job) -> CallResult:
        from scorer_kit.graders import REGISTRY

        seed = int(hashlib.sha256(f"{job.model}|{job.id}".encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)
        skill = mock_skill(ModelSpec.parse(job.model).name)
        grader = REGISTRY[job.meta["grader"]]
        if job.kind == "task":
            text = grader.mock_output(job, skill, rng)
        else:
            text = grader.mock_judgement(job, rng)
        return CallResult(
            text=text,
            latency_s=round(rng.uniform(2, 20) * (1.5 - skill), 3),
            input_tokens=sum(len(m.content) for m in job.messages) // 4,
            output_tokens=len(text) // 4,
            cost_usd=round(rng.uniform(0.001, 0.02), 5),
            backend=self.name,
        )


def mock_skill(label: str) -> float:
    """Stable pseudo-ability in [0.3, 0.95] derived from the mock model's label."""
    h = int(hashlib.sha256(label.encode()).hexdigest()[:8], 16)
    return 0.3 + 0.65 * (h / 0xFFFFFFFF)


# ---------------------------------------------------------------- factory


def make_backends(specs: list[str], handoff_dir: Path) -> dict[str, Backend]:
    """Build only the backends these model specs need, so a missing key fails before
    any call is made and only matters for providers actually in use."""
    factories = {
        "openrouter": openrouter_backend,
        "bailian": bailian_backend,
        "app": lambda: HandoffBackend(handoff_dir),
        "mock": MockBackend,
    }
    providers = {ModelSpec.parse(s).provider for s in specs}
    return {p: factories[p]() for p in sorted(providers)}
