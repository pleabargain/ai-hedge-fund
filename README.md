# AI Hedge Fund

This is a proof of concept for an AI-powered hedge fund.  The goal of this project is to explore the use of AI to make trading decisions.  This project is for **educational** purposes only and is not intended for real trading or investment.

## About this fork

This copy of the project diverges from [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) for two reasons I care about locally: **more use of [Ollama](https://ollama.com/)**—first-class paths for local models so day-to-day runs can stay on self-hosted LLMs, not only hosted APIs—and **better reporting output**—clearer terminal summaries plus HTML export (including timing and structure) so it is easier to review what each analyst produced after a run.

This system employs several agents working together:

1. Aswath Damodaran Agent - The Dean of Valuation, focuses on story, numbers, and disciplined valuation
2. Ben Graham Agent - The godfather of value investing, only buys hidden gems with a margin of safety
3. Bill Ackman Agent - An activist investor, takes bold positions and pushes for change
4. Cathie Wood Agent - The queen of growth investing, believes in the power of innovation and disruption
5. Charlie Munger Agent - Warren Buffett's partner, only buys wonderful businesses at fair prices
6. Michael Burry Agent - The Big Short contrarian who hunts for deep value
7. Mohnish Pabrai Agent - The Dhandho investor, who looks for doubles at low risk
8. Nassim Taleb Agent - The Black Swan risk analyst, focuses on tail risk, antifragility, and asymmetric payoffs
9. Peter Lynch Agent - Practical investor who seeks "ten-baggers" in everyday businesses
10. Phil Fisher Agent - Meticulous growth investor who uses deep "scuttlebutt" research 
11. Rakesh Jhunjhunwala Agent - The Big Bull of India
12. Stanley Druckenmiller Agent - Macro legend who hunts for asymmetric opportunities with growth potential
13. Warren Buffett Agent - The oracle of Omaha, seeks wonderful companies at a fair price
14. Valuation Agent - Calculates the intrinsic value of a stock and generates trading signals
15. Sentiment Agent - Analyzes market sentiment and generates trading signals
16. Fundamentals Agent - Analyzes fundamental data and generates trading signals
17. Technicals Agent - Analyzes technical indicators and generates trading signals
18. Risk Manager - Calculates risk metrics and sets position limits
19. Portfolio Manager - Makes final trading decisions and generates orders

<img width="1042" alt="Screenshot 2025-03-22 at 6 19 07 PM" src="https://github.com/user-attachments/assets/cbae3dcf-b571-490d-b0ad-3f0f035ac0d4" />

Note: the system does not actually make any trades.

[![Twitter Follow](https://img.shields.io/twitter/follow/virattt?style=social)](https://twitter.com/virattt)

## Disclaimer

This project is for **educational and research purposes only**.

- Not intended for real trading or investment
- No investment advice or guarantees provided
- Creator assumes no liability for financial losses
- Consult a financial advisor for investment decisions
- Past performance does not indicate future results

By using this software, you agree to use it solely for learning purposes.

### Security hygiene (keys, PII, and run artifacts)

- **Never commit** real API keys. Keep them in OS env vars or a local **`.env`** (see [`.gitignore`](.gitignore): `.env`, `.env.*`, `.env.local`, and common key/credential filenames are ignored). Only [`.env.example`](.env.example) belongs in git, with placeholders.
- **Scan before you push:** from the repo root run **`pwsh -File scripts/scan_secrets.ps1`** or **`.\scripts\scan_secrets.ps1`** (Windows PowerShell 5.1+ or [PowerShell 7+](https://github.com/PowerShell/PowerShell)). It uses `git grep` on tracked files for common key shapes (OpenAI `sk-proj-`, Anthropic `sk-ant-api`, GitHub PATs, `AIza…`, AWS `AKIA…`, PEM headers, non-placeholder `FINANCIAL_DATASETS_API_KEY=`, etc.) and exits **1** on any hit. Spot-check with `git grep -n "sk-"` / `FINANCIAL_DATASETS_API_KEY=` if you need broader coverage.
- **PII (personally identifiable information):** HTML reports and logs under **`outputs/`** are gitignored; they can still contain model-generated text or paths on your machine—treat exports like sensitive documents. If you meant **PID** (process ID) files, `*.pid` is also ignored so supervisor state is not committed.
- **Backend DB:** local `*.db` / SQLite files are ignored; do not commit production databases or dumps with user data.

## To-dos

Working checklist (research report and data pipeline):

1. Phase 1: HTML export module + CLI integration
2. Phase 2: Minimal provenance from fundamentals agent
3. Phase 3: get_company_facts + issuer profile
4. Phase 4: Peer/industry APIs spike
5. Phase 5: Connected industries + cycle sections

## Table of Contents
- [About this fork](#about-this-fork)
- [To-dos](#to-dos)
- [How to Install](#how-to-install)
  - [Security hygiene (keys, PII, and run artifacts)](#security-hygiene-keys-pii-and-run-artifacts)
  - [Financial Datasets: API rate limits and errors](#financial-datasets-api-rate-limits-and-errors)
- [How to Run](#how-to-run)
  - [⌨️ Command Line Interface](#️-command-line-interface)
  - [🖥️ Web Application](#️-web-application)
- [How to Contribute](#how-to-contribute)
- [Feature Requests](#feature-requests)
- [License](#license)

## How to Install

Before you can run the AI Hedge Fund, you'll need to install it and set up your API keys. These steps are common to both the full-stack web application and command line interface.

### 1. Clone the Repository

```bash
git clone https://github.com/virattt/ai-hedge-fund.git
cd ai-hedge-fund
```

### 2. Set up API keys

You can supply API keys two ways — both work, and the system-environment route takes precedence (`load_dotenv()` is non-destructive by default).

**Option A — Windows system / user environment variables (recommended on Windows 11)**

Set them once via *System Properties → Environment Variables* (or `setx`), and any new shell will inherit them. No `.env` file required.

```powershell
setx OPENAI_API_KEY "sk-..."
setx ANTHROPIC_API_KEY "sk-ant-..."
setx FINANCIAL_DATASETS_API_KEY "..."
# Google's own SDKs use GEMINI_API_KEY; this repo accepts either GOOGLE_API_KEY or GEMINI_API_KEY.
setx GEMINI_API_KEY "..."
```

**Option B — `.env` file in repo root**

```bash
cp .env.example .env
# then edit .env
```

**Important**: You must set at least one LLM API key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `XAI_API_KEY`, `MOONSHOT_API_KEY`, `OPENROUTER_API_KEY`, etc.) for the hedge fund to work.

`FINANCIAL_DATASETS_API_KEY` is optional only for Financial Datasets’ **free tickers** (per [their homepage](https://financialdatasets.ai/): **AAPL, GOOGL, NVDA, TSLA**). For **any other symbol** (including **MSFT**), you need a key.

**Where to get `FINANCIAL_DATASETS_API_KEY`:** sign up at [financialdatasets.ai](https://financialdatasets.ai/), then generate the key from your **dashboard** ([official quick start](https://docs.financialdatasets.ai/quickstart)). Send it on every request as the `X-API-KEY` header; in this repo set env `FINANCIAL_DATASETS_API_KEY` (Windows user/system env or `.env`). API reference: [docs.financialdatasets.ai](https://docs.financialdatasets.ai/). (Free-ticker list and signup steps above were checked against those pages on 2026-05-03.)

#### Verify keys and Financial Datasets connectivity

From the repo root (after `uv pip install -e .` or `poetry install`; optional for the HTTP ping itself — the script uses the standard library and only loads `python-dotenv` if installed):

```bash
uv run python scripts/check_env.py
# or
poetry run python scripts/check_env.py
```

This prints which known env vars are set (values masked) and requests recent **AAPL** daily prices from `api.financialdatasets.ai` (same URL and `X-API-KEY` behavior as `get_prices` in `src/tools/api.py`). If you see **HTTP 403** with body mentioning **error 1010**, that is often Cloudflare blocking the client; try again from your normal PC, set `FINANCIAL_DATASETS_API_KEY`, or rely on the main app’s `requests` client (already used by `src/tools/api.py`).

### Financial Datasets: API rate limits and errors

Official **plan limits** (requests per minute) are published on the vendor pricing page: [financialdatasets.ai/pricing](https://www.financialdatasets.ai/pricing). As of 2026-05-04 that page lists **1,000 requests / minute** on the **Developer** plan and **unlimited** API requests on **Pro** and **Enterprise**. (If their numbers change, treat the pricing page as the source of truth.) General API documentation: [docs.financialdatasets.ai](https://docs.financialdatasets.ai/) and [Quick start](https://docs.financialdatasets.ai/quickstart).

**What this repo does**

- [`src/tools/api.py`](src/tools/api.py) — `_make_api_request` retries **HTTP 429** (Too Many Requests) with backoff: wait **60s + 30s × attempt** before each retry, up to **4** attempts total (`max_retries` default **3** means `range(max_retries + 1)` attempts). When the API sends a **`Retry-After`** header, the log line includes it; the console line notes the wait.
- Non-200 responses (e.g. **404** not found, **401/403** auth) are **logged** via Python `logging` and summarized **once per** `(operation, ticker, status)` in the console so you do not get dozens of identical lines when many agents request the same symbol.
- **404** on endpoints such as **`/company/facts/`** usually means the ticker is **not in the dataset** or the symbol is wrong for that API — not a rate limit. Try a known-covered symbol or confirm your subscription covers that instrument.
- If the **portfolio manager** returns prose or echoes the initial prompt instead of JSON, the CLI prints a **clear portfolio-manager JSON error** (see [`src/utils/portfolio_json.py`](src/utils/portfolio_json.py)); fix by using a model that follows the JSON output instruction or tightening prompts.

## How to Run

### ⌨️ Command Line Interface

You can run the AI Hedge Fund directly via terminal. This approach offers more granular control and is useful for automation, scripting, and integration purposes.

<img width="992" alt="Screenshot 2025-01-06 at 5 50 17 PM" src="https://github.com/user-attachments/assets/e8ca04bf-9989-4a7d-a8b4-34e04666663b" />

#### Quick Start

You can use either **Poetry** or **uv** as the Python package manager. `uv` is the faster modern replacement. (Note: use `uv`, not `uvx` — `uvx` is for one-shot tool execution like `pipx run`, not for project dependency management.)

This repo declares dependencies under **`[tool.poetry.dependencies]`** only. **`uv sync` does not install those** until the project also has a PEP 621 `[project]` block. With uv, install the package into a venv like this:

##### Option 1 — uv (recommended)
get UV for python

```powershell
# Install uv (Windows PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Install dependencies (editable install reads Poetry’s pyproject.toml)
uv pip install -e .

# Run — flag is --tickers (plural). Without --analysts-all / --model, the CLI opens interactive prompts.
uv run python src/main.py --tickers AAPL,GOOGL,NVDA --analysts-all --model gpt-4.1
```

##### Option 2 — Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
poetry install
poetry run python src/main.py --tickers AAPL,GOOGL,NVDA --analysts-all --model gpt-4.1
```

#### Common flags (work with `uv run` or `poetry run`)

Run with local LLMs via Ollama:

```bash
uv run python src/main.py --tickers AAPL,GOOGL,NVDA --analysts-all --ollama
```

On an **interactive terminal**, the CLI first probes common Ollama URLs (`localhost`, `127.0.0.1`, `host.docker.internal`, `OLLAMA_BASE_URL`, etc.), lists reachable servers and which preset models from `src/llm/ollama_models.json` are already pulled, then asks you to pick an instance (unless you already set `OLLAMA_BASE_URL`). Without `--ollama`, it still **offers local Ollama first** before the cloud model picker.

If you choose Ollama, **`ensure_ollama_ready_for_run_with_amd_hint()`** runs immediately afterward: it requires HTTP 200 from `GET {OLLAMA_BASE_URL}/api/tags` and **exits with code 1** with a short message if the server is not running (same check you can preview with `python scripts/check_env.py`).

##### AMD Radeon + Vulkan (optional)

To prefer **Ollama’s experimental Vulkan path** on AMD Radeon GPUs, set **`OLLAMA_AMD_RADEON_VULKAN=1`** in your environment or `.env` (see `.env.example`). On startup the CLI sets **`OLLAMA_VULKAN=1`** and **`GGML_VK_VISIBLE_DEVICES=0`** (first Vulkan-visible GPU) for **this Python process** and any **`ollama serve`** it spawns. If you use the **Ollama desktop app** or a **Windows service**, set the same variables on **that** process and restart Ollama so inference actually hits the GPU—see [Ollama GPU docs](https://docs.ollama.com/gpu).

For predictable VRAM use on consumer cards, pull models with an **explicit GGUF quant** in the tag (for example **`q4_K_M`** or **`q4_0`**). If the tag has no quant suffix, the CLI prints a short hint when `OLLAMA_AMD_RADEON_VULKAN=1`.

Specify a date range:

```bash
uv run python src/main.py --tickers AAPL,GOOGL,NVDA --analysts-all --model gpt-4.1 --start-date 2024-01-01 --end-date 2024-03-01
```

##### Save research output as HTML

By default, the CLI **writes a self-contained HTML report** under **`outputs/`** when the workflow finishes (portfolio decisions, analyst signals, a Financial Datasets endpoint manifest, and collapsible raw JSON). The default filename is **`{TICKER}-{YYYYMMDD_HHMMSS}.html`** (one ticker) or **`{TICK1_TICK2_...}-{YYYYMMDD_HHMMSS}.html`** (several). Use **`--export-html-path`** for a fixed path. Use **`--no-export-html`** to skip writing HTML.

**Copy-paste: full research pass + saved report (cloud LLM)** — HTML is saved automatically to `outputs/` with a ticker–timestamp name:

```bash
uv run python src/main.py --tickers AAPL,GOOGL,NVDA --analysts-all --model gpt-4.1 --start-date 2024-01-01 --end-date 2024-12-31 --show-reasoning
```

**Same idea with local Ollama**

```bash
uv run python src/main.py --tickers AAPL,GOOGL,NVDA --analysts-all --ollama --start-date 2024-01-01 --end-date 2024-12-31 --show-reasoning
```

**Single ticker + Ollama + explicit HTML path (optional)**

```bash
uv run python src/main.py --tickers BCDA --analysts-all --ollama --export-html-path outputs/my_report.html
```

Open the printed path (or your **`--export-html-path`**) in a browser. Implementation lives in [`src/reporting/html_export.py`](src/reporting/html_export.py). Smoke tests: `uv run pytest tests/test_html_export.py`.

While HTML export is on, the run also refreshes a sidecar **`*.partial.html`** next to the final file (for example **`outputs/AAPL-20260503_143022.partial.html`** next to **`outputs/AAPL-20260503_143022.html`**) on a throttled interval (`--checkpoint-html-interval-seconds`, default **15**). That gives you something to open if a provider hangs mid-graph.

**Timeouts**

- **`--llm-call-timeout-seconds`** caps each structured LLM call inside an analyst (thread pool); retries still apply, then the agent falls back to defaults.
- **`--report-timeout-seconds`** stops the LangGraph stream after that many **wall-clock seconds from run start** (checked after each graph step). Incomplete runs still emit CLI/HTML output with a partial banner.
- **`--report-timeout-adaptive`** sets the report timeout from recent **completed** runs in **`--report-timing-history`** (JSONL): ceiling ≈ **`max(floor, avg_last_N × ratio)`** (defaults: ratio **1.67**, floor **30** s, fallback **120** s when history is empty). Example: average successful run **45** s → ceiling about **75** s before the next run is cut short.

```bash
uv run python src/main.py --tickers BCDA --analysts-all --ollama \
  --export-html-path outputs/research_report.html \
  --report-timeout-adaptive --llm-call-timeout-seconds 90
```

**Ollama stalls / frozen `/api/chat`**

When running against **localhost**, the CLI detects stall-like errors (timeouts, connection failures) and **attempts one automatic recovery per run**: kill local `ollama.exe` / `ollama serve`, start the server again, and **`ollama pull qwen3.5:9b`** if that tag is missing. Disable with **`OLLAMA_AUTO_RESTART_ON_STALL=0`**. The Rich progress table and HTML export show a red **Ollama / runtime** banner during recovery.

In the **web app**, Settings → Ollama polls server status every **10s** and raises a toast if Ollama goes from running to stopped; use **Restart & recover (qwen3.5:9b)** for the same stop/start/pull flow (localhost only).

#### Run the Backtester
```bash
uv run python src/backtester.py --tickers AAPL,GOOGL,NVDA --analysts-all --model gpt-4.1
```

**Example Output:**
<img width="941" alt="Screenshot 2025-01-06 at 5 47 52 PM" src="https://github.com/user-attachments/assets/00e794ea-8628-44e6-9a84-8f8a31ad3b47" />


Note: The `--ollama`, `--start-date`, and `--end-date` flags work for the backtester, as well!

### 🖥️ Web Application

The new way to run the AI Hedge Fund is through our web application that provides a user-friendly interface. This is recommended for users who prefer visual interfaces over command line tools.

Please see detailed instructions on how to install and run the web application [here](https://github.com/virattt/ai-hedge-fund/tree/main/app).

<img width="1721" alt="Screenshot 2025-06-28 at 6 41 03 PM" src="https://github.com/user-attachments/assets/b95ab696-c9f4-416c-9ad1-51feb1f5374b" />


## How to Contribute

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

**Important**: Please keep your pull requests small and focused.  This will make it easier to review and merge.

## Feature Requests

If you have a feature request, please open an [issue](https://github.com/virattt/ai-hedge-fund/issues) and make sure it is tagged with `enhancement`.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

_Last updated: 2026-05-04 (README: fork purpose—Ollama emphasis and reporting; prior: security, `scripts/scan_secrets.ps1`)._
