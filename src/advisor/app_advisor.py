import os, sys, shutil, json, atexit, re, time, requests, subprocess
from pathlib import Path
from src.extract.jobs_extract.jobs_reader import parse_pdf, JobPosting

from dotenv import load_dotenv, find_dotenv
from openai import OpenAI
from src.analysis.market_analysis import main_market_analysis
from src.extract.resume_extract.resume_analyzer import main_resume_analyzer


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
JOBS_JSON_DIR = BASE_DIR / "data" / "jobs_JSON"
REPORTS_DIR = BASE_DIR / "reports"
SCRIPT_DIR = Path(__file__).resolve().parent
USER_JOBPOST_JSON_DIR = SCRIPT_DIR / "user_jobpost_JSON"

# The URL of the Vercel Proxy to send user contributions. 
PROXY_URL = os.getenv("CONTRIBUTION_PROXY_URL")

SYS_PROMPT_FILE = os.path.join(SCRIPT_DIR, "INSTRUCTIONS_LLM.md")
with open(SYS_PROMPT_FILE, "r", encoding="utf-8") as f:
    SYS_PROMPT = f.read().strip()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# OpenAI client setup (OpenRouter endpoint)
openai = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)


def parse_user_jobpost(job_posting_path: str) -> JobPosting:
    if not job_posting_path:
        raise ValueError("A job posting path is required.")

    # if job_posting_path starts with ~, construct whole absolute path
    src_path = Path(job_posting_path).expanduser()

    # Enforce absolute paths so we can safely locate file on user's machine.
    if not src_path.is_absolute():
        raise ValueError(f"Expected an absolute path, got: {job_posting_path}")

    if not src_path.exists():
        raise FileNotFoundError(f"Job posting not found at: {src_path}")

    if src_path.suffix.lower() != ".pdf":
        raise ValueError(f"Job posting must be a PDF file, got: {src_path.name}")

    # Read and return the JobPosting schema from the parsed user's PDF.
    return parse_pdf(src_path)


# Remove __pycache__ folders to keep the repo clean after running.
def cleanup_pycaches(base_dir: Path) -> None:
    
    for root, dirs, _ in os.walk(base_dir):
        if "__pycache__" in dirs:
            cache_path = Path(root) / "__pycache__"
            try:
                shutil.rmtree(cache_path)
            except OSError as error:
                print(f"[DEBUG] Failed to remove {cache_path}: {error}", file=sys.stderr)


# Formats the elapsed time into a human-readable string with proper pluralization.
def timer(start_time: float, end_time: float) -> str:
   
    elapsed = end_time - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    if minutes == 0:
        unit = "second" if seconds == 1 else "seconds"
        return f"{seconds} {unit}"

    m_unit = "minute" if minutes == 1 else "minutes"
    if seconds == 0:
        return f"{minutes} {m_unit}"

    s_unit = "second" if seconds == 1 else "seconds"
    return f"{minutes} {m_unit} and {seconds} {s_unit}"


# Sends the job posting JSON to a remote proxy for centralized collection.
def contribute_database(json_path: Path) -> None:

    # Check if the PROXY_URL is configured in the .env file.
    if not PROXY_URL:
        print("[DEBUG] Contribution skipped: CONTRIBUTION_PROXY_URL not set in .env", file=sys.stderr)
        print('⚠️ macro: "CONTRIBUTION_PROXY_URL" not found in .env file. \n\n Please verify your ./.env and ensure this macro is set with the default value as in ./.env.example.')
        return 
    
    # Read the JSON job posting 
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            job_data = json.load(f)
    except Exception as e:
        # If reading fails, we log the error to the debug console.
        print(f"[DEBUG] Failed to read JSON for contribution: {e}", file=sys.stderr)
        print(f'⚠️ Contribution Error: Could not read the data file ({e}).')
        return 

    # Prepare the payload (the data packet we are sending to Vercel).
    payload = {
        "file_name": json_path.name,
        "content": job_data
    }

    # Send the payload to Vercel Proxy using an HTTP POST request.
    print(f"[DEBUG] Sending contribution to proxy: {PROXY_URL}", file=sys.stderr)
    try:
        # We set a 10-second timeout to prevent the app from hanging if the server is down.
        response = requests.post(PROXY_URL, json=payload, timeout=10)
        
        # Check the HTTP response status.
        # 200 (OK) or 201 (Created) means the Vercel Proxy successfully received the data.
        if response.status_code in [200, 201]:
            
            # Synchronize the local database with the new cloud contribution
            try:
                print("[DEBUG] Synchronizing local database...", file=sys.stderr)
                # --quiet keeps the terminal clean
                subprocess.run(["git", "pull", "--quiet"], check=True, cwd=BASE_DIR)
            except (subprocess.CalledProcessError, FileNotFoundError) as git_err:
                print(f"[DEBUG] Git sync failed: {git_err}", file=sys.stderr)

            print("\nThanks for contributing to our application, good luck for your job seeking! 💪")

        elif response.status_code >= 500:
            print(f"[DEBUG] Proxy returned error {response.status_code}: {response.text}", file=sys.stderr)
            print("⚠️ Contribution Error: The contributions server is currently having issues. Please notify the administrator.")

        else:
            print(f"[DEBUG] Proxy returned error {response.status_code}: {response.text}", file=sys.stderr)
            print(f"⚠️ Contribution Error: Status {response.status_code}). Please notify the administrator.")
   

    except requests.exceptions.Timeout:
        print(f"[DEBUG] Network error: Request timed out", file=sys.stderr)
        print("⚠️ Contribution Error: The contributions server took too long. The server might be busy.")

    except requests.exceptions.ConnectionError:
        print(f"[DEBUG] Network error: Could not connect to the contribution server", file=sys.stderr)
        print("⚠️ Contribution Error: Could not connect to the contribution server. It might be offline.")

    except requests.exceptions.RequestException as e:
        print(f"[DEBUG] Contribution Unexpected Error: {e}", file=sys.stderr)
        print(f"⚠️ Contribution Unexpected Error: {e}")


# Compares the user JobPosting JSON against the Market Analysis and Resume Comparison report
# Produces the Application Report.
def compare_jobpost(jobpost_json_path: Path) -> None:
    
    market_report_path = REPORTS_DIR / "market_analysis_report.md"
    resume_report_path = REPORTS_DIR / "resume_comparison_report.md"

    if not jobpost_json_path.exists():
        raise FileNotFoundError(
            f"Job posting JSON not found at: {jobpost_json_path}. Run app_advisor() first."
        )

    if not market_report_path.exists():
        raise FileNotFoundError(
            f"Market analysis report not found at: {market_report_path}. Run market_analysis() first."
        )

    if not resume_report_path.exists():
        raise FileNotFoundError(
            f"Resume comparison report not found at: {resume_report_path}. Run resume_analyzer() first."
        )

    print(f"[DEBUG] Reading user job posting JSON: {jobpost_json_path}", file=sys.stderr)

    with open(jobpost_json_path, "r", encoding="utf-8") as f:
        jobpost_json_text = f.read()
    try:
        jobpost_payload = json.loads(jobpost_json_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Job posting JSON is invalid: {jobpost_json_path}") from error

    # Get company name of the job post
    company_name = (jobpost_payload.get("company_name") or "").strip()
    if not company_name or company_name.lower() == "not listed.":
        company_name = "unknown_company"

    # Sanitize uncommon chars to underscore
    company_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", company_name).strip("_").lower()
    if not company_slug:
        company_slug = "unknown_company"

    print(f"[DEBUG] Reading market analysis report: {market_report_path}", file=sys.stderr)
    with open(market_report_path, "r", encoding="utf-8") as f:
        market_report_text = f.read()

    print(f"[DEBUG] Reading resume comparison report: {resume_report_path}", file=sys.stderr)
    with open(resume_report_path, "r", encoding="utf-8") as f:
        resume_report_text = f.read()

    # Keep all sources in a single user message so the model has full context.
    user_input = (
        "## Job Posting JSON\n"
        f"{jobpost_json_text}\n\n"
        "## Market Analysis Report\n"
        f"{market_report_text}\n\n"
        "## Resume Comparison Report\n"
        f"{resume_report_text}"
    )

    print("[DEBUG] LLM call: cohere/command-r-plus-08-2024 (compare_jobpost)", file=sys.stderr)
    response = openai.chat.completions.create(
        model="cohere/command-r-plus-08-2024",
        messages=[
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": user_input},
        ],
    )

    comparison_output = ""
    # Defensive extraction in case the provider returns empty choices.
    if response.choices and response.choices[0].message:
        comparison_output = response.choices[0].message.content or ""

    # Store the comparison output alongside the other reports for easy review.
    base_name = f"application_report_{company_slug}.md"
    out_path = REPORTS_DIR / base_name
    counter = 2

    # Append a number at the end of file name, if a previous file exists with the same name 
    # Handles cases when 2+ job posts are for the same role and company but have different descriptions (e.g. come from different job portals)
    # Also handles cases where resume changed & you want to compare the before/after
    while out_path.exists():
        out_path = REPORTS_DIR / f"application_report_{company_slug}_{counter}.md"
        counter += 1

    print(f"[DEBUG] Writing application report: {out_path}", file=sys.stderr)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(comparison_output)

   


def app_advisor():

    # Start the timer
    start_time = time.perf_counter()
    try:
        

        # CLI usage: python -m src.advisor.app_advisor <path_to_job_posting> [--verbose]
        args = sys.argv[1:]

        # Detect and handle accidental brackets in arguments
        for arg in args:
            if any(char in arg for char in '<>[]'):
                print(f"Error: Argument '{arg}' contains invalid bracket characters ('<', '>', '[', or ']').")
                print("Please provide the arguments without brackets (e.g., C:\\path\\to\\job.pdf).")
                return

        # Optional verbose flag must be the last argument when provided.
        verbose_mode = False
        if args and args[-1] == "--verbose":
            verbose_mode = True
            args = args[:-1]

        if len(args) < 1:
            raise ValueError(
                "Missing path to job posting PDF. Usage: python -m src.advisor.app_advisor <path_to_job_posting> [--verbose]"
            )
        if len(args) > 1:
            raise ValueError(
                "Too many arguments. Usage: python -m src.advisor.app_advisor <path_to_job_posting> [--verbose]"
            )

        # Redirect stderr to debug file when verbose mode is enabled.
        debug_stderr = sys.stderr
        if verbose_mode:
            debug_path = SCRIPT_DIR / "debug.txt"
            debug_file = open(debug_path, "w", encoding="utf-8")
            debug_stderr = IndentedStderr(debug_file)
            sys.stderr = debug_stderr
            atexit.register(debug_file.close)
            os.environ["APP_VERBOSE"] = "1"
        else:
            # Suppress debug logs in the terminal when verbose mode is off.
            sys.stderr = FilteredStderr(sys.stderr)

        # Helper to update indentation safely when stderr is wrapped.
        def set_debug_indent(level: int) -> None:
            if isinstance(debug_stderr, IndentedStderr):
                debug_stderr.indent = level

        def start_section(title: str) -> None:
            if verbose_mode:
                set_debug_indent(0)
                print(f"\n[DEBUG] === {title} ===\n", file=sys.stderr)
                set_debug_indent(2)

        def end_section() -> None:
            if verbose_mode:
                set_debug_indent(0)
                print("", file=sys.stderr)

        # python -m not included in sys.argv
        user_jobpost_path = args[0]

        # Read provided file and get its JobPosting schema
        start_section("Phase 0: Parse Job Posting")
        
        print(f"\nReading PDF 📃: {Path(user_jobpost_path).name}\n")
        user_jobpost_schema = parse_user_jobpost(user_jobpost_path)
        
        if not user_jobpost_schema:
            raise ValueError("No valid schema for user job posting.")


        print(f"[DEBUG] Parsed job posting from user as a JobPosting schema", file=sys.stderr)

            
        USER_JOBPOST_JSON_DIR.mkdir(parents=True, exist_ok=True)
        out_path = USER_JOBPOST_JSON_DIR / f"{Path(user_jobpost_path).stem}.json"
        json_exists = False

        # If user's job post JSON already exists and is valid, skip re-processing this PDF
        if out_path.exists():
            try:
                print(f"[DEBUG] Reading JSON file: {out_path}", file=sys.stderr)
                with open(out_path, "r", encoding="utf-8") as f:
                    # If the JSON is correct, nothing happens, otherwise, load() raises
                    json.load(f)

                # Existing JSON is valid, so we skip this PDF
                print(f"[DEBUG] JSON file for: {Path(user_jobpost_path).name} already exists.", file=sys.stderr)
                json_exists = True

            except Exception:
                # If JSON is missing/corrupt, fall through and re-generate it
                pass

        
        # If user's job post JSON not present in out_path, write it
        if not json_exists:

            # Write JSON file of JobPosting schema
            try:
                print(f"[DEBUG] Writing JSON file: {out_path}", file=sys.stderr)
                with open(out_path, "w", encoding="utf-8") as f:
                    # Convert job schema into a dict
                    job_dict = user_jobpost_schema.model_dump(mode="json")
                    # this method expects a python dict to convert it to JSON format
                    json.dump(job_dict, f, indent=2)

                print(f"[DEBUG] Wrote JSON file for: {Path(user_jobpost_path).name}.", file=sys.stderr)
            except OSError as error:
                raise RuntimeError(f"Failed to write JSON output: {out_path}") from error
        
        
        end_section()
        start_section("Phase 1: Market Analysis")

        # Do Phase 1: Build or refresh /data/jobs_JSON, then generate **Market Analysis Report**
        print("Analyzing the IT Market.... 🤔")
        main_market_analysis()
        print("Market Analysis Report ready.\n")

        end_section()
        start_section("Phase 2: Resume Comparison")

        # Do Phase 2: Parse resume PDF inside ./data/user/resume to JSON, then generate **Resume Comparison Report**
        print("🔎 Comparing current Resume with the IT Market.")
        main_resume_analyzer()
        print("Resume Comparison Report ready.\n")


        end_section()
        start_section("Phase 3: Application Report")

        # Do Phase 3: Compare user's job posting against both reports and generate **Application Report**
        print("Determining feasibility of applying to this job posting according to Resume... ⚖️")
        compare_jobpost(out_path)
        print("Application Report ready! 😄\n\n")
        end_section()


        # Final: Ask user whether to add their job posting to the database for enrichment.
        start_section("User Contribution")
        existing_db_copy = JOBS_JSON_DIR / f"{Path(user_jobpost_path).stem}.json"
        while True:
            user_choice = input(
                "The application report was succesfully written to the reports folder.\n"
                "Would you like us to collect your provided job posting PDF for enrichment purposes of our database? (yes/no)\n> "
            ).strip().lower()

            if user_choice == "yes":

                if existing_db_copy.exists():
                    print(
                        "\nIt looks like we already had your job posting file in our database, "
                        "do not hesitate to contribute with a new one next time!"
                    )
                    break

                # Send to the centralized database via the Vercel Proxy
                contribute_database(out_path)
                break
                    
            if user_choice == "no":
                print("Thanks for using our application, good luck for your job seeking! 💪")
                break

            # If the user did not provide a valid response, ask again.
            print("Please answer 'yes' or 'no'.\n")

        print('\nYou can now check your report(s) at ./reports !')
        end_section()
        
    except Exception as error:
        raise Exception(f"An error occurred: {error}")
    finally:
        end_time = time.perf_counter()
        print(f"Total time elapsed: {timer(start_time, end_time)}")
        cleanup_pycaches(BASE_DIR)




if __name__ == "__main__":
    try:
        app_advisor()
    except Exception as error:
        raise Exception(f"app_advisor() says: {error}") from error
