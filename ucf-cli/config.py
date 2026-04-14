from pathlib import Path

UCF_CLASS_SEARCH_URL = (
    "https://csprod-ss.net.ucf.edu/psc/CSPROD/EMPLOYEE/SA/c/"
    "COMMUNITY_ACCESS.CLASS_SEARCH.GBL"
)

# Spring 2026 = 2261  |  Summer 2026 = 2265  |  Fall 2026 = 2268
DEFAULT_TERM = "2261"

DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "schedule.json"

DAY_NAMES = {
    "M": "Monday",
    "T": "Tuesday",
    "W": "Wednesday",
    "R": "Thursday",
    "F": "Friday",
    "S": "Saturday",
    "U": "Sunday",
}
