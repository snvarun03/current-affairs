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
}

# Fixed calendar of widely-recognised observance days, keyed by "MM-DD".
# This is looked up directly rather than scraped from news, because a news
# article can mention an observance day (e.g. in a retrospective piece)
# without that day actually falling on the article's publish date — which
# was causing wrong days (like Women's Day) to appear under wrong dates.
IMPORTANT_DAYS_BY_MMDD = {
    "01-04": ["World Braille Day"],
    "01-15": ["Army Day (India)"],
    "01-24": ["National Girl Child Day (India)"],
    "01-25": ["National Voters' Day (India)"],
    "01-26": ["Republic Day (India)", "International Customs Day"],
    "02-04": ["World Cancer Day"],
    "02-06": ["International Day of Zero Tolerance to FGM"],
    "02-20": ["World Day of Social Justice"],
    "02-21": ["International Mother Language Day"],
    "02-28": ["National Science Day (India)"],
    "03-03": ["World Wildlife Day"],
    "03-08": ["International Women's Day"],
    "03-15": ["World Consumer Rights Day"],
    "03-20": ["International Day of Happiness", "World Sparrow Day"],
    "03-21": ["World Forestry Day", "International Day of Nowruz"],
    "03-22": ["World Water Day"],
    "03-23": ["World Meteorological Day"],
    "03-24": ["World Tuberculosis Day"],
    "04-02": ["World Autism Awareness Day"],
    "04-07": ["World Health Day"],
    "04-22": ["International Mother Earth Day"],
    "04-23": ["World Book and Copyright Day"],
    "05-01": ["International Labour Day"],
    "05-03": ["World Press Freedom Day"],
    "05-08": ["World Red Cross Day"],
    "05-11": ["National Technology Day (India)"],
    "05-12": ["International Nurses Day"],
    "05-15": ["International Day of Families"],
    "05-17": ["World Telecommunication and Information Society Day"],
    "05-21": ["Anti-Terrorism Day (India)"],
    "05-31": ["World No Tobacco Day"],
    "06-05": ["World Environment Day"],
    "06-08": ["World Oceans Day"],
    "06-14": ["World Blood Donor Day"],
    "06-20": ["World Refugee Day"],
    "06-21": ["International Day of Yoga"],
    "06-26": ["International Day Against Drug Abuse and Illicit Trafficking"],
    "07-01": ["National Doctors' Day (India)"],
    "07-11": ["World Population Day"],
    "07-28": ["World Hepatitis Day"],
    "08-06": ["Hiroshima Day"],
    "08-09": ["Quit India Movement Day", "International Day of the World's Indigenous Peoples"],
    "08-12": ["International Youth Day"],
    "08-15": ["Independence Day (India)"],
    "08-19": ["World Humanitarian Day"],
    "08-29": ["National Sports Day (India)"],
    "09-05": ["Teachers' Day (India)"],
    "09-08": ["International Literacy Day"],
    "09-14": ["Hindi Diwas (India)"],
    "09-16": ["World Ozone Day"],
    "09-21": ["International Day of Peace"],
    "09-27": ["World Tourism Day"],
    "10-01": ["International Day of Older Persons"],
    "10-02": ["Gandhi Jayanti (India)", "International Day of Non-Violence"],
    "10-05": ["World Teachers' Day"],
    "10-08": ["Indian Air Force Day"],
    "10-09": ["World Post Day"],
    "10-10": ["World Mental Health Day"],
    "10-16": ["World Food Day"],
    "10-24": ["United Nations Day"],
    "11-14": ["Children's Day (India)", "World Diabetes Day"],
    "11-19": ["World Toilet Day"],
    "11-21": ["World Television Day"],
    "11-26": ["National Law Day (India)"],
    "12-01": ["World AIDS Day"],
    "12-04": ["Indian Navy Day"],
    "12-07": ["Indian Armed Forces Flag Day"],
    "12-10": ["Human Rights Day"],
    "12-18": ["International Migrants Day"],
    "12-23": ["Kisan Diwas / Farmers' Day (India)"],
}


def lookup_important_days(target_date):
    key = target_date.strftime("%m-%d")
    names = IMPORTANT_DAYS_BY_MMDD.get(key, [])
    return [
        {"title": name, "summary": f"Observed annually on {target_date.strftime('%d %B')}."}
        for name in names
    ]


def verify_against_headlines(items, headlines):
    """Keep only items that clearly trace back to one specific scraped headline,
    and attach that headline as a clickable source.

    This is a safety net against the AI drifting from the source text: each
    item is matched to the single real headline it overlaps with most. If no
    headline overlaps enough, the item is dropped rather than risk showing an
    unverified or misattributed fact in an exam prep tool.
    """
    if not headlines:
        return []  # nothing was scraped for this section on this date — keep nothing

    verified = []
    for it in items:
        title_words = set(re.findall(r"[a-z]{4,}", it.get("title", "").lower()))
        if not title_words:
            continue

        best_headline, best_overlap = None, 0
        for h in headlines:
            h_words = set(re.findall(
                "[a-z]{4,}", (h.get("title", "") + " " + h.get("snippet", "")).lower()
            ))
            overlap = len(title_words & h_words)
            if overlap > best_overlap:
                best_overlap, best_headline = overlap, h

        threshold = 1 if len(title_words) <= 2 else 2
        if best_headline is not None and best_overlap >= threshold:
            it["source_title"] = best_headline["title"]
            it["source_url"] = best_headline.get("link", "")
            it["published_ist"] = best_headline.get("published_ist", "")
            verified.append(it)
    return verified


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
            "link": getattr(e, "link", ""),
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
  "mcqs": [
    {{"q": "...", "options": ["...","...","...","..."], "answer_index": 0, "explanation": "..."}}
  ]
}}

Do not include an "important_days" field — that is added separately from a
fixed calendar, not from these headlines.

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
        config={"temperature": 0},
    )
    text = response.text

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model output:\n" + text)
    data = json.loads(match.group(0))
    data["date"] = target_date_readable

    # Verify every AI-written item against the real scraped headlines for
    # its section, dropping anything that doesn't clearly trace back to a
    # real source — better to show fewer items than a wrong one.
    for section in QUERIES.keys():
        if section in data:
            data[section] = verify_against_headlines(data[section], raw.get(section, []))

    # Important days are looked up from a fixed calendar, never from search/AI,
    # so this field can never be wrong for the date it's shown under.
    data["important_days"] = lookup_important_days(target_date)
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
