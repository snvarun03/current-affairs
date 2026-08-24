"""
One-time backfill: generates current affairs entries for every day in a
given date range (default: all of May 2026), using the same exact-date
filtering as the daily script.

Run manually with:
    python backfill_month.py                      # defaults to May 2026
    python backfill_month.py 2026-05-01 2026-05-31 # custom range

Or trigger it via the "Backfill a date range" workflow in GitHub Actions
(Actions tab -> Backfill a date range -> Run workflow), which lets you type
the start and end dates in a form instead of using the command line.

Note: Google News' search index favours recent articles, so some days or
sections from far in the past may come back thin or empty. That is a
limitation of the free news source itself, not a bug in this script.
"""

import sys
import time
from datetime import date, timedelta

from generate_current_affairs import build_briefing, save_entry

DEFAULT_START = date(2026, 5, 1)
DEFAULT_END = date(2026, 5, 31)

# Pause between days to stay comfortably within Gemini's free-tier rate limit.
SECONDS_BETWEEN_CALLS = 20


def parse_args():
    if len(sys.argv) >= 3:
        start = date.fromisoformat(sys.argv[1])
        end = date.fromisoformat(sys.argv[2])
    else:
        start, end = DEFAULT_START, DEFAULT_END
    return start, end


def main():
    start, end = parse_args()
    if start > end:
        raise ValueError("start date must be before end date")

    current = start
    total_days = (end - start).days + 1
    done = 0

    while current <= end:
        done += 1
        print(f"[{done}/{total_days}] Building entry for {current.isoformat()} ...")
        try:
            data = build_briefing(current, use_date_operators=True)
            save_entry(data, current)
            print(f"    saved data/{current.isoformat()}.json")
        except Exception as exc:
            # Don't let one bad day stop the whole backfill.
            print(f"    FAILED for {current.isoformat()}: {exc}")

        current += timedelta(days=1)
        if current <= end:
            time.sleep(SECONDS_BETWEEN_CALLS)

    print("Backfill complete.")


if __name__ == "__main__":
    main()
