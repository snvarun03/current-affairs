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
import calendar
import urllib.parse
from datetime import datetime, timezone, timedelta

import feedparser
from google import genai

IST = timezone(timedelta(hours=5, minutes=30))

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


def fetch_headlines(query, target_date, limit=4, scan_limit=25, use_date_operators=False):
    """Fetch headlines and keep only ones actually published on target_date (IST).

    use_date_operators=True scopes the Google search itself to that exact
    day (needed for backfilling older dates); otherwise a rolling "when:2d"
    window is used, which works well for "today" and is a lighter query.
    """
    if use_date_operators:
        next_day = target_date + timedelta(days=1)
        date_scope = f" after:{target_date.isoformat()} before:{next_day.isoformat()}"
    else:
        date_scope = " when:2d"

    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query + date_scope)
           + "&hl=en-IN&gl=IN&ceid=IN:en")
    feed = feedparser.parse(url)

    results = []
    for e in feed.entries[:scan_limit]:
        published = getattr(e, "published_parsed", None)
        if published is None:
            continue  # can't verify the date, so skip it rather than risk a mismatch
        published_utc = datetime.fromtimestamp(calendar.timegm(published), tz=timezone.utc)
        published_ist_date = published_utc.astimezone(IST).date()
        if published_ist_date != target_date:
            continue  # not from the specific day we're building this entry for
        results.append({
            "title": e.title,
            "snippet": re.sub("<[^<]+?>", "", getattr(e, "summary", ""))[:300],
            "published_ist": published_ist_date.isoformat(),
        })
        if len(results) >= limit:
            break
    return results


PROMPT_TEMPLATE = """You are preparing a comprehensive daily current affairs
briefing for a competitive exam aspirant in India (UPSC Drug Inspector, SSC
CGL, and similar exams), specifically for {target_date_readable}.

Below are real headlines, each already verified to have been published on
{target_date_readable} (see the "published_ist" field on each item — trust
this field). Group by rough category. For each category, select the most
exam-relevant items, rewrite each into a clean 1-2 sentence factual summary,
and generate 5 self-check MCQs covering a spread of these facts (not just
one category).

RAW HEADLINES (all confirmed published on {target_date_readable}):
{raw_headlines}

Reply with ONLY valid JSON, no markdown fences, no commentary, matching this
exact schema:

{{
  "date": "{target_date_readable}",
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

Pick 3-5 items per section (skip a section only if truly nothing was scraped
for it — do not pad with unrelated or older items to fill the quota). Base
everything only on the headlines given above — do not invent facts, and do
not include anything not published on {target_date_readable}.
"""


def build_briefing(target_date, use_date_operators=False):
    """Fetch headlines and turn them into a structured briefing for target_date."""
    target_date_readable = target_date.strftime("%d %b %Y")  # e.g. 15 May 2026

    raw = {}
    for section, queries in QUERIES.items():
        items = []
        for q in queries:
            items.extend(fetch_headlines(q, target_date, use_date_operators=use_date_operators))
        raw[section] = items[:8]

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = PROMPT_TEMPLATE.format(
        target_date_readable=target_date_readable,
        raw_headlines=json.dumps(raw, indent=2),
    )
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    text = response.text

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output:\n" + text)
    data = json.loads(match.group(0))
    data["date"] = target_date_readable
    return data


def save_entry(data, target_date):
    """Write the briefing JSON and update the shared dates.json index."""
    iso = target_date.isoformat()  # e.g. 2026-05-15
    os.makedirs("data", exist_ok=True)

    with open(f"data/{iso}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    dates_file = "data/dates.json"
    if os.path.exists(dates_file):
        with open(dates_file, encoding="utf-8") as f:
            dates = json.load(f)
    else:
        dates = []
    if iso not in dates:
        dates.append(iso)
    dates.sort()
    with open(dates_file, "w", encoding="utf-8") as f:
        json.dump(dates, f, indent=2)


def main():
    target_date = datetime.now(IST).date()
    data = build_briefing(target_date, use_date_operators=False)
    save_entry(data, target_date)
    print(f"Saved current affairs for {target_date.isoformat()}")


if __name__ == "__main__":
    main()
