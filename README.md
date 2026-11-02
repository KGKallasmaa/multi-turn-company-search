# Web Search API Benchmark for AI Agents on Multi Hop Search Task

Open, independent benchmark on web search APIs for deep research agents. Unlike
BrowseComp, this is a benchmark on real user workflows that are not memorized by
models. Vendors measured: Exa, Parallel, Perplexity, Linkup, Tavily, Firecrawl,
Brave Search, You, Nimble, TinyFish, Seltz, and a Google SERP API. Scored on precision,
recall, F1, and exact-set accuracy over multi-constraint company discovery. Open
source code + open data. The agent is held constant; only the search
configuration changes.

**Live leaderboard:** [https://openbenchmarks.com/multi-turn-company-search](https://openbenchmarks.com/multi-turn-company-search)
**Public dataset:** [`openbenchmarks/OB-Company-Websearch`](https://huggingface.co/datasets/openbenchmarks/OB-Company-Websearch)

Published and maintained by **[OpenBenchmarks Labs](https://openbenchmarks.com)**.

This repo is the open runner and judge behind that page. It contains the fixed
agent, all measured vendor adapters, the local run-artifact contract, and the
deterministic offline scorer. It does not require a hosted database: the runner
reads one frozen dataset JSON file and writes one immutable JSON artifact per
trial under `runs/`.

## Why not BrowseComp

We evaluate web search APIs, so the answer has to be found, not recalled.
BrowseComp is a static browsing-agent set and models have trained on it.
LiveBrowseComp ([Fan et al., 2026](https://arxiv.org/abs/2605.28721)) shows agents
answer up to 44.5% of BrowseComp with no search tools at all, which means the
benchmark rewards memory-backed verification rather than evidence-driven
discovery.

This board is the alternative. Every question combines three or four constraints
such as headquarters, investor backing, accelerator participation, founding
period, or funding history. A correct set has to be assembled from several
searches.

Model-only baseline: with no search tool at all, GPT-5.6-sol scores F1 20.1% on
the private set (precision 30.0%, recall 18.7%).

Two boards are reported separately, because search-result quality and
page-retrieval quality are different products:

- **Search only.** The agent can issue focused searches and read normalized
titles, URLs, and snippets, but cannot fetch page text.
- **Search + fetch.** The same agent can fetch an exact URL returned by search,
using the provider's native extraction endpoint where available and a bounded
local HTTP/Playwright fetcher otherwise.



## Which web search API is most accurate for company search?

**Parallel basic** leads search-only at 46.5 F1; **Exa deep** leads search + fetch
at 48.2 F1. Rows are ranked by mean F1, then mean precision, across 45 questions
and 3 independent trials, with the agent fixed at `gpt-5.6-sol`.

Precision runs far ahead of recall on every row. The hard part of this task is
completeness, not correctness: agents return companies that genuinely satisfy the
constraints, then stop early and miss the rest.

### Search only


| # | Provider | Configuration | F1 | Precision | Recall | Exact set | Median time | Median cost |
| --- | ----------------- | --- | ---------- | --------- | ------ | --------- | ----------- | ----------- |
| 1 | Parallel basic | `mode=basic` | 46.5 ± 1.9 | 88.7 | 34.4 | 3.7 | 67.6s | $1.120 |
| 2 | Exa deep | `type=deep` | 45.4 ± 2.0 | 83.2 | 33.7 | 1.5 | 89.5s | $0.717 |
| 3 | Parallel advanced | `mode=advanced` | 44.2 ± 1.4 | 87.6 | 32.0 | 2.2 | 83.4s | $0.625 |
| 4 | Exa instant | `type=instant` | 43.3 ± 1.0 | 82.6 | 32.2 | 3.0 | 49.8s | $0.652 |
| 5 | Linkup fast | `depth=fast` | 41.1 ± 1.7 | 82.8 | 30.3 | 0.7 | 64.2s | $0.923 |
| 6 | Tavily advanced | `search_depth=advanced` | 41.1 ± 2.3 | 83.7 | 29.8 | 2.2 | 92.2s | $1.029 |
| 7 | Linkup standard | `depth=standard` | 40.6 ± 0.9 | 84.0 | 29.7 | 1.5 | 72.3s | $0.937 |
| 8 | You | `extraction_mode=highlights` | 38.6 ± 0.8 | 79.3 | 28.3 | 4.4 | 48.2s | $0.971 |
| 9 | You | `extraction_mode=highlights` · `knowledge=core` | 38.1 ± 0.6 | 80.9 | 27.4 | 3.0 | 47.6s | $0.895 |
| 10 | Parallel fast | `mode=fast` | 38.0 ± 2.0 | 79.9 | 27.5 | 1.5 | 53.9s | $0.460 |
| 11 | Perplexity (low) | `search_context_size=low` | 37.8 ± 2.1 | 79.3 | 26.8 | 2.2 | 48.9s | $0.334 |
| 12 | Parallel turbo | `mode=turbo` | 34.7 ± 2.4 | 80.0 | 24.8 | 1.5 | 46.4s | $0.419 |
| 13 | Nimble | `search_depth=standard` | 30.7 ± 1.4 | 70.3 | 21.3 | 0.7 | 53.0s | $0.467 |
| 14 | Firecrawl | Default | 30.4 ± 1.1 | 77.3 | 20.7 | 2.2 | 75.0s | $0.282 |
| 15 | Brave Search | Web Search | 28.0 ± 1.7 | 66.9 | 19.3 | 0.7 | 43.5s | $0.268 |
| 16 | TinyFish | Default | 26.6 ± 1.3 | 64.7 | 17.9 | 1.5 | 64.2s | $0.212 |
| 17 | Nimble | `search_depth=lite` | 24.1 ± 1.4 | 65.2 | 16.1 | 0.7 | 67.2s | $0.222 |
| 18 | Seltz companies | `scope=companies` | 14.5 ± 0.9 | 40.0 | 9.4 | 0.0 | 55.2s | $1.751 |
| 19 | SERP (RapidAPI) | `limit=10` | 0.4 ± 0.6 | 0.7 | 0.3 | 0.0 | 31.4s | $0.103 |




### Search + fetch


| # | Provider | Configuration | F1 | Precision | Recall | Exact set | Median time | Median cost |
| --- | ----------------- | --- | ---------- | --------- | ------ | --------- | ----------- | ----------- |
| 1 | Exa deep | `type=deep` | 48.2 ± 2.1 | 89.4 | 36.0 | 2.2 | 95.8s | $0.683 |
| 2 | Perplexity (high) | `search_context_size=high` | 46.6 ± 2.0 | 87.7 | 34.7 | 2.2 | 53.9s | $0.504 |
| 3 | Exa instant | `type=instant` | 44.9 ± 0.9 | 85.9 | 33.5 | 5.2 | 52.5s | $0.653 |
| 4 | Parallel basic | `mode=basic` | 42.3 ± 1.1 | 81.3 | 31.3 | 3.0 | 68.6s | $1.089 |
| 5 | Parallel advanced | `mode=advanced` | 42.2 ± 1.1 | 87.6 | 30.1 | 2.2 | 80.9s | $0.599 |
| 6 | Linkup standard | `depth=standard` | 42.0 ± 1.8 | 90.7 | 30.5 | 3.0 | 81.0s | $0.911 |
| 7 | Tavily advanced | `search_depth=advanced` | 41.0 ± 1.3 | 89.4 | 29.1 | 2.2 | 92.6s | $0.898 |
| 8 | Linkup fast | `depth=fast` | 39.9 ± 1.3 | 85.3 | 28.6 | 0.7 | 68.0s | $0.903 |
| 9 | Parallel fast | `mode=fast` | 39.3 ± 3.3 | 82.3 | 28.2 | 2.2 | 55.1s | $0.441 |
| 10 | You | `extraction_mode=highlights` | 38.5 ± 1.6 | 85.2 | 26.9 | 0.7 | 45.6s | $0.864 |
| 11 | You | `extraction_mode=highlights` · `knowledge=core` | 38.5 ± 2.4 | 78.2 | 28.3 | 3.7 | 48.5s | $0.894 |
| 12 | Parallel turbo | `mode=turbo` | 36.0 ± 3.5 | 83.6 | 25.0 | 0.0 | 48.1s | $0.414 |
| 13 | Firecrawl | Default | 33.2 ± 2.1 | 83.3 | 22.7 | 1.5 | 82.1s | $0.295 |
| 14 | Nimble | `search_depth=standard` | 31.3 ± 1.8 | 73.2 | 21.7 | 1.5 | 59.2s | — |
| 15 | TinyFish | Default | 30.2 ± 3.5 | 70.9 | 20.9 | 0.0 | 63.4s | $0.219 |
| 16 | Brave Search | Web Search | 29.4 ± 1.6 | 73.5 | 20.4 | 1.5 | 45.1s | $0.285 |
| 17 | Nimble | `search_depth=lite` | 25.8 ± 2.2 | 67.2 | 17.7 | 1.5 | 72.4s | — |
| 18 | Seltz companies | `scope=companies` | 16.3 ± 1.5 | 49.5 | 10.2 | 0.0 | 60.1s | $1.741 |
| 19 | SERP (RapidAPI) | `limit=10` | 0.0 ± 0.0 | 0.0 | 0.0 | 0.0 | 33.4s | $0.102 |


Quality metrics are percentages, reported as mean ± sample standard deviation in
percentage points across 3 trials, each trial aggregated over all 45 questions.
Median cost is LLM plus search/fetch API dollars per agent run at dated list
prices. Table updated 2026-09-15. The
[live board](https://openbenchmarks.com/multi-turn-company-search) is the source
of truth; re-read it before quoting these numbers.

Full ranking: [https://openbenchmarks.com/multi-turn-company-search/most-accurate-search-api](https://openbenchmarks.com/multi-turn-company-search/most-accurate-search-api)

## Which web search API is fastest for company search?

Ranked by time per task quality, which is median agent time divided by F1, because
a fast incomplete set costs more than it saves. **Exa instant** leads search-only
at 115s per unit of quality; **Perplexity (high)** leads search + fetch at 116s,
with Exa instant a second behind at 117s.

Raw speed inverts this. Brave Search is the fastest search-only row in wall-clock
terms at 43.5s median, but at 28.0 F1 it needs 155s per unit of quality, worse
than every row above it.

Full ranking: [https://openbenchmarks.com/multi-turn-company-search/fastest-search-api](https://openbenchmarks.com/multi-turn-company-search/fastest-search-api)

## Which web search API is cheapest for company search?

Ranked by LLM dollars per task quality, which is model cost per run divided by F1.
Search API spend is excluded because it dominates the comparison. **Firecrawl**
leads both boards at $0.70 search-only and $0.69 search + fetch.

Perplexity (low) is within a tenth of a cent of Firecrawl on search-only at $0.70,
and returns 37.8 F1 against Firecrawl's 30.4, so it buys materially more quality
at the same cost-to-quality ratio.

Full ranking: [https://openbenchmarks.com/multi-turn-company-search/cheapest-search-api](https://openbenchmarks.com/multi-turn-company-search/cheapest-search-api)

## What counts as a correct company set

One rule, applied identically to every provider:

1. **Every constraint must hold.** A company is correct only when it satisfies all
  parts of the question. Partial matches are false positives.
2. **The set must be complete.** A correct company omitted by the agent is a false
  negative. Returning no unsupported companies is not enough if valid companies
   were missed.
3. **Identity is canonical.** Predictions are matched to the frozen answer set by
  canonical domain, canonical name, or an explicitly declared alias.

That produces four headline metrics: **precision**, **recall**, **F1**, and
**exact-set accuracy**. Exact-set accuracy is the strictest measure: the returned
set must contain every gold company and no extras.

## Endpoints

- **Live benchmark UI:** [https://openbenchmarks.com/multi-turn-company-search](https://openbenchmarks.com/multi-turn-company-search)
- **GitHub repository:** [https://github.com/openbenchmarks-labs/multi-turn-company-search](https://github.com/openbenchmarks-labs/multi-turn-company-search)
- **Public dataset:** 10 questions + frozen gold on Hugging Face as `[openbenchmarks/OB-Company-Websearch](https://huggingface.co/datasets/openbenchmarks/OB-Company-Websearch)`
- **Markdown agent docs:** [https://openbenchmarks.com/llms.txt](https://openbenchmarks.com/llms.txt)
- **OpenAPI 3.1 spec:** [https://openbenchmarks.com/openapi.json](https://openbenchmarks.com/openapi.json)
- **MCP server discovery:** [https://openbenchmarks.com/.well-known/mcp.json](https://openbenchmarks.com/.well-known/mcp.json)



## Configurations measured

The benchmark compares the following concrete endpoints and configurations. A row
is a configuration rather than merely a vendor name, because two modes from the
same vendor can behave like different products.

Each provider receives three independent trials per question. For every quality
metric, the judge first averages each trial over the complete question set, then
reports the **mean ± sample standard deviation** of those three trial-level values.
Standard deviation is expressed in percentage points and is descriptive, not a
confidence interval.


| Provider     | Configuration                                                             |
| ------------ | ------------------------------------------------------------------------- |
| Brave Search | Brave web search                                                          |
| Exa          | Deep, Instant                                                             |
| Firecrawl    | Search                                                                    |
| Linkup       | Fast, Standard                                                            |
| Nimble       | Lite, Standard                                                            |
| Parallel     | Turbo, Fast, Basic, Advanced                                              |
| Perplexity   | Search (`search_context_size` low on search-only, high on search + fetch) |
| Seltz        | Companies                                                                 |
| Google SERP  | RapidAPI                                                                  |
| Keenable     | Pro; native Fetch (indexed copy); results pending                         |
| Tavily       | Basic, Advanced                                                           |
| TinyFish     | Search                                                                    |
| You          | Highlights; highlights + `knowledge=core`; native Contents fetch          |


Parallel maps `site:` hosts into `source_policy.include_domains` and strips those
operators from the query; other vendors receive the agent query unchanged.

## Datasets

Board scores use a locked **45-question** private set: 24 questions have
three constraints and 21 have four. The gold release contains **375**
canonical question-company memberships (between two and thirty-seven
valid companies per question). Every provider is run **three** independent
trials per question on both modes.

A separate **10-question** public search-only set, including frozen
reference companies, is on Hugging Face as
`[openbenchmarks/OB-Company-Websearch](https://huggingface.co/datasets/openbenchmarks/OB-Company-Websearch)`.
It can be used to inspect the schema and run this harness; scores on those
rows are not comparable to the live boards.

The live page publishes the current search-only and search + fetch rankings, ordered
by mean F1 and then mean precision. This repository contains the runner rather than
a database export; locally generated rankings are written by the offline judge.

## What's in this repo


| path                                        | purpose                                                                                  |
| ------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `scripts/run_company_research_benchmark.py` | Offline planner and explicitly paid multi-provider orchestrator.                         |
| `scripts/judge_company_research.py`         | Builds leaderboard JSON from saved trial artifacts without network calls.                |
| `scripts/company_research/agent.py`         | Fixed OpenAI Responses API tool loop, prompt, budgets, and full search/fetch transcript. |
| `scripts/company_research/vendors.py`       | Search and native-fetch adapters for every measured configuration.                       |
| `scripts/company_research/custom_fetch.py`  | SSRF-hardened bounded HTTP fetch with a concurrency-limited Playwright fallback.         |
| `scripts/company_research/dataset.py`       | Frozen dataset schema validation and SHA-256 content receipts.                           |
| `scripts/company_research/parser.py`        | Strict structured company-set parser and normalization.                                  |
| `scripts/company_research/runner.py`        | Concurrent execution, resume rules, and atomic local artifact writes.                    |
| `scripts/company_research/judge.py`         | Canonical matching, completeness gates, metric calculation, and mean ± SD aggregation.   |
| `scripts/company_research/test_*.py`        | Offline runner, model-client, and judge contract tests.                                  |
| `.env.example`                              | OpenAI and provider credential names; no secrets or database configuration.              |




## Reproducing a run

Pick any `(mode, provider, question, trial)` tuple. Its artifact lives at:

```text
runs/<dataset>/<mode>/<provider>/<case>/trial-<n>.json
```

The file contains:

- `case`: the exact question and frozen canonical answer set used by the
offline judge. Gold answers are never included in the model prompt.
- `result.searches[]`: each literal provider request, redacted response
envelope, normalized hits, latency, attempts, and cost receipt.
- `result.fetches[]`: each requested URL plus the native or bounded-local
fetch response when fetch is enabled.
- `result.raw_model_response`: every model turn and token-usage receipt.
- `parsed_companies`: the strict structured set extracted from the final
response.
- `dataset.content_sha256`: the frozen input receipt that prevents results
from different datasets being mixed silently.

Existing successful trials are skipped on rerun. Failed trials remain available for
inspection and are retried only with `--retry-errors`.

## Running the benchmark yourself

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
cp .env.example .env && $EDITOR .env

# Offline plan: validates the dataset and prints calls, budgets, and required keys.
PYTHONPATH=scripts python scripts/run_company_research_benchmark.py \
  --dataset /absolute/path/to/dataset.json \
  --research-mode search_only

# Paid execution requires both explicit confirmation flags.
PYTHONPATH=scripts python scripts/run_company_research_benchmark.py \
  --dataset /absolute/path/to/dataset.json \
  --research-mode search_only \
  --execute --confirm-paid

PYTHONPATH=scripts python scripts/run_company_research_benchmark.py \
  --dataset /absolute/path/to/dataset.json \
  --research-mode search_and_fetch \
  --execute --confirm-paid
```

The runner uses the standard OpenAI API through `OPENAI_API_KEY`. Fill only the
provider keys selected with `--vendors`. Useful controls include `--trials`,
`--query-offset`, `--query-limit`, `--vendor-concurrency`, `--trial-concurrency`,
`--max-turns`, `--max-searches`, and `--max-fetches`.

Context.dev is available with `--vendors context` in both research modes.
Set `CONTEXT_API_KEY`; search requests Highlights with `maxCharacters=4000`,
matching the shared snippet cap, with descriptions as a fallback. Native fetch returns main-content
Markdown under the shared page cap. Requests retain Context's default cache
policy. Costs use returned credit usage at the Developer top-up rate of $2.20
per 1,000 credits, verified 2026-10-20, excluding the subscription. Highlights
search (10 results) uses two credits; standard Markdown fetch uses one. Missing usage
stays unknown. Leaderboard results are pending.

Keenable is available with `--vendors keenable` in both research modes, using
`KEENABLE_API_KEY` (rate limit: 10 requests/second per organization). Search calls
`POST /v1/search` with `mode=pro` sent explicitly, 10 results, and
`snippet_max_length=4000`, matching the shared snippet cap; the snippet is the
evidence text, with the description as a fallback. Native fetch returns Keenable's
indexed copy of the page (`GET /v1/fetch` with `live=false`) under the shared page
cap; a 404 or empty page is a failed fetch, like any other vendor's. Costs use the
list price of $4 per 1,000 requests ($0.004 per search or fetch, keenable.ai/pricing,
checked 2026-11-02), scaled by returned `usage.credits` when present. No scored run
yet; leaderboard results are pending.

A valid input uses the `company-research-dataset-v1` contract:

```text
dataset.json
├── schema_version
├── dataset { slug, name, ... }
├── cases[]
│   ├── case_key, question, constraints[]
│   └── gold[] { entity_key, name, domain, aliases[] }
└── content_sha256
```

Run the offline contract suite:

```bash
PYTHONPATH=scripts python -m unittest discover \
  -s scripts/company_research -p 'test_*.py'
```



## Judging saved runs

Judging is deterministic and makes no provider or model calls:

```bash
PYTHONPATH=scripts python scripts/judge_company_research.py \
  --runs runs/multi-constraint-company-research-v1 \
  --output leaderboard.json \
  --trials 3
```

The judge rejects incomplete comparisons: every provider in a mode must contain the
same questions and every expected trial index. Failed or unparseable completed runs
score as empty predictions rather than disappearing from the denominator.

## Contributing a new provider

1. Add a `VendorSpec` entry to `scripts/company_research/vendors.py` with the
  endpoint, credential environment variable, public request configuration, fetch
   capability, and dated unit-cost assumption.
2. Add the provider's request branch and normalize its response to the shared
  `{url, title, snippet, metadata}` hit shape.
3. If the provider exposes native page extraction, add its fetch request and page
  parser. Otherwise opt into the bounded custom fetcher explicitly.
4. Add offline adapter fixtures/tests, run the contract suite, then run one isolated
  question with `--vendors <your-provider> --trials 1 --query-limit 1` before a full
   benchmark.

Do not add OpenAI-native web tools or provider-specific prompting. The provider
adapter is the comparison variable; the research agent must remain fixed.

## Methodology

- **Frozen questions and gold sets.** Each dataset artifact is schema-validated and
content-addressed before execution. Every case contains one multi-constraint
question and a canonical company set. Gold data is available only to the offline
judge, never to the agent. The published boards use the locked 45-question set;
the public Hugging Face dump is a 10-question schema sample.
- **Fixed agent.** The default agent is `gpt-5.6-sol` at medium reasoning effort,
with a maximum of eight model turns, fourteen searches, two searches per turn,
and ten results per search. Search + fetch additionally permits fourteen fetches,
at most two per turn.
- **Provider swap.** The question, system prompt, model, reasoning effort, budgets,
output schema, and trial count are identical across rows. Only the provider-backed
search and fetch implementations change.
- **No native model search.** The model receives only the selected provider's
`web_search` tool and, in search + fetch, `web_fetch`. OpenAI-native web search and
fetch are not enabled.
- **Set scoring.** True positives are canonical identities present in both predicted
and gold sets. Extra predictions are false positives; missed gold identities are
false negatives. Precision, recall, F1, and exact-set accuracy are calculated per
agent run.
- **Three-trial aggregation.** Each metric is first averaged across all questions
within trial 1, trial 2, and trial 3. The leaderboard reports the mean and sample
standard deviation of those three values rather than selecting the best attempt.
- **Operational metrics.** Trial artifacts retain end-to-end latency, provider
latency, model turns, token usage, cited-return rate, and estimated vendor/model
cost. Costs use dated list-price assumptions rather than invoice reconciliation.
- **Concurrency.** Questions run sequentially within one provider so a systematic
failure can stop further spend. Providers run concurrently, as do the three trials
for a question.
- **Fetch safety.** Custom fetch rejects local/private network targets and bounds
redirects, response size, navigation time, and browser concurrency. Search + fetch
validates Chromium before paid calls begin.
- **Credential safety.** Authorization headers are redacted before artifacts are
written. `.env`, `.env.local`, `runs/`, and local virtual environments are ignored
by Git.
- **Known limitations.** This benchmark measures multi-constraint company discovery,
not general web search, news, coding, academic research, or consumer navigation.
Three trials expose obvious stochastic instability but are too few for a strong
inferential uncertainty claim. Search + fetch measures the combined search and
retrieval stack; use search only to isolate result quality. Local browser compute
is excluded from reported cost.

No vendor sponsors or controls this benchmark.

## Related benchmarks

This is the multi-hop deep research task of the OpenBenchmarks web search
benchmark. The same vendors are measured on two other jobs:

- **Factual lookup.** 300 company-news questions, scored on extracted-answer
accuracy: [https://openbenchmarks.com/company-news](https://openbenchmarks.com/company-news)
- **Hard retrieval.** Coding-agent tickets against enterprise docs, scored on
grounded task completion: [https://openbenchmarks.com/web-search-for-coding-agents](https://openbenchmarks.com/web-search-for-coding-agents)
- **Methodology and all three boards:** [https://openbenchmarks.com/web-search](https://openbenchmarks.com/web-search)




Nimble uses Search lite or standard with `focus=general` and `full_content=false`.
Search + fetch uses a separate Extract request with `formats=[markdown]`.
Set `NIMBLE_API_KEY` for either mode. Extract pricing is not assumed to be free;
set `NIMBLE_EXTRACT_USD_PER_REQUEST` only when an applicable rate is known.
The Nimble search + fetch total-cost cells remain unavailable without that rate.

## Changelog

- **2026-09-15.** Added Nimble lite and standard to both existing tables with three-repeat means and standard deviations. Search uses `focus=general` and `full_content=false`; search + fetch calls `POST /v2/extract` with `formats=[markdown]`. Added You highlights and highlights + `knowledge=core` to both research modes, using You Contents for fetch. Published 45-question, three-repeat results for each mode, including standard deviations; replaced the older plain You rows.

## License

[MIT](LICENSE)
