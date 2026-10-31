# AGENTS.md

## Environment & Setup

- **Python environment**: Use the local virtual environment (`.venv\Scripts\python.exe` on Windows, `.venv/bin/python` on macOS/Linux).
- **Working directory**: Run all module commands from the repository root.
- **Required `.env` keys**: Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` and `TAVILY_API_KEY`.
- **Serverless proxy (`api/app.py`)**: Runs on Vercel (`BaseHTTPRequestHandler`), not locally. Expects `GITHUB_PAT`, `GITHUB_OWNER`, `GITHUB_REPO`, and optional `APP_VERBOSE=1` in the Vercel environment.
- **No test/lint runner**: There is no test suite, linter, or typechecker configured in this repository.

## Commands & Pipeline Execution

The pipeline consists of three module entrypoints. `app_advisor` runs all phases end-to-end, while Phase 1 and Phase 2 can be run standalone:

1. **Phase 1 — Market Analysis**:
   ```sh
   python -m src.analysis.market_analysis [--verbose]
   ```
   Parses any new PDFs in `data/jobs_postings/` into `data/jobs_JSON/<stem>.json`, summarizes every JSON in `data/jobs_JSON/`, and writes `reports/market_analysis_report.md`.

2. **Phase 2 — Resume Comparison** (requires `reports/market_analysis_report.md` from Phase 1):
   ```sh
   python -m src.extract.resume_extract.resume_analyzer [--verbose]
   ```
   Parses the single resume PDF in `data/user/resume/` into `data/user/resume/<stem>.json` and compares it against the market report to produce `reports/resume_comparison_report.md`.

3. **Full Pipeline — Job Advisor**:
   ```sh
   python -m src.advisor.app_advisor "<absolute_path_to_job_posting.pdf>" [--verbose]
   ```
   Parses the target job PDF into `src/advisor/user_jobpost_JSON/<stem>.json`, executes Phase 1 and Phase 2, and writes `reports/application_report_<company_slug>.md` (auto-incrementing `_2`, `_3`, etc. if a report for that company already exists).

## Operational Gotchas & Quirks

- **Interactive prompt at the end of `app_advisor`**: `src.advisor.app_advisor` finishes with a blocking `input()` loop asking `(yes/no)` to upload the parsed job JSON to the community database.
  - When invoking non-interactively, pipe `no` to stdin (e.g., `echo no | python -m src.advisor.app_advisor ...`).
  - Answering `yes` POSTs the JSON to `CONTRIBUTION_PROXY_URL` and runs `git pull --quiet`.
- **Auto-commit side effect in `jobs_reader()`**: When `src/extract/jobs_extract/jobs_reader.py` parses a new PDF from `data/jobs_postings/` into `data/jobs_JSON/<stem>.json`, it automatically executes `git add` and `git commit -m "User contribution before executing app."` on the new JSON file.
- **Manual `sys.argv` parsing**:
  - `--verbose` **must be the final argument** on the command line.
  - `app_advisor` requires an **absolute path** (or `~`-expanded path) ending in `.pdf` and rejects arguments containing `<`, `>`, `[`, or `]`.
- **Single resume PDF constraint**: `data/user/resume/` must contain **exactly one** `.pdf` file. Having zero or multiple PDFs raises a `ValueError`.
- **Aggressive JSON caching by filename stem**: PDF extraction is skipped whenever a valid `<stem>.json` file already exists (`data/jobs_JSON/`, `data/user/resume/`, `src/advisor/user_jobpost_JSON/`). If you modify Pydantic schemas (`schemas.py`) or reader prompts (`INSTRUCTIONS_LLM*.md`), delete the cached `.json` file to force re-parsing.
- **Stderr filtering & debug logs**:
  - By default, entrypoints wrap `sys.stderr` in `FilteredStderr`, silently dropping any stderr line prefixed with `[DEBUG]`.
  - Passing `--verbose` sets `APP_VERBOSE=1` and redirects `sys.stderr` (including `[DEBUG]` lines) to a module-local `debug.txt` (`src/analysis/debug.txt`, `src/extract/resume_extract/debug.txt`, or `src/advisor/debug.txt`).
- **Env limit overrides**: `MAX_PDF_PAGES` and `MAX_PDF_CHARS` have different per-module defaults (`jobs_reader.py`: 8 pages / 30,000 chars; `resume_analyzer.py`: 3 pages / 12,000 chars). Uncommenting them in `.env` forces a single global limit across both extractors.
- **`__pycache__` cleanup**: Entrypoints recursively delete all `__pycache__` directories across the repository in their `finally` blocks.

## Architecture & Model Routing

All LLM requests use the `openai` Python SDK pointed at OpenRouter (`https://openrouter.ai/api/v1`) with system prompts loaded from co-located `INSTRUCTIONS_LLM*.md` files:

- **`src/extract/jobs_extract/`**: `openai/gpt-4o-mini` with structured output (`JobPosting` in `schemas.py`) and Tavily `web_search` tool calls (`tools.py`, capped at `MAX_LLM_TOOL_CALLS = 3`; falls back to direct company search if `ENABLE_LLM_TOOLS=0`).
- **`src/analysis/market_analysis.py`**: `nvidia/nemotron-3-nano-30b-a3b` summarizes each job JSON individually to prevent context drift, then `arcee-ai/trinity-large-thinking` synthesizes `reports/market_analysis_report.md`.
- **`src/extract/resume_extract/`**: `mistralai/codestral-2508` extracts the resume PDF into the `ResumeProfile` Pydantic schema; `cohere/command-r-plus-08-2024` compares it with the market report.
- **`src/advisor/app_advisor.py`**: `cohere/command-r-plus-08-2024` combines the user job posting JSON, market report, and resume comparison report into the final application report.
- **Git-tracked vs. local data**: `data/jobs_JSON/` is the committed shared database of parsed job postings. User inputs and outputs in `data/jobs_postings/`, `data/user/`, `src/advisor/user_jobpost_JSON/`, and `reports/` are gitignored.
