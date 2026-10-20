"""Download the lobbying filings behind Public Citizen's "AI Lobbyists by Quarter and Year".

The figure is Figure 1 of Public Citizen, "Generative Influence" (Mike Tanglis and Eileen
O'Grady, February 24, 2026), shown in POLISCI 158 Session 4 ("AI lobbying grew"). It counts
the lobbyists who reported lobbying on AI issues in each quarter and each year, 2020-2025.

Source
------
Quarterly lobbying reports (form LD-2) filed under the Lobbying Disclosure Act, read from
the LDA.gov REST API (https://lda.gov/api/v1/filings/). LDA.gov is the joint House-Senate
system that now serves the filings Public Citizen took from the House Clerk's site.

Method (after the report's methodology section)
------
1. Search the API, quarter by quarter, for filings whose lobbying-activity text mentions an
   AI-issue term. The report names artificial intelligence (or AI / A.I.), autonomous
   vehicles and systems, data centers, large language models and facial recognition, and
   says it also searched "variations of those words" and "a handful of other AI terms".
   Those are not listed, so a second search adds other autonomous/automated-vehicle
   wording (autonomous, automated vehicles, self-driving, driverless), machine learning
   and deepfakes. The output keeps both counts.
2. Keep quarterly reports (not registrations). When a report was amended, keep only the
   latest version for that registrant, client and quarter.
3. Keep the lobbying activities whose own description mentions a term (a filing can list
   several activities) and take the lobbyists listed on them. A lobbyist is a person,
   identified by first and last name, so someone who lobbies for several firms counts once.

Outputs
-------
data/ai_lobbying_activities.csv   one row per matching lobbying activity, with its lobbyists
data/ai_lobbyists_by_quarter.csv  unique lobbyists, clients and filings per quarter and year
data/raw/                         the API responses, gzipped, per quarter and search

Usage
-----
python get_data.py             download (skipping cached quarters), then build
python get_data.py --refresh   download everything again
python get_data.py --from-raw  rebuild the CSVs from data/raw/ only

LDA.gov throttles anonymous requests, so a full download takes about an hour. With a free
API key from https://lda.gov/api/register/ in the LDA_API_KEY environment variable it is
several times faster.
"""

import argparse
import gzip
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent / "data"
RAW = DATA / "raw"

API = "https://lda.gov/api/v1/filings/"
HEADERS = {"User-Agent": "ps158-reproduce get_data.py (course replication)"}
if os.environ.get("LDA_API_KEY"):
    HEADERS["Authorization"] = f"Token {os.environ['LDA_API_KEY']}"
YEARS = range(2020, 2027)
QUARTERS = {"first_quarter": "Q1", "second_quarter": "Q2", "third_quarter": "Q3", "fourth_quarter": "Q4"}

# Server-side full-text searches (the API accepts OR and minus, and does not match plurals).
# They only narrow the download to candidate filings; the regular expressions below decide
# which activities count. CORE holds the terms the report names; VARIANTS holds the
# "variations of those words" and other AI terms it mentions without listing, searched
# only in filings CORE did not already return.
CORE = ['"artificial intelligence"', "AI", '"A.I."', '"autonomous vehicle"', '"autonomous vehicles"',
        '"autonomous system"', '"autonomous systems"', '"data center"', '"data centers"', "datacenter",
        '"large language model"', '"facial recognition"']
VARIANTS = ["autonomous", '"automated vehicle"', '"automated vehicles"', '"automated driving"',
            '"self-driving"', "driverless", '"machine learning"', "deepfake", "deepfakes"]
SEARCHES = {
    "core": " OR ".join(CORE),
    "variants": " OR ".join(f"{v} " + " ".join(f"-{c}" for c in CORE) for v in VARIANTS),
}

TERM_PATTERNS = {
    "artificial intelligence": re.compile(r"artificial[\s-]+intelligence", re.I),
    # Upper-case AI or A.I. as a word, but not AI/AN (American Indian/Alaska Native).
    "AI": re.compile(r"(?<![A-Za-z0-9])A\.?I\.?(?![A-Za-z0-9])(?!\s*/\s*AN\b)"),
    "autonomous vehicles/systems": re.compile(r"\bautonomous[\s-]+(?:vehicle|system)s?\b", re.I),
    "data centers": re.compile(r"\bdata[\s-]?cent(?:er|re)s?\b", re.I),
    "large language models": re.compile(r"\blarge[\s-]+language[\s-]+models?\b", re.I),
    "facial recognition": re.compile(r"\bfacial[\s-]+recognition\b", re.I),
    # Variants
    "other autonomous/automated driving": re.compile(
        r"\bautonomous\b|\bautomated[\s-]+(?:vehicle|driving)s?\b|\bself[\s-]?driving\b|\bdriverless\b", re.I),
    "machine learning": re.compile(r"\bmachine[\s-]+learning\b", re.I),
    "deepfakes": re.compile(r"\bdeep[\s-]?fakes?\b", re.I),
}
CORE_TERMS = list(TERM_PATTERNS)[:6]


def matched_terms(text):
    return [name for name, pattern in TERM_PATTERNS.items() if pattern.search(text or "")]


def slim(filing):
    """The fields of a filing this analysis uses (the API returns many more)."""
    return {
        "filing_uuid": filing["filing_uuid"],
        "filing_type": filing["filing_type"],
        "filing_type_display": filing["filing_type_display"],
        "filing_year": filing["filing_year"],
        "filing_period": filing["filing_period"],
        "dt_posted": filing["dt_posted"],
        "registrant_id": filing["registrant"]["id"],
        "registrant": filing["registrant"]["name"],
        "client_id": filing["client"]["id"],
        "client": filing["client"]["name"],
        "activities": [{
            "issue_code": a["general_issue_code"],
            "description": a["description"],
            "lobbyists": [{"id": l["lobbyist"]["id"], "first_name": l["lobbyist"]["first_name"],
                           "last_name": l["lobbyist"]["last_name"]} for l in a["lobbyists"]],
        } for a in filing["lobbying_activities"]],
    }


def get(session, url, params=None):
    """GET with retries; LDA.gov throttles anonymous clients and sometimes drops connections."""
    for attempt in range(8):
        try:
            r = session.get(url, params=params, headers=HEADERS, timeout=120)
        except (requests.ConnectionError, requests.Timeout) as error:
            print(f"  {type(error).__name__}, retrying")
            time.sleep(min(60, 2 ** attempt))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            wait = float(r.headers.get("Retry-After", 0)) or min(60, 2 ** attempt)
            print(f"  HTTP {r.status_code}, waiting {wait:.0f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def download(refresh=False):
    RAW.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        for name, search in SEARCHES.items():
            for year in YEARS:
                for period, quarter in QUARTERS.items():
                    path = RAW / f"lda_{year}_{quarter}{'' if name == 'core' else '_' + name}.json.gz"
                    if path.exists() and not refresh:
                        continue
                    params = {"filing_year": year, "filing_period": period, "filing_specific_lobbying_issues": search,
                              "ordering": "dt_posted", "page_size": 25}
                    body = get(session, API, params)
                    if not body["count"]:
                        print(f"{year} {quarter} {name}: no filings yet")
                        continue
                    expected, filings = body["count"], [slim(f) for f in body["results"]]
                    while body["next"]:
                        body = get(session, body["next"])
                        filings += [slim(f) for f in body["results"]]
                    print(f"{year} {quarter} {name}: {len(filings):,} candidate filings (API count {expected:,})")
                    with gzip.open(path, "wt", encoding="utf-8") as f:
                        json.dump({"year": year, "quarter": quarter, "search": search, "count": expected,
                                   "filings": filings}, f)


def person(lobbyist):
    """First name (first word only) and last name, upper case, without punctuation."""
    first = re.sub(r"[^A-Z ]", "", (lobbyist["first_name"] or "").upper()).split()
    last = re.sub(r"[^A-Z ]", "", (lobbyist["last_name"] or "").upper()).split()
    return " ".join(first[:1] + last)


def build():
    filings = {}
    for path in sorted(RAW.glob("lda_*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for filing in json.load(f)["filings"]:
                filings[filing["filing_uuid"]] = filing
    df = pd.DataFrame(filings.values())
    print("filing types found:", df.groupby(["filing_type", "filing_type_display"]).size().to_dict())

    # Quarterly reports, amendments and terminations; registrations have no quarter
    df = df[df.filing_period.isin(QUARTERS) & ~df.filing_type_display.str.contains("Registration")]
    # Latest version of each registrant-client-quarter report
    df = (df.sort_values("dt_posted")
            .drop_duplicates(["registrant_id", "client_id", "filing_year", "filing_period"], keep="last"))

    rows = []
    for f in df.itertuples():
        for i, a in enumerate(f.activities):
            terms = matched_terms(a["description"])
            if not terms or not a["lobbyists"]:
                continue
            rows.append({
                "year": f.filing_year,
                "quarter": QUARTERS[f.filing_period],
                "filing_uuid": f.filing_uuid,
                "filing_type": f.filing_type_display,
                "dt_posted": f.dt_posted,
                "registrant": f.registrant,
                "client_id": f.client_id,
                "client": f.client,
                "activity": i + 1,
                "issue_code": a["issue_code"],
                "matched_terms": "; ".join(terms),
                "lobbyists": "; ".join(sorted({person(l) for l in a["lobbyists"]})),
                "lobbyist_ids": "; ".join(sorted({str(l["id"]) for l in a["lobbyists"]})),
                "description": " ".join((a["description"] or "").split()),
            })
    acts = pd.DataFrame(rows).sort_values(["year", "quarter", "registrant", "client", "activity"])
    acts.to_csv(DATA / "ai_lobbying_activities.csv", index=False)

    people = acts.assign(lobbyist=acts.lobbyists.str.split("; ")).explode("lobbyist")
    people = people[people.lobbyist != ""]
    named = people[people.matched_terms.str.split("; ").map(lambda t: bool(set(t) & set(CORE_TERMS)))]
    ids = acts.assign(lobbyist_id=acts.lobbyist_ids.str.split("; ")).explode("lobbyist_id")

    def summarise(keys):
        out = people.groupby(keys).agg(lobbyists=("lobbyist", "nunique"), clients=("client_id", "nunique"),
                                      filings=("filing_uuid", "nunique"))
        out["lobbyists_named_terms"] = named.groupby(keys).lobbyist.nunique()
        out["lobbyist_records"] = ids.groupby(keys).lobbyist_id.nunique()
        out["data_center_lobbyists"] = (people[people.matched_terms.str.contains("data centers")]
                                        .groupby(keys).lobbyist.nunique())
        return out.fillna(0).astype(int).reset_index()

    summary = pd.concat([summarise(["year", "quarter"]), summarise(["year"]).assign(quarter="Year")])
    summary = summary.sort_values(["year", "quarter"])[
        ["year", "quarter", "lobbyists", "lobbyists_named_terms", "lobbyist_records", "clients", "filings",
         "data_center_lobbyists"]]
    summary.to_csv(DATA / "ai_lobbyists_by_quarter.csv", index=False)
    print(f"{len(acts):,} matching activities in {acts.filing_uuid.nunique():,} reports")
    print(summary.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--refresh", action="store_true", help="download everything again")
    parser.add_argument("--from-raw", action="store_true", help="rebuild from data/raw/ only")
    args = parser.parse_args()
    if not args.from_raw:
        download(refresh=args.refresh)
    build()


if __name__ == "__main__":
    main()
