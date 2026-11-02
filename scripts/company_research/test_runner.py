from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from company_research.agent import AgentConfig, AgentResult, run_agent
from company_research.dataset import build_artifact
from company_research.runner import RunnerConfig, execute, runner_plan
from company_research.vendors import (
    VENDORS,
    VendorCall,
    _page,
    _parse_hits,
    capability_inventory,
    fetch,
    parallel_site_policy,
    search,
)


def _dataset(path: Path) -> dict:
    payload = build_artifact(
        {
            "method": "test",
            "items": [
                {
                    "id": "q-1",
                    "question": "Find companies founded after 2020",
                    "family": "other",
                    "constraint_count": 1,
                    "clauses": ["founded after 2020"],
                    "answers": ["Acme"],
                    "answer_domains": {"Acme": "acme.example"},
                }
            ],
        },
        dataset_slug="test-dataset",
        dataset_name="Test dataset",
    )
    path.write_text(json.dumps(payload))
    return payload


class RunnerTest(unittest.TestCase):
    def test_parallel_modes_use_source_policy_for_site_queries(self) -> None:
        fixture = {"results": [{"url": "https://example.test", "title": "Example", "excerpts": ["Evidence"]}]}
        empty_call = VendorCall(
            status="ok", latency_ms=1, raw_request={}, raw_response=fixture,
            error=None, attempts=[], cost_usd=None,
        )
        query = "funding site:Crunchbase.com/org site:https://techcrunch.com/startups -site:reddit.com"
        self.assertEqual(
            parallel_site_policy(query),
            ("funding -site:reddit.com", ["crunchbase.com", "techcrunch.com"]),
        )
        for key, mode in (
            ("parallel_basic", "basic"),
            ("parallel_advanced", "advanced"),
            ("parallel_fast", "fast"),
            ("parallel_turbo", "turbo"),
        ):
            with self.subTest(key=key):
                spec = VENDORS[key]
                self.assertEqual(spec.request_config, {
                    "mode": mode,
                    "site_operator_policy": "source_policy",
                })
                self.assertEqual(
                    spec.search_unit_cost_usd,
                    0.001 if mode in {"fast", "turbo"} else 0.005,
                )
                self.assertTrue(spec.native_fetch)
                self.assertEqual(_parse_hits(key, fixture, 10)[0]["url"], "https://example.test")
                with (
                    patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}),
                    patch("company_research.vendors._request", return_value=empty_call) as request,
                ):
                    search(key, query, max_results=7)
                    body = request.call_args.kwargs["body"]
                    self.assertEqual(body["mode"], mode)
                    self.assertEqual(body["objective"], "funding -site:reddit.com")
                    self.assertEqual(body["search_queries"], ["funding -site:reddit.com"])
                    self.assertEqual(body["advanced_settings"], {
                        "max_results": 7,
                        "source_policy": {
                            "include_domains": ["crunchbase.com", "techcrunch.com"],
                        },
                    })

    def test_parallel_query_without_site_filter_is_unchanged(self) -> None:
        empty_call = VendorCall(
            status="ok", latency_ms=1, raw_request={}, raw_response={"results": []},
            error=None, attempts=[], cost_usd=None,
        )
        with (
            patch.dict(os.environ, {"PARALLEL_API_KEY": "test-key"}),
            patch("company_research.vendors._request", return_value=empty_call) as request,
        ):
            search("parallel_fast", "ordinary company query")
        body = request.call_args.kwargs["body"]
        self.assertEqual(body["objective"], "ordinary company query")
        self.assertNotIn("source_policy", body["advanced_settings"])

    def test_plan_is_local_and_counts_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "dataset.json"
            _dataset(dataset)
            config = RunnerConfig(
                dataset_path=dataset,
                output_dir=root / "runs",
                vendor_keys=("brave",),
                trial_count=3,
                research_mode="search_only",
                agent=AgentConfig(max_fetches=0, max_fetches_per_turn=None),
            )
            plan = runner_plan(config)
            self.assertEqual(plan["planned_agent_runs"], 3)
            self.assertIn("local JSON only", plan["writes"])
            self.assertFalse((root / "runs").exists())

    def test_execute_writes_resumable_trial_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / "dataset.json"
            _dataset(dataset)
            config = RunnerConfig(
                dataset_path=dataset,
                output_dir=root / "runs",
                vendor_keys=("brave",),
                trial_count=2,
                research_mode="search_only",
                agent=AgentConfig(max_fetches=0, max_fetches_per_turn=None),
            )
            response = json.dumps(
                {
                    "companies": [
                        {
                            "name": "Acme",
                            "domain": "acme.example",
                            "cited_urls": ["https://acme.example/about"],
                            "evidence": [
                                {"url": "https://acme.example/about", "claim": "Founded in 2021"}
                            ],
                        }
                    ]
                }
            )

            def fake_run(question, *, vendor_key, client, config):
                return AgentResult(question, vendor_key, response, "ok", None, 10)

            with patch("company_research.runner.run_agent", side_effect=fake_run) as run:
                execute(config, object())
                execute(config, object())
            self.assertEqual(run.call_count, 2)
            paths = sorted((root / "runs").rglob("trial-*.json"))
            self.assertEqual(len(paths), 2)
            artifact = json.loads(paths[0].read_text())
            self.assertEqual(artifact["dataset"]["slug"], "test-dataset")
            self.assertEqual(artifact["parsed_companies"][0]["name"], "Acme")

    def test_search_only_rejects_fetch_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dataset = Path(temporary) / "dataset.json"
            _dataset(dataset)
            with self.assertRaisesRegex(ValueError, "max_fetches=0"):
                runner_plan(
                    RunnerConfig(
                        dataset_path=dataset,
                        vendor_keys=("brave",),
                        research_mode="search_only",
                    )
                )

    def test_vendor_roster_and_fetch_inventory(self) -> None:
        self.assertEqual(
            set(VENDORS),
            {
                "context", "keenable_pro", "keenable_realtime", "nimble_lite", "nimble_standard", "brave", "exa_deep", "exa_instant", "firecrawl", "linkup_fast",
                "linkup_standard", "parallel_advanced", "parallel_basic",
                "parallel_fast", "parallel_turbo", "seltz_companies", "serp",
                "tavily_advanced", "tavily_basic", "you_highlights", "you_highlights_core", "tinyfish", "perplexity",
            },
        )
        capabilities = {row["vendor"]: row for row in capability_inventory()}
        for key in (
            "context", "keenable_pro", "keenable_realtime", "exa_deep", "exa_instant", "firecrawl", "linkup_fast",
            "linkup_standard", "parallel_advanced", "parallel_basic",
            "parallel_fast", "parallel_turbo", "tavily_advanced", "tavily_basic", "you_highlights", "you_highlights_core", "tinyfish",
        ):
            self.assertTrue(capabilities[key]["native_fetch"])
        for key in ("brave", "seltz_companies", "serp", "perplexity"):
            self.assertFalse(capabilities[key]["native_fetch"])
            self.assertTrue(capabilities[key]["custom_fetch"])
        self.assertTrue(all(row["fetch_available"] for row in capabilities.values()))
        self.assertEqual(
            VENDORS["perplexity"].request_config["search_context_size_by_research_mode"],
            {"search_only": "low", "search_and_fetch": "high"},
        )

    def test_every_vendor_response_shape_produces_ranked_hits(self) -> None:
        fixtures = {
            "context": {"results": [{"url": "https://a.test", "title": "A", "description": "fallback",
                                      "highlights": {"code": "SUCCESS", "highlights": ["one"]}}]},
            "brave": {"web": {"results": [{"url": "https://a.test", "title": "A", "description": "one"}]}},
            "exa_deep": {"results": [{"url": "https://a.test", "title": "A", "highlights": ["one"]}]},
            "exa_instant": {"results": [{"url": "https://a.test", "title": "A", "highlights": ["one"]}]},
            "firecrawl": {"data": {"web": [{"url": "https://a.test", "title": "A", "description": "one"}]}},
            "linkup_fast": {"results": [{"url": "https://a.test", "name": "A", "content": "one"}]},
            "linkup_standard": {"results": [{"url": "https://a.test", "name": "A", "content": "one"}]},
            "parallel_advanced": {"results": [{"url": "https://a.test", "title": "A", "excerpts": ["one"]}]},
            "parallel_basic": {"results": [{"url": "https://a.test", "title": "A", "excerpts": ["one"]}]},
            "parallel_fast": {"results": [{"url": "https://a.test", "title": "A", "excerpts": ["one"]}]},
            "parallel_turbo": {"results": [{"url": "https://a.test", "title": "A", "excerpts": ["one"]}]},
            "seltz_companies": {"documents": [{"url": "https://a.test", "title": "A", "content": "one"}]},
            "serp": {"results": [{"url": "https://a.test", "title": "A", "description": "one"}]},
            "tavily_advanced": {"results": [{"url": "https://a.test", "title": "A", "content": "one"}]},
            "tavily_basic": {"results": [{"url": "https://a.test", "title": "A", "content": "one"}]},
            "you_highlights": {"results": {"web": [{"url": "https://a.test", "title": "A", "snippets": ["one"]}]}},
            "tinyfish": {"results": [{"url": "https://a.test", "title": "A", "snippet": "one"}]},
            "perplexity": {"results": [{"url": "https://a.test", "title": "A", "snippet": "one"}]},
        }
        fixtures["you_highlights_core"] = fixtures["you_highlights"]
        fixtures["nimble_lite"] = {"results": [{"url": "https://a.test", "title": "A", "description": "one"}]}
        fixtures["nimble_standard"] = fixtures["nimble_lite"]
        fixtures["keenable_pro"] = {"results": [{"url": "https://a.test", "title": "A", "description": "", "snippet": "one"}]}
        fixtures["keenable_realtime"] = fixtures["keenable_pro"]
        self.assertEqual(set(fixtures), set(VENDORS))
        for vendor, payload in fixtures.items():
            with self.subTest(vendor=vendor):
                self.assertEqual(_parse_hits(vendor, payload, 10)[0]["url"], "https://a.test")
                if vendor == "context":
                    self.assertEqual(_parse_hits(vendor, payload, 10)[0]["snippet"], "one")

    def test_public_board_search_request_contracts(self) -> None:
        fixtures = {
            "you_highlights": ("YOU_API_KEY", "https://ydc-index.io/v1/search", "POST"),
            "tinyfish": ("TINYFISH_API_KEY", "https://api.search.tinyfish.ai", "GET"),
            "perplexity": ("PERPLEXITY_API_KEY", "https://api.perplexity.ai/search", "POST"),
        }
        for vendor, (env_key, endpoint, method) in fixtures.items():
            with self.subTest(vendor=vendor):
                empty_call = VendorCall(
                    status="ok", latency_ms=1, raw_request={}, raw_response={},
                    error=None, attempts=[], cost_usd=None,
                )
                with (
                    patch.dict(os.environ, {env_key: "test-key"}),
                    patch("company_research.vendors._request", return_value=empty_call) as request,
                ):
                    search(vendor, "company query", max_results=7)
                self.assertEqual(request.call_args.kwargs["url"], endpoint)
                self.assertEqual(request.call_args.kwargs["method"], method)

    def test_perplexity_search_context_size_contract(self) -> None:
        for context_size in ("low", "high"):
            with self.subTest(context_size=context_size):
                empty_call = VendorCall("ok", 1, {}, {"results": []}, None, [], None)
                with (
                    patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}),
                    patch("company_research.vendors._request", return_value=empty_call) as request,
                ):
                    search(
                        "perplexity",
                        "company query",
                        search_context_size=context_size,
                    )
                self.assertEqual(
                    request.call_args.kwargs["body"]["search_context_size"],
                    context_size,
                )

    def test_tavily_search_depth_contracts(self) -> None:
        empty_call = VendorCall("ok", 1, {}, {"results": []}, None, [], None)
        for vendor, depth, expected_cost in (
            ("tavily_basic", "basic", 0.008),
            ("tavily_advanced", "advanced", 0.016),
        ):
            with self.subTest(vendor=vendor):
                with (
                    patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}),
                    patch("company_research.vendors._request", return_value=empty_call) as request,
                ):
                    search(vendor, "company query", max_results=7)
                body = request.call_args.kwargs["body"]
                self.assertEqual(body["search_depth"], depth)
                self.assertEqual(body["max_results"], 7)
                self.assertEqual(VENDORS[vendor].search_unit_cost_usd, expected_cost)
                if depth == "advanced":
                    self.assertEqual(body["chunks_per_source"], 3)
                else:
                    self.assertNotIn("chunks_per_source", body)

    def test_public_board_native_fetch_response_shapes(self) -> None:
        fixtures = {
            "you_highlights": [{"url": "https://a.test", "title": "A", "markdown": "one"}],
            "tinyfish": {
                "results": [{
                    "url": "https://a.test",
                    "final_url": "https://a.test/final",
                    "title": "A",
                    "text": "one",
                }],
            },
        }
        for vendor, payload in fixtures.items():
            with self.subTest(vendor=vendor):
                page = _page(vendor, "https://a.test", payload, 12_000)
                self.assertEqual(page["text"], "one")
                self.assertEqual(page["fetch_provider"], VENDORS[vendor].fetch_kind)

    def test_public_board_native_fetch_request_contracts(self) -> None:
        fixtures = {
            "you_highlights": ("YOU_API_KEY", "https://ydc-index.io/v1/contents"),
            "tinyfish": ("TINYFISH_API_KEY", "https://api.fetch.tinyfish.ai"),
        }
        responses = {
            "you_highlights": [{"url": "https://a.test", "markdown": "one"}],
            "tinyfish": {"results": [{"url": "https://a.test", "text": "one"}]},
        }
        for vendor, (env_key, endpoint) in fixtures.items():
            with self.subTest(vendor=vendor):
                vendor_call = VendorCall(
                    status="ok", latency_ms=1, raw_request={}, raw_response=responses[vendor],
                    error=None, attempts=[], cost_usd=None,
                )
                with (
                    patch.dict(os.environ, {env_key: "test-key"}),
                    patch("company_research.vendors._assert_public_url"),
                    patch("company_research.vendors._request", return_value=vendor_call) as request,
                ):
                    result = fetch(vendor, "https://a.test", objective="Find evidence")
                self.assertEqual(result.status, "ok")
                self.assertEqual(request.call_args.kwargs["url"], endpoint)
                self.assertEqual(request.call_args.kwargs["method"], "POST")

        with patch("company_research.vendors.fetch_page", return_value={
            "requested_url": "https://a.test", "final_url": "https://a.test",
            "title": "A", "text": "one", "truncated": False,
            "fetch_provider": "http",
        }) as custom_fetch:
            result = fetch("perplexity", "https://a.test", objective="Find evidence")
        self.assertEqual(result.status, "ok")
        custom_fetch.assert_called_once_with("https://a.test", max_chars=12_000)

    def test_perplexity_context_size_follows_research_mode(self) -> None:
        tool_call = [{
            "type": "function_call", "name": "web_search", "call_id": "call-1",
            "arguments": json.dumps({"query": "focused company query"}),
        }]
        vendor_call = VendorCall("ok", 5, {}, {}, None, [], 0.005, hits=[])
        for config, expected in (
            (AgentConfig(), "high"),
            (AgentConfig(max_fetches=0, max_fetches_per_turn=None), "low"),
        ):
            with self.subTest(context_size=expected):
                client = FakeClient([FakeResponse({}, tool_call), FakeResponse({"companies": []})])
                with patch("company_research.agent.search", return_value=vendor_call) as search_mock:
                    result = run_agent(
                        "Find companies",
                        vendor_key="perplexity",
                        client=client,
                        config=config,
                    )
                self.assertEqual(result.status, "ok")
                search_mock.assert_called_once_with(
                    "perplexity",
                    "focused company query",
                    max_results=10,
                    search_context_size=expected,
                )


class FakeUsage:
    input_tokens = 100
    input_tokens_details = None
    output_tokens = 20


class FakeResponse:
    def __init__(self, payload: dict, output: list[dict] | None = None) -> None:
        self.output = output or []
        self.output_text = json.dumps(payload) if not self.output else ""
        self.usage = FakeUsage()

    def model_dump(self, **_: object) -> dict:
        return {"output": [], "output_text": self.output_text}


class FakeResponses:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.requests: list[dict] = []
        self.responses = list(responses or [])

    def create(self, **request: object) -> FakeResponse:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else FakeResponse({"companies": []})


class FakeClient:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = FakeResponses(responses)


if __name__ == "__main__":
    unittest.main()
