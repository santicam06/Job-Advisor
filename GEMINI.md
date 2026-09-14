# Project Overview: Three-Phase Pipeline

This project is an automated "Three-Phase Pipeline" designed for job market analysis and resume optimization. It leverages Large Language Models (LLMs) via OpenRouter to extract structured data from job postings and resumes, perform market synthesis, and provide personalized job application advice.

## Key Technologies
- **Python**: Core programming language.
- **OpenRouter (OpenAI-compatible)**: Orchestrates LLM interactions (e.g., GPT-4o-mini).
- **Pydantic**: Ensures strict data validation and structured LLM outputs.
- **PyPDF**: Extracts text from PDF documents.
- **Tavily**: Enriches job postings with real-time web search data about companies.
- **dotenv**: Manages environment-specific configurations.

## Project Structure
- `src/analysis/`: Phase 1 - Aggregates multiple job postings into a comprehensive Market Analysis Report.
- `src/extract/`:
    - `jobs_extract/`: Tools and schemas for parsing job posting PDFs into structured JSON.
    - `resume_extract/`: Tools and schemas for parsing resumes and comparing them against market data.
- `src/advisor/`: Phase 3 - A final application that provides tailored advice based on a specific job posting and the previously generated market data.
- `data/`: Local storage for input PDFs (jobs, resumes) and intermediate JSON data.
- `reports/`: Target directory for generated Markdown reports.

---

## Building and Running

### Setup
1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Environment Configuration**:
   - Copy `.env.example` to `.env`.
   - Set `OPENROUTER_API_KEY` (required).
   - Set `TAVILY_API_KEY` (optional, for web enrichment).

### Execution Phases
- **Phase 1: Market Analysis**
  ```bash
  python -m src.analysis.market_analysis [--verbose]
  ```
  Generates `reports/market_analysis_report.md` from `data/jobs_postings/*.pdf`.

- **Phase 2: Resume Comparison**
  ```bash
  python -m src.extract.resume_extract.resume_analyzer [--verbose]
  ```
  Compares `data/user/resume/*.pdf` against the market report, generating `reports/resume_comparison_report.md`.

- **Main Application: Job Advisor**
  ```bash
  python -m src.advisor.app_advisor <absolute_path_to_pdf> [--verbose]
  ```
  Provides specific advice for a single job posting.

---

## Development Conventions

### Data Integrity & Validation
- **Pydantic Schemas**: All extracted data MUST conform to schemas defined in `src/extract/jobs_extract/schemas.py` and `src/extract/resume_extract/schemas.py`.
- **Structured Output**: LLM calls utilize `openai.chat.completions.parse` to ensure responses match the Pydantic models.

### AI Context Management
- **Instruction Files**: System prompts are maintained in `INSTRUCTIONS_LLM.md` files located within their respective module directories. This keeps the logic and the prompt closely coupled.
- **Enrichment**: The `maybe_enrich_with_web` function (in `jobs_reader.py`) uses Tavily to fetch missing company information if `ENABLE_LLM_TOOLS` is active.

### Logging and Debugging
- **Verbose Mode**: Setting `APP_VERBOSE=1` or using the `--verbose` flag redirects `[DEBUG]` logs (written to `sys.stderr`) to module-specific `debug.txt` files.
- **Indented Output**: Custom stream wrappers (`IndentedStderr`) are used to ensure debug logs are readable and properly formatted.

### Error Handling
- The pipeline includes a global failure cap (`MAX_LLM_FAILURES`) to prevent excessive API costs if multiple documents fail to parse.
- PDF reading includes checks for maximum page counts (`MAX_PDF_PAGES`) and character limits (`MAX_PDF_CHARS`) to stay within LLM context windows.
