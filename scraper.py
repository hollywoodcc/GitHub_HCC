"""
Hollywood Cricket Club — Weekly Site Updater
=============================================
Scrapes all 4 Hollywood team pages from cricclubs.com/SCCA and updates
hollywoodcc.html with the latest results, standings, batting, bowling,
upcoming fixtures, and scrolling ticker content.

Usage:
    python scraper.py                        # updates hollywoodcc.html in place
    python scraper.py --input path/to/file   # specify input HTML file
    python scraper.py --dry-run              # print what would change, don't write

Requirements:
    pip install playwright
    playwright install chromium
"""

import re
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Team config
# ---------------------------------------------------------------------------

TEAMS = [
    {
        "num":      1,
        "label":    "HW1",
        "name":     "Hollywood 1",
        "division": "2026 OD Div 1",
        "series_id":"E3fP_GI8dqYYOIeCUnfTcw",
        "team_hash":"YPCtBhfsGB5qjfklxBLPKA",
        "color":    "#1A5C3A",
        "div_key":  "Div 1",
    },
    {
        "num":      2,
        "label":    "HW2",
        "name":     "Hollywood 2",
        "division": "2026 OD Div 2",
        "series_id":"jqVCP7p_259dJv6vajaYYg",
        "team_hash":"31c2kEqdnKzxl7mDVNZVUg",
        "color":    "#1B3F6E",
        "div_key":  "Div 2",
    },
    {
        "num":      3,
        "label":    "HW3",
        "name":     "Hollywood 3",
        "division": "2026 OD Div 3",
        "series_id":"betgectBJ7qRH8CajBaROA",
        "team_hash":"SE8vSPGlCNuAIFcV1b4s_g",
        "color":    "#4A2B7A",
        "div_key":  "Div 3",
    },
    {
        "num":      4,
        "label":    "HW4",
        "name":     "Hollywood 4",
        "division": "2026 OD Div 5",
        "series_id":"f6ZxqbZmn6o9A4WC9BQknA",
        "team_hash":"fN3_xwJQQaRxvMia4RQzPg",
        "color":    "#8B2020",
        "div_key":  "Div 5",
    },
]

BASE_URL   = "https://cricclubs.com/SCCA"
SERIES_URL = BASE_URL + "/series-list/{series_id}?seriesName={div}&tab={tab}"
TEAM_URL   = BASE_URL + "/teams/{team_hash}?seriesId={series_id}&tab={tab}"

PAGE_TIMEOUT   = 60_000   # 60 seconds
WAIT_AFTER_NAV = 4        # seconds after navigation for React to render
MAX_RETRIES    = 3

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("hcc")


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def get_page_text(page, url: str) -> str:
    """Navigate and return body text. Retries up to MAX_RETRIES times."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            time.sleep(WAIT_AFTER_NAV)
            return page.inner_text("body")
        except Exception as e:
            last_err = e
            log.warning(f"  Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    raise RuntimeError(f"Failed after {MAX_RETRIES} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

def scrape_points_table(page, team: dict) -> list:
    url  = SERIES_URL.format(
        series_id=team["series_id"],
        div=team["division"].replace(" ", "+"),
        tab="pointsTable",
    )
    log.info(f"  Standings: {url}")
    text  = get_page_text(page, url)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows  = []
    in_table = False
    i = 0
    while i < len(lines):
        if "Points Table" in lines[i] and "Details" not in lines[i]:
            in_table = True
            i += 1
            continue
        if in_table:
            if re.match(r'^\d+$', lines[i].lstrip("#").strip()):
                try:
                    pos       = int(lines[i].lstrip("#").strip())
                    team_name = lines[i+1].strip() if i+1 < len(lines) else ""
                    offset    = 2
                    nums      = []
                    while len(nums) < 9 and (i + offset) < len(lines):
                        c = lines[i + offset].strip()
                        if re.match(r'^-?\d+\.?\d*%?$', c) or re.match(r'^\d+/\d+\.\d+$', c):
                            nums.append(c)
                        offset += 1
                    if len(nums) >= 7:
                        rows.append({
                            "pos":  pos,
                            "team": team_name,
                            "mat":  int(nums[0]),
                            "won":  int(nums[1]),
                            "lost": int(nums[2]),
                            "nr":   int(nums[3]),
                            "tie":  int(nums[4]),
                            "pts":  int(float(nums[5])),
                            "nrr":  nums[7] if len(nums) > 7 else "0",
                        })
                except (ValueError, IndexError):
                    pass
                i += offset
                continue
            if "©" in lines[i]:
                break
        i += 1
    log.info(f"  → {len(rows)} teams")
    return rows


def scrape_team_results(page, team: dict) -> list:
    url  = TEAM_URL.format(team_hash=team["team_hash"], series_id=team["series_id"], tab="results")
    log.info(f"  Results: {url}")
    text    = get_page_text(page, url)
    results = []
    lines   = [l.strip() for l in text.splitlines() if l.strip()]
    i = 0
    while i < len(lines):
        dm = re.match(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\w+ \d+, \d{4})', lines[i])
        if dm:
            date_str = dm.group(2)
            block    = lines[i:i+22]
            bt       = " | ".join(block)
            scores   = re.findall(r'\d+/\d+\(\d+\.?\d*/\d+\)', bt)
            result_line = ""
            for bl in block:
                if re.search(r'\b(won|tied|Tie|Abandoned|No result)\b', bl, re.I):
                    if not any(x in bl for x in ["Scorecard", "Ball by Ball", "Umpire"]):
                        result_line = bl.strip()
                        break
            opponent, venue = "", ""
            for idx, bl in enumerate(block):
                if re.match(r'^2026 OD Div', bl):
                    if idx + 1 < len(block):
                        venue = block[idx + 1]
                    break
            for bl in block:
                if re.search(r'\bvs\b', bl, re.I):
                    for p in re.split(r'\s+vs\s+', bl, flags=re.I):
                        p = p.strip()
                        if p and team["name"] not in p and len(p) > 2:
                            opponent = p
                            break
                    break
            if result_line:
                rl = result_line.lower()
                if "tie" in rl or "tied" in rl:
                    outcome = "T"
                elif "abandoned" in rl or "no result" in rl:
                    outcome = "NR"
                else:
                    wp = result_line.split("won")[0].strip() if "won" in rl else ""
                    outcome = "W" if team["name"].lower() in wp.lower() else "L"
                results.append({
                    "date":      date_str,
                    "opponent":  opponent,
                    "venue":     venue,
                    "hw_score":  scores[0] if scores else "",
                    "opp_score": scores[1] if len(scores) > 1 else "",
                    "result":    result_line,
                    "outcome":   outcome,
                })
        i += 1
    log.info(f"  → {len(results)} results")
    return results


def scrape_team_schedule(page, team: dict) -> list:
    url  = TEAM_URL.format(team_hash=team["team_hash"], series_id=team["series_id"], tab="schedule")
    log.info(f"  Schedule: {url}")
    text     = get_page_text(page, url)
    upcoming = []
    lines    = [l.strip() for l in text.splitlines() if l.strip()]
    i = 0
    while i < len(lines):
        dm = re.match(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\w+ \d+, \d{4})', lines[i])
        if dm:
            date_str  = dm.group(2)
            block     = lines[i:i+15]
            has_score = any(re.search(r'\d+/\d+\(', bl) for bl in block)
            if not has_score:
                opponent, venue = "", ""
                for idx, bl in enumerate(block):
                    if re.match(r'^2026 OD Div', bl):
                        if idx + 1 < len(block):
                            venue = block[idx + 1]
                        break
                for bl in block:
                    if re.search(r'\bvs\b', bl, re.I):
                        for p in re.split(r'\s+vs\s+', bl, flags=re.I):
                            p = p.strip()
                            if p and team["name"] not in p and len(p) > 2:
                                opponent = p
                                break
                        break
                if opponent:
                    upcoming.append({"date": date_str, "opponent": opponent, "venue": venue})
        i += 1
    log.info(f"  → {len(upcoming)} upcoming")
    return upcoming


def scrape_batting(page, team: dict) -> list:
    url  = TEAM_URL.format(team_hash=team["team_hash"], series_id=team["series_id"], tab="batting")
    log.info(f"  Batting: {url}")
    text  = get_page_text(page, url)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    stats = []
    i     = 0
    while i < len(lines):
        if re.match(r'^\d+$', lines[i]) and i + 10 < len(lines):
            try:
                rank   = int(lines[i])
                name   = lines[i+1]
                offset = 3 if lines[i+2].startswith("Hollywood") else 2
                vals   = lines[i+offset:i+offset+14]
                nums   = [v for v in vals if re.match(r'^-?\d+\.?\d*$', v)]
                if len(nums) >= 10:
                    stats.append({
                        "rank": rank, "name": name,
                        "mat":  int(nums[0]),  "inns": int(nums[1]),
                        "no":   int(nums[2]),  "runs": int(nums[3]),
                        "balls":int(nums[4]),  "fours":int(nums[5]),
                        "sixes":int(nums[6]),  "fifties":int(nums[7]),
                        "hundreds":int(nums[8]),"hs":int(nums[9]),
                        "sr":  float(nums[10]) if len(nums) > 10 else 0.0,
                        "avg": float(nums[11]) if len(nums) > 11 else 0.0,
                    })
            except (ValueError, IndexError):
                pass
        i += 1
    log.info(f"  → {len(stats)} batters")
    return stats


def scrape_bowling(page, team: dict) -> list:
    url  = TEAM_URL.format(team_hash=team["team_hash"], series_id=team["series_id"], tab="bowling")
    log.info(f"  Bowling: {url}")
    text  = get_page_text(page, url)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    stats = []
    i     = 0
    while i < len(lines):
        if re.match(r'^\d+$', lines[i]) and i + 10 < len(lines):
            try:
                rank   = int(lines[i])
                name   = lines[i+1]
                offset = 3 if lines[i+2].startswith("Hollywood") else 2
                vals   = lines[i+offset:i+offset+16]
                nums   = [v for v in vals if re.match(r'^-?\d+\.?\d*$', v)]
                bbf    = next((v for v in vals if re.match(r'^\d+/\d+$', v)), "0/0")
                if len(nums) >= 7:
                    stats.append({
                        "rank": rank, "name": name,
                        "mat":  int(nums[0]),
                        "overs":float(nums[2]) if len(nums) > 2 else 0.0,
                        "mdns": int(nums[3])   if len(nums) > 3 else 0,
                        "runs": int(nums[4])   if len(nums) > 4 else 0,
                        "wkts": int(nums[5])   if len(nums) > 5 else 0,
                        "bbf":  bbf,
                        "econ": float(nums[7]) if len(nums) > 7 else 0.0,
                        "avg":  float(nums[8]) if len(nums) > 8 else 0.0,
                        "sr":   float(nums[9]) if len(nums) > 9 else 0.0,
                    })
            except (ValueError, IndexError):
                pass
        i += 1
    log.info(f"  → {len(stats)} bowlers")
    return stats


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

def q(s):
    """Escape single quotes for JS string literals."""
    return str(s).replace("'", "")


def fmt_results(results: list) -> str:
    lines = []
    for r in results[:9]:
        margin = ""
        if "by" in r["result"].lower():
            margin = "by " + r["result"].lower().split("by", 1)[1].strip()
        outcome_str = (
            f'W {margin}' if r["outcome"] == "W" and margin else
            f'L {margin}' if r["outcome"] == "L" and margin else
            r["outcome"]
        )
        lines.append(
            f"      {{date:'{q(r['date'])}',opp:'{q(r['opponent'])}',venue:'{q(r['venue'])}',"
            f"hw1:'{q(r['hw_score'])}',opp_score:'{q(r['opp_score'])}',"
            f"result:'{q(outcome_str)}'}}"
        )
    return "[\n" + ",\n".join(lines) + "\n    ]"


def fmt_batting(stats: list) -> str:
    lines = []
    for b in stats[:12]:
        lines.append(
            f"      {{rank:{b['rank']},name:'{q(b['name'])}'"
            f",mat:{b['mat']},inns:{b['inns']},no:{b['no']},runs:{b['runs']}"
            f",balls:{b['balls']},fours:{b['fours']},sixes:{b['sixes']}"
            f",fifties:{b['fifties']},hundreds:{b['hundreds']},hs:{b['hs']}"
            f",sr:{b['sr']},avg:{b['avg']}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n    ]"


def fmt_bowling(stats: list) -> str:
    lines = []
    for bw in stats[:10]:
        lines.append(
            f"      {{rank:{bw['rank']},name:'{q(bw['name'])}'"
            f",mat:{bw['mat']},overs:{bw['overs']},mdns:{bw['mdns']}"
            f",runs:{bw['runs']},wkts:{bw['wkts']},bbf:'{q(bw['bbf'])}'"
            f",econ:{bw['econ']},avg:{bw['avg']},sr:{bw['sr']}}}"
        )
    return "[\n" + ",\n".join(lines) + "\n    ]"


def build_standings_rows(all_standings: dict) -> str:
    div_colors = {1:"#1A5C3A", 2:"#1B3F6E", 3:"#4A2B7A", 4:"#8B2020"}
    div_labels = {1:"2026 OD Div 1", 2:"2026 OD Div 2", 3:"2026 OD Div 3", 4:"2026 OD Div 5"}
    rows = ""
    for t in TEAMS:
        num   = t["num"]
        color = div_colors[num]
        label = div_labels[num]
        tname = f"Hollywood {num}"
        entry = next((s for s in all_standings.get(num, []) if tname in s["team"]), None)
        rows += (
            f'<tr style="background:#f0f4ff"><td colspan="8" style="padding:8px 14px;'
            f'font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;'
            f'color:{color}">{label} — {tname}</td></tr>\n'
        )
        if entry:
            try:
                nrr_f   = float(entry["nrr"])
                nrr_col = "#27ae60" if nrr_f >= 0 else "#c0392b"
                nrr_str = f"+{nrr_f:.4f}" if nrr_f >= 0 else f"{nrr_f:.4f}"
            except ValueError:
                nrr_col, nrr_str = "#555", entry["nrr"]
            tie_nr = entry["tie"] + entry["nr"]
            rows += (
                f'<tr class="hw-row"><td><strong>{entry["pos"]}</strong></td>'
                f'<td><strong>{tname}</strong></td>'
                f'<td>{entry["mat"]}</td><td>{entry["won"]}</td>'
                f'<td>{entry["lost"]}</td><td>{tie_nr}</td>'
                f'<td>{entry["pts"]}</td>'
                f'<td style="font-size:12px;color:{nrr_col}">{nrr_str}</td></tr>\n'
            )
        else:
            rows += (
                f'<tr class="hw-row"><td>–</td><td><strong>{tname}</strong></td>'
                f'<td colspan="6" style="color:#999">No data</td></tr>\n'
            )
    return rows


def build_ticker(all_data: dict) -> str:
    items = []

    def item(cls, tag, text):
        return f'<div class="ticker-item"><span class="ticker-tag {cls}">{tag}</span> {text}</div>'

    # Upcoming
    for t in TEAMS:
        for u in all_data[t["num"]]["upcoming"][:2]:
            v = f' &bull; {u["venue"]}' if u["venue"] else ""
            items.append(item("upcoming", "Upcoming",
                f'{t["label"]} vs {u["opponent"]} &mdash; {u["date"]}{v}'))

    # Results
    for t in TEAMS:
        for r in all_data[t["num"]]["results"][:3]:
            oc = r["outcome"]
            cls  = "win" if oc == "W" else "tie" if oc in ("T","NR") else "loss"
            verb = "beat" if oc == "W" else "tied with" if oc == "T" else "lost to"
            margin = (" by " + r["result"].lower().split("by",1)[1].strip()) if "by" in r["result"].lower() else ""
            sd = " ".join(r["date"].split(",")[-1].strip().split()[:2]) if "," in r["date"] else r["date"]
            items.append(item(cls, "Result",
                f'{t["label"]} {verb} {r["opponent"]}{margin} &mdash; {sd}'))

    # Player highlights
    for t in TEAMS:
        num = t["num"]
        bat = all_data[num]["batting"]
        bwl = all_data[num]["bowling"]
        if bat:
            b = bat[0]
            items.append(item("highlight", "&#9733; Player",
                f'{b["name"]} ({t["label"]}) &mdash; {b["runs"]} runs'
                + (f', {b["fifties"]} fifties' if b["fifties"] else "")
                + f', avg {b["avg"]:.2f}'))
        if bwl:
            bw = bwl[0]
            items.append(item("highlight", "&#9733; Player",
                f'{bw["name"]} ({t["label"]}) &mdash; {bw["wkts"]} wkts'
                + (f' incl {bw["bbf"]}' if bw["bbf"] != "0/0" else "")
                + f', econ {bw["econ"]:.2f}'))

    # Standings
    for t in TEAMS:
        stgds = all_data[t["num"]]["standings"]
        entry = next((s for s in stgds if f'Hollywood {t["num"]}' in s["team"]), None)
        if entry and entry["won"] > 0:
            try:
                nrr_f = float(entry["nrr"])
                nrr_s = f'+{nrr_f:.2f}' if nrr_f >= 0 else f'{nrr_f:.2f}'
            except ValueError:
                nrr_s = entry["nrr"]
            sfx = {1:"st",2:"nd",3:"rd"}.get(entry["pos"], "th")
            items.append(item("highlight", "Standings",
                f'{t["label"]} sit {entry["pos"]}{sfx} in {t["division"]} &mdash; '
                f'{entry["won"]}W {entry["lost"]}L, {entry["pts"]} pts, NRR {nrr_s}'))

    # Double for seamless loop
    doubled = "\n        ".join(items)
    return doubled + "\n        " + doubled


def replace_nth(html, pattern, replacement, n):
    matches = list(re.finditer(pattern, html, re.DOTALL))
    if len(matches) >= n:
        m = matches[n-1]
        return html[:m.start()] + replacement + html[m.end():]
    return html


def update_html(html: str, all_data: dict) -> str:
    # Date stamp
    today = datetime.now().strftime("%B %-d, %Y")
    html  = re.sub(r'Live standings as of [^.]+\.', f'Live standings as of {today}.', html)

    # Standings table
    new_rows = build_standings_rows({t["num"]: all_data[t["num"]]["standings"] for t in TEAMS})
    html = re.sub(
        r'(<tr style="background:#f0f4ff"><td colspan="8"[^>]*>2026 OD Div 1).*?'
        r'(</tr>\s*)(?=<!-- |<div|</tbody)',
        new_rows,
        html, flags=re.DOTALL, count=1
    )

    # Team arrays
    for t in TEAMS:
        num = t["num"]
        d   = all_data[num]
        if d["results"]:
            html = replace_nth(html, r'results:\[.*?\](?=,\s*\n\s*upcoming:)',
                               f'results:{fmt_results(d["results"])}', num)
        if d["batting"]:
            html = replace_nth(html, r'batting:\[.*?\](?=,\s*\n\s*bowling:)',
                               f'batting:{fmt_batting(d["batting"])}', num)
        if d["bowling"]:
            html = replace_nth(html, r'bowling:\[.*?\](?=,\s*\n\s*fielding:)',
                               f'bowling:{fmt_bowling(d["bowling"])}', num)

    # Ticker
    new_ticker = build_ticker(all_data)
    html = re.sub(
        r'(<div class="ticker-inner"[^>]*>)\s*.*?(\s*</div>\s*</div>\s*</div>\s*\n\s*<div class="stats-strip">)',
        rf'\g<1>\n        {new_ticker}\n      \g<2>',
        html, flags=re.DOTALL, count=1
    )

    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HCC weekly site updater")
    parser.add_argument("--input",   default="hollywoodcc.html")
    parser.add_argument("--output",  default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Run: pip install playwright && playwright install chromium")
        return

    all_data = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx  = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        page.set_default_timeout(PAGE_TIMEOUT)

        for t in TEAMS:
            log.info(f"\nScraping {t['name']} ({t['division']}) ...")
            all_data[t["num"]] = {
                "standings": scrape_points_table(page, t),
                "results":   scrape_team_results(page, t),
                "upcoming":  scrape_team_schedule(page, t),
                "batting":   scrape_batting(page, t),
                "bowling":   scrape_bowling(page, t),
            }

        browser.close()

    html     = input_path.read_text(encoding="utf-8")
    new_html = update_html(html, all_data)

    if args.dry_run:
        log.info("\nDry run — summary:")
        for t in TEAMS:
            d   = all_data[t["num"]]
            w   = sum(1 for r in d["results"] if r["outcome"] == "W")
            l   = sum(1 for r in d["results"] if r["outcome"] == "L")
            bat = f'{d["batting"][0]["name"]} {d["batting"][0]["runs"]}r' if d["batting"] else "–"
            bwl = f'{d["bowling"][0]["name"]} {d["bowling"][0]["wkts"]}w' if d["bowling"] else "–"
            print(f"  {t['name']}: {w}W {l}L | {len(d['upcoming'])} upcoming | bat: {bat} | bowl: {bwl}")
    else:
        output_path.write_text(new_html, encoding="utf-8")
        log.info(f"\n✓ Written: {output_path}")
        log.info(f"✓ Complete — {datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()
