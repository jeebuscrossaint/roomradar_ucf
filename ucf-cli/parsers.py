"""
Pure parsing functions for UCF PeopleSoft HTML.
Logic adapted from https://github.com/xxfmin/ucf-spots (MIT)
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class TimeSlot:
    start: str  # "09:30"  (24-hr)
    end: str    # "10:50"


@dataclass
class Location:
    building: str  # "ENG2"
    room: str      # "0302"


@dataclass
class Section:
    time: Optional[TimeSlot]
    location: Optional[Location]
    days: List[str]    # ["M", "W", "F"]
    start_date: str    # "2026-01-12"
    end_date: str      # "2026-05-05"


@dataclass
class Course:
    number: str
    title: Optional[str] = None
    sections: List[Section] = field(default_factory=list)


def parse_days(day_str: str) -> List[str]:
    if not day_str or "TBA" in day_str or "ARR" in day_str:
        return []
    mapping = {"Mo": "M", "Tu": "T", "We": "W", "Th": "R", "Fr": "F", "Sa": "S", "Su": "U"}
    days = []
    for abbrev, code in mapping.items():
        if abbrev in day_str:
            days.append(code)
    if not days:
        valid = {"M", "T", "W", "R", "F", "S", "U"}
        for ch in day_str:
            if ch in valid and ch not in days:
                days.append(ch)
    return days


def parse_time(time_str: str) -> Optional[TimeSlot]:
    if not time_str or "TBA" in time_str or "ARR" in time_str:
        return None
    m = re.search(r"(\d{1,2}:\d{2}[AP]M)\s*-\s*(\d{1,2}:\d{2}[AP]M)", time_str)
    if not m:
        return None
    try:
        start = datetime.strptime(m.group(1), "%I:%M%p").strftime("%H:%M")
        end   = datetime.strptime(m.group(2), "%I:%M%p").strftime("%H:%M")
        return TimeSlot(start=start, end=end)
    except ValueError:
        return None


def parse_location(room_str: str) -> Optional[Location]:
    if not room_str or "TBA" in room_str or "WEB" in room_str:
        return None
    parts = room_str.strip().split()
    if len(parts) >= 2:
        return Location(building=parts[0], room=parts[1])
    return None


def parse_dates(date_str: str):
    if not date_str:
        return ("", "")
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})", date_str)
    if m:
        try:
            start = datetime.strptime(m.group(1), "%m/%d/%Y").strftime("%Y-%m-%d")
            end   = datetime.strptime(m.group(2), "%m/%d/%Y").strftime("%Y-%m-%d")
            return (start, end)
        except ValueError:
            pass
    return ("", "")


def scrape_search_results(html_content: str) -> List[Course]:
    soup = BeautifulSoup(html_content, "html.parser")
    courses = []

    headers = soup.find_all(
        "a",
        attrs={"title": re.compile(r"Collapse section [A-Z]{3,4} \d{4}[A-Z]?")}
    )

    for header in headers:
        title = header.get("title", "")
        if not isinstance(title, str):
            continue
        match = re.search(r"Collapse section ([A-Z]{3,4} \d{4}[A-Z]?) - (.+)", title)
        if not match:
            continue

        course = Course(number=match.group(1), title=match.group(2))

        parent = header.find_parent(
            "div", id=re.compile(r"win0divSSR_CLSRSLT_WRK_GROUPBOX2\$\d+")
        )
        if not parent:
            continue

        rows = parent.find_all("tr", id=re.compile(r"trSSR_CLSRCH_MTG1\$\d+_row\d+"))

        for row in rows:
            try:
                daytime_span = row.find("span", id=re.compile(r"MTG_DAYTIME\$\d+"))
                room_span    = row.find("span", id=re.compile(r"MTG_ROOM\$\d+"))
                dates_span   = row.find("span", id=re.compile(r"MTG_TOPIC\$\d+"))

                daytimes = daytime_span.get_text(separator="\n", strip=True).split("\n") if daytime_span else []
                rooms    = room_span.get_text(separator="\n", strip=True).split("\n")    if room_span    else []
                dates    = dates_span.get_text(separator="\n", strip=True).split("\n")   if dates_span   else []

                for i in range(max(len(daytimes), len(rooms), len(dates))):
                    dt_str   = daytimes[i].strip() if i < len(daytimes) else ""
                    room_str = rooms[i].strip()    if i < len(rooms)    else ""
                    date_str = dates[i].strip()    if i < len(dates)    else ""

                    time_slot = parse_time(dt_str)
                    location  = parse_location(room_str)
                    days      = parse_days(dt_str)
                    start_date, end_date = parse_dates(date_str)

                    if location and time_slot:
                        course.sections.append(Section(
                            time=time_slot,
                            location=location,
                            days=days,
                            start_date=start_date,
                            end_date=end_date,
                        ))

            except Exception as e:
                logger.warning("Failed to parse row in %s: %s", course.number, e)

        if course.sections:
            courses.append(course)

    return courses
