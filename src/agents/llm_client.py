"""BYOM LLM client with Pydantic-enforced JSON output and a deterministic offline fallback.

Routing:
  * DATABRICKS_HOST + DATABRICKS_TOKEN set -> Databricks Model Serving
    `{HOST}/serving-endpoints/{DATABRICKS_SERVING_ENDPOINT}/invocations`. No OpenAI `response_format` is sent
    (it fails on Databricks Claude endpoints); JSON is enforced by system-prompt instructions plus a
    `model_validate_json()` retry loop, so databricks-claude-sonnet-4-5 and databricks-meta-llama-3-3-70b-instruct both work.
  * else BYOM_BASE_URL / BYOM_MODEL_NAME / BYOM_API_KEY (OpenAI-compatible: Ollama, vLLM, cloud APIs).
  * BYOM_OFFLINE=true, or any failure -> deterministic heuristic fallback (never raises).

Provider-aware structured output (`backend`):
  * `openai-compatible` servers that support it (api.openai.com, or BYOM_JSON_SCHEMA=true for vLLM/others): native
    `response_format={"type": "json_schema", ...}` built from the Pydantic model. A server that rejects it is detected once and
    downgraded to `json_object`.
  * `databricks-claude` (endpoint `databricks-claude-*`) and every other Databricks endpoint: never `response_format` (it fails on
    Databricks Claude); strict prompt-enforced JSON + `extract_json` + Pydantic validation retry.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Callable, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
DEFAULT_DATABRICKS_ENDPOINT = "databricks-claude-sonnet-4-5"
MAX_ATTEMPTS = 3


class Narrative(BaseModel):
    summary: str


def _load_dotenv() -> None:
    path = os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = v.strip()
                # Matching outer quotes delimit .env values, including connection URIs.
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                os.environ.setdefault(k.strip(), v)


def extract_json(content: str) -> str:
    """Pull the JSON object out of a model reply (handles ```json fences and prose around it)."""
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    m = re.search(r"\{.*\}", content, re.S)
    return m.group(0) if m else content


class LLMClient:
    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None,
                 offline: bool | None = None, probe_timeout: float = 1.5, http: httpx.Client | None = None):
        _load_dotenv()
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        self.use_anthropic = bool(self.anthropic_key and not os.getenv("DATABRICKS_HOST")) and base_url is None

        self.db_host = (os.getenv("DATABRICKS_HOST") or "").rstrip("/")
        self.db_token = os.getenv("DATABRICKS_TOKEN") or ""
        self.db_endpoint = os.getenv("DATABRICKS_SERVING_ENDPOINT") or DEFAULT_DATABRICKS_ENDPOINT
        self.use_databricks = bool(self.db_host and self.db_token) and base_url is None
        self.base_url = base_url or os.getenv("BYOM_BASE_URL") or "http://localhost:11434/v1"
        self.model = model or os.getenv("BYOM_MODEL_NAME", "llama3.1:8b")
        self.api_key = api_key or os.getenv("BYOM_API_KEY") or "none"
        self.offline = offline if offline is not None else os.getenv("BYOM_OFFLINE", "false").lower() == "true"
        self.probe_timeout = probe_timeout
        self._available: bool | None = None
        self._client = None
        self._anthropic_client = None
        self._http = http

    @property
    def backend(self) -> str:
        """Which transport / structured-output strategy is active."""
        if self.use_anthropic:
            return "anthropic"
        if self.use_databricks:
            return "databricks-claude" if self.db_endpoint.lower().startswith("databricks-claude") else "databricks"
        return "openai-compatible"

    @property
    def supports_json_schema(self) -> bool:
        """Native json_schema response_format: only on OpenAI-compatible servers known (or declared) to support it."""
        if self.backend != "openai-compatible" or getattr(self, "_schema_rejected", False):
            return False
        flag = os.getenv("BYOM_JSON_SCHEMA", "").lower()
        if flag in {"true", "false"}:
            return flag == "true"
        return "api.openai.com" in self.base_url

    @property
    def databricks_endpoint(self) -> str | None:
        return self.db_endpoint if self.use_databricks and not self.offline else None

    @property
    def invocations_url(self) -> str:
        return f"{self.db_host}/serving-endpoints/{self.db_endpoint}/invocations"

    def available(self) -> bool:
        if self.offline:
            return False
        if self.use_anthropic or self.use_databricks:
            return True
        if self._available is None:
            try:
                r = httpx.get(self.base_url.rstrip("/") + "/models", timeout=self.probe_timeout,
                              headers={"Authorization": f"Bearer {self.api_key}"})
                self._available = r.status_code < 500
            except Exception:
                self._available = False
            if not self._available:
                log.info("BYOM endpoint %s unreachable; using deterministic fallback", self.base_url)
        return self._available

    # ---- transport
    def _complete(self, messages: list[dict], schema: type[BaseModel] | None = None) -> str:
        if self.use_anthropic:
            if self._anthropic_client is None:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=self.anthropic_key, timeout=45)
            # Separate system prompt from messages for Anthropic API
            sys_text = ""
            chat_msgs = []
            for m in messages:
                if m.get("role") == "system":
                    sys_text += ("\n" if sys_text else "") + m.get("content", "")
                else:
                    chat_msgs.append({"role": m.get("role"), "content": m.get("content", "")})
            res = self._anthropic_client.messages.create(
                model=self.anthropic_model,
                system=sys_text or "You are a regulatory compliance auditor.",
                messages=chat_msgs,
                max_tokens=2048,
            )
            return "".join(getattr(b, "text", "") or "" for b in (res.content or []) if getattr(b, "type", "text") == "text")

        if self.use_databricks:
            http = self._http or httpx.Client(timeout=60)
            r = http.post(self.invocations_url, headers={"Authorization": f"Bearer {self.db_token}"},
                          json={"messages": messages, "max_tokens": 1024, "temperature": 0})  # NB: no response_format
            r.raise_for_status()
            body = r.json()
            return body["choices"][0]["message"]["content"] or ""
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=30)
        if schema is not None and self.supports_json_schema:
            fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema(), "strict": False}}
            try:
                resp = self._client.chat.completions.create(model=self.model, messages=messages, temperature=0, response_format=fmt)
                return resp.choices[0].message.content or ""
            except Exception as exc:
                if "response_format" not in str(exc).lower() and "schema" not in str(exc).lower():
                    raise
                self._schema_rejected = True  # server does not support json_schema: remember and use json_object
        resp = self._client.chat.completions.create(model=self.model, messages=messages, temperature=0,
                                                    response_format={"type": "json_object"})
        return resp.choices[0].message.content or ""

    def structured(self, system: str, user: str, schema: type[T], fallback: Callable[[], T]) -> T:
        """Validated `schema` instance via prompt-enforced JSON + retry loop; any failure yields `fallback()`."""
        if not self.available():
            return fallback()
        messages = [
            {"role": "system", "content": system + "\nReturn ONLY one valid JSON object (no markdown, no commentary) "
             "that conforms exactly to this JSON schema: " + json.dumps(schema.model_json_schema())},
            {"role": "user", "content": user},
        ]
        for _ in range(MAX_ATTEMPTS):
            try:
                content = self._complete(messages, schema)
            except Exception as exc:
                log.warning("BYOM call failed (%s); falling back", type(exc).__name__)
                if not self.use_databricks:
                    self._available = False
                return fallback()
            try:
                return schema.model_validate_json(extract_json(content))
            except (ValidationError, ValueError) as exc:
                messages += [{"role": "assistant", "content": content[:1500]},
                             {"role": "user", "content": f"That was not valid for the schema ({str(exc)[:300]}). "
                              "Reply again with ONLY the corrected JSON object."}]
        return fallback()


# --------------------------------------------------------------------------- dynamic context pruning
_CLAIM_LINE_RE = {
    "PRIVACY": re.compile(r"redact|mask|anonymi|presidio|requests\.|httpx|fetch\(|\.post\(|\.get\(|openai|anthropic|email|ssn|phone|passport", re.I),
    "HOSTING": re.compile(r"https?://|region|endpoint|base_url|host", re.I),
    "HITL": re.compile(r"human|review|approv|queue|decision|score|decide|override|escalat", re.I),
    "SAFETY_MODERATION": re.compile(r"moderat|filter|refus|safety|toxic|hate|prompt|generate|completion", re.I),
    "WATERMARK": re.compile(r"watermark|c2pa|ai[_-]?generated|disclos|header|metadata|generate", re.I),
    "IP_LICENSE": re.compile(r"licen[cs]e|gpl|import |from .* import|weights|model", re.I),
}


def build_focused_context(assertion=None, ast_slice=None, capability_card=None, max_lines: int = 14, around: int = 1, max_chars: int = 1800) -> str:
    """Prompt context with only what the model needs: the policy claim, the capability tags, and the code lines that bear on the claim.

    Instead of sending whole files, pick the lines of `ast_slice` matching the claim type (plus `around` neighbours), prefix them with their
    real line numbers, and cap the total size. Any argument may be None. Returns "" when nothing is available.
    """
    parts: list[str] = []
    if assertion is not None:
        parts.append(f"Policy claim ({getattr(assertion, 'claim_type', '')}): {str(getattr(assertion, 'claim_text', ''))[:400]}")
    if capability_card is not None:
        tags = ", ".join(getattr(capability_card, "capability_tags", []) or []) or "none"
        parts.append(f"Capability tags: {tags} @ {getattr(capability_card, 'exact_locator', '')}")
    if ast_slice is not None:
        lines = ast_slice.code_snippet.splitlines()
        rx = _CLAIM_LINE_RE.get(getattr(assertion, "claim_type", ""), None)
        keep: set[int] = set()
        for i, line in enumerate(lines):
            if rx is None or rx.search(line):
                keep.update(range(max(0, i - around), min(len(lines), i + around + 1)))
        picked = sorted(keep)[:max_lines] or list(range(min(max_lines, len(lines))))
        body = "\n".join(f"{ast_slice.start_line + i}: {lines[i].rstrip()[:160]}" for i in picked)
        parts.append(f"Code ({ast_slice.file_path}, {len(picked)} of {len(lines)} lines):\n{body}")
    return "\n".join(parts)[:max_chars]
