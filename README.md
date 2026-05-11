# Job Advisor Pipeline

LLMs used in this application:
- **Arcee Trinity Large Thinking**
- **Cohere Command R+ (08-2024)**
- **OpenAI GPT-4o mini**
- **Mistral AI Codestral 25.08**
- **NVIDIA Nemotron 3 Nano 30B-A3B**


## Setup Instructions

Before running the application, follow these steps:

1. For this repository, create a **GitHub Codespace (Cloud)** OR clone it locally and open it with your preferred code editor (e.g. Visual Studio Code, ...).

2. **Install Python** (If not already installed):
   - **Windows**: Download the latest installer from [python.org](https://www.python.org/downloads/windows/) or use: `winget install Python.Python.3.12`
   - **macOS**: Use Homebrew: `brew install python`
   - **Linux (Ubuntu/Debian)**: `sudo apt update && sudo apt install python3 python3-venv python3-pip`
   - **Cloud Workspaces (Codespaces, etc.)**: Python is usually pre-installed. Run `python3 --version` to verify and skip this step.

3. **Create and Activate a Virtual Environment**:

>[!IMPORTANT]
From this point on, make sure that your present working directory on your terminal is the root directory of the application: `./Job-Advisor`. 

   - Create the environment:
     - **Windows**: `python -m venv .venv`
     - **macOS/Linux**: `python3 -m venv .venv`
   - Activate it:
     - **Windows**: `.\.venv\Scripts\activate`
     - **macOS/Linux**: `source .venv/bin/activate`

4. **Install Dependencies**:
   - Upgrade `pip` and install required libraries:
     ```powershell
     python -m pip install --upgrade pip
     python -m pip install -r requirements.txt
     ```

5. **Environment Configuration**:
   - Create a local `.env` file by copying the template file `.env.example`. This file contains all required API keys and configuration macros for the application, read it carefully:
   ```powershell
     # On Windows (Command Prompt)
     copy .env.example .env
     # On macOS/Linux or PowerShell
     cp .env.example .env
   ```
> [!IMPORTANT]
Always **copy** the template. Do not rename `.env.example` directly, as it must remain in the repository as a reference for required environment variables.

   - Open the newly created `.env` file and fill in your API keys (e.g., `OPENROUTER_API_KEY, ...`) and adjust optional configuration settings as needed. The application **will not** function without a valid `.env` file in the **application root** (`./Job-Advisor`).

6. **Main Directories Glossary**:
   - `./api/`: Vercel proxy integration logic for user contributions.
   - `./data/`: Contains subdirectories for input documents and application's database.
   - `./reports/`: Target directory for LLM-generated Markdown reports.
   - `./src/`: Scripts with application's behaviour and system prompts.
> [!NOTE]
The content inside `./src/advisor/user_jobpost_JSON/`, `./reports/` and `./data/` is Git ignored (except for `./data/jobs_JSON/` which is the **database**) as it is private information that you should manage locally, you can change the `./.gitignore` file at your convenience.
   
        

### Troubleshooting
- **Missing API Key**: Ensure `OPENROUTER_API_KEY/TAVILY_API_KEY` are correctly set in your `.env` file.
- **Dependency Issues**: If running in a new environment, ensure you have executed the commands in **Step 3**.
- **Virtual Environment Not Activated**: If you receive "module not found" errors, ensure your virtual environment is activated **(Step 3)**.
- **Absolute Paths**: For the Main Application (Job Advisor), ensure you provide an **absolute path** to the PDF file (instructions below). 


---
### This codebase runs in three phases. Each phase is a separate Python module entrypoint. 
- First 2 phases should be run only for engineering purposes, go down straight to the **Job Advisor** section if you only care about getting that job!

>[!IMPORTANT]
**Reminder:** All the following terminal commands you'll see must be executed from the root of the application `./Job-Advisor`.


## Phase 1: Market Analysis Report

**Command**

```powershell
# Windows
python -m src.analysis.market_analysis
# macOS/Linux
python3 -m src.analysis.market_analysis
```

Optional verbose flag:
```powershell
# Windows
python -m src.analysis.market_analysis --verbose
# macOS/Linux
python3 -m src.analysis.market_analysis --verbose
```
This writes detailed debug logs to `./src/analysis/debug.txt`.


#### What it does

- Summarizes the data in `./data/jobs_JSON/` which is parsed from real job posting PDFs plus RAG enriched (using **Tavily Search**) to get extra information about each employer. 
- Generates a Market Analysis Report in `./reports/`, showing relevant data about the current IT (developers) industry scenario such as: key fields, skills, practices, academic requirements and other features, in order to assist with job seeking.

#### Considerations
- The application comes with a pre-populated database in `./data/jobs_JSON/` which is aimed for software developers. 

- If you wish to enrich the database further (e.g. with job postings for punctual IT roles), you can add more job postings in **PDF** format to `./data/jobs_postings/` and re-run the script, the system will parse their JSON versions. Save the PDF(s) as: `[Role] - [Employer Name]` (e.g. Full Stack Developer - Tech & Geeks Inc.), this will help you visualize your files in a clean and ordered way.

Enriching the database will enhance the analysis of the LLM in charge of producing the Market Analysis Report, new files added will be automatically commited only **locally**, when running the phase.

## Phase 2: Resume Comparison

**Command**

```powershell
# Windows
python -m src.extract.resume_extract.resume_analyzer
# macOS/Linux
python3 -m src.extract.resume_extract.resume_analyzer
```

Optional verbose flag:
```powershell
# Windows
python -m src.extract.resume_extract.resume_analyzer --verbose
# macOS/Linux
python3 -m src.extract.resume_extract.resume_analyzer --verbose
```
This writes detailed debug logs to `./src/extract/resume_extract/debug.txt`.


#### What it does

- Reads a single resume PDF from `./data/user/resume`.
- Creates a JSON parsed version from that resume as `./data/user/resume/[PDF NAME].json`.
- Compares the JSON file against the Market Analysis Report.
- Generates a Resume Comparison Report in `./reports/` stating **strengths, unique value, and gaps** from the user's resume compared to the Market Analysis Report, along with recommendations of how to enhance their profile. 

#### Additional information
- A new JSON parsed resume will be generated only when a new PDF resume is uploaded, this means that when running the phase several times with the same resume, the JSON file **will not** change at all.
- For cleaning purposes, JSONs from older PDF resumes can be deleted, as this phase only processes the JSON from the current PDF uploaded, the rest will be ignored.

> [!IMPORTANT]
**Uploading the resume**: **Drag and drop** the resume from your local computer directly onto the `./data/user/resume` directory in the explorer bar of your editor. Phase 2 only reads **one** PDF from this directory, **ensure** is the **only** PDF there. 

If you don't want to use your own resume you can look for sample resumes PDFs online and download one prototype.



## Job Advisor (end-user usage)

This app receives the path to a **job posting PDF** that you provide (it can be whichever you want). 
   
> [!TIP]
If you need help converting an online job posting (e.g. from LinkedIn) into a PDF format you can save the job's page as a PDF using `CTRL + P` (or respective shortcut). Alternatively try online converters such as: [W2P](https://www.web2pdfconvert.com/). 

Save the PDF **locally** in your computer as: `[Role] - [Employer Name]` (e.g. Full Stack Developer - Tech & Geeks Inc.), this will help you visualize your files in a clean and ordered way.

> [!IMPORTANT]
**Verify** that the job posting looks correct in the PDF such as you saw it on the web.


As well make sure you have uploaded ONE **PDF resume**.
- **Drag and drop** the PDF from your local computer directly onto the `./data/user/resume` folder in the explorer bar of your editor.
---

 
**Command**

```powershell
# Windows
python -m src.advisor.app_advisor "<path_to_job_posting>"
# macOS/Linux
python3 -m src.advisor.app_advisor "<path_to_job_posting>"
```

> [!IMPORTANT]
The path to the PDF must be an **absolute path**, note the quotes to wrap the path as parameter.

> [!NOTE]
**Cloud Workspace Users (Codespaces, GitPod, ...)**: If you are working in a remote environment you will need to upload the job posting PDF into `./data/user/` (**drag and drop**). Then copy its absolute path and use it in the command above. 

**Examples:**
- **Windows**: `python -m src.advisor.app_advisor "C:\Users\johndoe\Documents\job_posting.pdf"`
- **macOS/Linux**: `python3 -m src.advisor.app_advisor "/home/johndoe/Documents/job_posting.pdf"`
- **Codespaces**: `python3 -m src.advisor.app_advisor "/workspaces/Job-Advisor/data/user/job_posting.pdf"`



Optional verbose flag:
```powershell
# Windows
python -m src.advisor.app_advisor "<path_to_job_posting>" --verbose
# macOS/Linux
python3 -m src.advisor.app_advisor "<path_to_job_posting>" --verbose
```
This writes detailed debug logs to `./src/advisor/debug.txt`.


#### What it does
- Gathers a Market Analysis Report & Resume Comparison Report using the previous phases.
- From the provided PDF path, it will parse your job posting as a JSON file in `src\advisor\user_jobpost_JSON`.
- Compares the JSON file against both aforementioned reports.
- Generates an Application Report in `./reports/` stating how feasible it is to really apply for the job provided; considering the market, and the uploaded resume.


#### About the Application Report

- It will display a score at the beggining that shows the feasibility to apply for the job.

##### The scoring rubric

| Score Range | Recommendation                                                                       |
| :---------- | :----------------------------------------------------------------------------------- |
| 80%+        | Strong fit, you should definitely apply                                              |
| 50–79%      | Good fit, you meet the core requirements, apply and highlight your strengths         |
| 30–49%      | Stretch, worth applying if the role excites you, but there is room for improvement   |
| Below 30%   | Significant gaps, consider this a growth target rather than an immediate application |
---

- You'll find written sections for tailoring the resume, tips for a cover letter, and interview preparation (questions, advices, etc.).


#### End of the app

At the end, the app asks:

```
The application report was successfully written to the reports folder. Would you like us to collect your provided job posting for enrichment purposes of our database? (yes/no)
```

**Response format**

- Reply with `yes` or `no` (case-insensitive). Any other input will re-prompt.

---

## Final Step: Deactivate the Virtual Environment

Once you are finished working with the application, you can deactivate the virtual environment to return to your global Python context:

```powershell
# Terminal
deactivate
```


### Good luck in your job seeking 💪!�!�!
