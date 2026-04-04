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


# ── Built-in: Web Search ──────────────────────────────────────────────────────

class WebSearchTool:
    name        = "web_search"
    description = (
        "Search the web for current information. "
        "Constructor: use for ground retrieval (case evidence). "
        "Evaluator: use for criterion establishment (current protocols and standards). "
        "Returns a summary of the most relevant results."
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
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                )
                data = r.json()

            parts: list[str] = []
            if data.get("Abstract"):
                parts.append(f"Summary: {data['Abstract']}")
                if data.get("AbstractURL"):
                    parts.append(f"Source: {data['AbstractURL']}")
            for topic in data.get("RelatedTopics", [])[:4]:
                if isinstance(topic, dict) and topic.get("Text"):
                    parts.append(f"- {topic['Text']}")

            if parts:
                return f"[{purpose}] Query: {query!r}\n\n" + "\n".join(parts)
            return f"[{purpose}] Query: {query!r}\n\nNo direct results. Try a more specific query."
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
