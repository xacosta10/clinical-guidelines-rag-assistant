"""
Cleans Synthea CCDA XML files into plain-text patient documents,
ready for chunking and embedding in a RAG pipeline.

Usage:
    pip install beautifulsoup4 lxml
    python clean_ccda.py

Reads all .xml files from ccda_raw/ and writes cleaned .txt files to ccda_cleaned/,
one per patient, organized by section (Problems, Medications, Allergies, etc.)
"""

import re
from pathlib import Path
from bs4 import BeautifulSoup


def extract_patient_name(soup):
    patient_role = soup.find("patientRole")
    if patient_role is None:
        return "Unknown Patient"
    given = patient_role.find("given")
    family = patient_role.find("family")
    given = given.get_text(strip=True) if given else ""
    family = family.get_text(strip=True) if family else ""
    name = f"{given} {family}".strip()
    return name or "Unknown Patient"


def table_to_lines(table):
    """Turn a CCDA narrative table into readable 'Field: Value' lines."""
    lines = []
    headers = []
    thead = table.find("thead")
    if thead:
        header_row = thead.find("tr")
        if header_row:
            headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

    tbody = table.find("tbody") or table
    for row in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if not cells:
            continue
        if headers and len(headers) == len(cells):
            line = ", ".join(f"{h}: {c}" for h, c in zip(headers, cells) if c)
        else:
            line = ", ".join(c for c in cells if c)
        if line:
            lines.append("- " + line)
    return lines


def extract_narrative_text(text_tag):
    """Pull the human-readable narrative out of a CCDA <text> block, tables and all."""
    output_lines = []
    tables = text_tag.find_all("table")

    if tables:
        for table in tables:
            output_lines.extend(table_to_lines(table))
    else:
        raw = text_tag.get_text(separator=" ", strip=True)
        raw = re.sub(r"\s+", " ", raw)
        if raw:
            output_lines.append(raw)

    return "\n".join(output_lines)


def clean_ccda_file(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()

    soup = BeautifulSoup(content, "lxml-xml")
    patient_name = extract_patient_name(soup)

    section_blocks = []
    for section in soup.find_all("section"):
        title_tag = section.find("title")
        title = title_tag.get_text(strip=True) if title_tag else "Untitled Section"

        text_tag = section.find("text")
        if text_tag is None:
            continue

        section_text = extract_narrative_text(text_tag)
        # Skip empty or boilerplate-only sections (ignore trailing punctuation when checking)
        normalized = section_text.strip().lower().rstrip(".")
        if section_text.strip() and normalized not in (
            "no information available", "no known allergies", "none", "no known problems"
        ):
            section_blocks.append(f"## {title}\n{section_text}")

    return patient_name, section_blocks


def clean_all_ccda(input_dir="ccda_raw", output_dir="ccda_cleaned"):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    xml_files = sorted(input_dir.glob("*.xml"))
    if not xml_files:
        print(f"No .xml files found in {input_dir}/")
        return

    for filepath in xml_files:
        try:
            name, section_blocks = clean_ccda_file(filepath)
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
            out_path = output_dir / f"{safe_name}_{filepath.stem}.txt"

            full_text = f"# Patient Record: {name}\n\n" + "\n\n".join(section_blocks)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(full_text)

            print(f"Cleaned: {filepath.name} -> {out_path.name} ({len(section_blocks)} sections)")
        except Exception as e:
            print(f"Failed on {filepath.name}: {e}")


if __name__ == "__main__":
    clean_all_ccda()
