import json, os, sys, concurrent.futures, concurrent.futures, openai, subprocess
from pathlib import Path
from src.extract.jobs_extract.schemas import JobPosting
from pypdf import PdfReader
from pydantic import ValidationError
from dotenv import load_dotenv, find_dotenv
from src.extract.jobs_extract.tools import web_search, get_web_results
from typing import cast
from openai.types.chat import ChatCompletionMessageParam
from openai import OpenAI
from tavily import TavilyClient

load_dotenv(find_dotenv())

# Directory macros
BASE_DIR = Path(__file__).resolve().parents[3]
JOBS_JSON_DIR = BASE_DIR / "data" / "jobs_JSON"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

SYS_PROMPT_FILE = os.path.join(SCRIPT_DIR, "INSTRUCTIONS_LLM.md")
with open(SYS_PROMPT_FILE, "r", encoding="utf-8") as f:
    SYS_PROMPT = f.read().strip()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
tavily = TavilyClient(api_key=TAVILY_API_KEY)

LLM_MODEL =  "openai/gpt-4o-mini"

# If macros are not in .env file, use 2nd param default
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "8"))
MAX_PDF_CHARS = int(os.getenv("MAX_PDF_CHARS", "30000"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "800"))

# Boolean macro
ENABLE_LLM_TOOLS = os.getenv("ENABLE_LLM_TOOLS", "1") == "1"

WEB_TIMEOUT = float(os.getenv("WEB_TIMEOUT", "20"))

MAX_LLM_TOOL_CALLS = 3
MAX_LLM_FAILURES = 5

# OpenAI client setup (OpenRouter endpoint)
openai = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

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


web_search_schema = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            web_search.__doc__ or
            "Tool used to search in the web for relevant information about a company, job roles and related topics to a job posting in order to help an applicant for it"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to use based on the desired information to fetch in the web"
                }
            },
            "required": ["query"],
            "additionalProperties": False
        },
        "strict": True  # This is required for auto-parsing
    }
}


def call_with_timeout(func, timeout, *args, **kwargs):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            # Waits for result of function before timeout
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Function call timed out after {timeout} seconds")



# Depends on boolean macros whether to perform a web_search
# This function is just an assistant in case we don't want to use tool calls
def maybe_enrich_with_web(result: JobPosting) -> JobPosting:
    
    # Do not run this function if tools are being used
    if ENABLE_LLM_TOOLS:
        return result

    company_name = (result.company_name or "").strip()
    # If no company listed, do not web_Search
    if not company_name or company_name.lower() == "not listed.":
        return result

    try:
        web_results = call_with_timeout(get_web_results, WEB_TIMEOUT, company_name)
    except TimeoutError:
        return result

    if result.relevant_data == ["Not found."] or result.relevant_data == ["Not listed."]:
        result.relevant_data = [web_results]
    else:
        result.relevant_data.append(web_results)

    return result



# Second parameter only used if LLM output is wrongly parsed
def parse_job_posting(content: str, raw_output: str) -> JobPosting:
    try:
        parsed = JobPosting.model_validate_json(content)
        print("[DEBUG] Structured output validation: passed (JobPosting)", file=sys.stderr)
    except ValidationError as error:
        raise ValueError(f"Output not properly parsed with JobPosting schema:\n {raw_output}.\nValidation error: {error}") from error
    return maybe_enrich_with_web(parsed)


# Calls the LLM to parse the file with the schema provided
# Handles web search for additional retrieved data (future agent use)
def schema_parse(pdf_path: str) -> JobPosting:
    try:
        # Get a LLM friendly format from the pdf content 
        pdf_text = read_pdf(pdf_path)
        pdf_name = os.path.basename(pdf_path)

        system_prompt = SYS_PROMPT
        if not ENABLE_LLM_TOOLS:
            system_prompt += "\n\nDo not call any tools in this step. Extract only from the provided PDF text."

        messages_pack = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": pdf_text},
        ]
        
        raw_output = None
        message = None
        result = None
        try:
            # keyword arguments
            request_kwargs = {
                "model": LLM_MODEL,
                "messages": cast(list[ChatCompletionMessageParam], messages_pack),
                "response_format": JobPosting,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            if ENABLE_LLM_TOOLS:
                request_kwargs["tools"] = [web_search_schema]
            print(f"[DEBUG] LLM call: {LLM_MODEL} (schema_parse initial)", file=sys.stderr)
            response = call_with_timeout(
                openai.chat.completions.parse,
                LLM_TIMEOUT,
                **request_kwargs,
            )

        except TimeoutError as error:
            raise TimeoutError(f"LLM call timed out: {error}") from error
            
        message = response.choices[0].message
        raw_output = message.content

        # Aggregate conversation messages
        msg_dict = {"role": message.role, "content": message.content}
        if hasattr(message, "tool_calls") and message.tool_calls:
            msg_dict["tool_calls"] = message.tool_calls
        messages_pack.append(msg_dict)

        try:
            # No more tool calls
            if not message.tool_calls and message.content and raw_output:
                # VALID SCHEMA RESULT
                return parse_job_posting(message.content, raw_output)
        except ValidationError as error:
            raise ValueError(f"Output not properly parsed with JobPosting schema:\n {raw_output}.\nValidation error: {error}") from error
        

        tool_call_count = 0
        if ENABLE_LLM_TOOLS and message.tool_calls:

            # Process tool call(s) and continue
            for tool_call in message.tool_calls:
                tool_call_count += 1

                if tool_call_count > MAX_LLM_TOOL_CALLS:

                    print(f"[DEBUG] Exceeded maximum allowed tool calls ({MAX_LLM_TOOL_CALLS}) for {pdf_name}", file=sys.stderr)
                    # Limit tool calls but still respond to each tool_call_id
                    result = {"error": f"Exceeded maximum allowed tool calls ({MAX_LLM_TOOL_CALLS}) for {pdf_name}"}
                
                if tool_call_count <= MAX_LLM_TOOL_CALLS:
                    fn_name = tool_call.function.name
                    try:
                        args_json = json.loads(tool_call.function.arguments)

                        # Check for correct tool call name
                        if fn_name == "web_search":
                            valid_args = web_search(**args_json)

                            import time
                            # Measure time for web_search
                            tool_start = time.perf_counter()
                            try:
                                result = call_with_timeout(get_web_results, WEB_TIMEOUT, valid_args.query)
                            except TimeoutError as e:

                                print(f"[DEBUG] Tavily search timed out: {e}", file=sys.stderr)
                                result = {"error": f"Tavily search timed out: {e}"}

                            tool_elapsed = time.perf_counter() - tool_start
                            print(f"[DEBUG]         get_web_results took {tool_elapsed:.2f} seconds", file=sys.stderr)

                        else:
                            print(f"[DEBUG]     Unknown tool called: {fn_name}", file=sys.stderr)
                            result = {"error": "Unknown tool"}

                    except Exception as error:
                        result = {"error": str(error)}

                if not isinstance(result, str):
                    result = json.dumps(result)

                messages_pack.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

        print(f"[DEBUG] Total tool calls for {pdf_name}: {tool_call_count - 1}", file=sys.stderr)


        # Final LLM call after tools
        try:
            # keyword arguments
            request_kwargs = {
                "model": LLM_MODEL,
                "messages": cast(list[ChatCompletionMessageParam], messages_pack),
                "response_format": JobPosting,
                "max_tokens": MAX_OUTPUT_TOKENS,
            }
            print(f"[DEBUG] LLM call: {LLM_MODEL} (schema_parse final)", file=sys.stderr)
            response = call_with_timeout(
                openai.chat.completions.parse,
                LLM_TIMEOUT,
                **request_kwargs,
            )

        except TimeoutError as error:
            raise TimeoutError(f"LLM FINAL call timed out: {error}") from error
        
        message = response.choices[0].message
        raw_output = message.content

        if not message or not message.content:
            raise ValueError("LLM did not return any valid result.")
        
        # Parse the result of the agent according to schema
        try:
            # VALID SCHEMA RESULT
            if message.content and raw_output:
                return parse_job_posting(message.content, raw_output)
           
        except ValidationError as error:
            raise ValueError(f"Output not properly parsed with JobPosting schema:\n {raw_output}.\nValidation error: {error}") from error
    
    # other unknown errors
    except Exception as error:
        raise RuntimeError(error) from error
    
    # Final safety net
    raise RuntimeError("schema_parse() did not return a JobPosting and did not raise an error earlier.")


# Parses a PDF according to JobPosting schema and returns it
# Handles limited attempts for the LLM to parse
def parse_pdf(pdf_path: Path) -> JobPosting:
    string_path = str(pdf_path)

    import time
   
    try:
        # LLM response with parsed JobPosting 
        print(f"[DEBUG] Parsing job posting PDF: {pdf_path.name}", file=sys.stderr)

        # Measure time running schema_parse()
        start_time = time.perf_counter()
        result = schema_parse(string_path)
        elapsed = time.perf_counter() - start_time
        
        print(f"[DEBUG] schema_parse for {pdf_path.name} took {elapsed:.2f} seconds", file=sys.stderr)
        print(f"[DEBUG] Extracted {len(result.required_skills)} required skills, {len(result.nice_have_skills)} preferred skills", file=sys.stderr)
        return result
    except Exception as error:
        raise error
        

# Reads PDFs in data/jobs_postings (if present) and generates JSON files from them
# into data/jobs_JSON
def jobs_reader() -> list[JobPosting]:

    results: list[JobPosting] = []
    failure_count = 0
    verbose_mode = os.getenv("APP_VERBOSE") == "1"

    def section_break() -> None:
        if verbose_mode:
            print("", file=sys.stderr)

    try:
        # List of paths to PDFs in alphabet order (same as in directory)
        pdf_paths = sorted((BASE_DIR / "data" / "jobs_postings").rglob("*.pdf"))

        # Verify if new PDFs were added in data/jobs_postings
        if len(pdf_paths) > 0:
            
            print(f"[DEBUG] Found {len(pdf_paths)} potential job posting PDFs to process", file=sys.stderr)

            # Creates dir if it does not exist
            JOBS_JSON_DIR.mkdir(parents=True, exist_ok=True)

            # Sequentially process each PDF
            for pdf_path in pdf_paths:
                try:

                    out_path = JOBS_JSON_DIR / f"{pdf_path.stem}.json"

                    # If JSON already exists and is valid, skip re-processing this PDF
                    if out_path.exists():
                        try:
                            print(f"[DEBUG] Reading JSON file: {out_path}", file=sys.stderr)
                            with open(out_path, "r", encoding="utf-8") as f:
                                # If the JSON is correct, nothing happens, otherwise, load() raises
                                json.load(f)

                            # Existing JSON is valid, so we skip this PDF
                            print(f"[DEBUG] Skipping {pdf_path.name} (valid JSON exists).", file=sys.stderr)
                            continue
                        except Exception:
                            # If JSON is missing/corrupt, fall through and re-generate it
                            pass

                    # LLM response with parsed JobPosting 
                    job_posting = parse_pdf(pdf_path)
                    # Store in collection of JobPostings
                    results.append(job_posting)


                    # Write JSON file of JobPosting schema
                    try:
                        print(f"[DEBUG] Writing JSON file: {out_path}", file=sys.stderr)
                        with open(out_path, "w", encoding="utf-8") as f:
                            # Convert job schema into a dict
                            job_dict = job_posting.model_dump(mode="json")
                            # this method expects a python dict to convert it to JSON format
                            json.dump(job_dict, f, indent=2)
                    except (OSError, TypeError) as error:
                        raise RuntimeError(f"Failed to write JSON output: {out_path}") from error

                    # Automatically stage and commit the new job posting to the repository
                    try:
                        subprocess.run(["git", "add", str(out_path)], check=True, cwd=BASE_DIR)
                        subprocess.run(["git", "commit", "-m", "User contribution before executing app.", str(out_path)], check=True, cwd=BASE_DIR)
                        print(f"[DEBUG] Git: Added and committed {out_path}", file=sys.stderr)
                    except Exception as git_error:
                        print(f"[DEBUG] Git contribution failed: {git_error}", file=sys.stderr)

                except Exception as error:
                    failure_count += 1
                    print(f"[DEBUG] Error occured with {pdf_path.name}: {error}", file=sys.stderr)
                    if failure_count >= MAX_LLM_FAILURES:
                        raise RuntimeError(
                            f"Global LLM failure cap reached ({failure_count}). Last file {pdf_path.name} failed to parse."
                        ) from error

                    # Next pdf if failure_count not yet reached to max
                    continue
                finally:
                    section_break()

    except Exception as error:
        print(f"[DEBUG] jobs_reader() says: {error}", file=sys.stderr)
        sys.exit(1)
    return results


