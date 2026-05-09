import os, sys, shutil, atexit
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from openai import OpenAI
from src.extract.jobs_extract.jobs_reader import jobs_reader

load_dotenv(find_dotenv())

# Adds indentation to stderr lines for readable debug logs.
class IndentedStderr:
    def __init__(self, stream):
        self.stream = stream
        self.indent = 0
        self._at_line_start = True

    # print(..., file=sys.stderr) calls write() under the hood.
    def write(self, text: str) -> int:
        written = 0
        for ch in text:
            if self._at_line_start and ch != "\n":
                prefix = " " * self.indent
                self.stream.write(prefix)
                written += len(prefix)
                self._at_line_start = False
            self.stream.write(ch)
            written += 1
            if ch == "\n":
                self._at_line_start = True
        return written

    # flush() is invoked by print(..., flush=True) or on stream shutdown.
    def flush(self) -> None:
        self.stream.flush()

# Filters out [DEBUG] lines from stderr when verbose mode is off.
class FilteredStderr:
    def __init__(self, stream):
        self.stream = stream
        self._buffer = ""

    # Buffer text until a newline, then drop lines that start with [DEBUG].
    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, rest = self._buffer.split("\n", 1)
            if line.strip() and not line.lstrip().startswith("[DEBUG]"):
                self.stream.write(line + "\n")
            self._buffer = rest
        return len(text)

    # Flush any remaining buffered text (non-debug) before closing.
    def flush(self) -> None:
        if self._buffer and not self._buffer.lstrip().startswith("[DEBUG]"):
            self.stream.write(self._buffer)
        self._buffer = ""
        self.stream.flush()

# Directory macros
BASE_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = BASE_DIR / "reports"
JOBS_JSON_DIR = BASE_DIR / "data" / "jobs_JSON"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


SYS_PROMPT_FILE = os.path.join(SCRIPT_DIR, "INSTRUCTIONS_LLM.md")
with open(SYS_PROMPT_FILE, "r", encoding="utf-8") as f:
    SYS_PROMPT = f.read().strip()


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# OpenAI client setup (OpenRouter endpoint)
openai = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)


# Uses one LLM loop to summarize each JSON file (prevents context-drift)
# Provides a pack of those summaries (text format) to a final LLM to produce a Markdown report
def market_analysis():
    # Ensure reports directory exists
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    verbose_mode = os.getenv("APP_VERBOSE") == "1"

    def section_break() -> None:
        if verbose_mode:
            print("", file=sys.stderr)

    # Collect JSON files to analyze
    json_paths = sorted(JOBS_JSON_DIR.glob("*.json"))
    if not json_paths:
        raise ValueError("No JSON files found in jobs_JSON directory.")
    print(f"[DEBUG] Found {len(json_paths)} job posting JSON files to analyze", file=sys.stderr)

    json_summaries: list[str] = []
    total_files = len(json_paths)

    # Simple system prompt for per-file summaries
    per_file_sysprompt = (
        "You are an assistant that summarizes a single IT job-posting JSON into concise, factual bullets. "
        "Focus on role, the employer profile (is a company, startup, or individual?, etc...), skills required or nice to have, experience, education requirements, salary (if any), and key responsibilities in the role. "
        "IMPORTANT: Do not add anything not present in the JSON."
        "Your summaries will be provided to another assistant so that it builds a report, so focus on important things and not vain, from the job-posting."
    )

    # LLM loop: one call per JSON file
    for json_path in json_paths:
        print(f"[DEBUG] Reading job posting JSON: {json_path}", file=sys.stderr)
        with open(json_path, "r", encoding="utf-8") as f:
            json_text = f.read()

        # Per-file summary call 
        print("[DEBUG] LLM call: nvidia/nemotron-3-nano-30b-a3b (per-file summary)", file=sys.stderr)
        response = openai.chat.completions.create(
            model="nvidia/nemotron-3-nano-30b-a3b",
            messages=[
                {"role": "system", "content": per_file_sysprompt},
                {"role": "user", "content": json_text},
            ],
        )

        # Defensive extraction in case the provider returns empty choices
        summary = ""
        if response.choices and response.choices[0].message:
            summary = response.choices[0].message.content or ""

        # Store summaries in order; keep file name to preserve provenance
        json_summaries.append(f"{json_path.name}\n{summary}\n".strip())
        section_break()


    # Final LLM call (separate from loop), build market report from plain text summaries

    # We pass summaries instead of raw JSON to keep context compact and consistent
    numbered_summaries = "\n\n".join(f"{i}. {text}" for i, text in enumerate(json_summaries, start=1))
    
    # Provide exact count of summaries (JSON files) so model doesn't guess it
    final_input = (
        f"You are analyzing exactly {total_files} job postings. "
        "Do not estimate or invent a different count.\n\n"
        f"{numbered_summaries}"
    )
    print("[DEBUG] LLM call: arcee-ai/trinity-large-thinking (market report)", file=sys.stderr)
    final_response = openai.chat.completions.create(
        model="arcee-ai/trinity-large-thinking",
        messages=[
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": final_input},
        ],
    )

    report = ""
    if final_response.choices and final_response.choices[0].message:
        report = final_response.choices[0].message.content or ""

    # Write report to disk for review
    out_path = REPORTS_DIR / "market_analysis_report.md"
    print(f"[DEBUG] Writing market analysis report: {out_path}", file=sys.stderr)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    section_break()


# Remove __pycache__ folders to keep the repo clean after running.
def cleanup_pycaches(base_dir: Path) -> None:
    
    for root, dirs, _ in os.walk(base_dir):
        if "__pycache__" in dirs:
            cache_path = Path(root) / "__pycache__"
            try:
                shutil.rmtree(cache_path)
            except OSError as error:
                print(f"[DEBUG] Failed to remove {cache_path}: {error}", file=sys.stderr)


# Phase 1 entrypoint: build or refresh ./data/jobs_JSON, then generate Market Analysis Report
def main_market_analysis():
    try:
        jobs_reader()
        market_analysis()
    except Exception as error:
        raise Exception(f"main_market_analysis() says: {error}") from error
    finally:
        cleanup_pycaches(BASE_DIR)


# Entrypoint for multiprocessing safety 
if __name__ == "__main__":
    try:
        # CLI usage: python -m src.analysis.market_analysis [--verbose]
        args = sys.argv[1:]
        verbose_mode = False
        if args and args[-1] == "--verbose":
            verbose_mode = True
            args = args[:-1]
        if len(args) > 0:
            raise ValueError(
                "Too many arguments. Usage: python -m src.analysis.market_analysis [--verbose]"
            )

        # Divert all debug logs to debug.txt
        if verbose_mode:
            debug_path = Path(SCRIPT_DIR) / "debug.txt"
            debug_file = open(debug_path, "w", encoding="utf-8")
            sys.stderr = IndentedStderr(debug_file)
            atexit.register(debug_file.close)
            os.environ["APP_VERBOSE"] = "1"
        else:
            # Do not show error logs in stdout
            sys.stderr = FilteredStderr(sys.stderr)

        jobs_reader()
        market_analysis()
    except Exception as error:
        raise Exception(f"market_analysis() says: {error}") from error
    finally:
        cleanup_pycaches(BASE_DIR)
