"""
Logic for finding free rooms at a given day/time.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

DAY_MAP = {0: "M", 1: "T", 2: "W", 3: "R", 4: "F", 5: "S", 6: "U"}

DAY_NAMES = {
    "M": "Monday", "T": "Tuesday", "W": "Wednesday",
    "R": "Thursday", "F": "Friday", "S": "Saturday", "U": "Sunday",
}


def time_to_min(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def min_to_ampm(total: int) -> str:
    h, m = divmod(total, 60)
    period = "AM" if h < 12 else "PM"
    h = h % 12 or 12
    return f"{h}:{m:02d} {period}"


def parse_day(day_str: str) -> str:
    mapping = {
        "monday": "M", "mon": "M", "m": "M",
        "tuesday": "T", "tue": "T", "tu": "T", "t": "T",
        "wednesday": "W", "wed": "W", "w": "W",
        "thursday": "R", "thu": "R", "th": "R", "r": "R",
        "friday": "F", "fri": "F", "f": "F",
        "saturday": "S", "sat": "S", "s": "S",
        "sunday": "U", "sun": "U", "u": "U",
    }
    return mapping.get(day_str.strip().lower(), day_str.strip().upper())


def parse_time(time_str: str) -> str:
    """Parse user time input into HH:MM (24-hr). Accepts '2:30 PM', '14:30', etc."""
    time_str = time_str.strip()
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            return datetime.strptime(time_str.upper(), fmt).strftime("%H:%M")
        except ValueError:
            pass
    for fmt in ("%H:%M", "%H"):
        try:
            return datetime.strptime(time_str, fmt).strftime("%H:%M")
        except ValueError:
            pass
    raise ValueError(f"Can't parse time: '{time_str}'")


def now() -> Tuple[str, str]:
    """Return (day_code, HH:MM) for right now."""
    n = datetime.now()
    return DAY_MAP[n.weekday()], n.strftime("%H:%M")


def find_free_rooms(
    rooms: Dict,
    day: str,
    query_time: str,
    building_filter: Optional[str] = None,
    min_duration: int = 0,
) -> List[Dict]:
    """
    Return rooms that are free at (day, query_time).
    Each result dict has: building, room, free_until, free_for_minutes.
    Sorted by free_for_minutes descending (longest first).
    """
    q = time_to_min(query_time)
    results = []

    for room_data in rooms.values():
        building = room_data["building"]

        if building_filter and building.upper() != building_filter.upper():
            continue

        day_slots = [s for s in room_data.get("slots", []) if day in s.get("days", [])]

        # Skip if occupied right now
        occupied = any(
            time_to_min(s["start"]) <= q < time_to_min(s["end"])
            for s in day_slots
        )
        if occupied:
            continue

        # Find next occupied slot after query_time
        future = [time_to_min(s["start"]) for s in day_slots if time_to_min(s["start"]) > q]
        next_min = min(future) if future else None
        duration = (next_min - q) if next_min is not None else None

        if min_duration > 0 and duration is not None and duration < min_duration:
            continue

        results.append({
            "building": building,
            "room": room_data["room"],
            "free_until": min_to_ampm(next_min) if next_min is not None else "End of day",
            "free_for_minutes": duration,
        })

    results.sort(
        key=lambda r: r["free_for_minutes"] if r["free_for_minutes"] is not None else float("inf"),
        reverse=True,
    )
    return results
