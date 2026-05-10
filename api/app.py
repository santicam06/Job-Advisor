from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import requests
import base64

# Adds indentation to stderr lines for readable debug logs.
class IndentedStderr:
    def __init__(self, stream):
        self.stream = stream
        self.indent = 0
        self._at_line_start = True

    # print(..., file=sys.stderr) calls write() under the hood.
    def write(self, text: str) -> int:
        lines = text.splitlines(keepends=True)
        for line in lines:
            if self._at_line_start and line != "\n":
                prefix = " " * self.indent
                self.stream.write(prefix)
            
            self.stream.write(line)
            self._at_line_start = line.endswith("\n")
        return len(text)

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

# This class handles the incoming network requests 
class handler(BaseHTTPRequestHandler):

    # Handles the HTTP POST request sent by app_advisor.py
    # All DEBUG logs in this function will be seen in the Vercel (cloud) dashboard
    def do_POST(self):

        # Set up logging based on the environment variable
        # This allows the administrator to see detailed logs in the Vercel dashboard
        verbose_mode = os.environ.get("APP_VERBOSE") == "1"
        if verbose_mode:
            sys.stderr = IndentedStderr(sys.stderr)
        else:
            sys.stderr = FilteredStderr(sys.stderr)
        
        # GitHub configuration macros
        token = os.environ.get("GITHUB_PAT")
        owner = os.environ.get("GITHUB_OWNER")
        repo = os.environ.get("GITHUB_REPO")

        try:
            # Validate that the server has the necessary credentials
            if not token or not owner or not repo:

                print(f"[DEBUG] configuration error: PAT={bool(token)}, Owner={owner}, Repo={repo}", file=sys.stderr)

                # Send a polite, generic error to the end user
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Contribution failed: GitHub credentials may be missing.")
                return

            print(f"[DEBUG] Parsing user's contribution", file=sys.stderr)
            # Parse the user's contribution data
            content_length = int(self.headers.get('Content-Length', 0))
            raw_data = self.rfile.read(content_length)
            # Transform raw JSON into Python dict
            payload : dict = json.loads(raw_data)

            file_name = payload.get('file_name')
            job_content = payload.get('content')

            if not file_name or not job_content:
                # Log payload issue for the administrator
                print(f"[DEBUG] Invalid contribution payload format. Received keys: {list(payload.keys()) if payload else 'None'}", file=sys.stderr)
                
                # Send generic error to the user
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Contribution failed: Payload keys different than file_name & job_content.")
                return

            # Prepare GitHub API data
            # Data must be base64 STRING-encoded for the GitHub 'Contents' API
            json_string = json.dumps(job_content, indent=2)
            # JSON > bytes > base64 (bytes) > base64 (string, e.g. SGVsbG8gd29ybGQ)
            encoded_content = base64.b64encode(json_string.encode('utf-8')).decode('utf-8')

            github_url = f"https://api.github.com/repos/{owner}/{repo}/contents/data/jobs_JSON/{file_name}"

            # Call the GitHub API
            print(f"[DEBUG] Proxying contribution to GitHub: {owner}/{repo}", file=sys.stderr)
            gh_response = requests.put(
                github_url,
                headers={
                    "Authorization": f"token {token}",
                    # Response back format from GitHub
                    "Accept": "application/vnd.github.v3+json"
                },
                # The format of the sender payload (user contribution)
                json={
                    # Commit message
                    "message": f"User Contribution: {file_name}",
                    "content": encoded_content
                },
                timeout=15
            )

            # Send response back to user's CLI
            if gh_response.status_code in [200, 201]:
                print(f"[DEBUG] GitHub upload successful: {file_name}", file=sys.stderr)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Contribution successful.")
            else:
                # Log exact GitHub API response for administrator debugging
                print(f"[DEBUG] GitHub API Error ({gh_response.status_code}): {gh_response.text}", file=sys.stderr)
                
                # Generic message for user
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Contribution failed: The server encountered an error while updating the database.")

        except Exception as e:
            # Log the exact exception object for the administrator
            print(f"[DEBUG] Critical Proxy Error: {e}", file=sys.stderr)
            
            # Send general message to the user
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Contribution failed: An internal error occurred in the proxy server.")
