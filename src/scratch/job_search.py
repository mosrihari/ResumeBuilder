import json
import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tavily import TavilyClient

# Load API keys from environment
load_dotenv()

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
GEMINI_KEY = os.getenv("GOOGLE_API_KEY")

if not TAVILY_KEY or not GEMINI_KEY:
    raise ValueError(
        "Missing API keys! Check that TAVILY_API_KEY and GEMINI_API_KEY exist in your .env file."
    )

# ------------------------------------------------------------------
# MASTER LIST OF ALL MAJOR ATS PLATFORMS
# ------------------------------------------------------------------
ALL_ATS_DOMAINS = [
    # Modern High-Growth Tech & Startups
    "boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "jobs.smartrecruiters.com",
    "apply.workable.com",
    "jobs.breezy.hr",
    "jobs.personio.com",
    "jobs.personio.de",
    "careers.bamboohr.com",
    "pinpoint.careers",
    # Major Global Enterprise & Corporate Portals
    "myworkdayjobs.com",
    "icims.com",
    "jobs.jobvite.com",
    "taleo.net",
    "oraclecloud.com",
    "successfactors.com",
    "eightfold.ai",
]

# ------------------------------------------------------------------
# STEP 1: Single Tavily Call Across ALL Domains (1 Credit Used)
# ------------------------------------------------------------------
print(
    f"[1/2] Querying Tavily across {len(ALL_ATS_DOMAINS)} ATS portals for Singapore roles..."
)

tavily = TavilyClient(api_key=TAVILY_KEY)

tavily_response = tavily.search(
    query='"Data Scientist" OR "Machine Learning Engineer" OR "AI Engineer" Singapore',
    include_domains=ALL_ATS_DOMAINS,
    search_depth="basic",  # Fixed to 1 credit per execution
    max_results=30,  # Maximize returned job count
)

raw_results = tavily_response.get("results", [])
print(f"  -> Retrieved {len(raw_results)} raw hits from Tavily.")

if not raw_results:
    print("No jobs found matching the search query.")
    exit()

# ------------------------------------------------------------------
# STEP 2: Gemini Evaluation & JSON Structuring (No Grounding Tool = No 429)
# ------------------------------------------------------------------
print("\n[2/2] Sending raw payload to Gemini for evaluation...")

gemini_client = genai.Client(api_key=GEMINI_KEY)

prompt = f"""
You are an executive AI recruiter in Singapore evaluating raw job postings.

TARGET ROLES: Data Scientist / ML Engineer / AI Specialist
LOCATION: Singapore

RAW TAVILY SEARCH DATA:
{json.dumps(raw_results, indent=2)}

TASKS:
1. Filter out duplicates, expired postings, non-Singapore locations, and non-job pages.
2. Clean up company names and job titles.
3. Extract core hiring signals (domain context, key tech stack requirements).
4. Score role relevance (1-10) for an experienced Data Scientist / ML Engineer.

Return ONLY a valid JSON array of objects following this schema:
[
  {{
    "company": "Company Name",
    "job_title": "Clean Job Title",
    "url": "Direct ATS Application URL",
    "relevance_score": 9,
    "hiring_signals": ["Domain/Tech 1", "Domain/Tech 2"]
  }}
]
"""


def evaluate_with_gemini(prompt_text, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            return response.text
        except APIError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_time = (attempt + 1) * 10
                print(
                    f"⚠️ Rate limit pause ({wait_time}s) before retry {attempt + 1}..."
                )
                time.sleep(wait_time)
            else:
                raise e
    raise Exception("Gemini API call failed after retries.")


# Execute evaluation
cleaned_jobs_json = evaluate_with_gemini(prompt)
consolidated_jobs = json.loads(cleaned_jobs_json)

print(
    f"\n============================================================"
    f"\nVALIDATED JOBS ({len(consolidated_jobs)} Cleaned Openings)"
    f"\n============================================================"
)
print(json.dumps(consolidated_jobs, indent=2))