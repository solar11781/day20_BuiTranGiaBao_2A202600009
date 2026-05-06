"""Search client abstraction for ResearcherAgent.

This implementation never reads the repository ``docs/`` folder or README as a
knowledge base. By default it performs a normal OpenAI Responses API call that
asks the configured model to produce a research brief. This default is chosen so
``OPENAI_MODEL=gpt-4.1-nano`` works reliably without rejected web-search tool
requests.

If you explicitly set ``OPENAI_SEARCH_MODE=web`` and choose a model that supports
OpenAI's hosted web-search tool, the client uses the Responses API ``web_search``
tool. If that web-search call fails, it falls back to a normal OpenAI model call
and records the limitation in metadata.
"""

from typing import Any

from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.schemas import SourceDocument
from multi_agent_research_lab.services.llm_client import LLMClient, estimate_openai_cost


class SearchClient:
    """OpenAI-backed research client with explicit fallback behavior."""

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.openai_search_model or settings.openai_model
        self.search_mode = settings.openai_search_mode.lower().strip()

    def search(self, query: str, max_results: int = 5) -> list[SourceDocument]:
        """Run an OpenAI-backed research step, never a repo-doc lookup."""

        settings = get_settings()
        if not settings.openai_api_key:
            return [self._fallback_source(query, "OPENAI_API_KEY is not set")]

        if self.search_mode == "web":
            try:
                return self._search_with_openai_web(query, max_results)
            except Exception as exc:  # pragma: no cover - external API dependent
                return [self._openai_model_research_source(query, fallback_reason=str(exc))]

        return [self._openai_model_research_source(query, fallback_reason=None)]

    def _openai_model_research_source(
        self,
        query: str,
        fallback_reason: str | None,
    ) -> SourceDocument:
        """Use a standard OpenAI model call for the Researcher step.

        This is not live web search. It is still a real OpenAI API call when the
        key is configured, which keeps the lab compatible with inexpensive models
        such as ``gpt-4.1-nano``.
        """

        system_prompt = "You are the Researcher in a multi-agent research system."
        user_prompt = "\n".join(
            [
                f"User query: {query}",
                "Produce concise research notes for downstream Analyst and Writer agents.",
                "Do not claim that you used this repository's docs, README, rubric, or config as evidence.",
                "Do not invent URLs or citations.",
                "If live web search was not used, explicitly say this is model-based research synthesis.",
            ]
        )
        response = LLMClient(provider="openai", model=self.model).complete(system_prompt, user_prompt)
        source_type = "openai_model_research"
        if response.fallback_used:
            source_type = "fallback"
        elif fallback_reason:
            source_type = "openai_model_fallback"

        snippet = response.content[:1200]
        if fallback_reason:
            snippet = (
                "OpenAI hosted web search failed, so this source contains model-only "
                f"research synthesis. Web-search error: {fallback_reason}\n\n{snippet}"
            )[:1200]

        return SourceDocument(
            title=(
                "OpenAI model research synthesis"
                if not fallback_reason
                else "OpenAI model-only research fallback"
            ),
            url=None,
            snippet=snippet,
            metadata={
                "source_type": source_type,
                "provider": response.provider,
                "model": response.model or self.model,
                "query": query,
                "used_web_search": False,
                "fallback_reason": fallback_reason or response.error,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
                "api_call_count": 0 if response.provider == "local" else 1,
                "llm_fallback_used": response.fallback_used,
            },
        )

    def _search_with_openai_web(self, query: str, max_results: int) -> list[SourceDocument]:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "The openai package is not installed. Run: pip install -e '.[dev,llm]'"
            ) from exc

        client = OpenAI(api_key=get_settings().openai_api_key)
        if not hasattr(client, "responses"):
            raise RuntimeError("Installed openai package does not expose client.responses")

        prompt = (
            "Use OpenAI web search for the user query below. Return a concise research "
            "summary grounded in current public web sources. Prefer reliable primary or "
            "official sources when available. Include source URLs through the API's web "
            "search citations when possible.\n\n"
            f"User query: {query}"
        )
        response = client.responses.create(
            model=self.model,
            tools=[{"type": "web_search", "search_context_size": "low"}],
            tool_choice={"type": "web_search"},
            input=prompt,
        )
        return self._documents_from_response(
            response=response,
            query=query,
            max_results=max_results,
            tool_type="web_search",
        )

    def _documents_from_response(
        self,
        response: Any,
        query: str,
        max_results: int,
        tool_type: str,
    ) -> list[SourceDocument]:
        output_text = self._response_output_text(response)
        input_tokens, output_tokens = self._usage_tokens(response)
        cost_usd = estimate_openai_cost(self.model, input_tokens, output_tokens)
        web_search_cost = get_settings().openai_web_search_cost_per_call
        used_web_search = self._used_web_search(response)
        if used_web_search and web_search_cost is not None:
            cost_usd = (cost_usd or 0.0) + web_search_cost

        base_metadata = {
            "provider": "openai",
            "model": self.model,
            "query": query,
            "tool_type": tool_type,
            "used_web_search": used_web_search,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "api_call_count": 1,
            "response_excerpt": output_text[:1200],
        }

        citations = self._citations(response)
        documents: list[SourceDocument] = []
        for citation in citations[:max_results]:
            documents.append(
                SourceDocument(
                    title=citation.get("title") or "OpenAI web citation",
                    url=citation.get("url"),
                    snippet=output_text[:700] or "OpenAI web search returned this cited source.",
                    metadata={**base_metadata, "source_type": "openai_web_citation"},
                )
            )

        if documents:
            return documents

        return [
            SourceDocument(
                title=(
                    "OpenAI web-search synthesis"
                    if used_web_search
                    else "OpenAI model synthesis without web citations"
                ),
                url=None,
                snippet=output_text[:1200],
                metadata={
                    **base_metadata,
                    "source_type": (
                        "openai_web_synthesis" if used_web_search else "openai_model_synthesis"
                    ),
                },
            )
        ]

    def _fallback_source(self, query: str, reason: str) -> SourceDocument:
        return SourceDocument(
            title="Search unavailable fallback",
            url=None,
            snippet=(
                "OpenAI research was not executed. The final response must disclose this "
                f"limitation. Reason: {reason}. Query: {query}"
            ),
            metadata={
                "source_type": "fallback",
                "provider": "none",
                "query": query,
                "fallback_reason": reason,
                "used_web_search": False,
                "cost_usd": 0.0,
                "api_call_count": 0,
            },
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
        return "\n".join(parts).strip() or "OpenAI returned an empty research response."

    def _usage_tokens(self, response: Any) -> tuple[int | None, int | None]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None, None
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        return _as_int(input_tokens), _as_int(output_tokens)

    def _used_web_search(self, response: Any) -> bool:
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", None) == "web_search_call":
                return True
        return False

    def _citations(self, response: Any) -> list[dict[str, str | None]]:
        citations: list[dict[str, str | None]] = []
        seen: set[str] = set()
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                for annotation in getattr(content, "annotations", []) or []:
                    annotation_type = getattr(annotation, "type", None)
                    if annotation_type != "url_citation":
                        continue
                    url = getattr(annotation, "url", None)
                    title = getattr(annotation, "title", None)
                    nested = getattr(annotation, "url_citation", None)
                    if nested is not None:
                        url = url or getattr(nested, "url", None)
                        title = title or getattr(nested, "title", None)
                    key = url or title or ""
                    if key and key not in seen:
                        citations.append({"title": title, "url": url})
                        seen.add(key)
        return citations


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
