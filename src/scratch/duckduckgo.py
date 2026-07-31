import time
from ddgs import DDGS

JOB_ROLE = "Data Scientist"
LOCATION = "Singapore"

# Master list of ATS domains
ATS_DOMAINS = [
    # Startups & Modern Tech
    "boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "jobs.smartrecruiters.com",
    "apply.workable.com",
    "jobs.breezy.hr",
    "jobs.personio.com",
    # Enterprise & MNCs
    "myworkdayjobs.com",
    "icims.com",
]

all_jobs = []
seen_urls = set()  # To track and prevent duplicate links

print(f"Starting job search for '{JOB_ROLE}' in {LOCATION}...\n")

with DDGS() as ddgs:
    for domain in ATS_DOMAINS:
        query = f'"{JOB_ROLE}" {LOCATION} site:{domain}'
        print(f"Searching {domain}...")

        try:
            # IMPORTANT: timelimit='w' forces results from the PAST 7 DAYS ONLY.
            # Use timelimit='d' for the LAST 24 HOURS.
            results = list(
                ddgs.text(
                    query,
                    region="sg-en",  # Singapore region
                    timelimit="w",  # Restrict to last week
                    max_results=10,
                )
            )

            count = 0
            for r in results:
                url = r.get("href")

                # Deduplication logic
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_jobs.append({
                        "domain": domain,
                        "title": r.get("title"),
                        "url": url,
                        "snippet": r.get("body", "")[:150],
                    })
                    count += 1

            print(f"  -> Found {count} new jobs.")

        except Exception as e:
            print(f"  -> Error querying {domain}: {e}")

        # Sleep briefly between calls to avoid hitting rate limits
        time.sleep(1)

print(
    f"\n"
    + "=" * 60
    + f"\nTOTAL UNIQUE RECENT JOBS FOUND: {len(all_jobs)}\n"
    + "=" * 60
)

for idx, job in enumerate(all_jobs, start=1):
    print(f"[{idx}] {job['title']}")
    print(f"    Source: {job['domain']}")
    print(f"    URL: {job['url']}\n")