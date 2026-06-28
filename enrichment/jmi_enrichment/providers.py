"""Pluggable LLM providers for the enrichment classifier.

Default is **Ollama** (local, 0€, no key). Gemini (free tier) and Anthropic
(paid) are drop-in alternatives selected via ``settings.llm_provider``. Each
provider takes a system + user prompt and a Pydantic schema, and returns the
validated model plus token/cost usage.

Ollama and Gemini enforce JSON output mode and we validate against the schema
client-side (lenient extraction); Anthropic uses native structured outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from jmi_core.settings import Settings

T = TypeVar("T", bound=BaseModel)

# Anthropic pricing (USD per 1M tokens) for the optional paid path.
_ANTHROPIC_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}


class ClassificationError(RuntimeError):
    """Raised when a provider refuses or returns no parseable output."""


@dataclass(slots=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class LLMProvider(Protocol):
    model: str

    def classify(self, *, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]: ...

    def complete(self, *, system: str, user: str) -> str:
        """Free-form text completion (used by the text-to-SQL agent)."""
        ...


def extract_json(text: str) -> str:
    """Pull the first JSON object out of a model response (tolerates fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ClassificationError("no JSON object found in model response")
    return t[start : end + 1]


def _validate(schema: type[T], text: str) -> T:
    try:
        return schema.model_validate_json(extract_json(text))
    except (ValidationError, ClassificationError) as exc:
        raise ClassificationError(f"response did not match schema: {exc}") from exc


# ---------------------------------------------------------------------------
# Ollama (local, default, 0€)
# ---------------------------------------------------------------------------
class OllamaProvider:
    def __init__(
        self,
        model: str,
        *,
        host: str = "http://localhost:11434",
        timeout: float = 180.0,
        num_thread: int = 0,
        keep_alive: str = "5m",
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        # num_thread=0 lets Ollama use every core; a positive value caps CPU use
        # (protects a laptop from sustained 100%-on-all-cores heat/throttling).
        self.num_thread = num_thread
        self.keep_alive = keep_alive

    def _options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {"temperature": 0}
        if self.num_thread and self.num_thread > 0:
            opts["num_thread"] = self.num_thread
        return opts

    def classify(self, *, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]:
        import httpx

        try:
            resp = httpx.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "format": "json",
                    "keep_alive": self.keep_alive,
                    "options": self._options(),
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClassificationError(f"ollama request failed: {exc}") from exc

        data = resp.json()
        content = (data.get("message") or {}).get("content", "")
        parsed = _validate(schema, content)
        usage = LLMUsage(
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            cost_usd=0.0,
        )
        return parsed, usage

    def complete(self, *, system: str, user: str) -> str:
        import httpx

        resp = httpx.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "keep_alive": self.keep_alive,
                "options": self._options(),
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return (resp.json().get("message") or {}).get("content", "")


# ---------------------------------------------------------------------------
# Gemini (free tier)
# ---------------------------------------------------------------------------
class GeminiProvider:
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None,
        timeout: float = 60.0,
        max_retries: int = 5,
        min_interval: float = 0.0,
    ):
        if not api_key:
            raise ClassificationError("GEMINI_API_KEY is required for the gemini provider")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        # Proactive throttle: keep at least this many seconds between requests so
        # we stay under the free-tier RPM cap instead of relying on 429 backoff.
        self.min_interval = min_interval
        self._last_call = 0.0

    def _generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to generateContent, retrying on 429/503 (free-tier rate limits)."""
        import time

        import httpx

        url = f"{self.BASE}/{self.model}:generateContent"
        for attempt in range(self.max_retries + 1):
            if self.min_interval > 0:
                wait = self.min_interval - (time.monotonic() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
            try:
                resp = httpx.post(
                    url, params={"key": self.api_key}, json=payload, timeout=self.timeout
                )
                self._last_call = time.monotonic()
            except httpx.HTTPError as exc:
                raise ClassificationError(f"gemini request failed: {exc}") from exc
            if resp.status_code in (429, 503) and attempt < self.max_retries:
                time.sleep(self._backoff(resp, attempt))
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ClassificationError(f"gemini request failed: {exc}") from exc
            return resp.json()
        raise ClassificationError(
            "gemini rate limit: exhausted retries (free-tier RPM/RPD likely hit)"
        )

    @staticmethod
    def _backoff(resp: Any, attempt: int) -> float:
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return min(2.0**attempt, 30.0)

    def classify(self, *, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]:
        data = self._generate(
            {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
            }
        )
        candidates = data.get("candidates") or []
        if not candidates:
            raise ClassificationError("gemini returned no candidates (possible safety block)")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        parsed = _validate(schema, text)
        meta = data.get("usageMetadata") or {}
        usage = LLMUsage(
            input_tokens=meta.get("promptTokenCount"),
            output_tokens=meta.get("candidatesTokenCount"),
            cost_usd=0.0,
        )
        return parsed, usage

    def complete(self, *, system: str, user: str) -> str:
        data = self._generate(
            {
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0},
            }
        )
        candidates = data.get("candidates") or []
        if not candidates:
            raise ClassificationError("gemini returned no candidates")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)


# ---------------------------------------------------------------------------
# Anthropic (paid, optional)
# ---------------------------------------------------------------------------
class AnthropicProvider:
    def __init__(self, model: str, *, client: Any | None = None, max_tokens: int = 1024):
        self.model = model
        self.max_tokens = max_tokens
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic  # lazy; reads ANTHROPIC_API_KEY

            self._client = anthropic.Anthropic()
        return self._client

    def classify(self, *, system: str, user: str, schema: type[T]) -> tuple[T, LLMUsage]:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        if getattr(response, "stop_reason", None) == "refusal":
            raise ClassificationError("anthropic refused the request")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise ClassificationError("anthropic returned no parsed output")
        usage = LLMUsage(
            input_tokens=self._total_input(response.usage),
            output_tokens=getattr(response.usage, "output_tokens", None),
            cost_usd=self._cost(response.usage),
        )
        return parsed, usage

    def _cost(self, usage: Any) -> float:
        price_in, price_out = _ANTHROPIC_PRICING.get(self.model, (1.0, 5.0))
        uncached = getattr(usage, "input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        output = getattr(usage, "output_tokens", 0) or 0
        return round(
            (uncached * price_in + cache_write * price_in * 1.25 + cache_read * price_in * 0.1
             + output * price_out) / 1_000_000,
            6,
        )

    @staticmethod
    def _total_input(usage: Any) -> int:
        return (
            (getattr(usage, "input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        )

    def complete(self, *, system: str, user: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


def get_provider(settings: Settings) -> LLMProvider:
    name = settings.llm_provider.lower()
    if name == "ollama":
        return OllamaProvider(
            settings.llm_model,
            host=settings.ollama_host,
            num_thread=settings.ollama_num_thread,
            keep_alive=settings.ollama_keep_alive,
        )
    if name == "gemini":
        return GeminiProvider(
            settings.llm_model,
            api_key=settings.gemini_api_key,
            min_interval=settings.gemini_min_interval_s,
        )
    if name == "anthropic":
        return AnthropicProvider(settings.llm_model)
    raise ValueError(f"Unknown llm_provider '{settings.llm_provider}' (ollama|gemini|anthropic)")
