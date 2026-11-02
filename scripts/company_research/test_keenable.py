"""Offline search and indexed fetch contracts for the Keenable (mode=pro) arm."""
import os
import unittest
from unittest.mock import Mock, patch

from company_research import vendors

ARM = "keenable"
ENV = {"KEENABLE_API_KEY": "test-key"}


def _call(payload, status="ok", status_code=200):
    return vendors.VendorCall(
        status=status, latency_ms=1, raw_request={}, raw_response=payload,
        error=None if status == "ok" else f"HTTP {status_code}",
        attempts=[{"attempt": 1, "status_code": status_code, "latency_ms": 1}], cost_usd=None,
    )


class KeenableSearch(unittest.TestCase):
    def test_request_contract(self):
        with patch.dict(os.environ, ENV), \
                patch.object(vendors, "_request", return_value=_call({"results": []})) as request:
            vendors.search(ARM, "Unchanged question?", max_results=10)
            kwargs = request.call_args.kwargs
            self.assertEqual(kwargs["method"], "POST")
            self.assertEqual(kwargs["url"], "https://api.keenable.ai/v1/search")
            self.assertEqual(kwargs["headers"]["X-API-Key"], "test-key")
            self.assertEqual(kwargs["body"], {
                "query": "Unchanged question?", "mode": "pro", "max_results": 10, "snippet_max_length": 4000,
            })
            vendors.search(ARM, "q", max_results=500)
            self.assertEqual(request.call_args.kwargs["body"]["max_results"], 50)

    def test_parser(self):
        payload = {"results": [
            {"url": "https://a.test", "title": "A", "description": "desc", "snippet": "Snippet evidence",
             "published_at": 1730505600},
            {"url": "https://b.test", "title": "B", "description": "Description fallback", "snippet": ""},
            {"title": "No url", "snippet": "skip"},
            {"url": "https://a.test", "title": "Dup", "snippet": "dup"},
        ]}
        hits = vendors._parse_hits(ARM, payload, 10)
        self.assertEqual([hit["url"] for hit in hits], ["https://a.test", "https://b.test"])
        self.assertEqual(hits[0]["snippet"], "Snippet evidence")
        self.assertEqual(hits[1]["snippet"], "Description fallback")
        self.assertEqual(hits[0]["metadata"], {"published_at": 1730505600})
        self.assertEqual(vendors._parse_hits(ARM, payload, 1)[0]["title"], "A")
        self.assertEqual(vendors._parse_hits(ARM, None, 10), [])
        self.assertEqual(vendors._parse_hits(ARM, {}, 10), [])
        self.assertEqual(vendors._parse_hits(ARM, {"results": None}, 10), [])
        self.assertEqual(vendors._parse_hits(ARM, {"results": {"url": "https://a.test"}}, 10), [])
        odd = vendors._parse_hits(ARM, {"results": [None, "x", 3, {"url": "https://c.test", "snippet": "ok"}]}, 10)
        self.assertEqual([hit["url"] for hit in odd], ["https://c.test"])

    def test_search_cost(self):
        cases = (
            ({"results": [], "usage": {"sku": "search", "credits": 2}}, "ok", 0.008),
            ({"results": []}, "ok", 0.004),
            ({"results": [], "usage": {"credits": "n/a"}}, "ok", 0.004),
            ({"error": "boom"}, "error", 0.0),
        )
        for payload, status, expected in cases:
            with self.subTest(payload=payload), patch.dict(os.environ, ENV), \
                    patch.object(vendors, "_request", return_value=_call(payload, status, 200 if status == "ok" else 500)):
                result = vendors.search(ARM, "q")
                self.assertAlmostEqual(result.cost_usd, expected)


class KeenableFetch(unittest.TestCase):
    def _fetch(self, call, max_chars=12_000):
        with patch.dict(os.environ, ENV), patch.object(vendors, "_assert_public_url"), \
                patch.object(vendors, "_request", return_value=call) as request:
            result = vendors.fetch(ARM, "https://a.test", objective="research", max_chars=max_chars)
        return result, request

    def test_indexed_fetch_contract(self):
        result, request = self._fetch(_call({
            "url": "https://a.test/final", "title": "A", "content": "abcdef", "author": None,
            "published_at": 1730505600, "usage": {"credits": 1},
        }), max_chars=3)
        self.assertEqual(request.call_count, 1)
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["method"], "GET")
        self.assertEqual(kwargs["url"], "https://api.keenable.ai/v1/fetch")
        self.assertEqual(kwargs["headers"]["X-API-Key"], "test-key")
        self.assertEqual(kwargs["params"], {"url": "https://a.test", "max_chars": 3, "live": "false"})
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.page["text"], "abc")
        self.assertEqual(result.page["final_url"], "https://a.test/final")
        self.assertEqual(result.page["fetch_provider"], "keenable_fetch")
        self.assertAlmostEqual(result.cost_usd, 0.004)

    def test_fetch_cost_scales_with_credits(self):
        result, _ = self._fetch(_call({"url": "https://a.test", "content": "page", "usage": {"credits": 2}}))
        self.assertAlmostEqual(result.cost_usd, 0.008)

    def test_not_indexed_is_failed_fetch(self):
        result, request = self._fetch(_call({"detail": "not indexed"}, "error", 404))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.page)
        self.assertEqual(result.cost_usd, 0.0)

    def test_empty_content_is_failed_fetch(self):
        result, request = self._fetch(_call({"url": "https://a.test", "content": ""}))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.page)
        self.assertIn("no page content", result.error)
        self.assertEqual(result.cost_usd, 0.0)


class KeenableRoster(unittest.TestCase):
    def test_roster_and_redaction(self):
        self.assertIn(ARM, vendors.DEFAULT_VENDOR_KEYS)
        self.assertEqual([key for key in vendors.VENDORS if "keenable" in key], [ARM])
        spec = vendors.VENDORS[ARM]
        self.assertEqual(spec.provider_name, "Keenable")
        self.assertTrue(spec.native_fetch)
        self.assertEqual(spec.request_config["mode"], "pro")
        self.assertEqual(spec.env_keys, ("KEENABLE_API_KEY",))
        self.assertEqual(spec.search_unit_cost_usd, 0.004)
        self.assertEqual(spec.fetch_unit_cost_usd, 0.004)
        self.assertEqual(vendors.required_env([ARM]), ["KEENABLE_API_KEY"])
        for header in ("X-API-Key", "x-api-key", "X-API-KEY"):
            self.assertEqual(vendors._redact_headers({header: "secret"})[header], vendors.REDACTED)

    def test_request_helper_redacts_key(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {"results": []}
        call = vendors._request(
            method="POST", url="https://api.keenable.ai/v1/search",
            headers={"X-API-Key": "secret-key", "Content-Type": "application/json"},
            body={"query": "q"}, request_fn=Mock(return_value=response),
        )
        self.assertNotIn("secret-key", str(call.raw_request))


if __name__ == "__main__":
    unittest.main()
