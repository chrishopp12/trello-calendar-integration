#!/usr/bin/env python3
"""
fetch_day.py

On-demand one-way import:
- Fetch all Google Calendar events for a given day
- Create one Trello card per event in a fixed list
- No due dates, no dedup, no labels

Usage:
  python fetch_day.py --date 2026-02-25
  python fetch_day.py --date today
  python fetch_day.py --date 2026-02-25 --calendar-id primary

Environment variables:
  TRELLO_KEY       - Trello API key
  TRELLO_TOKEN     - Trello API token
  TRELLO_LIST_ID   - Trello list id (destination)
  TRELLO_LABEL_ID  - Trello label id (optional)
Optional:
  GOOGLE_CREDENTIALS_FILE (default: credentials.json)
  GOOGLE_TOKEN_FILE       (default: token.json)
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from dataclasses import dataclass

import requests
from dateutil import tz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


@dataclass(frozen=True)
class Config:
    trello_key: str
    trello_token: str
    trello_list_id: str
    calendar_id: str
    credentials_file: str
    token_file: str
    trello_label_id: str | None = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD or 'today'")
    p.add_argument("--calendar-id", default="primary", help="Google calendar id (default: primary)")
    return p.parse_args()


def get_local_tzinfo() -> dt.tzinfo:
    # local timezone on the machine running the script
    return tz.tzlocal()


def get_day_bounds(date_str: str, local_tz: dt.tzinfo) -> tuple[dt.datetime, dt.datetime, str]:
    if date_str.lower() == "today":
        day = dt.datetime.now(local_tz).date()
    else:
        # Expect YYYY-MM-DD
        day = dt.date.fromisoformat(date_str)

    start_local = dt.datetime.combine(day, dt.time(0, 0, 0), tzinfo=local_tz)
    end_local = start_local + dt.timedelta(days=1)
    pretty = day.isoformat()
    return start_local, end_local, pretty

def get_event_due(ev: dict) -> str | None:
    """Return an RFC3339 timestamp to use as the Trello due date.

    Google events can be timed (start.dateTime) or all-day (start.date).
    For timed events we use start.dateTime; for all-day events we return None.
    """
    start = ev.get("start", {})
    return start.get("dateTime")


def google_calendar_service(credentials_file: str, token_file: str):
    creds: Credentials | None = None

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_file):
                raise FileNotFoundError(
                    f"Missing {credentials_file}. Download OAuth client JSON and save it as {credentials_file}."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save token for next time
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def list_events_for_window(service, calendar_id: str, time_min: dt.datetime, time_max: dt.datetime) -> list[dict]:
    # RFC3339 timestamps
    time_min_rfc3339 = time_min.isoformat()
    time_max_rfc3339 = time_max.isoformat()

    events: list[dict] = []
    page_token: str | None = None

    while True:
        resp = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min_rfc3339,
                timeMax=time_max_rfc3339,
                singleEvents=True,   # expand recurring events into instances
                orderBy="startTime",
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )

        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return events


def trello_create_card(
    *,
    trello_key: str,
    trello_token: str,
    list_id: str,
    name: str,
    desc: str,
    due: str | None = None,
    label_id: str | None = None,
) -> None:
    url = "https://api.trello.com/1/cards"
    params = {
        "key": trello_key,
        "token": trello_token,
        "idList": list_id,
        "name": name,
        "desc": desc,
    }

    if due:
        params["due"] = due
    if label_id:
        params["idLabels"] = label_id

    r = requests.post(url, params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Trello create card failed ({r.status_code}): {r.text}")


def format_event_for_trello(ev: dict) -> tuple[str, str]:
    summary = ev.get("summary") or "(No title)"
    location = ev.get("location", "")
    html_link = ev.get("htmlLink", "")

    start = ev.get("start", {})
    end = ev.get("end", {})

    # start/end can be dateTime or date (all-day)
    start_s = start.get("dateTime") or start.get("date") or ""
    end_s = end.get("dateTime") or end.get("date") or ""

    lines = []
    if start_s or end_s:
        lines.append(f"When: {start_s} -> {end_s}")
    if location:
        lines.append(f"Where: {location}")
    if html_link:
        lines.append(f"Google event: {html_link}")

    desc = "\n".join(lines).strip()
    return summary, desc


def load_config(args: argparse.Namespace) -> Config:
    trello_key = os.environ.get("TRELLO_KEY", "").strip()
    trello_token = os.environ.get("TRELLO_TOKEN", "").strip()
    trello_list_id = os.environ.get("TRELLO_LIST_ID", "").strip()
    trello_label_id = os.environ.get("TRELLO_CALENDAR_LABEL_ID", "").strip()
    if not trello_key or not trello_token or not trello_list_id:
        raise RuntimeError(
            "Missing Trello env vars. Set TRELLO_KEY, TRELLO_TOKEN, and TRELLO_LIST_ID."
        )

    credentials_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    token_file = os.environ.get("GOOGLE_TOKEN_FILE", "token.json")

    return Config(
        trello_key=trello_key,
        trello_token=trello_token,
        trello_list_id=trello_list_id,
        trello_label_id=trello_label_id or None,
        calendar_id=args.calendar_id,
        credentials_file=credentials_file,
        token_file=token_file,
    )


def main() -> int:
    args = parse_args()
    cfg = load_config(args)

    local_tz = get_local_tzinfo()
    t0, t1, day_str = get_day_bounds(args.date, local_tz)

    service = google_calendar_service(cfg.credentials_file, cfg.token_file)
    events = list_events_for_window(service, cfg.calendar_id, t0, t1)

    if not events:
        print(f"No events found for {day_str}.")
        return 0

    created = 0
    for ev in events:
        name, desc = format_event_for_trello(ev)
        due = get_event_due(ev)
        trello_create_card(
            trello_key=cfg.trello_key,
            trello_token=cfg.trello_token,
            list_id=cfg.trello_list_id,
            name=name,
            desc=desc,
            due=due,
            label_id=cfg.trello_label_id,
        )
        created += 1
        print(f"Created card: {name}")

    print(f"\nDone. Created {created} Trello card(s) for {day_str}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)