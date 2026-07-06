"""
Firecrawl intent enrichment for ForgeResonance.

When FIRECRAWL_ENABLED=true and an API key is configured, enriches intent
signals by scraping URLs mentioned in harvested text. Uses the Firecrawl
REST API (same backend as the Firecrawl MCP `firecrawl_scrape` tool).

Gracefully no-ops when disabled or unreachable.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from config import FIRECRAWL_API_KEY, FIRECRAWL_ENABLED
from utils.logging import setup_logging

logger = setup_logging("forge.harvesting.firecrawl")

URL_PATTERN = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)

# Optional injectable scrape function (e.g. wired to Firecrawl MCP in agent runtime)
ScrapeFn = Callable[[str], dict[str, Any] | None]


@dataclass
class EnrichmentResult:
    """Anonymized enrichment metadata — no full page content stored."""

    urls_found: list[str] = field(default_factory=list)
    urls_enriched: list[str] = field(default_factory=list)
    summaries: dict[str, str] = field(default_factory=dict)
    status: str = "skipped"


class FirecrawlEnricher:
    """
    Enriches intent context by scraping URLs found in text.

    Only stores short summaries/hashes in the signal context vector —
    never persists full page content in agent memory.
    """

    def __init__(
        self,
        api_key: str | None = None,
        enabled: bool | None = None,
        scrape_fn: ScrapeFn | None = None,
        max_urls: int = 2,
        summary_max_chars: int = 300,
    ) -> None:
        self._api_key = api_key if api_key is not None else FIRECRAWL_API_KEY
        self._enabled = enabled if enabled is not None else FIRECRAWL_ENABLED
        self._scrape_fn = scrape_fn
        self._max_urls = max_urls
        self._summary_max_chars = summary_max_chars

    @property
    def is_available(self) -> bool:
        return self._enabled and bool(self._api_key or self._scrape_fn)

    @staticmethod
    def extract_urls(text: str) -> list[str]:
        """Extract HTTP(S) URLs from text."""
        return list(dict.fromkeys(URL_PATTERN.findall(text)))[:10]

    def enrich(self, text: str) -> EnrichmentResult:
        """
        Scrape URLs mentioned in text and return anonymized summaries.

        Returns EnrichmentResult with status 'skipped' when Firecrawl is
        disabled or no URLs are present.
        """
        urls = self.extract_urls(text)
        if not urls:
            return EnrichmentResult(status="no_urls")

        if not self._enabled:
            logger.debug("Firecrawl disabled; skipping enrichment")
            return EnrichmentResult(urls_found=urls, status="disabled")

        if not self._api_key and not self._scrape_fn:
            logger.debug("Firecrawl API key not configured; skipping enrichment")
            return EnrichmentResult(urls_found=urls, status="not_configured")

        summaries: dict[str, str] = {}
        enriched: list[str] = []

        for url in urls[: self._max_urls]:
            try:
                data = self._scrape(url)
                if data:
                    snippet = self._extract_summary(data)
                    if snippet:
                        summaries[url] = snippet[: self._summary_max_chars]
                        enriched.append(url)
            except Exception as exc:
                logger.warning("Firecrawl enrichment failed for %s: %s", url, exc)

        status = "enriched" if enriched else "failed"
        logger.info(
            "Firecrawl enrichment: found=%d enriched=%d status=%s",
            len(urls),
            len(enriched),
            status,
        )
        return EnrichmentResult(
            urls_found=urls,
            urls_enriched=enriched,
            summaries=summaries,
            status=status,
        )

    def _scrape(self, url: str) -> dict[str, Any] | None:
        if self._scrape_fn:
            return self._scrape_fn(url)
        return self._scrape_via_api(url)

    def _scrape_via_api(self, url: str) -> dict[str, Any] | None:
        """Call Firecrawl REST API (equivalent to MCP firecrawl_scrape)."""
        body = json.dumps({
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": True,
        }).encode()

        req = urllib.request.Request(
            "https://api.firecrawl.dev/v1/scrape",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode())
            return payload.get("data") or payload
        except urllib.error.URLError as exc:
            logger.warning("Firecrawl API unreachable: %s", exc)
            return None

    @staticmethod
    def _extract_summary(data: dict[str, Any]) -> str:
        """Pull a short summary from scrape response."""
        if "markdown" in data:
            md = str(data["markdown"]).strip()
            return " ".join(md.split()[:50])
        if "summary" in data:
            return str(data["summary"]).strip()
        if "content" in data:
            return str(data["content"])[:300]
        return ""