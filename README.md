# Google Calendar - Trello (One-Way Import)

On-demand script that:
- Fetches all Google Calendar events for a given day
- Creates one Trello card per event

## Plans/ Todo
- Schedule to fetch automatically instead of only when run manually.
- Set other fields according to information in the Google event (time, due date, notes, etc.).
- Automatically retreive Trello Board and List identifiers from common names.
- Organize cards onto different boards or lists by event type automatically.
- Populate other cards based on event information (if event type A, add cards B and C).
- Maybe two-way sync that allows the Trello board to populate events in the calendar?
- General personal orchestrator that calls more general fetch and populate scripts.



## Setup

### 1. Create a Google OAuth client
Download credentials JSON and save as:

    credentials.json

### 2. Set environment variables

    export TRELLO_KEY=...
    export TRELLO_TOKEN=...
    export TRELLO_LIST_ID=...

Optional:

    export GOOGLE_CREDENTIALS_FILE=credentials.json
    export GOOGLE_TOKEN_FILE=token.json

### 3. Run

    python fetch_day.py --date 2026-02-25
    python fetch_day.py --date today