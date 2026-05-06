"""LLM client abstraction with OpenAI support and local fallback.

The lab uses OpenAI when ``OPENAI_API_KEY`` is present and ``LLM_PROVIDER`` is
not set to ``local``. If the SDK, key, or provider call is unavailable, the
client falls back to a deterministic local response and records that fallback in
metadata instead of pretending that a provider call succeeded.
"""

from dataclasses import dataclass
from os import getenv
from time import perf_counter
from typing import Any

from multi_agent_research_lab.core.config import get_settings


# Public OpenAI model pages currently list GPT-4.1 nano text-token pricing as
# $0.10 input / $0.40 output per 1M tokens. Other models are left unpriced
# unless explicit environment overrides are supplied.
_DEFAULT_PRICE_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-nano-2025-04-14": (0.10, 0.40),
}


@dataclass(frozen=True)
class LLMResponse:
    """Provider-agnostic completion result."""

    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    provider: str = "local"
    model: str | None = None
    latency_seconds: float | None = None
    fallback_used: bool = False
    error: str | None = None


class LLMClient:
    """Small provider-agnostic LLM client used by agents.

    ``OPENAI_MODEL`` controls the model. The code does not hard-code a GPT-5
    model; if your `.env` says ``OPENAI_MODEL=gpt-4.1-nano``, that is the model
    sent to OpenAI.
    """

    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.provider = provider or getenv("LLM_PROVIDER") or settings.llm_provider
        self.model = model or settings.openai_model

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Return a completion with retry, fallback, and token/cost metadata."""

        started = perf_counter()
        provider = self.provider.lower().strip()
        last_error: Exception | None = None

        if provider != "local" and get_settings().openai_api_key:
            for _ in range(2):
                try:
                    response = self._complete_with_openai(system_prompt, user_prompt)
                    return LLMResponse(
                        content=response.content,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        cost_usd=response.cost_usd,
                        provider="openai",
                        model=self.model,
                        latency_seconds=perf_counter() - started,
                    )
                except Exception as exc:  # pragma: no cover - depends on external SDK/API
                    last_error = exc

        content = self._complete_locally(system_prompt, user_prompt)
        if last_error is not None:
            content = (
                "Local deterministic synthesis used after OpenAI provider failure. "
                f"Provider error: {last_error}\n\n{content}"
            )
        elif provider != "local" and not get_settings().openai_api_key:
            content = (
                "Local deterministic synthesis used because OPENAI_API_KEY is not set.\n\n"
                f"{content}"
            )

        input_tokens = self._estimate_tokens(system_prompt) + self._estimate_tokens(user_prompt)
        output_tokens = self._estimate_tokens(content)
        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0.0,
            provider="local",
            model=None,
            latency_seconds=perf_counter() - started,
            fallback_used=True,
            error=str(last_error) if last_error else None,
        )

    def _complete_with_openai(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Call OpenAI using the Responses API, with Chat Completions fallback.

        The fallback is only for SDK compatibility. It is still an OpenAI API
        call and therefore should show up in platform usage when it succeeds.
        """

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "The openai package is not installed. Run: pip install -e '.[dev,llm]'"
            ) from exc

        client = OpenAI(api_key=get_settings().openai_api_key)
        if hasattr(client, "responses"):
            response = client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=user_prompt,
            )
            content = self._response_output_text(response)
            input_tokens, output_tokens = self._usage_tokens(response)
            return LLMResponse(
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=estimate_openai_cost(self.model, input_tokens, output_tokens),
                provider="openai",
                model=self.model,
            )

        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = completion.choices[0].message.content or ""
        input_tokens, output_tokens = self._usage_tokens(completion)
        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_openai_cost(self.model, input_tokens, output_tokens),
            provider="openai",
            model=self.model,
        )

    def _response_output_text(self, response: Any) -> str:
        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()

        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                content_text = getattr(content, "text", None)
                if isinstance(content_text, str):
                    parts.append(content_text)
        return "\n".join(parts).strip() or "OpenAI returned an empty response."

    def _usage_tokens(self, response: Any) -> tuple[int | None, int | None]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if input_tokens is None:
            input_tokens = getattr(usage, "prompt_tokens", None)
        if output_tokens is None:
            output_tokens = getattr(usage, "completion_tokens", None)
        return _as_int(input_tokens), _as_int(output_tokens)

    def _complete_locally(self, system_prompt: str, user_prompt: str) -> str:
        """Create a deterministic extractive response from the supplied prompt."""

        del system_prompt
        sentences = self._split_sentences(user_prompt)
        selected = sentences[:5]
        if not selected:
            selected = ["No prompt content was provided."]
        bullets = "\n".join(f"- {sentence}" for sentence in selected)
        return f"Local deterministic synthesis:\n{bullets}"

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into short, readable sentences without external packages."""

        normalised = text.replace("\n", " ").strip()
        if not normalised:
            return []
        chunks: list[str] = []
        current: list[str] = []
        for token in normalised.split():
            current.append(token)
            if token.endswith((".", "!", "?")):
                chunks.append(" ".join(current).strip())
                current = []
        if current:
            chunks.append(" ".join(current).strip())
        return [chunk[:240] for chunk in chunks if chunk]

    def _estimate_tokens(self, text: str) -> int:
        """Approximate token count for local fallback metrics."""

        if not text:
            return 0
        return max(1, len(text.split()))


def estimate_openai_cost(
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """Estimate text-generation cost when token counts and rates are available."""

    if input_tokens is None or output_tokens is None:
        return None

    settings = get_settings()
    configured_input = settings.openai_input_cost_per_1m
    configured_output = settings.openai_output_cost_per_1m
    if configured_input is not None and configured_output is not None:
        input_rate, output_rate = configured_input, configured_output
    else:
        rates = _DEFAULT_PRICE_PER_1M.get(model or "")
        if rates is None:
            return None
        input_rate, output_rate = rates

    return round(
        (input_tokens / 1_000_000 * input_rate)
        + (output_tokens / 1_000_000 * output_rate),
        8,
    )


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
