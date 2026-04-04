"""
tools.py — Tool protocol, registry, and built-in implementations.

ADDING A TOOL (3 steps, this file only):
  1. Implement the Tool protocol (name, description, openai_schema, execute)
  2. Call registry.register(MyTool())
  3. Add the tool name to CONSTRUCTOR_TOOLS or EVALUATOR_TOOLS

Permission enforcement is structural: only tools in the allowed list passed
to run_agent() can be called by that agent. No instruction can expand this.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol, runtime_checkable

import httpx


@runtime_checkable
class Tool(Protocol):
    """Every tool must implement this protocol."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    def openai_schema(self) -> dict[str, Any]: ...

    async def execute(self, arguments: dict[str, Any]) -> str: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_many(self, names: list[str]) -> list[Tool]:
        return [self._tools[n] for n in names if n in self._tools]


registry = ToolRegistry()


# ── Built-in: Web Search (Tavily) ─────────────────────────────────────────────

class WebSearchTool:
    """
    Tavily-backed web search. Replaces DuckDuckGo instant-answer API, which
    silently returns empty results for most evidence retrieval queries.

    Tavily returns actual web results with scored excerpts.
    search_depth "advanced" is used for criterion_establishment (guideline
    lookup) where thoroughness matters; "basic" for ground_retrieval.

    Requires TAVILY_API_KEY in environment.
    """
    name        = "web_search"
    description = (
        "Search the web for current information. "
        "Constructor: use for ground retrieval (case evidence). "
        "Evaluator: use for criterion establishment (current protocols and standards). "
        "Returns scored excerpts from the most relevant results."
    )

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type":        "string",
                            "description": "The search query. Be specific.",
                        },
                        "purpose": {
                            "type": "string",
                            "enum": ["ground_retrieval", "criterion_establishment"],
                            "description": (
                                "ground_retrieval: finding case-specific evidence. "
                                "criterion_establishment: finding current standards or protocols."
                            ),
                        },
                    },
                    "required": ["query", "purpose"],
                },
            },
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        query   = arguments.get("query", "")
        purpose = arguments.get("purpose", "ground_retrieval")
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return f"[{purpose}] Search unavailable: TAVILY_API_KEY not set."
        # Use advanced depth for guideline/standard lookup; basic for evidence retrieval
        depth = "advanced" if purpose == "criterion_establishment" else "basic"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key":        api_key,
                        "query":          query,
                        "search_depth":   depth,
                        "include_answer": True,
                        "max_results":    5,
                    },
                )
                r.raise_for_status()
                data = r.json()

            parts: list[str] = []
            if data.get("answer"):
                parts.append(f"Summary: {data['answer']}")
            for result in data.get("results", [])[:5]:
                title   = result.get("title", "")
                content = result.get("content", "")[:400]
                url     = result.get("url", "")
                parts.append(f"- {title}: {content}")
                if url:
                    parts.append(f"  Source: {url}")

            if parts:
                return f"[{purpose}] Query: {query!r}\n\n" + "\n".join(parts)
            return f"[{purpose}] Query: {query!r}\n\nNo results returned."
        except Exception as e:
            return f"[{purpose}] Search failed: {e}"


# ── Built-in: Document Fetch ──────────────────────────────────────────────────

class DocumentFetchTool:
    name        = "fetch_document"
    description = (
        "Fetch the text content of a specific URL. "
        "Use when you have a direct URL to a guideline, protocol, or standard."
    )

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch."},
                        "excerpt_only": {
                            "type":        "boolean",
                            "description": "Return only the first 2000 chars if true.",
                            "default":     True,
                        },
                    },
                    "required": ["url"],
                },
            },
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        url          = arguments.get("url", "")
        excerpt_only = arguments.get("excerpt_only", True)
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": "Gauntlet/0.2"})
                text = r.text

            import re
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:2000] if excerpt_only else text
        except Exception as e:
            return f"Failed to fetch {url}: {e}"


# ── Register built-ins ────────────────────────────────────────────────────────

web_search     = registry.register(WebSearchTool())
fetch_document = registry.register(DocumentFetchTool())

# Structural permission lists — agents are given one of these
CONSTRUCTOR_TOOLS: list[str] = ["web_search", "fetch_document"]
EVALUATOR_TOOLS:   list[str] = ["web_search", "fetch_document"]
