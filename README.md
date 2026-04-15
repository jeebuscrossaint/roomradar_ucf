# RoomRadar UCF

Find empty classrooms at the University of Central Florida in real time.

**Live site:** https://jeebuscrossaint.github.io/roomradar_ucf/

---

## What it does

UCF has hundreds of classrooms sitting empty between classes. RoomRadar scrapes the university's class schedule and lets you filter by building, day, and time to find a room that's free right now — and for how long.

- See all free rooms at a glance, sorted by how long they stay free
- Pick a specific room to check its full weekly schedule
- Browse an embedded UCF campus map with deep-links to each building
- Data updates automatically every Monday via GitHub Actions

---

## Architecture

```
UCF PeopleSoft → Python scraper → schedule.json → GitHub Pages → browser
```

No server. No database. No framework. The scraper commits `schedule.json` to the repo, GitHub Pages serves it as a static file, and the browser does all filtering in JavaScript.

---

## Tech stack

### Scraper (`ucf-cli/`)

| Tool | Purpose |
|---|---|
| **Selenium 4** | Drives a headless Chrome/Edge to navigate UCF's PeopleSoft class search UI |
| **BeautifulSoup4** | Parses the resulting HTML to extract room, time, and course data |
| **Click** | CLI interface (`python main.py refresh --workers 4`) |
| **Rich** | Colored terminal output |

**How the scraper works:**

UCF's class search is a PeopleSoft AJAX app — there's no public API, so Selenium automates it like a real user. For each academic subject (168 total), it fills the search form, waits for the AJAX spinner to clear, expands the result accordions, and scrapes the HTML.

A few optimizations keep it fast:
- **Parallel browsers** — `--workers N` splits subjects across N Chrome instances running concurrently via `ThreadPoolExecutor`
- **Page reuse** — after scraping the first career type for a subject, subsequent careers click "Modify Search" to reuse the same page instead of doing a full reload
- **Spinner-based waits** — instead of `time.sleep()`, the scraper polls for PeopleSoft's loading overlay to disappear (up to 15s timeout)
- **Incremental re-scrape** — `--subjects CHM,PHY` re-scrapes just those subjects and merges the results into the existing data file

The output is a single `schedule.json`:

```json
{
  "term": "2261",
  "scraped_at": "2026-04-14T12:34:55",
  "rooms": {
    "ENG2-0302": {
      "building": "ENG2",
      "room": "0302",
      "slots": [
        {
          "days": ["M", "W", "F"],
          "start": "09:30",
          "end": "10:20",
          "course": "COP 3502",
          "title": "Computer Science I"
        }
      ]
    }
  }
}
```

### Frontend (`docs/`)

A single `index.html` file — no build step, no bundler, no framework.

| Tool | Purpose |
|---|---|
| **Vanilla JS** | All filtering, rendering, and UI logic (~500 lines) |
| **Tailwind CSS** (CDN) | Utility classes for layout and spacing |
| **Inter + JetBrains Mono** | Typography via Google Fonts |
| **UCF Map API** | `map.ucf.edu/locations.json` — fetched at runtime to build building → map URL lookups |

**How the frontend works:**

On load, `schedule.json` is fetched once and held in memory as `allRooms`. Every filter change re-runs `findFree()` over the in-memory object — no network requests. This makes filtering instant regardless of the number of rooms.

```
fetch(schedule.json)
  → allRooms = { "ENG2-0302": { building, room, slots[] }, ... }
      → findFree(day, time, building, minDuration)
          → filter slots by day
          → check if any slot overlaps current time
          → compute duration until next class
          → sort by longest free first
              → render cards
```

The mini-timeline on each card and the full week calendar in the detail sheet both work by mapping time (minutes since midnight) to percentage positions within a fixed 7 AM–10 PM window.

### Automation (`.github/workflows/scrape.yml`)

A GitHub Actions workflow runs every Monday at 8 AM UTC:

1. Installs Chrome and Python dependencies
2. Runs `python main.py refresh --workers 4`
3. Copies `ucf-cli/data/schedule.json` → `docs/schedule.json`
4. Commits and pushes the updated data file

The workflow can also be triggered manually from the Actions tab.

---

## Running the scraper locally

```bash
cd ucf-cli
pip install -r requirements.txt

# full scrape (takes ~20-40 min)
python main.py refresh

# faster with parallel browsers
python main.py refresh --workers 4

# re-scrape specific subjects only
python main.py refresh --subjects CHM,PHY,COP

# watch the browser (useful for debugging)
python main.py refresh --no-headless --subjects COP
```

**Term codes** (update `config.py` each semester):

| Term | Code |
|---|---|
| Spring 2026 | `2261` |
| Summer 2026 | `2265` |
| Fall 2026 | `2268` |

After scraping, copy the output to the site:

```bash
cp ucf-cli/data/schedule.json docs/schedule.json
```

---

## Credits

Adapted from [ucf-spots](https://github.com/xxfmin/ucf-spots) (MIT).
