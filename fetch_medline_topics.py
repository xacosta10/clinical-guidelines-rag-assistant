"""
Extracts unique SNOMED CT codes from the Problems sections of cleaned
CCDA patient files, then looks up each one against MedlinePlus Connect
(NLM's free public web service) to pull a matching plain-language
patient-education summary.

Usage:
    pip install requests
    python3 fetch_medline_topics.py

Reads all .txt files from ccda_cleaned/ and writes one .txt file per
matched topic into medline_topics/, ready to feed into chunk_documents.py
alongside your patient records.
"""

import json
import re
import time
from pathlib import Path

import requests

# SNOMED CT's official OID, required by MedlinePlus Connect to know
# which code system we're sending it.
SNOMED_OID = "2.16.840.1.113883.6.96"

CONNECT_URL = "https://connect.medlineplus.gov/service"

# Be polite to a free public NLM service. 1 request/second is well
# under any reasonable rate limit for ~50-100 unique codes.
DELAY_SECONDS = 1.0

# Matches lines like:
#   "Description: Chronic sinusitis (disorder), Code: SNOMED-CT 40055000"
CODE_PATTERN = re.compile(
    r"Description:\s*(.+?),\s*Code:\s*SNOMED-CT\s*(\d+)"
)


def extract_codes(input_dir="ccda_cleaned"):
    """Scan every cleaned patient file and pull out every unique
    (description, snomed_code) pair mentioned anywhere in the file."""
    input_dir = Path(input_dir)
    txt_files = sorted(input_dir.glob("*.txt"))

    if not txt_files:
        print(f"No .txt files found in {input_dir}/")
        return {}

    codes = {}  # code -> description (first description we see wins)
    for filepath in txt_files:
        text = filepath.read_text(encoding="utf-8")
        for match in CODE_PATTERN.finditer(text):
            description, code = match.group(1).strip(), match.group(2).strip()
            if code not in codes:
                codes[code] = description

    return codes


def fetch_medline_topic(code, description):
    """Query MedlinePlus Connect for a single SNOMED code.
    Returns a dict with title/summary/url, or None if no match found."""
    params = {
        "mainSearchCriteria.v.cs": SNOMED_OID,
        "mainSearchCriteria.v.c": code,
        "mainSearchCriteria.v.dn": description,
        "informationRecipient.languageCode.c": "en",
        "knowledgeResponseType": "application/json",
    }

    try:
        response = requests.get(CONNECT_URL, params=params, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"  Request failed for {code} ({description}): {e}")
        return None

    try:
        data = response.json()
    except json.JSONDecodeError:
        print(f"  Could not parse response for {code} ({description})")
        return None

    entries = data.get("feed", {}).get("entry", [])
    if not entries:
        return None

    # Take the first (most relevant) matching topic
    entry = entries[0]
    title = entry.get("title", {}).get("_value", "Untitled topic")

    summary_obj = entry.get("summary", {})
    summary = summary_obj.get("_value", "") if summary_obj else ""
    # Strip any HTML tags MedlinePlus sometimes includes in summaries
    summary = re.sub(r"<[^>]+>", "", summary).strip()

    link = ""
    links = entry.get("link", [])
    if links:
        link = links[0].get("href", "")

    return {"title": title, "summary": summary, "url": link}


def safe_filename(text):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:80]


def fetch_all_topics(output_dir="medline_topics"):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    codes = extract_codes()
    if not codes:
        return

    print(f"Found {len(codes)} unique SNOMED codes across your patient files.\n")

    matched = 0
    unmatched = []

    for i, (code, description) in enumerate(sorted(codes.items()), 1):
        print(f"[{i}/{len(codes)}] Looking up {code} ({description})...")
        topic = fetch_medline_topic(code, description)

        if topic is None:
            unmatched.append((code, description))
            print("  No MedlinePlus match found.")
        else:
            matched += 1
            out_name = f"{safe_filename(description)}_{code}.txt"
            out_path = output_dir / out_name
            content = (
                f"# {topic['title']}\n\n"
                f"Source: MedlinePlus (medlineplus.gov)\n"
                f"Matched condition: {description} (SNOMED-CT {code})\n"
                f"Link: {topic['url']}\n\n"
                f"{topic['summary']}"
            )
            out_path.write_text(content, encoding="utf-8")
            print(f"  Saved: {out_name}")

        # Be a good citizen of the free service
        if i < len(codes):
            time.sleep(DELAY_SECONDS)

    print(f"\nDone. {matched} topics saved to {output_dir}/, {len(unmatched)} codes had no match.")
    if unmatched:
        print("\nUnmatched codes (may need a more general search term or don't have a MedlinePlus page):")
        for code, description in unmatched:
            print(f"  - {description} (SNOMED-CT {code})")


if __name__ == "__main__":
    fetch_all_topics()
