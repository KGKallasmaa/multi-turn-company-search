"""Vendor web-search and vendor-native fetch adapters.

There is deliberately no generic HTTP fallback in this module. A provider
without a documented native fetch endpoint exposes search only until a custom
fetch implementation is designed and reviewed separately.
"""

from __future__ import annotations

import ipaddress
import os
import nimble
import re
import socket
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .custom_fetch import fetch_page


REDACTED = "***REDACTED***"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class VendorSpec:
    key: str
    provider_slug: str
    provider_name: str
    config_slug: str
    endpoint: str
    env_keys: tuple[str, ...]
    search_unit_cost_usd: float | None
    native_fetch: bool
    fetch_endpoint: str | None
    fetch_kind: str | None
    request_config: dict[str, Any]
    fetch_unit_cost_usd: float | None = None
    custom_fetch: bool = False

    @property
    def effective_fetch_unit_cost_usd(self) -> float | None:
        return nimble.extract_price() if self.key.startswith("nimble_") else self.fetch_unit_cost_usd

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["env_keys"] = list(self.env_keys)
        value["fetch_unit_cost_usd"] = self.effective_fetch_unit_cost_usd
        return value


@dataclass
class VendorCall:
    status: str
    latency_ms: int
    raw_request: dict[str, Any]
    raw_response: Any
    error: str | None
    attempts: list[dict[str, Any]]
    cost_usd: float | None
    hits: list[dict[str, Any]] | None = None
    page: dict[str, Any] | None = None


CONTEXT_USD_PER_CREDIT = 0.0022
# $4 / 1,000 requests for search and fetch, checked 2026-11-02 (https://keenable.ai/pricing).
KEENABLE_USD_PER_REQUEST = 0.004
KEENABLE_SEARCH_URL = "https://api.keenable.ai/v1/search"
KEENABLE_FETCH_URL = "https://api.keenable.ai/v1/fetch"


VENDORS: dict[str, VendorSpec] = {
    # Developer top-up: $2.20 / 1,000 credits, checked 2026-10-20.
    # https://www.context.dev/pricing; two credits / 10 results with Highlights, one / Markdown scrape.
    "context": VendorSpec(
        "context", "context", "Context.dev", "context", "POST /v1/web/search",
        ("CONTEXT_API_KEY",), 2 * CONTEXT_USD_PER_CREDIT, True, "GET /v1/web/scrape/markdown", "context_markdown",
        {"highlightsOptions": {"enabled": True, "maxCharacters": 4000}}, fetch_unit_cost_usd=CONTEXT_USD_PER_CREDIT,
    ),
    "brave": VendorSpec(
        "brave", "brave-search", "Brave Search", "brave", "GET /res/v1/web/search",
        ("BRAVE_SEARCH_API_KEY",), 0.005, False, None, None,
        {"count": 10, "result_filter": "web"}, custom_fetch=True,
    ),
    "exa_deep": VendorSpec(
        "exa_deep", "exa-deep", "Exa deep", "exa-deep", "POST /search type=deep",
        ("EXA_API_KEY",), 0.012, True, "POST /contents", "exa_contents",
        {"type": "deep", "contents": {"highlights": True}}, fetch_unit_cost_usd=0.001,
    ),
    "exa_instant": VendorSpec(
        "exa_instant", "exa-instant", "Exa instant", "exa-instant", "POST /search type=instant",
        ("EXA_API_KEY",), 0.007, True, "POST /contents", "exa_contents",
        {"type": "instant", "contents": {"highlights": True}}, fetch_unit_cost_usd=0.001,
    ),
    "firecrawl": VendorSpec(
        "firecrawl", "firecrawl-search", "Firecrawl", "firecrawl", "POST /v2/search",
        ("FIRECRAWL_API_KEY",), 0.005, True, "POST /v2/scrape", "firecrawl_scrape",
        {}, fetch_unit_cost_usd=0.0025,
    ),
    "linkup_fast": VendorSpec(
        "linkup_fast", "linkup-fast", "Linkup fast", "linkup-fast", "POST /v1/search depth=fast",
        ("LINKUP_API_KEY",), 0.005, True, "POST /v1/fetch", "linkup_fetch",
        {"depth": "fast", "outputType": "searchResults"}, fetch_unit_cost_usd=0.001,
    ),
    "linkup_standard": VendorSpec(
        "linkup_standard", "linkup-standard", "Linkup standard", "linkup-standard",
        "POST /v1/search depth=standard", ("LINKUP_API_KEY",), 0.005, True,
        "POST /v1/fetch", "linkup_fetch",
        {"depth": "standard", "outputType": "searchResults"}, fetch_unit_cost_usd=0.001,
    ),
    "parallel_advanced": VendorSpec(
        "parallel_advanced", "parallel-advanced", "Parallel advanced", "parallel-advanced",
        "POST /v1/search mode=advanced", ("PARALLEL_API_KEY",), 0.005, True,
        "POST /v1/extract", "parallel_extract",
        {"mode": "advanced", "site_operator_policy": "source_policy"}, fetch_unit_cost_usd=0.001,
    ),
    "parallel_basic": VendorSpec(
        "parallel_basic", "parallel-basic", "Parallel basic", "parallel-basic",
        "POST /v1/search mode=basic", ("PARALLEL_API_KEY",), 0.005, True,
        "POST /v1/extract", "parallel_extract",
        {"mode": "basic", "site_operator_policy": "source_policy"}, fetch_unit_cost_usd=0.001,
    ),
    "parallel_fast": VendorSpec(
        "parallel_fast", "parallel-fast", "Parallel fast", "parallel-fast",
        "POST /v1/search mode=fast", ("PARALLEL_API_KEY",), 0.001, True,
        "POST /v1/extract", "parallel_extract",
        {"mode": "fast", "site_operator_policy": "source_policy"}, fetch_unit_cost_usd=0.001,
    ),
    "parallel_turbo": VendorSpec(
        "parallel_turbo", "parallel-turbo", "Parallel turbo", "parallel-turbo",
        "POST /v1/search mode=turbo", ("PARALLEL_API_KEY",), 0.001, True,
        "POST /v1/extract", "parallel_extract",
        {"mode": "turbo", "site_operator_policy": "source_policy"}, fetch_unit_cost_usd=0.001,
    ),
    "seltz_companies": VendorSpec(
        "seltz_companies", "seltz-companies", "Seltz companies", "seltz-companies",
        "POST /v1/search scope=companies", ("SELTZ_API_KEY",), 0.005, False, None, None,
        {"scope": "companies"}, custom_fetch=True,
    ),
    "serp": VendorSpec(
        "serp", "serp-rapidapi", "SERP (RapidAPI)", "serp", "GET google-search74.p.rapidapi.com",
        ("RAPIDAPI_KEY",), 0.003, False, None, None, {"limit": 10}, custom_fetch=True,
    ),
    "tavily_advanced": VendorSpec(
        "tavily_advanced", "tavily-advanced", "Tavily advanced", "tavily-advanced",
        "POST /search search_depth=advanced", ("TAVILY_API_KEY",), 0.016, True,
        "POST /extract", "tavily_extract",
        {"search_depth": "advanced", "chunks_per_source": 3}, fetch_unit_cost_usd=0.0032,
    ),
    "tavily_basic": VendorSpec(
        "tavily_basic", "tavily-basic", "Tavily basic", "tavily-basic",
        "POST /search search_depth=basic", ("TAVILY_API_KEY",), 0.008, True,
        "POST /extract", "tavily_extract",
        {"search_depth": "basic"}, fetch_unit_cost_usd=0.0016,
    ),
    "tinyfish": VendorSpec(
        "tinyfish", "tinyfish-search", "TinyFish", "tinyfish",
        "GET api.search.tinyfish.ai", ("TINYFISH_API_KEY",), 0.0, True,
        "POST api.fetch.tinyfish.ai", "tinyfish_fetch", {}, fetch_unit_cost_usd=0.0,
    ),
    "perplexity": VendorSpec(
        "perplexity", "perplexity-search", "Perplexity", "perplexity",
        "POST /search", ("PERPLEXITY_API_KEY",), 0.005, False, None, None,
        {
            "max_results": 10,
            "search_context_size_by_research_mode": {
                "search_only": "low",
                "search_and_fetch": "high",
            },
        },
        custom_fetch=True,
    ),
}

for _depth, _price in nimble.SEARCH_PRICES.items():
    _key = f"nimble_{_depth}"
    VENDORS[_key] = VendorSpec(
        _key, f"nimble-{_depth}", f"Nimble {_depth}", f"nimble-{_depth}",
        f"POST /v2/search search_depth={_depth} full_content=false",
        ("NIMBLE_API_KEY",), _price, True, "POST /v2/extract", "nimble_extract",
        {"search_depth": _depth, "full_content": False, "focus": "general"},
    )

for _core in (False, True):
    _key = "you_highlights_core" if _core else "you_highlights"
    _slug = _key.replace("_", "-")
    VENDORS[_key] = VendorSpec(
        _key, _slug, "You highlights core" if _core else "You highlights", _slug,
        "POST /v1/search", ("YOU_API_KEY",), 0.005, True,
        "POST /v1/contents", "you_contents",
        {"count": 10, "extraction": {"extraction_mode": "highlights"},
         **({"knowledge": "core"} if _core else {})}, fetch_unit_cost_usd=0.001,
    )

# Standard index-based config: mode=pro search, indexed fetch (live=false).
VENDORS["keenable"] = VendorSpec(
    "keenable", "keenable", "Keenable", "keenable",
    "POST /v1/search mode=pro", ("KEENABLE_API_KEY",), KEENABLE_USD_PER_REQUEST, True,
    "GET /v1/fetch live=false", "keenable_fetch",
    {"mode": "pro", "snippet_max_length": 4000}, fetch_unit_cost_usd=KEENABLE_USD_PER_REQUEST,
)

DEFAULT_VENDOR_KEYS = tuple(VENDORS)


def capability_inventory() -> list[dict[str, Any]]:
    return [
        {
            "vendor": spec.key,
            "search": True,
            "native_fetch": spec.native_fetch,
            "fetch_kind": spec.fetch_kind,
            "custom_fetch": spec.custom_fetch,
            "fetch_available": spec.native_fetch or spec.custom_fetch,
        }
        for spec in VENDORS.values()
    ]


def required_env(vendor_keys: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({key for vendor in vendor_keys for key in VENDORS[vendor].env_keys})


def validate_vendor_keys(vendor_keys: list[str] | tuple[str, ...]) -> None:
    unknown = sorted(set(vendor_keys) - set(VENDORS))
    if unknown:
        raise ValueError(f"unknown company-research vendors: {unknown}")


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: REDACTED if any(token in key.lower() for token in ("key", "token", "authorization", "secret")) else value
        for key, value in headers.items()
    }


def _json_or_text(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"_raw": str(getattr(response, "text", ""))[:100_000]}


def _request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 90,
    retries: int = 3,
    request_fn: Callable[..., Any] = requests.request,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> VendorCall:
    started = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    payload: Any = None
    error: str | None = None
    for attempt in range(1, retries + 2):
        attempt_started = time.perf_counter()
        try:
            response = request_fn(
                method=method, url=url, headers=headers, json=body, params=params, timeout=timeout
            )
            payload = _json_or_text(response)
            attempts.append({
                "attempt": attempt,
                "status_code": response.status_code,
                "latency_ms": round((time.perf_counter() - attempt_started) * 1000),
            })
            if response.ok:
                error = None
                break
            error = f"HTTP {response.status_code}: {str(payload)[:500]}"
            if response.status_code not in RETRYABLE_STATUS or attempt > retries:
                break
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            attempts.append({
                "attempt": attempt,
                "status_code": None,
                "latency_ms": round((time.perf_counter() - attempt_started) * 1000),
                "error": error,
            })
            if attempt > retries:
                break
        sleep_fn(min(2 ** (attempt - 1), 8))
    return VendorCall(
        status="ok" if error is None else "error",
        latency_ms=round((time.perf_counter() - started) * 1000),
        raw_request={
            "method": method,
            "url": url,
            "headers": _redact_headers(headers),
            "body": body,
            "params": params,
        },
        raw_response=payload,
        error=error,
        attempts=attempts,
        cost_usd=None,
    )


def _hit(url: Any, title: Any, snippet: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "url": str(url or ""),
        "title": str(title or ""),
        "snippet": str(snippet or "")[:4000],
        "metadata": metadata or {},
    }


def _dedupe(hits: list[dict[str, Any]], max_results: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        url = hit["url"].strip()
        if not url or url in seen:
            continue
        seen.add(url)
        output.append(hit)
        if len(output) >= max_results:
            break
    return output


def _keenable_cost(payload: Any) -> float:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    credits = usage.get("credits") if isinstance(usage, dict) else None
    if isinstance(credits, (int, float)) and not isinstance(credits, bool) and credits >= 0:
        return credits * KEENABLE_USD_PER_REQUEST
    return KEENABLE_USD_PER_REQUEST


def _keenable_headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["KEENABLE_API_KEY"], "Content-Type": "application/json"}


def _reported_dollar_cost(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    cost = payload.get("costDollars")
    candidate = cost.get("total") if isinstance(cost, dict) else None
    if candidate is None and isinstance(payload.get("usage"), dict):
        candidate = payload["usage"].get("total_cost_usd")
    try:
        total = float(candidate)
    except (TypeError, ValueError):
        return None
    return total if total >= 0 else None


_SITE_INCLUDE_RE = re.compile(r"(?<![-])site:([^\s]+)", re.I)


def parallel_site_policy(query: str) -> tuple[str, list[str]]:
    """Move positive site: filters to Parallel's include_domains policy."""
    domains: list[str] = []
    seen: set[str] = set()

    def take(match: re.Match[str]) -> str:
        raw = match.group(1).strip("\"'").rstrip("/")
        raw = re.sub(r"^https?://", "", raw, flags=re.I).removeprefix("www.")
        host = raw.split("/", 1)[0].strip(".").lower()
        if host and host not in seen:
            seen.add(host)
            domains.append(host)
        return " "

    cleaned = re.sub(r"\s+", " ", _SITE_INCLUDE_RE.sub(take, query)).strip()
    return cleaned, domains


def _parse_hits(vendor_key: str, payload: Any, max_results: int) -> list[dict[str, Any]]:
    payload = payload if isinstance(payload, dict) else {}
    hits: list[dict[str, Any]] = []
    if vendor_key.startswith("nimble_"):
        return _dedupe([_hit(h["url"], h["title"], h["snippet"]) for h in nimble.search_hits(payload, max_results)], max_results)
    if vendor_key == "context":
        for item in payload.get("results") or []:
            highlights = item.get("highlights") or {}
            parts = highlights.get("highlights") or []
            snippet = "\n".join(part for part in parts if isinstance(part, str)) if highlights.get("code") == "SUCCESS" else ""
            hits.append(_hit(item.get("url"), item.get("title"), snippet.strip() or item.get("description")))
    elif vendor_key == "keenable":
        results = payload.get("results")
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                continue
            hits.append(_hit(
                item.get("url"), item.get("title"), item.get("snippet") or item.get("description"),
                {"published_at": item.get("published_at")},
            ))
    elif vendor_key.startswith("parallel_"):
        for item in payload.get("results") or []:
            excerpts = item.get("excerpts") or []
            hits.append(_hit(item.get("url"), item.get("title"), "\n".join(x for x in excerpts if isinstance(x, str))))
    elif vendor_key.startswith("exa_"):
        for item in payload.get("results") or []:
            highlights = item.get("highlights") or []
            snippet = " ".join(x for x in highlights if isinstance(x, str)) or item.get("text")
            hits.append(_hit(item.get("url"), item.get("title"), snippet))
    elif vendor_key == "firecrawl":
        data = payload.get("data") or {}
        rows = (data.get("web") or data.get("results") or []) if isinstance(data, dict) else data
        for item in rows or []:
            hits.append(_hit(item.get("url") or item.get("link"), item.get("title"), item.get("description") or item.get("snippet")))
    elif vendor_key == "brave":
        for item in (payload.get("web") or {}).get("results") or []:
            hits.append(_hit(item.get("url"), item.get("title"), item.get("description") or item.get("snippet")))
    elif vendor_key.startswith("linkup_"):
        for item in payload.get("results") or []:
            if item.get("type") != "image":
                hits.append(_hit(item.get("url"), item.get("name") or item.get("title"), item.get("content") or item.get("snippet")))
    elif vendor_key == "seltz_companies":
        for item in payload.get("documents") or []:
            hits.append(_hit(item.get("url"), item.get("title") or item.get("name"), item.get("content") or item.get("snippet"), {"domain": item.get("domain")}))
    elif vendor_key == "serp":
        for item in payload.get("results") or []:
            hits.append(_hit(item.get("url") or item.get("link"), item.get("title"), item.get("description") or item.get("snippet")))
    elif vendor_key.startswith("tavily_"):
        for item in payload.get("results") or []:
            hits.append(_hit(item.get("url"), item.get("title"), item.get("content"), {"score": item.get("score")}))
    elif vendor_key in {"you_highlights", "you_highlights_core"}:
        results = payload.get("results") or {}
        for item in results.get("web") or []:
            contents = item.get("contents") or {}
            snippets = contents.get("highlights") or item.get("snippets") or []
            snippet = "\n".join(value for value in snippets if isinstance(value, str))
            hits.append(_hit(
                item.get("url"), item.get("title"), snippet or item.get("description"),
                {"page_age": item.get("page_age")},
            ))
    elif vendor_key == "tinyfish":
        for item in payload.get("results") or []:
            hits.append(_hit(
                item.get("url"), item.get("title"), item.get("snippet"),
                {"site_name": item.get("site_name"), "date": item.get("date")},
            ))
    elif vendor_key == "perplexity":
        for item in payload.get("results") or []:
            hits.append(_hit(
                item.get("url"), item.get("title"), item.get("snippet"),
                {"date": item.get("date"), "last_updated": item.get("last_updated")},
            ))
    return _dedupe(hits, max_results)


def search(
    vendor_key: str,
    query: str,
    *,
    max_results: int = 10,
    search_context_size: str | None = None,
) -> VendorCall:
    spec = VENDORS[vendor_key]
    if vendor_key == "context":
        call = _request(
            method="POST", url="https://api.context.dev/v1/web/search",
            headers={"Authorization": f"Bearer {os.environ['CONTEXT_API_KEY']}", "Content-Type": "application/json"},
            body={**spec.request_config, "query": query, "numResults": max(10, min(max_results, 100))},
        )
    elif vendor_key == "keenable":
        call = _request(
            method="POST", url=KEENABLE_SEARCH_URL, headers=_keenable_headers(),
            body={**spec.request_config, "query": query, "max_results": max(1, min(max_results, 50))},
        )
    elif vendor_key.startswith("nimble_"):
        call = _request(
            method="POST", url=nimble.SEARCH_URL,
            headers={"Authorization": f"Bearer {os.environ['NIMBLE_API_KEY']}", "Content-Type": "application/json"},
            body=nimble.search_body(query, spec.request_config["search_depth"], max_results),
        )
    elif vendor_key.startswith("parallel_"):
        mode = str(spec.request_config["mode"])
        sent_query = query
        advanced_settings: dict[str, Any] = {"max_results": max_results}
        if spec.request_config.get("site_operator_policy") == "source_policy":
            sent_query, include_domains = parallel_site_policy(query)
            if not sent_query:
                sent_query = " ".join(include_domains) or query
            if include_domains:
                advanced_settings["source_policy"] = {"include_domains": include_domains}
        call = _request(
            method="POST", url="https://api.parallel.ai/v1/search",
            headers={"x-api-key": os.environ["PARALLEL_API_KEY"], "Content-Type": "application/json"},
            body={
                "objective": sent_query,
                "search_queries": [sent_query],
                "mode": mode,
                "advanced_settings": advanced_settings,
            },
            timeout=120 if mode == "advanced" else 60,
        )
    elif vendor_key.startswith("exa_"):
        kind = vendor_key.removeprefix("exa_")
        call = _request(
            method="POST", url="https://api.exa.ai/search",
            headers={"x-api-key": os.environ["EXA_API_KEY"], "Content-Type": "application/json"},
            body={"query": query, "type": kind, "numResults": max_results, "contents": {"highlights": True}},
            timeout=120 if kind == "deep" else 60,
        )
    elif vendor_key == "firecrawl":
        call = _request(
            method="POST", url="https://api.firecrawl.dev/v2/search",
            headers={"Authorization": f"Bearer {os.environ['FIRECRAWL_API_KEY']}", "Content-Type": "application/json"},
            body={"query": query, "limit": max_results},
        )
    elif vendor_key == "brave":
        call = _request(
            method="GET", url="https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": os.environ["BRAVE_SEARCH_API_KEY"], "Accept": "application/json"},
            params={"q": query, "count": min(max_results, 20), "result_filter": "web"},
            timeout=45,
        )
    elif vendor_key.startswith("linkup_"):
        depth = vendor_key.removeprefix("linkup_")
        call = _request(
            method="POST", url="https://api.linkup.so/v1/search",
            headers={"Authorization": f"Bearer {os.environ['LINKUP_API_KEY']}", "Content-Type": "application/json"},
            body={"q": query, "depth": depth, "outputType": "searchResults", "maxResults": max_results},
        )
    elif vendor_key == "seltz_companies":
        call = _request(
            method="POST", url="https://api.seltz.ai/v1/search",
            headers={"x-api-key": os.environ["SELTZ_API_KEY"], "Content-Type": "application/json"},
            body={"query": query, "max_results": max_results, "scope": "companies"},
            timeout=45,
        )
    elif vendor_key == "serp":
        call = _request(
            method="GET", url="https://google-search74.p.rapidapi.com/",
            headers={"x-rapidapi-key": os.environ["RAPIDAPI_KEY"], "x-rapidapi-host": "google-search74.p.rapidapi.com"},
            params={"query": query, "limit": max_results}, timeout=45,
        )
    elif vendor_key.startswith("tavily_"):
        search_depth = str(spec.request_config["search_depth"])
        body = {"query": query, "search_depth": search_depth, "max_results": max_results}
        if search_depth == "advanced":
            body["chunks_per_source"] = int(spec.request_config["chunks_per_source"])
        call = _request(
            method="POST", url="https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}", "Content-Type": "application/json"},
            body=body,
        )
    elif vendor_key in {"you_highlights", "you_highlights_core"}:
        call = _request(
            method="POST", url="https://ydc-index.io/v1/search",
            headers={"X-API-Key": os.environ["YOU_API_KEY"], "Content-Type": "application/json"},
            body={**spec.request_config, "query": query, "count": min(max_results, 20)},
        )
    elif vendor_key == "tinyfish":
        call = _request(
            method="GET", url="https://api.search.tinyfish.ai",
            headers={"X-API-Key": os.environ["TINYFISH_API_KEY"], "Accept": "application/json"},
            params={"query": query}, timeout=45,
        )
    elif vendor_key == "perplexity":
        if search_context_size not in {None, "low", "medium", "high"}:
            raise ValueError("Perplexity search_context_size must be low, medium, or high")
        call = _request(
            method="POST", url="https://api.perplexity.ai/search",
            headers={"Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}", "Content-Type": "application/json"},
            body={
                "query": query,
                "max_results": min(max_results, 20),
                "search_context_size": search_context_size or "high",
            },
        )
    else:  # pragma: no cover - registry and dispatcher change together
        raise KeyError(vendor_key)
    reported_cost = _reported_dollar_cost(call.raw_response)
    call.cost_usd = (
        reported_cost if reported_cost is not None else spec.search_unit_cost_usd
    ) if call.status == "ok" else 0.0
    if vendor_key == "context":
        payload = call.raw_response if isinstance(call.raw_response, dict) else {}
        credits = (payload.get("key_metadata") or {}).get("credits_consumed")
        call.cost_usd = credits * CONTEXT_USD_PER_CREDIT if isinstance(credits, (int, float)) else None
    if vendor_key == "keenable" and call.status == "ok":
        call.cost_usd = _keenable_cost(call.raw_response)
    call.hits = _parse_hits(vendor_key, call.raw_response, max_results) if call.status == "ok" else []
    return call


def _assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("web_fetch requires a public absolute http(s) URL")
    if parsed.hostname.lower() == "localhost":
        raise ValueError("web_fetch blocks localhost and private networks")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("web_fetch blocks localhost and private networks")


def _page(vendor_key: str, url: str, payload: Any, max_chars: int) -> dict[str, Any]:
    raw_payload = payload
    payload = payload if isinstance(payload, dict) else {}
    if vendor_key.startswith("nimble_"):
        return nimble.extract_page(payload, url, max_chars)
    if vendor_key == "context":
        if payload.get("success") is not True:
            raise RuntimeError("context native fetch failed")
        metadata = payload.get("metadata") or {}
        text = payload.get("markdown") or ""
        final_url, title = metadata.get("finalUrl") or payload.get("url") or url, metadata.get("title") or ""
    elif vendor_key == "keenable":
        text, final_url, title = payload.get("content") or "", payload.get("url") or url, payload.get("title") or ""
    elif vendor_key.startswith("parallel_"):
        item = (payload.get("results") or [{}])[0]
        text = item.get("full_content") or "\n".join(item.get("excerpts") or [])
        final_url, title = item.get("url") or url, item.get("title") or ""
    elif vendor_key.startswith("exa_"):
        item = (payload.get("results") or [{}])[0]
        text, final_url, title = item.get("text") or "", item.get("url") or url, item.get("title") or ""
    elif vendor_key == "firecrawl":
        item = payload.get("data") or {}
        metadata = item.get("metadata") or {}
        text, final_url, title = item.get("markdown") or "", metadata.get("sourceURL") or url, metadata.get("title") or ""
    elif vendor_key.startswith("tavily_"):
        item = (payload.get("results") or [{}])[0]
        text, final_url, title = item.get("raw_content") or item.get("content") or "", item.get("url") or url, ""
    elif vendor_key.startswith("linkup_"):
        text, final_url, title = payload.get("markdown") or "", url, ""
    elif vendor_key in {"you_highlights", "you_highlights_core"}:
        item = (raw_payload if isinstance(raw_payload, list) else [{}])[0]
        text = item.get("markdown") or item.get("html") or ""
        final_url, title = item.get("url") or url, item.get("title") or ""
    elif vendor_key == "tinyfish":
        item = (payload.get("results") or [{}])[0]
        text = item.get("text") or ""
        final_url, title = item.get("final_url") or item.get("url") or url, item.get("title") or ""
    else:
        raise RuntimeError(f"{vendor_key} has no vendor-native fetch adapter")
    if not str(text).strip():
        raise RuntimeError(f"{vendor_key} native fetch returned no page content")
    return {
        "requested_url": url,
        "final_url": str(final_url),
        "title": str(title),
        "text": str(text)[:max_chars],
        "truncated": len(str(text)) > max_chars,
        "fetch_provider": VENDORS[vendor_key].fetch_kind,
    }


def fetch(vendor_key: str, url: str, *, objective: str, max_chars: int = 12_000) -> VendorCall:
    spec = VENDORS[vendor_key]
    if spec.custom_fetch:
        started = time.perf_counter()
        try:
            page = fetch_page(url, max_chars=max_chars)
            return VendorCall(
                status="ok", latency_ms=round((time.perf_counter() - started) * 1000),
                raw_request={"url": url, "fetch_kind": "custom_http_with_playwright_fallback"},
                raw_response=page, error=None,
                attempts=[{"attempt": 1, "provider": page["fetch_provider"]}],
                cost_usd=0.0, page=page,
            )
        except Exception as exc:  # noqa: BLE001
            return VendorCall(
                status="error", latency_ms=round((time.perf_counter() - started) * 1000),
                raw_request={"url": url, "fetch_kind": "custom_http_with_playwright_fallback"},
                raw_response=None, error=f"{type(exc).__name__}: {exc}",
                attempts=[], cost_usd=0.0,
            )
    if not spec.native_fetch:
        return VendorCall(
            status="unavailable", latency_ms=0,
            raw_request={"url": url, "vendor": vendor_key}, raw_response=None,
            error="vendor-native web_fetch is unavailable; custom fetch is intentionally not implemented",
            attempts=[], cost_usd=None,
        )
    _assert_public_url(url)
    if vendor_key == "keenable":
        call = _request(
            method="GET", url=KEENABLE_FETCH_URL, headers=_keenable_headers(),
            params={"url": url, "max_chars": max_chars, "live": "false"},
        )
    elif vendor_key == "context":
        call = _request(
            method="GET", url="https://api.context.dev/v1/web/scrape/markdown",
            headers={"Authorization": f"Bearer {os.environ['CONTEXT_API_KEY']}"},
            params={"url": url, "useMainContentOnly": "true"}, timeout=120,
        )
    elif vendor_key.startswith("nimble_"):
        nimble.extract_price()  # Validate an optional rate before issuing the call.
        call = _request(
            method="POST", url=nimble.EXTRACT_URL,
            headers={"Authorization": f"Bearer {os.environ['NIMBLE_API_KEY']}", "Content-Type": "application/json"},
            body={"url": url, "formats": ["markdown"]}, timeout=90,
        )
    elif vendor_key.startswith("parallel_"):
        call = _request(
            method="POST", url="https://api.parallel.ai/v1/extract",
            headers={"x-api-key": os.environ["PARALLEL_API_KEY"], "Content-Type": "application/json"},
            body={"urls": [url], "objective": objective, "max_chars_total": max_chars, "advanced_settings": {"full_content": True}},
            timeout=120,
        )
    elif vendor_key.startswith("exa_"):
        call = _request(
            method="POST", url="https://api.exa.ai/contents",
            headers={"x-api-key": os.environ["EXA_API_KEY"], "Content-Type": "application/json"},
            body={"urls": [url], "text": {"maxCharacters": max_chars, "includeHtmlTags": False}},
        )
    elif vendor_key == "firecrawl":
        call = _request(
            method="POST", url="https://api.firecrawl.dev/v2/scrape",
            headers={"Authorization": f"Bearer {os.environ['FIRECRAWL_API_KEY']}", "Content-Type": "application/json"},
            body={"url": url, "formats": ["markdown"], "onlyMainContent": True},
        )
    elif vendor_key.startswith("tavily_"):
        call = _request(
            method="POST", url="https://api.tavily.com/extract",
            headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}", "Content-Type": "application/json"},
            body={"urls": [url], "extract_depth": spec.request_config["search_depth"]},
        )
    elif vendor_key.startswith("linkup_"):
        call = _request(
            method="POST", url="https://api.linkup.so/v1/fetch",
            headers={"Authorization": f"Bearer {os.environ['LINKUP_API_KEY']}", "Content-Type": "application/json"},
            body={"url": url, "mode": "standard", "renderJs": False},
        )
    elif vendor_key in {"you_highlights", "you_highlights_core"}:
        call = _request(
            method="POST", url="https://ydc-index.io/v1/contents",
            headers={"X-API-Key": os.environ["YOU_API_KEY"], "Content-Type": "application/json"},
            body={"urls": [url], "formats": ["markdown", "metadata"]},
        )
    elif vendor_key == "tinyfish":
        call = _request(
            method="POST", url="https://api.fetch.tinyfish.ai",
            headers={"X-API-Key": os.environ["TINYFISH_API_KEY"], "Content-Type": "application/json"},
            body={"urls": [url], "purpose": objective, "format": "markdown"},
            timeout=120,
        )
    else:  # pragma: no cover
        raise KeyError(vendor_key)
    if call.status == "ok":
        try:
            call.page = _page(vendor_key, url, call.raw_response, max_chars)
        except Exception as exc:  # noqa: BLE001
            call.status = "error"
            call.error = f"{type(exc).__name__}: {exc}"
    reported_cost = _reported_dollar_cost(call.raw_response)
    call.cost_usd = (
        reported_cost if reported_cost is not None else spec.effective_fetch_unit_cost_usd
    ) if call.status == "ok" else 0.0
    if vendor_key == "context":
        payload = call.raw_response if isinstance(call.raw_response, dict) else {}
        credits = (payload.get("key_metadata") or {}).get("credits_consumed")
        call.cost_usd = credits * CONTEXT_USD_PER_CREDIT if isinstance(credits, (int, float)) else None
    if vendor_key == "keenable" and call.status == "ok":
        call.cost_usd = _keenable_cost(call.raw_response)
    return call
