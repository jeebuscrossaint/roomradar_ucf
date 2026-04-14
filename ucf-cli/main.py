#!/usr/bin/env python3
"""
RoomRadar UCF

Usage:
    python main.py                          Show all free rooms right now
    python main.py ENG2                     Free rooms in ENG2
    python main.py ENG2 0302                Check if ENG2 0302 is free now
    python main.py -s ENG2 0302             Show ENG2 0302's full schedule
    python main.py 0302                     Find any room matching "0302" (partial ok)
    python main.py refresh                  Re-scrape UCF data
    python main.py help                     This help text

Options (work with any query):
    -t / --time  "2:30 PM"    Check at a specific time instead of now
    -d / --day   Monday       Check a specific day instead of today
    -m / --min-free  60       Only show rooms free for at least N minutes
    -n / --limit     40       Max results to display
    -s / --schedule           Show full schedule instead of availability
"""

import json
import sys
from datetime import datetime

import click
from rich import box
from rich.console import Console
from rich.table import Table

from config import DATA_FILE, DEFAULT_TERM, DAY_NAMES
from finder import DAY_MAP, find_free_rooms, min_to_ampm, now, parse_day, parse_time, time_to_min

console = Console()


# ── data helpers ──────────────────────────────────────────────────────────────

def _load():
    if not DATA_FILE.exists():
        console.print("[red]No cached data.[/red] Run [bold]python main.py refresh[/bold] first.")
        sys.exit(1)
    return json.loads(DATA_FILE.read_text())


def _resolve_time(at_time, day):
    """Return (day_code, time_24, label_day, label_time, is_today)."""
    now_day, now_time = now()

    if day:
        day_code = parse_day(day)
    else:
        day_code = now_day

    if at_time:
        try:
            time_24 = parse_time(at_time)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(1)
    else:
        time_24 = now_time

    label_day  = DAY_NAMES.get(day_code, day_code)
    label_time = datetime.strptime(time_24, "%H:%M").strftime("%I:%M %p").lstrip("0")
    is_today   = (day_code == now_day)

    return day_code, time_24, label_day, label_time, is_today


def _fmt_time(hhmm: str) -> str:
    return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")


# ── display helpers ───────────────────────────────────────────────────────────

def _show_free_rooms(rooms, building_filter, at_time, day, min_free, limit):
    day_code, time_24, label_day, label_time, _ = _resolve_time(at_time, day)

    results = find_free_rooms(
        rooms,
        day=day_code,
        query_time=time_24,
        building_filter=building_filter,
        min_duration=min_free,
    )

    header = f"Free rooms — {label_day} at {label_time}"
    if building_filter:
        header += f" — {building_filter.upper()}"

    if not results:
        console.print(f"\n[yellow]No free rooms found.[/yellow]")
        return

    table = Table(title=header, box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Building", style="bold", min_width=9)
    table.add_column("Room",     min_width=6)
    table.add_column("Free Until", min_width=11)
    table.add_column("Available For", min_width=13)

    for r in results[:limit]:
        mins = r["free_for_minutes"]
        if mins is None:
            avail = "[dim]all day[/dim]"
        else:
            h, m = divmod(mins, 60)
            avail = (f"{h}h {m}m" if h and m else f"{h}h" if h else f"{m}m")
        table.add_row(r["building"], r["room"], r["free_until"], avail)

    console.print()
    console.print(table)
    _print_footer(_load())


def _show_room_status(rooms, building, room_query, at_time, day):
    """Check a specific room and show whether it's free right now."""
    room_data = _find_room(rooms, building, room_query)
    if room_data is None:
        console.print(f"[red]No room found matching '{building} {room_query}'.[/red]")
        sys.exit(1)

    day_code, time_24, label_day, label_time, is_today = _resolve_time(at_time, day)
    now_min = time_to_min(time_24)

    day_slots = sorted(
        [s for s in room_data.get("slots", []) if day_code in s.get("days", [])],
        key=lambda s: time_to_min(s["start"]),
    )

    console.print(f"\n[bold]{room_data['building']} {room_data['room']}[/bold] — {label_day} at {label_time}\n")

    if not day_slots:
        console.print("[green]Free all day — nothing scheduled.[/green]\n")
        return

    occupied = next(
        (s for s in day_slots if time_to_min(s["start"]) <= now_min < time_to_min(s["end"])),
        None,
    )

    if occupied:
        ends = _fmt_time(occupied["end"])
        gap  = time_to_min(occupied["end"]) - now_min
        h, m = divmod(gap, 60)
        dur  = (f"{h}h {m}m" if h and m else f"{h}h" if h else f"{m}m")
        console.print(f"[red]Occupied[/red] — free at {ends} (in {dur})\n")
    else:
        future = [s for s in day_slots if time_to_min(s["start"]) > now_min]
        if future:
            nxt    = future[0]
            starts = _fmt_time(nxt["start"])
            gap    = time_to_min(nxt["start"]) - now_min
            h, m   = divmod(gap, 60)
            dur    = (f"{h}h {m}m" if h and m else f"{h}h" if h else f"{m}m")
            console.print(f"[green]Free[/green] — occupied again at {starts} (in {dur})\n")
        else:
            console.print(f"[green]Free[/green] — no more bookings today\n")

    _print_footer(_load())


def _show_room_schedule(rooms, building, room_query, day):
    """Show the full occupied time blocks for a room on a given day."""
    room_data = _find_room(rooms, building, room_query)
    if room_data is None:
        console.print(f"[red]No room found matching '{building} {room_query}'.[/red]")
        sys.exit(1)

    day_code, time_24, label_day, label_time, is_today = _resolve_time(None, day)
    now_min = time_to_min(time_24) if is_today else -1

    day_slots = sorted(
        [s for s in room_data.get("slots", []) if day_code in s.get("days", [])],
        key=lambda s: time_to_min(s["start"]),
    )

    console.print(f"\n[bold]{room_data['building']} {room_data['room']}[/bold] — {label_day}\n")

    if not day_slots:
        console.print("[green]Nothing scheduled.[/green]\n")
        return

    table = Table(box=box.SIMPLE, header_style="bold cyan")
    table.add_column("Start", min_width=9)
    table.add_column("End",   min_width=9)
    table.add_column("",      min_width=10)

    for slot in day_slots:
        s = time_to_min(slot["start"])
        e = time_to_min(slot["end"])
        tag = ""
        if is_today:
            if s <= now_min < e:
                tag = "[red]occupied now[/red]"
            elif s > now_min:
                gap = s - now_min
                h, m = divmod(gap, 60)
                tag = f"[dim]in {h}h {m}m[/dim]" if h else f"[dim]in {m}m[/dim]"
        table.add_row(_fmt_time(slot["start"]), _fmt_time(slot["end"]), tag)

    console.print(table)
    _print_footer(_load())


def _show_partial_search(rooms, query, at_time, day, min_free, limit, schedule):
    """
    Single-token search: match building prefix OR partial room number.
    e.g. "ENG" matches ENG1, ENG2 buildings. "302" matches any room containing "302".
    """
    q = query.upper()
    is_numeric = q.isdigit()

    matched = {}
    for key, rd in rooms.items():
        if is_numeric:
            # partial room number match
            if q in rd["room"]:
                matched[key] = rd
        else:
            # building prefix match
            if rd["building"].upper().startswith(q):
                matched[key] = rd

    if not matched:
        console.print(f"[red]No rooms found matching '{query}'.[/red]")
        sys.exit(1)

    if schedule:
        day_code, _, label_day, _, _ = _resolve_time(None, day)
        for rd in sorted(matched.values(), key=lambda r: (r["building"], r["room"])):
            day_slots = sorted(
                [s for s in rd.get("slots", []) if day_code in s.get("days", [])],
                key=lambda s: time_to_min(s["start"]),
            )
            if not day_slots:
                continue
            console.print(f"\n[bold]{rd['building']} {rd['room']}[/bold]")
            for slot in day_slots:
                console.print(f"  {_fmt_time(slot['start'])} – {_fmt_time(slot['end'])}")
    else:
        _show_free_rooms(matched, building_filter=None, at_time=at_time, day=day,
                         min_free=min_free, limit=limit)


def _find_room(rooms, building, room_query):
    """Find a room by exact or partial match (building exact, room partial)."""
    b = building.upper()
    r = room_query.upper()
    # exact
    exact = rooms.get(f"{b}-{room_query}")
    if exact:
        return exact
    # case-insensitive / partial room number
    for rd in rooms.values():
        if rd["building"].upper() == b and r in rd["room"].upper():
            return rd
    return None


def _print_footer(data):
    console.print(f"[dim]Term {data.get('term')} · data from {data.get('scraped_at','?')[:10]}[/dim]\n")


# ── refresh helper ────────────────────────────────────────────────────────────

def _do_refresh(term, headless, subjects_raw, workers=1):
    import logging
    from scraper import scrape

    subject_list = [s.strip().upper() for s in subjects_raw.split(",")] if subjects_raw else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")

    console.print(f"[bold]Scraping UCF — term [cyan]{term}[/cyan][/bold]")
    if subject_list:
        console.print(f"Subjects: {', '.join(subject_list)}")
    else:
        console.print("[dim]All subjects — this takes a while, go touch grass[/dim]")
    if workers > 1:
        console.print(f"[dim]Using {workers} parallel browsers[/dim]")

    try:
        result = scrape(term=term, headless=headless, subjects=subject_list, workers=workers)
        console.print(f"\n[green]Done![/green] {len(result['rooms'])} rooms cached → [dim]{DATA_FILE}[/dim]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Error:[/red] {e}")
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command(
    context_settings={"help_option_names": []},   # we handle --help / help ourselves
    add_help_option=False,
)
@click.argument("query", nargs=-1)
@click.option("-s", "--schedule", is_flag=True,    help="Show full schedule instead of availability")
@click.option("-t", "--time",     "at_time",        default=None,  metavar="TIME",  help='e.g. "2:30 PM"')
@click.option("-d", "--day",                        default=None,  metavar="DAY",   help="e.g. Monday or M")
@click.option("-m", "--min-free",                   default=0,     type=int,        metavar="MINS")
@click.option("-n", "--limit",                      default=40,    type=int,        metavar="N")
# refresh-only options (hidden from main help)
@click.option("--term",           default=DEFAULT_TERM, hidden=True)
@click.option("--headless/--no-headless", default=True, hidden=True)
@click.option("--subjects",       default=None, hidden=True)
@click.option("--workers", "-w",  default=1, type=int, hidden=True)
def cli(query, schedule, at_time, day, min_free, limit, term, headless, subjects, workers):
    parts = list(query)

    # ── help ──────────────────────────────────────────────────────────────────
    if parts and parts[0] in ("help", "--help", "-h"):
        console.print(__doc__)
        return

    # ── refresh ───────────────────────────────────────────────────────────────
    if parts and parts[0] == "refresh":
        _do_refresh(term, headless, subjects, workers)
        return

    # ── load data for all search commands ─────────────────────────────────────
    data  = _load()
    rooms = data["rooms"]

    # ── no query: show all free rooms now ────────────────────────────────────
    if not parts:
        _show_free_rooms(rooms, building_filter=None,
                         at_time=at_time, day=day, min_free=min_free, limit=limit)
        return

    # ── two tokens: building + room  e.g.  ENG2 0302 ─────────────────────────
    if len(parts) == 2:
        building, room_q = parts[0], parts[1]
        if schedule:
            _show_room_schedule(rooms, building, room_q, day)
        else:
            _show_room_status(rooms, building, room_q, at_time, day)
        return

    # ── one token: building code, partial room, or prefix ─────────────────────
    if len(parts) == 1:
        token = parts[0].upper()
        # If it looks like an exact building code (all letters) and exists → filter free rooms
        is_exact_building = (not token.isdigit()) and any(
            rd["building"].upper() == token for rd in rooms.values()
        )
        if is_exact_building and not schedule:
            _show_free_rooms(rooms, building_filter=token,
                             at_time=at_time, day=day, min_free=min_free, limit=limit)
        else:
            _show_partial_search(rooms, token, at_time, day, min_free, limit, schedule)
        return



if __name__ == "__main__":
    cli()
