"""
Scrapes UCF's PeopleSoft class search to build a local room schedule cache.
Adapted from https://github.com/xxfmin/ucf-spots (MIT)

Speed notes:
  - Fixed sleeps are replaced with PeopleSoft AJAX-spinner waits.
  - For each subject, the first career does a full page load; subsequent
    careers reuse the same page via "Modify Search" — no extra reload.
  - --workers N runs N browsers in parallel, each covering a slice of subjects.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from config import DATA_DIR, DATA_FILE, DEFAULT_TERM, UCF_CLASS_SEARCH_URL
from parsers import scrape_search_results

logger = logging.getLogger(__name__)

SUBJECT_CODES = [
    'ACG', 'ADE', 'ADV', 'AFA', 'AFH', 'AFR', 'AMH', 'AML', 'ANG', 'ANT', 'APK',
    'ARA', 'ARC', 'ARE', 'ARH', 'ART', 'ASH', 'ASL', 'AST', 'ATR', 'AVM', 'BCH',
    'BME', 'BMS', 'BOT', 'BSC', 'BTE', 'BUL', 'CAI', 'CAP', 'CBH', 'CCE', 'CCJ',
    'CDA', 'CEG', 'CEN', 'CES', 'CGN', 'CGS', 'CHI', 'CHM', 'CHS', 'CIS', 'CJC',
    'CJE', 'CJJ', 'CJL', 'CJT', 'CLA', 'CLP', 'CLT', 'CNT', 'COM', 'COP', 'COT',
    'CPO', 'CRW', 'CWR', 'CYP', 'DAA', 'DAE', 'DAN', 'DEP', 'DIE', 'DIG', 'DSC',
    'EAB', 'EAP', 'EAS', 'EBD', 'ECM', 'ECO', 'ECP', 'ECS', 'ECT', 'ECW', 'EDA',
    'EDE', 'EDF', 'EDG', 'EDH', 'EDM', 'EDP', 'EDS', 'EEC', 'EEE', 'EEL', 'EES',
    'EEX', 'EGC', 'EGI', 'EGM', 'EGN', 'EGS', 'EIN', 'ELD', 'EMA', 'EME', 'EML',
    'EMR', 'ENC', 'ENG', 'ENL', 'ENT', 'ENV', 'ENY', 'ESE', 'ESI', 'EUH', 'EVR',
    'EXP', 'FIL', 'FIN', 'FLE', 'FOL', 'FRE', 'FRT', 'FRW', 'FSS', 'GEA', 'GEB',
    'GEO', 'GER', 'GEW', 'GEY', 'GIS', 'GLY', 'GMS', 'GRA', 'HAI', 'HAT', 'HBR',
    'HCW', 'HFT', 'HIM', 'HIS', 'HLP', 'HMG', 'HSA', 'HSC', 'HUM', 'HUN', 'IDC',
    'IDH', 'IDS', 'IHS', 'INP', 'INR', 'ISC', 'ISM', 'ITA', 'ITT', 'ITW', 'JOU',
    'JPN', 'JST', 'KOR', 'LAE', 'LAH', 'LAS', 'LDR', 'LEI', 'LIN', 'LIT', 'MAA',
    'MAC', 'MAD', 'MAE', 'MAN', 'MAP', 'MAR', 'MAS', 'MAT', 'MCB', 'MDC', 'MDE',
    'MDI', 'MDR', 'MDX', 'MET', 'MGF', 'MHF', 'MHS', 'MLS', 'MMC', 'MSL', 'MTG',
    'MUC', 'MUE', 'MUG', 'MUH', 'MUL', 'MUM', 'MUN', 'MUO', 'MUS', 'MUT', 'MVB',
    'MVJ', 'MVK', 'MVO', 'MVP', 'MVS', 'MVV', 'MVW', 'NGR', 'NSP', 'NUR', 'OCE',
    'OSE', 'PAD', 'PAF', 'PAZ', 'PCB', 'PCO', 'PEL', 'PEM', 'PEO', 'PET', 'PGY',
    'PHC', 'PHH', 'PHI', 'PHM', 'PHP', 'PHT', 'PHY', 'PHZ', 'PLA', 'POR', 'POS',
    'POT', 'PPE', 'PSB', 'PSC', 'PSY', 'PUP', 'PUR', 'QMB', 'RED', 'REE', 'REL',
    'RMI', 'RTV', 'RUS', 'RUT', 'SCC', 'SCE', 'SDS', 'SLS', 'SOP', 'SOW', 'SPA',
    'SPB', 'SPC', 'SPM', 'SPN', 'SPS', 'SPT', 'SPW', 'SSE', 'STA', 'SYA', 'SYD',
    'SYG', 'SYO', 'SYP', 'TAX', 'THE', 'TPA', 'TPP', 'TSL', 'TTE', 'URP', 'VIC',
    'WOH', 'WST', 'ZOO',
]


# ── browser setup ─────────────────────────────────────────────────────────────

def _setup_driver(headless: bool) -> webdriver.Chrome:
    args = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--window-size=1920,1080"]
    if headless:
        args.append("--headless=new")

    try:
        opts = ChromeOptions()
        for a in args:
            opts.add_argument(a)
        return webdriver.Chrome(options=opts)
    except Exception as chrome_err:
        logger.debug("Chrome unavailable (%s), trying Edge...", chrome_err)

    try:
        from selenium.webdriver.edge.options import Options as EdgeOptions
        opts = EdgeOptions()
        for a in args:
            opts.add_argument(a)
        return webdriver.Edge(options=opts)
    except Exception as edge_err:
        raise RuntimeError(
            f"Could not launch Chrome or Edge.\n"
            f"Chrome: {chrome_err}\nEdge: {edge_err}"
        ) from edge_err


# ── PeopleSoft helpers ────────────────────────────────────────────────────────

def _wait_ps(driver: webdriver.Chrome, timeout: int = 15) -> None:
    """Wait for PeopleSoft's loading spinner to disappear."""
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.ID, "processing"))
        )
    except TimeoutException:
        pass  # spinner may not have appeared at all — that's fine


def _dismiss_overflow_modal(driver: webdriver.Chrome) -> None:
    """Dismiss PeopleSoft's >300-results overflow modal (lives in an iframe)."""
    try:
        # Give the modal a generous window to appear for large result sets
        WebDriverWait(driver, 8).until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, "ptModFrame_0"))
        )
        ok = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.ID, "ICSave")))
        ok.click()
        driver.switch_to.default_content()
        _wait_ps(driver)
        logger.debug("Dismissed overflow modal")
    except Exception:
        driver.switch_to.default_content()


def _has_no_results(driver: webdriver.Chrome) -> bool:
    return "no results" in driver.page_source.lower()


def _click_search(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    """Click the Search button using a real browser event (JS synthetic click is ignored)."""
    btn = wait.until(EC.element_to_be_clickable((By.ID, "CLASS_SRCH_WRK2_SSR_PB_CLASS_SRCH")))
    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
    ActionChains(driver).move_to_element(btn).click().perform()


def _has_invalid_request(driver: webdriver.Chrome) -> bool:
    return "invalid request" in driver.page_source.lower()


def _wait_for_results(driver: webdriver.Chrome, wait: WebDriverWait, subject: str, career: str) -> bool:
    """
    Wait for results, a no-results message, or an error page.
    Returns True if there are results to parse, False otherwise.
    """
    try:
        wait.until(EC.any_of(
            EC.presence_of_element_located((By.ID, "SSR_CLSRSLT_WRK_GROUPBOX2$0")),
            EC.presence_of_element_located((By.CLASS_NAME, "PSERRORMSGTEXT")),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'no results')]")),
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Invalid Request')]")),
        ))
    except TimeoutException:
        dump = DATA_DIR / f"debug_{subject}_{career}.html"
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            dump.write_text(driver.page_source, encoding="utf-8")
        except Exception:
            pass
        logger.warning("Timeout on %s/%s", subject, career)
        return False

    src = driver.page_source.lower()
    if "no results" in src:
        logger.debug("No results: %s/%s", subject, career)
        return False
    if "invalid request" in src:
        logger.warning("Invalid request (checkbox?) on %s/%s", subject, career)
        return False

    return True


def _expand_sections(driver: webdriver.Chrome) -> None:
    for link in driver.find_elements(By.CSS_SELECTOR, "a[id^='SSR_CLSRSLT_WRK_GROUPBOX2']"):
        try:
            driver.execute_script("arguments[0].click();", link)
        except Exception:
            pass
    _wait_ps(driver, 5)


def _get_career_codes(driver: webdriver.Chrome) -> List[str]:
    driver.get(UCF_CLASS_SEARCH_URL)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.ID, "SSR_CLSRCH_WRK_ACAD_CAREER$3"))
    )
    _wait_ps(driver)
    sel = Select(driver.find_element(By.ID, "SSR_CLSRCH_WRK_ACAD_CAREER$3"))
    codes = [o.get_attribute("value") for o in sel.options if o.get_attribute("value")]
    logger.info("Careers: %s", codes)
    return codes


# ── form interactions ─────────────────────────────────────────────────────────

def _fill_form(driver: webdriver.Chrome, wait: WebDriverWait, subject: str, career: str) -> None:
    """Fill the search form from scratch (used on full page load)."""
    wait.until(EC.presence_of_element_located((By.ID, "SSR_CLSRCH_WRK_SUBJECT$0")))
    _wait_ps(driver)

    # Subject
    f = driver.find_element(By.ID, "SSR_CLSRCH_WRK_SUBJECT$0")
    f.clear()
    f.send_keys(subject)

    # Verify checkbox
    _tick_verify(driver)

    # Location → Main Campus
    try:
        Select(driver.find_element(By.ID, "SSR_CLSRCH_WRK_LOCATION$4")).select_by_value("M")
    except Exception:
        pass

    # Uncheck "open only"
    try:
        cb2 = driver.find_element(By.ID, "SSR_CLSRCH_WRK_SSR_OPEN_ONLY$6")
        if cb2.is_selected():
            cb2.click()
    except NoSuchElementException:
        pass

    # Career — set last, then wait for AJAX
    Select(driver.find_element(By.ID, "SSR_CLSRCH_WRK_ACAD_CAREER$3")).select_by_value(career)
    _wait_ps(driver)


def _tick_verify(driver: webdriver.Chrome) -> None:
    """Ensure the Verify Search checkbox is ticked."""
    try:
        cb = driver.find_element(By.ID, "FX_CLSSRCH_DER_FLAG")
        if not cb.is_selected():
            cb.click()
            _wait_ps(driver, 5)
    except NoSuchElementException:
        pass


def _modify_career(driver: webdriver.Chrome, wait: WebDriverWait, career: str) -> bool:
    """
    From the results page, click "Modify Search" and change only the career.
    Much faster than a full page reload.
    Returns False if the Modify button isn't found (caller should fall back to reload).
    """
    try:
        modify_btn = wait.until(
            EC.element_to_be_clickable((By.ID, "CLASS_SRCH_WRK2_SSR_PB_MODIFY"))
        )
        ActionChains(driver).move_to_element(modify_btn).click().perform()
        wait.until(EC.presence_of_element_located((By.ID, "SSR_CLSRCH_WRK_SUBJECT$0")))
        _wait_ps(driver)

        # Re-tick verify — it resets when returning to the search form
        _tick_verify(driver)

        # Career last, then wait for AJAX
        Select(driver.find_element(By.ID, "SSR_CLSRCH_WRK_ACAD_CAREER$3")).select_by_value(career)
        _wait_ps(driver)
        return True
    except Exception:
        return False


# ── per-subject scrape ────────────────────────────────────────────────────────

def _scrape_subject(driver: webdriver.Chrome, subject: str, careers: List[str], term: str) -> Dict:
    """Scrape all careers for one subject. Returns room dict."""
    wait  = WebDriverWait(driver, 30)
    rooms: Dict = {}

    for i, career in enumerate(careers):
        if i == 0:
            # First career: full page load
            driver.delete_all_cookies()
            driver.get(UCF_CLASS_SEARCH_URL)
            try:
                _fill_form(driver, wait, subject, career)
            except Exception as e:
                logger.error("Form fill failed %s/%s: %s", subject, career, e)
                continue
        else:
            # Subsequent careers: reuse page via "Modify Search"
            if not _modify_career(driver, wait, career):
                # Modify button not found — fall back to full reload
                driver.delete_all_cookies()
                driver.get(UCF_CLASS_SEARCH_URL)
                try:
                    _fill_form(driver, wait, subject, career)
                except Exception as e:
                    logger.error("Form fill failed %s/%s: %s", subject, career, e)
                    continue

        got_results = False
        for attempt in range(2):
            try:
                _click_search(driver, wait)
            except Exception as e:
                logger.error("Search click failed %s/%s attempt %d: %s", subject, career, attempt, e)
                break

            _dismiss_overflow_modal(driver)

            if _wait_for_results(driver, wait, subject, career):
                got_results = True
                break

            if attempt == 0:
                # First attempt failed — fresh reload and retry once
                logger.info("Retrying %s/%s with fresh page load", subject, career)
                driver.delete_all_cookies()
                driver.get(UCF_CLASS_SEARCH_URL)
                try:
                    _fill_form(driver, wait, subject, career)
                except Exception as e:
                    logger.error("Retry form fill failed %s/%s: %s", subject, career, e)
                    break

        if not got_results:
            continue

        _expand_sections(driver)
        courses = scrape_search_results(driver.page_source)
        for key, data in _to_room_dict(courses).items():
            if key not in rooms:
                rooms[key] = data
            else:
                rooms[key]["slots"].extend(data["slots"])

    return rooms


# ── room dict ─────────────────────────────────────────────────────────────────

def _to_room_dict(courses) -> Dict:
    rooms: Dict = {}
    for course in courses:
        for section in course.sections:
            if not section.location or not section.time:
                continue
            key = f"{section.location.building}-{section.location.room}"
            if key not in rooms:
                rooms[key] = {"building": section.location.building, "room": section.location.room, "slots": []}
            rooms[key]["slots"].append({
                "days":  section.days,
                "start": section.time.start,
                "end":   section.time.end,
            })
    return rooms


def _merge(all_rooms: Dict, new_rooms: Dict) -> None:
    for key, data in new_rooms.items():
        if key not in all_rooms:
            all_rooms[key] = data
        else:
            all_rooms[key]["slots"].extend(data["slots"])



# ── worker (one per parallel browser) ────────────────────────────────────────

def _worker(subjects: List[str], careers: List[str], term: str,
            headless: bool, worker_id: int) -> Dict:
    driver = _setup_driver(headless)
    rooms: Dict = {}
    total = len(subjects)
    try:
        for i, subject in enumerate(subjects, 1):
            logger.info("[worker %d | %d/%d] %s", worker_id, i, total, subject)
            result = _scrape_subject(driver, subject, careers, term)
            _merge(rooms, result)
    finally:
        driver.quit()
    return rooms


# ── public entry point ────────────────────────────────────────────────────────

def scrape(
    term: str = DEFAULT_TERM,
    headless: bool = True,
    subjects: Optional[List[str]] = None,
    workers: int = 1,
) -> Dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if subjects is None:
        subjects = SUBJECT_CODES

    # Get career codes from a throw-away browser so workers start clean
    probe = _setup_driver(headless)
    try:
        careers = _get_career_codes(probe)
    finally:
        probe.quit()

    # Seed with existing data so partial re-runs don't wipe previous results
    all_rooms: Dict = {}
    if DATA_FILE.exists():
        try:
            all_rooms = json.loads(DATA_FILE.read_text()).get("rooms", {})
            logger.info("Loaded %d existing rooms from %s", len(all_rooms), DATA_FILE)
        except Exception:
            pass

    if workers <= 1:
        all_rooms = _worker(subjects, careers, term, headless, 0)
    else:
        # Split subjects across workers
        chunks = [subjects[i::workers] for i in range(workers)]
        logger.info("Launching %d parallel browsers", workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_worker, chunk, careers, term, headless, idx): idx
                for idx, chunk in enumerate(chunks)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    _merge(all_rooms, future.result())
                except Exception as e:
                    logger.error("Worker %d failed: %s", idx, e)

    output = {
        "term": term,
        "scraped_at": datetime.now().isoformat(),
        "rooms": all_rooms,
    }
    DATA_FILE.write_text(json.dumps(output, indent=2))
    logger.info("Saved %d rooms to %s", len(all_rooms), DATA_FILE)
    return output
