import json, os, sys, openai, shutil, atexit
from pathlib import Path
from src.extract.resume_extract.schemas import ResumeProfile
from pydantic import ValidationError
from typing import cast
from dotenv import load_dotenv, find_dotenv
from openai.types.chat import ChatCompletionMessageParam
from openai import OpenAI, RateLimitError
from pypdf import PdfReader


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
BASE_DIR = Path(__file__).resolve().parents[3]
USER_RESUME_DIR = BASE_DIR / "data" / "user" / "resume"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SYS_PROMPT_FILE_R = os.path.join(SCRIPT_DIR, "INSTRUCTIONS_LLM_READER.md")
with open(SYS_PROMPT_FILE_R, "r", encoding="utf-8") as f:
    SYS_PROMPT_READER = f.read().strip()

SYS_PROMPT_FILE_C = os.path.join(SCRIPT_DIR, "INSTRUCTIONS_LLM_COMPARATOR.md")
with open(SYS_PROMPT_FILE_C, "r", encoding="utf-8") as f:
    SYS_PROMPT_COMPARATOR = f.read().strip()


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# OpenAI client setup (OpenRouter endpoint)
openai = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "3"))
MAX_PDF_CHARS = int(os.getenv("MAX_PDF_CHARS", "12000"))


# Reads a PDF and returns a string with all pages, formatted for LLM input
def read_pdf(file_path: str) -> str:
    try:
        print(f"[DEBUG] Reading PDF: {Path(file_path).name}", file=sys.stderr)
        reader = PdfReader(file_path)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"PDF not found: {file_path}") from error
    except Exception as error:
        raise RuntimeError(f"Failed to read PDF '{file_path}': {error}") from error

    pages = []
    pages.insert(0, f"# Source PDF: {Path(file_path).name}")

    # Process each page of the pdf
    pages_read = 0
    for i, page in enumerate(reader.pages, start=1):
        pages_read += 1

        # Check if pdf exceeds in pages
        if MAX_PDF_PAGES and i > MAX_PDF_PAGES:
            pages.append(f"[Truncated after {MAX_PDF_PAGES} pages]")
            break

        text = page.extract_text() or ""
        text = text.strip()
        if text:
            pages.append(f"## Page {i}\n{text}")

    full_text = "\n\n".join(pages)
    print(f"[DEBUG] Read {pages_read} pages from {Path(file_path).name}", file=sys.stderr)

    # Check if pdf exceeds in chars
    if MAX_PDF_CHARS and len(full_text) > MAX_PDF_CHARS:
        full_text = full_text[:MAX_PDF_CHARS] + f"\n\n[Truncated to {MAX_PDF_CHARS} characters]"
        print(f"[DEBUG] Truncated PDF text to {MAX_PDF_CHARS} characters", file=sys.stderr)
    print(f"[DEBUG] Extracted {len(full_text)} characters from {Path(file_path).name}", file=sys.stderr)
    return full_text


# Second parameter only used if LLM output is wrongly parsed
def parse_resume(content: str, raw_output: str) -> ResumeProfile:
    try:
        parsed = ResumeProfile.model_validate_json(content)
        print("[DEBUG] Structured output validation: passed (ResumeProfile)", file=sys.stderr)
    except ValidationError as error:
        raise ValueError(f"Output not properly parsed with ResumeProfile schema:\n {raw_output}.\nValidation error: {error}") from error
    return parsed


# Remove __pycache__ folders to keep the repo clean after running.
def cleanup_pycaches(base_dir: Path) -> None:
    
    for root, dirs, _ in os.walk(base_dir):
        if "__pycache__" in dirs:
            cache_path = Path(root) / "__pycache__"
            try:
                shutil.rmtree(cache_path)
            except OSError as error:
                print(f"[DEBUG] Failed to remove {cache_path}: {error}", file=sys.stderr)


# Reads a resume PDF from ./data/user/resume and converts it into a JSON format file with a schema 
def resume_reader():

    verbose_mode = os.getenv("APP_VERBOSE") == "1"

    def section_break() -> None:
        if verbose_mode:
            print("", file=sys.stderr)

    # Only allow a single resume PDF in the directory to avoid ambiguity.
    pdf_paths = sorted(USER_RESUME_DIR.glob("*.pdf"))
    if len(pdf_paths) == 0:
        raise ValueError(f"No PDF resumes found in: {USER_RESUME_DIR}")
    if len(pdf_paths) > 1:
        raise ValueError(
            f"Multiple PDF resumes found in {USER_RESUME_DIR}. Keep only one file."
        )

    pdf_path = pdf_paths[0]
    pdf_path_str = str(pdf_path)

    # Name of the new JSON file to write, with same stem name of PDF
    out_path = USER_RESUME_DIR / f"{pdf_path.stem}.json"
    # Verify if JSON file of this PDF already exists
    if out_path.exists():
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                # If the JSON is correct, nothing happens, otherwise, load() raises
                json.load(f)

            # Existing JSON is valid, so we skip this PDF
            print(f"[DEBUG] Skipping {pdf_path.name} (valid JSON exists).", file=sys.stderr)
            section_break()
            return
        except Exception:
            # If JSON is missing/corrupt, fall through and re-generate it
            pass
    
    # Read and get LLM friendly format content
    pdf_text = read_pdf(pdf_path_str)
    
    messages_pack = [
            {"role": "system", "content": SYS_PROMPT_READER},
            {"role": "user", "content": pdf_text},
    ]

    try:
        # keyword arguments
        kwargs = {
            "model": "mistralai/codestral-2508",
            "messages": cast(list[ChatCompletionMessageParam], messages_pack),
            "response_format": ResumeProfile,
        }
        print("[DEBUG] LLM call: mistralai/codestral-2508 (resume_reader)", file=sys.stderr)
        response = openai.chat.completions.parse(**kwargs)
            
    except RateLimitError as error:
        raise Exception(f"LLM rate limit error: {error}") from error


    message = response.choices[0].message
    raw_output = message.content

    resume_schema = None
    try:
        # No more tool calls
        if message.content and raw_output:
            # VALID SCHEMA RESULT
            resume_schema = parse_resume(message.content, raw_output)

        if not resume_schema:
            raise ValidationError("No valid output when parsing resume schema.")
    except ValidationError as error:
        raise ValueError(f"Output not properly parsed with JobPosting schema:\n {raw_output}.\nValidation error: {error}") from error
    

    try:
        print(f"[DEBUG] Writing JSON resume to: {out_path}", file=sys.stderr)
        with open(out_path, "w", encoding="utf-8") as f:
            # Convert job schema into a dict
            job_dict = resume_schema.model_dump(mode="json")
            # this method expects a python dict to convert it to JSON format
            json.dump(job_dict, f, indent=2)
    except OSError as error:
        raise RuntimeError(f"Failed to write JSON output: {out_path}") from error
    section_break()


# Compares the parsed resume JSON created, with Market Analysis Report 
# Generates the Resume Comparison Report
def compare_resume():

    verbose_mode = os.getenv("APP_VERBOSE") == "1"

    def section_break() -> None:
        if verbose_mode:
            print("", file=sys.stderr)

    REPORTS_DIR = BASE_DIR / "reports"
    market_report_path = REPORTS_DIR / "market_analysis_report.md"
    # Match the JSON name to the single resume PDF present in the directory.
    pdf_paths = sorted(USER_RESUME_DIR.glob("*.pdf"))
    if len(pdf_paths) == 0:
        raise ValueError(f"No PDF resumes found in: {USER_RESUME_DIR}")
    if len(pdf_paths) > 1:
        raise ValueError(
            f"Multiple PDF resumes found in {USER_RESUME_DIR}. Keep only one file."
        )

    resume_json_path = USER_RESUME_DIR / f"{pdf_paths[0].stem}.json"

    if not resume_json_path.exists():
        raise FileNotFoundError(
            f"Resume JSON not found at: {resume_json_path}. Run resume_reader() first."
        )

    if not market_report_path.exists():
        raise FileNotFoundError(
            f"Market analysis report not found at: {market_report_path}. Run market_analysis() first."
        )

    print(f"[DEBUG] Reading resume JSON: {resume_json_path}", file=sys.stderr)
    with open(resume_json_path, "r", encoding="utf-8") as f:
        resume_json_text = f.read()

    print(f"[DEBUG] Reading market analysis report: {market_report_path}", file=sys.stderr)
    with open(market_report_path, "r", encoding="utf-8") as f:
        market_report_text = f.read()

    # Keep both sources in a single user message so the model has full context.
    user_input = (
        "## Resume JSON\n"
        f"{resume_json_text}\n\n"
        "## Market Analysis Report\n"
        f"{market_report_text}"
    )

    print("[DEBUG] LLM call: cohere/command-r-plus-08-2024 (compare_resume)", file=sys.stderr)
    response = openai.chat.completions.create(
        model="cohere/command-r-plus-08-2024",
        messages=[
            {"role": "system", "content": SYS_PROMPT_COMPARATOR},
            {"role": "user", "content": user_input},
        ],
    )

    comparison_output = ""
    # Defensive extraction in case the provider returns empty choices.
    if response.choices and response.choices[0].message:
        comparison_output = response.choices[0].message.content or ""

    # Store the comparison output alongside the market report for easy review.
    out_path = REPORTS_DIR / "resume_comparison_report.md"
    print(f"[DEBUG] Writing resume comparison report: {out_path}", file=sys.stderr)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(comparison_output)
    section_break()


def main_resume_analyzer():
    try:
        resume_reader()
        compare_resume()
    except Exception as error:
        raise Exception(f"main_resume_analyzer() says: {error}") from error
    finally:
        cleanup_pycaches(BASE_DIR)


# Entrypoint for multiprocessing safety 
if __name__ == "__main__":
    try:
        # CLI usage: python -m src.extract.resume_extract.resume_analyzer [--verbose]
        args = sys.argv[1:]
        verbose_mode = False
        if args and args[-1] == "--verbose":
            verbose_mode = True
            args = args[:-1]
        if len(args) > 0:
            raise ValueError(
                "Too many arguments. Usage: python -m src.extract.resume_extract.resume_analyzer [--verbose]"
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

        resume_reader()
        compare_resume()
    except Exception as error:
        raise Exception(f"resume_analyzer() says: {error}") from error
    finally:
        cleanup_pycaches(BASE_DIR)
