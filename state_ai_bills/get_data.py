"""Download data on AI legislation and policy, and write tidy CSVs to data/.

Sources
-------
NCSL (National Conference of State Legislatures)
    2019-2024  NCSL's annual "Artificial Intelligence ... Legislation" pages (HTML tables).
    2025-      NCSL's Artificial Intelligence Legislation Database (powered by LexisNexis
               State Net), queried for every year in its Year menu. These records also carry
               sponsors and a dated action history. NCSL updates the database monthly.
Public Citizen
    Tracker of state legislation on deepfakes in elections.
OECD.AI
    Policy Navigator of national and international AI policy initiatives, read from the
    JSON API behind https://oecd.ai/en/dashboards/policy-initiatives.

Outputs
-------
data/ncsl_ai_bills.csv                      one row per bill, 2019 onward
data/ncsl_ai_bill_history.csv               dated legislative actions, 2025 onward
data/public_citizen_election_deepfakes.csv  one row per bill
data/oecd_ai_policy_initiatives.csv         one row per initiative
data/raw/                                   the pages and JSON the CSVs were parsed from

Usage
-----
python get_data.py             download everything, then parse
python get_data.py --from-raw  re-parse the snapshots in data/raw/ without downloading
"""

import argparse
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

DATA = Path(__file__).resolve().parent / "data"
RAW = DATA / "raw"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ps158-reproduce get_data.py)"}

NCSL_STATIC_PAGES = {
    "ncsl_static_2019-2022": "https://www.ncsl.org/technology-and-communication/legislation-related-to-artificial-intelligence",
    "ncsl_static_2023": "https://www.ncsl.org/technology-and-communication/artificial-intelligence-2023-legislation",
    "ncsl_static_2024": "https://www.ncsl.org/technology-and-communication/artificial-intelligence-2024-legislation",
}
NCSL_DB_URL = "https://www.ncsl.org/financial-services/artificial-intelligence-legislation-database"
PUBLIC_CITIZEN_URL = "https://www.citizen.org/article/tracker-legislation-on-deepfakes-in-elections/"
OECD_API_URL = "https://api.oecd.ai/policy-initiatives/public"

# The topic tags used by NCSL's database. The 2019-2024 pages use the same labels, with a
# few spelling variants and some cells that run two labels together without a separator.
NCSL_TOPICS = [
    "Appropriations", "Audit", "Child Pornography", "Criminal Use", "Cybersecurity",
    "Deepfake", "Education Use", "Education/Training", "Effect on Labor/Employment",
    "Elections", "Energy", "Government Use", "Health Use", "Housing", "Impact Assessment",
    "Judicial Use", "Notification", "Oversight/Governance", "Personhood",
    "Private Right of Action", "Private Sector Use", "Provenance", "Responsible Use",
    "Studies", "Taxes",
]
TOPIC_ALIASES = {"private sector": "Private Sector Use", "impact assessments": "Impact Assessment"}

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "N. Mariana Islands", "US": "U.S. Congress",
}
STATE_CODES = {name.lower(): code for code, name in STATES.items()}
STATE_CODES.update({"northern mariana islands": "MP", "virgin islands": "VI", "a. samoa": "AS"})

MONTH = r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def clean(text):
    """Unescape HTML entities, drop tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return " ".join(text.replace("\xa0", " ").split())


def split_topics(text):
    """Map an NCSL category or topics cell to a '; '-joined list of NCSL_TOPICS labels."""
    found = []
    for piece in re.split(r"[;,]", text):
        rest = " ".join(piece.split()).lower()
        if rest in TOPIC_ALIASES:
            found.append(TOPIC_ALIASES[rest])
            continue
        for topic in sorted(NCSL_TOPICS, key=len, reverse=True):
            if topic.lower() in rest:
                found.append(topic)
                rest = rest.replace(topic.lower(), " ")
        rest = rest.strip()
        if rest in TOPIC_ALIASES:
            found.append(TOPIC_ALIASES[rest])
        elif rest:
            print(f"  warning: unrecognised NCSL topic {piece.strip()!r}, kept as is")
            found.append(piece.strip())
    return "; ".join(dict.fromkeys(found))


def status_group(status):
    s = status.lower()
    for prefix, group in [("enacted", "Enacted"), ("adopted", "Adopted"), ("veto", "Vetoed"),
                          ("fail", "Failed"), ("to governor", "To Governor"), ("pending", "Pending")]:
        if s.startswith(prefix):
            return group
    return "Other" if s else ""


def fetch(session, url, **kwargs):
    r = session.get(url, headers=HEADERS, timeout=120, **kwargs)
    r.raise_for_status()
    return r


# --------------------------------------------------------------------------- NCSL, 2019-2024

def download_ncsl_static(session):
    for name, url in NCSL_STATIC_PAGES.items():
        print(f"NCSL page {url}")
        (RAW / f"{name}.html").write_text(fetch(session, url).text, encoding="utf-8")


def parse_ncsl_static():
    rows = []
    for name, url in NCSL_STATIC_PAGES.items():
        soup = BeautifulSoup((RAW / f"{name}.html").read_text(encoding="utf-8"), "html.parser")
        for table in soup.find_all("table"):
            header = [clean(c.get_text(" ")) for c in table.find("tr").find_all(["td", "th"])]
            if "Bill Number" not in header:
                continue
            # The 2019-2022 page holds one table per year under a "20XX Legislation" heading.
            heading = table.find_previous(["h2", "h3"])
            year = re.search(r"20\d\d", heading.get_text() if heading else "") or re.search(r"20\d\d", url)
            year = int(year.group())
            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all(["td", "th"])
                if len(cells) < 6:
                    continue
                bill = clean(cells[1].get_text(" "))
                # Placeholder rows: "None", "Not available", "No 2024 legislative session"
                if not bill or bill in ("None", "Not available") or bill.startswith("No "):
                    continue
                state = clean(cells[0].get_text(" "))
                status = clean(cells[3].get_text(" ")).replace("–", "-")
                link = cells[1].find("a")
                rows.append({
                    "year": year,
                    "state": state,
                    "state_code": STATE_CODES.get(state.lower(), ""),
                    "bill_number": bill,
                    "title": clean(cells[2].get_text(" ")),
                    "status": status,
                    "status_group": status_group(status),
                    "topics": split_topics(clean(cells[5].get_text(" "))),
                    "summary": clean(cells[4].get_text(" ")),
                    "bill_url": link["href"] if link else "",
                    "source": "NCSL annual page",
                })
    return rows


# --------------------------------------------------------------------------- NCSL, 2025 on

def download_ncsl_database(session):
    """POST one search per year (all states, all topics, any status) to NCSL's database.

    The database is an ASP.NET form, so each search replays the page's hidden form state.
    All matching bills come back on one page (about 5 MB for a full year).
    """
    page = fetch(session, NCSL_DB_URL).text
    form = BeautifulSoup(page, "html.parser").find("form")

    def control(suffix):  # control names look like dnn$ctr34167$StateNetDB$ddlYear
        return form.find(attrs={"name": re.compile(re.escape("$StateNetDB$" + suffix) + "$")})["name"]

    years = [o["value"] for o in form.find("select", attrs={"name": control("ddlYear")}).find_all("option")
             if o["value"].isdigit()]
    for year in sorted(years):
        print(f"NCSL database, {year} (all states, topics and statuses)")
        form = BeautifulSoup(fetch(session, NCSL_DB_URL).text, "html.parser").find("form")
        data = {i["name"]: i.get("value", "") for i in form.find_all("input", type="hidden") if i.get("name")}
        data.update({
            control("ckBxAllStates"): "on", control("ckBxAllTopics"): "on",
            control("ddlYear"): year, control("ddlStatus"): "NA",
            control("txtKeyword"): "", control("txtBillNumber"): "", control("txtAuthor"): "",
            control("btnSearch"): "Search",
        })
        r = session.post(NCSL_DB_URL, data=data, headers=HEADERS, timeout=600)
        r.raise_for_status()
        # Drop the ~1 MB of encoded form state; the bill records are plain HTML.
        text = re.sub(r'(id="__VIEWSTATE" value=")[^"]*', r"\1", r.text)
        (RAW / f"ncsl_database_{year}.html").write_text(text, encoding="utf-8")


RECORD_START = re.compile(r"<div>\s*<a href='([^']*)'[^>]*>([^<]+)</a><br\s*/>\s*(\d{4})<br\s*/>")
SIGNED = re.compile(r"SIGNED BY GOVERNOR|APPROVED BY GOVERNOR|BECAME LAW|WITHOUT .*SIGNATURE|ENACTED", re.I)
CHAPTERED = re.compile(r"CHAPTER|ACT NO|PUBLIC ACT|SESSION LAW", re.I)


def field(block, label, end=r"<br"):
    m = re.search(rf"<b>\s*{label}:?\s*</b>(.*?){end}", block, re.S)
    return m.group(1) if m else ""


def parse_ncsl_database():
    bills, history = [], []
    for path in sorted(RAW.glob("ncsl_database_*.html")):
        text = path.read_text(encoding="utf-8")
        listing = text[text.find("StateNetDB_linkList"):]
        expected = re.search(r"Total Bills:\s*(\d+)", text)
        starts = list(RECORD_START.finditer(listing))
        for i, m in enumerate(starts):
            block = listing[m.end(): starts[i + 1].start() if i + 1 < len(starts) else len(listing)]
            url, label, year = m.group(1), clean(m.group(2)), int(m.group(3))
            code = re.search(r"ID:bill:([A-Z]{2})", url)
            code = code.group(1) if code else label.split()[0]
            bill = label[len(code):].strip() if label.startswith(code) else label
            title = re.search(r'<div style="font-weight: bold;">(.*?)<br', block, re.S)
            author = field(block, "Author")
            primary, _, additional = author.partition("Additional Authors:")
            status = clean(field(block, "Status"))
            last = clean(field(block, "Date of Last Action"))
            last_date, _, last_action = last.partition(" - ")
            hist = re.search(r'class="historyList"[^>]*>(.*?)</div>', block, re.S)
            events = []
            for line in re.split(r"<br\s*/?>", hist.group(1) if hist else ""):
                d, _, action = clean(line).partition(" - ")
                if re.fullmatch(r"\d\d/\d\d/\d{4}", d):
                    events.append((datetime.strptime(d, "%m/%d/%Y").date(), action))
            introduced = next((d for d, a in events if re.search(r"INTRODUCED|PREFILED", a, re.I)),
                              events[0][0] if events else None)
            enacted = None
            if status_group(status) == "Enacted":
                enacted = (next((d for d, a in events if SIGNED.search(a)), None)
                           or next((d for d, a in events if CHAPTERED.search(a)), None)
                           or (datetime.strptime(last_date, "%m/%d/%Y").date() if last_date else None))
            bill_id = f"{code}-{year}-{bill.replace(' ', '')}"
            bills.append({
                "year": year,
                "state": STATES.get(code, code),
                "state_code": code,
                "bill_number": bill,
                "title": clean(title.group(1)) if title else "",
                "status": status,
                "status_group": status_group(status),
                "topics": split_topics(clean(field(block, "Topics"))),
                "summary": clean(field(block, "Summary", end=r'<div id="divClickforHistory"')),
                "author": clean(primary.replace("<b>", "")),
                "additional_authors": clean(additional),
                "date_introduced": introduced,
                "date_enacted": enacted,
                "date_last_action": datetime.strptime(last_date, "%m/%d/%Y").date() if last_date else None,
                "last_action": last_action,
                "bill_url": url,
                "source": "NCSL database",
            })
            history += [{"bill_id": bill_id, "date": d, "action": a} for d, a in events]
        if expected and int(expected.group(1)) != len(starts):
            print(f"  warning: {path.name} reports {expected.group(1)} bills, parsed {len(starts)}")
    return bills, history


def build_ncsl():
    bills, history = parse_ncsl_database()
    df = pd.DataFrame(parse_ncsl_static() + bills)
    df.insert(0, "bill_id", df.state_code.where(df.state_code != "", df.state) + "-"
              + df.year.astype(str) + "-" + df.bill_number.str.replace(" ", ""))
    dupes = df.bill_id.duplicated()
    if dupes.any():
        print(f"  dropping {dupes.sum()} duplicate NCSL rows")
        df = df[~dupes]
    df = df.sort_values(["year", "state", "bill_number"])
    df.to_csv(DATA / "ncsl_ai_bills.csv", index=False)
    pd.DataFrame(history).to_csv(DATA / "ncsl_ai_bill_history.csv", index=False)
    print(f"NCSL: {len(df)} bills, {len(history)} history entries")
    print(df.groupby("year").agg(bills=("bill_id", "size"),
                                 enacted=("status_group", lambda s: (s == "Enacted").sum())).to_string())


# --------------------------------------------------------------------------- Public Citizen

def ym(event):
    """'Enacted Sept. 2024' -> '2024-09'; 'Passed House 2026' -> '2026'; no date -> ''."""
    m = re.search(MONTH + r"\s+(\d{4})", event)
    if m:
        return f"{m.group(2)}-{MONTHS[m.group(1)]:02d}"
    m = re.search(r"\b(20\d\d)\b", event)
    return m.group(1) if m else ""


def parse_public_citizen_status(text):
    """Split a free-text status ('Introduced Jan. 2025, Passed House Mar. 2025, Failed ...')."""
    events = [e.strip() for e in re.split(r"[,;]", text) if e.strip()]
    introduced = next((ym(e) for e in events if "introduced" in e.lower()), "")
    enacted = next((ym(e) for e in events if "enacted" in e.lower()), "")
    rules = [("Enacted", r"enacted"), ("Vetoed", r"vetoed"),
             ("Failed", r"failed|indefinitely postponed|senate tabled"),
             ("Superseded", r"incorporated|integrated|substituted|re-intro|reprint|^see "),
             ("Provision removed", r"provision removed")]
    outcome, outcome_ym = "Pending", ym(events[-1]) if events else ""
    for label, pattern in rules:
        hit = next((e for e in reversed(events) if re.search(pattern, e, re.I)), None)
        if hit:
            outcome, outcome_ym = label, ym(hit)
            break
    return {"introduced_ym": introduced, "enacted_ym": enacted, "outcome": outcome, "outcome_ym": outcome_ym}


def download_public_citizen(session):
    print(f"Public Citizen {PUBLIC_CITIZEN_URL}")
    (RAW / "public_citizen_election_deepfakes.html").write_text(
        fetch(session, PUBLIC_CITIZEN_URL).text, encoding="utf-8")


def build_public_citizen():
    soup = BeautifulSoup((RAW / "public_citizen_election_deepfakes.html").read_text(encoding="utf-8"),
                         "html.parser")
    updated = re.search(r"Last updated:?\s*([A-Z][a-z]+\.? \d{1,2}, \d{4})", soup.get_text(" "))
    rows = []
    for tr in soup.find("table", id=re.compile("^tablepress")).tbody.find_all("tr"):
        state, bill, status = tr.find_all("td")[:3]
        link = bill.find("a")
        text = clean(status.get_text(" "))
        rows.append({"state": clean(state.get_text(" ")),
                     "state_code": STATE_CODES.get(clean(state.get_text(" ")).lower(), ""),
                     "bill_number": clean(bill.get_text(" ")),
                     "status_text": text,
                     **parse_public_citizen_status(text),
                     "bill_url": link["href"] if link else ""})
    df = pd.DataFrame(rows)
    df.to_csv(DATA / "public_citizen_election_deepfakes.csv", index=False)
    print(f"Public Citizen: {len(df)} bills (page last updated {updated.group(1) if updated else 'unknown'})")
    print(df.outcome.value_counts().to_string())


# --------------------------------------------------------------------------- OECD.AI

# Contributor names and e-mail addresses are in the API but are not needed, so they are
# dropped before anything is written to disk.
OECD_PERSONAL = {"createdByEmail", "createdByName", "updatedByEmail", "updatedByName",
                 "publishedByEmail", "publishedByName"}


def download_oecd(session):
    records, page, last = [], 1, 1
    while page <= last:
        r = fetch(session, OECD_API_URL, params={"publishedOnly": "true", "perPage": 100, "page": page})
        body = r.json()
        last = body["lastPage"]
        records += [{k: v for k, v in rec.items() if k not in OECD_PERSONAL} for rec in body["data"]]
        print(f"OECD.AI page {page}/{last}", end="\r")
        page += 1
        time.sleep(0.5)
    print(f"\nOECD.AI: {len(records)} of {body['total']} initiatives downloaded")
    (RAW / "oecd_ai_policy_initiatives.json").write_text(json.dumps(records, ensure_ascii=False),
                                                        encoding="utf-8")


def names(items):
    return "; ".join(i["name"] for i in items or [])


def build_oecd():
    records = json.loads((RAW / "oecd_ai_policy_initiatives.json").read_text(encoding="utf-8"))
    rows = []
    for rec in records:
        country, org = rec.get("gaiinCountry") or {}, rec.get("intergovernmentalOrganisation") or {}
        itype = rec.get("initiativeType") or {}
        rows.append({
            "id": rec["id"],
            "name": rec["englishName"],
            "original_name": rec["originalName"],
            "jurisdiction": country.get("name") or org.get("name"),
            "jurisdiction_code": country.get("code"),
            "jurisdiction_type": "International organisation" if org and not country else country.get("category"),
            # Other country and organisation metadata in the API (income group, language,
            # founding year, ...) is placeholder text, so only the region is kept.
            "region": country.get("region"),
            "category": rec["category"],
            "initiative_type": itype.get("name"),
            "initiative_group": itype.get("displayGroup"),
            "status": rec["status"],
            "binding": rec["extentBinding"],
            "start_year": rec["startYear"],
            "end_year": rec["endYear"],
            "tags": names(rec.get("tags")),
            "ai_principles": names(rec.get("principles")),
            "target_sectors": names(rec.get("targetSectors")),
            "description": clean(rec["description"]),
            "created_at": rec["createdAt"],
            "updated_at": rec["updatedAt"],
            "url": f"https://oecd.ai/en/dashboards/policy-initiatives/{rec['slug']}",
        })
    df = pd.DataFrame(rows).sort_values(["jurisdiction", "start_year", "name"])
    df.to_csv(DATA / "oecd_ai_policy_initiatives.csv", index=False)
    print(f"OECD.AI: {len(df)} initiatives from {df.jurisdiction.nunique()} jurisdictions")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--from-raw", action="store_true", help="re-parse data/raw/ without downloading")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    if not args.from_raw:
        with requests.Session() as session:
            download_ncsl_static(session)
            download_ncsl_database(session)
            download_public_citizen(session)
            download_oecd(session)
    build_ncsl()
    build_public_citizen()
    build_oecd()


if __name__ == "__main__":
    main()
