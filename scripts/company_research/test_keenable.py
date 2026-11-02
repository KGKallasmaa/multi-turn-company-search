"""Offline search and native fetch contracts for Keenable pro/realtime."""
import os
import unittest
from unittest.mock import Mock, patch

from company_research import vendors

ARMS = ("keenable_pro", "keenable_realtime")
ENV = {"KEENABLE_API_KEY": "test-key"}


def _call(payload, status="ok", status_code=200):
    return vendors.VendorCall(
        status=status, latency_ms=1, raw_request={}, raw_response=payload,
        error=None if status == "ok" else f"HTTP {status_code}",
        attempts=[{"attempt": 1, "status_code": status_code, "latency_ms": 1}], cost_usd=None,
    )


class KeenableSearch(unittest.TestCase):
    def test_request_contract_per_arm(self):
        for arm, mode in (("keenable_pro", "pro"), ("keenable_realtime", "realtime")):
            with self.subTest(arm=arm), patch.dict(os.environ, ENV), \
                    patch.object(vendors, "_request", return_value=_call({"results": []})) as request:
                vendors.search(arm, "Unchanged question?", max_results=10)
                kwargs = request.call_args.kwargs
                self.assertEqual(kwargs["method"], "POST")
                self.assertEqual(kwargs["url"], "https://api.keenable.ai/v1/search")
                self.assertEqual(kwargs["headers"]["X-API-Key"], "test-key")
                self.assertEqual(kwargs["body"], {
                    "query": "Unchanged question?", "mode": mode, "max_results": 10, "snippet_max_length": 4000,
                })
                vendors.search(arm, "q", max_results=500)
                self.assertEqual(request.call_args.kwargs["body"]["max_results"], 50)

    def test_parser(self):
        payload = {"results": [
            {"url": "https://a.test", "title": "A", "description": "desc", "snippet": "Snippet evidence",
             "published_at": 1730505600},
            {"url": "https://b.test", "title": "B", "description": "Description fallback", "snippet": ""},
            {"title": "No url", "snippet": "skip"},
            {"url": "https://a.test", "title": "Dup", "snippet": "dup"},
        ]}
        for arm in ARMS:
            with self.subTest(arm=arm):
                hits = vendors._parse_hits(arm, payload, 10)
                self.assertEqual([hit["url"] for hit in hits], ["https://a.test", "https://b.test"])
                self.assertEqual(hits[0]["snippet"], "Snippet evidence")
                self.assertEqual(hits[1]["snippet"], "Description fallback")
                self.assertEqual(vendors._parse_hits(arm, payload, 1)[0]["title"], "A")
                self.assertEqual(vendors._parse_hits(arm, None, 10), [])
                self.assertEqual(vendors._parse_hits(arm, {}, 10), [])
                self.assertEqual(vendors._parse_hits(arm, {"results": None}, 10), [])

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
                result = vendors.search("keenable_pro", "q")
                self.assertAlmostEqual(result.cost_usd, expected)


class KeenableFetch(unittest.TestCase):
    def _fetch(self, *calls, max_chars=12_000):
        with patch.dict(os.environ, ENV), patch.object(vendors, "_assert_public_url"), \
                patch.object(vendors, "_request", side_effect=list(calls)) as request:
            result = vendors.fetch("keenable_pro", "https://a.test", objective="research", max_chars=max_chars)
        return result, request

    def test_indexed_ok_no_retry(self):
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
        self.assertEqual([a["live"] for a in result.attempts], [False])

    def test_404_then_live_retry_ok(self):
        result, request = self._fetch(
            _call({"detail": "not indexed"}, "error", 404),
            _call({"url": "https://a.test", "title": "A", "content": "Live page", "published_at": 1730505600}),
        )
        self.assertEqual(request.call_count, 2)
        self.assertEqual([c.kwargs["params"]["live"] for c in request.call_args_list], ["false", "true"])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.page["text"], "Live page")
        self.assertAlmostEqual(result.cost_usd, 0.004)
        self.assertEqual([(a["live"], a["status_code"]) for a in result.attempts], [(False, 404), (True, 200)])

    def test_empty_content_then_live_retry_bills_both(self):
        result, request = self._fetch(
            _call({"url": "https://a.test", "content": ""}),
            _call({"url": "https://a.test", "content": "Live page"}),
        )
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.cost_usd, 0.008)

    def test_both_fail(self):
        result, request = self._fetch(
            _call({"detail": "not indexed"}, "error", 422),
            _call({"detail": "unreachable"}, "error", 404),
        )
        self.assertEqual(request.call_count, 2)
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.page)
        self.assertEqual(result.cost_usd, 0.0)

    def test_non_retryable_error_does_not_go_live(self):
        result, request = self._fetch(_call({"detail": "bad key"}, "error", 401))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.cost_usd, 0.0)


class KeenableRoster(unittest.TestCase):
    def test_roster_and_redaction(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                self.assertIn(arm, vendors.DEFAULT_VENDOR_KEYS)
                spec = vendors.VENDORS[arm]
                self.assertTrue(spec.native_fetch)
                self.assertEqual(spec.env_keys, ("KEENABLE_API_KEY",))
                self.assertEqual(spec.search_unit_cost_usd, 0.004)
                self.assertEqual(spec.fetch_unit_cost_usd, 0.004)
        self.assertEqual(vendors.required_env(ARMS), ["KEENABLE_API_KEY"])
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
