"""
Generates today's current affairs briefing for the UPSC Drug Inspector exam
— entirely free:
  1. Pulls real, today's headlines from Google News RSS (no key, no cost, no limit)
  2. Sends those headlines to Google's Gemini API FREE TIER to pick the best
     ones, write clean exam-style summaries, and generate MCQs
  3. Saves the result as JSON for the website to display

Run manually with:  python generate_current_affairs.py
It is normally triggered automatically once a day by the GitHub Actions
workflow in .github/workflows/daily.yml
"""

import json
import os
import re
import urllib.parse
from datetime import date

import feedparser
from google import genai

# Google News RSS search — free, no API key required.
QUERIES = {
    "pharma": ["CDSCO drug approval India", "NPPA drug price India",
               "pharmacovigilance India", "drug regulation India"],
    "national": ["India national news today", "India government policy news"],
    "international": ["world news today", "international relations India news"],
    "economy": ["India economy business news today", "RBI monetary policy news"],
    "science": ["India science technology news", "India health news today"],
    "environment": ["India environment climate news"],
    "sports": ["India sports news today"],
    "awards_honours": ["award honour India news today"],
    "defence": ["India defence security news today"],
    "schemes_appointments": ["India government scheme launch news",
                              "India new appointment chairman news"],
    "important_days": ["international observance day today"],
}


def fetch_headlines(query, limit=4):
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query)
           + "&hl=en-IN&gl=IN&ceid=IN:en")
    feed = feedparser.parse(url)
    return [
        {"title": e.title, "snippet": re.sub("<[^<]+?>", "", getattr(e, "summary", ""))[:300]}
        for e in feed.entries[:limit]
    ]


PROMPT_TEMPLATE = """You are preparing a comprehensive daily current affairs
briefing for a competitive exam aspirant in India (UPSC Drug Inspector, SSC
CGL, and similar exams). Below are real headlines scraped today from Google
News, grouped by rough category. For each category, select the most
exam-relevant items, rewrite each into a clean 1-2 sentence factual summary,
and generate 5 self-check MCQs covering a spread of these facts (not just
one category).

RAW HEADLINES:
{raw_headlines}

Reply with ONLY valid JSON, no markdown fences, no commentary, matching this
exact schema:

{{
  "date": "24 Aug 2026",
  "pharma": [{{"title": "...", "summary": "..."}}],
  "national": [{{"title": "...", "summary": "..."}}],
  "international": [{{"title": "...", "summary": "..."}}],
  "economy": [{{"title": "...", "summary": "..."}}],
  "science": [{{"title": "...", "summary": "..."}}],
  "environment": [{{"title": "...", "summary": "..."}}],
  "sports": [{{"title": "...", "summary": "..."}}],
  "awards_honours": [{{"title": "...", "summary": "..."}}],
  "defence": [{{"title": "...", "summary": "..."}}],
  "schemes_appointments": [{{"title": "...", "summary": "..."}}],
  "important_days": [{{"title": "...", "summary": "..."}}],
  "mcqs": [
    {{"q": "...", "options": ["...","...","...","..."], "answer_index": 0, "explanation": "..."}}
  ]
}}

Pick 3-5 items per section (skip a section only if truly nothing relevant
was scraped for it). Base everything only on the headlines given above — do
not invent facts.
"""


def main():
    raw = {}
    for section, queries in QUERIES.items():
        items = []
        for q in queries:
            items.extend(fetch_headlines(q))
        raw[section] = items[:8]

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = PROMPT_TEMPLATE.format(raw_headlines=json.dumps(raw, indent=2))
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    text = response.text

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output:\n" + text)
    data = json.loads(match.group(0))

    today = date.today().isoformat()  # e.g. 2026-08-24
    data.setdefault("date", today)

    os.makedirs("data", exist_ok=True)

    # Save today's entry
    with open(f"data/{today}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Update the index of available dates (for the website's archive list)
    dates_file = "data/dates.json"
    if os.path.exists(dates_file):
        with open(dates_file, encoding="utf-8") as f:
            dates = json.load(f)
    else:
        dates = []
    if today not in dates:
        dates.append(today)
    dates.sort()
    with open(dates_file, "w", encoding="utf-8") as f:
        json.dump(dates, f, indent=2)

    print(f"Saved current affairs for {today}")


if __name__ == "__main__":
    main()
