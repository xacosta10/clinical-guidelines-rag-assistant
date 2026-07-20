"""
Splits cleaned patient text files AND MedlinePlus topic files into
chunks for embedding.

Two source types are handled differently:

1. Patient records (ccda_cleaned/): chunked by section first (Problems,
   Medications, Encounters, etc.), since each section is already a
   natural semantic boundary. Long sections get split further into
   overlapping word-based chunks.

2. MedlinePlus topics (medline_topics/): these don't have the same
   '## Section' structure, so they're chunked purely by word count
   with overlap, after pulling out the title/metadata header.

Usage:
    python3 chunk_documents.py

Reads all .txt files from ccda_cleaned/ and medline_topics/ and writes
a single chunks.json file containing every chunk plus its source
metadata, tagged with source_type so you can tell them apart later.
"""

import json
import re
from pathlib import Path

# Target chunk size in words (roughly maps to ~500-800 tokens) and
# how many words of overlap to carry between consecutive chunks of
# the same long section, so context isn't lost at a cut point.
MAX_WORDS = 450
OVERLAP_WORDS = 80


# ---------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------

def split_long_section(text, max_words=MAX_WORDS, overlap_words=OVERLAP_WORDS):
    """Break a long section into overlapping word-based chunks."""
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + max_words
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        if end >= len(words):
            break
        start = end - overlap_words  # step back so chunks overlap

    return chunks


# ---------------------------------------------------------------
# Patient records (ccda_cleaned/)
# ---------------------------------------------------------------

def parse_sections(text):
    """Split a cleaned patient file into (title, body) pairs using the
    '## ' section headers written by clean_ccda.py."""
    parts = re.split(r"\n## ", text)
    sections = []

    # The first part contains the "# Patient Record: Name" line before
    # any "## " header, so it's handled separately, not as a section.
    for part in parts[1:]:
        lines = part.split("\n", 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        if body:
            sections.append((title, body))

    return sections


def get_patient_name(text):
    match = re.search(r"# Patient Record: (.+)", text)
    return match.group(1).strip() if match else "Unknown Patient"


def chunk_patient_records(input_dir, chunk_id_start=0):
    input_dir = Path(input_dir)
    txt_files = sorted(input_dir.glob("*.txt"))

    chunks = []
    chunk_id = chunk_id_start

    if not txt_files:
        print(f"No .txt files found in {input_dir}/")
        return chunks, chunk_id

    for filepath in txt_files:
        text = filepath.read_text(encoding="utf-8")
        patient_name = get_patient_name(text)
        sections = parse_sections(text)

        for section_title, section_body in sections:
            pieces = split_long_section(section_body)
            for piece in pieces:
                chunks.append({
                    "chunk_id": chunk_id,
                    "source_type": "patient_record",
                    "patient_name": patient_name,
                    "source_file": filepath.name,
                    "section": section_title,
                    "text": piece,
                    "word_count": len(piece.split())
                })
                chunk_id += 1

    print(f"Processed {len(txt_files)} patient files into "
          f"{len(chunks)} chunks")
    return chunks, chunk_id


# ---------------------------------------------------------------
# MedlinePlus topics (medline_topics/)
# ---------------------------------------------------------------

# Matches the header block written by fetch_medline_topics.py:
#   # Fibromyalgia
#
#   Source: MedlinePlus (medlineplus.gov)
#   Matched condition: Primary fibromyalgia syndrome (SNOMED-CT 95417003)
#   Link: https://medlineplus.gov/fibromyalgia.html?...
#
#   <body text follows>
TITLE_PATTERN = re.compile(r"^#\s*(.+)")
CONDITION_PATTERN = re.compile(r"Matched condition:\s*(.+?)\s*\(SNOMED-CT\s*(\d+)\)")
LINK_PATTERN = re.compile(r"Link:\s*(\S+)")


def parse_medline_file(text):
    """Pull title, matched condition, SNOMED code, link, and body text
    out of a MedlinePlus topic file."""
    lines = text.split("\n")

    title_match = TITLE_PATTERN.match(lines[0]) if lines else None
    title = title_match.group(1).strip() if title_match else "Untitled Topic"

    condition_match = CONDITION_PATTERN.search(text)
    condition = condition_match.group(1).strip() if condition_match else ""
    snomed_code = condition_match.group(2).strip() if condition_match else ""

    link_match = LINK_PATTERN.search(text)
    link = link_match.group(1).strip() if link_match else ""

    # Body is everything after the header block (after the first blank
    # line that follows the "Link:" line).
    if link_match:
        body_start = text.index(link_match.group(0)) + len(link_match.group(0))
        body = text[body_start:].strip()
    else:
        # Fallback: just drop the first line (title) if header parsing failed
        body = "\n".join(lines[1:]).strip()

    return title, condition, snomed_code, link, body


def chunk_medline_topics(input_dir, chunk_id_start=0):
    input_dir = Path(input_dir)
    txt_files = sorted(input_dir.glob("*.txt"))

    chunks = []
    chunk_id = chunk_id_start

    if not txt_files:
        print(f"No .txt files found in {input_dir}/ (skipping MedlinePlus topics)")
        return chunks, chunk_id

    for filepath in txt_files:
        text = filepath.read_text(encoding="utf-8")
        title, condition, snomed_code, link, body = parse_medline_file(text)

        if not body:
            continue

        pieces = split_long_section(body)
        for piece in pieces:
            chunks.append({
                "chunk_id": chunk_id,
                "source_type": "medline_topic",
                "topic_title": title,
                "matched_condition": condition,
                "snomed_code": snomed_code,
                "source_file": filepath.name,
                "link": link,
                "text": piece,
                "word_count": len(piece.split())
            })
            chunk_id += 1

    print(f"Processed {len(txt_files)} MedlinePlus topic files into "
          f"{len(chunks)} chunks")
    return chunks, chunk_id


# ---------------------------------------------------------------
# Combine both sources
# ---------------------------------------------------------------

def chunk_all_documents(
    ccda_dir="ccda_cleaned",
    medline_dir="medline_topics",
    output_file="chunks.json"
):
    patient_chunks, next_id = chunk_patient_records(ccda_dir, chunk_id_start=0)
    medline_chunks, next_id = chunk_medline_topics(medline_dir, chunk_id_start=next_id)

    all_chunks = patient_chunks + medline_chunks

    if not all_chunks:
        print("No chunks produced. Check that ccda_cleaned/ and/or "
              "medline_topics/ contain .txt files.")
        return

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2)

    print(f"\nTotal: {len(all_chunks)} chunks "
          f"({len(patient_chunks)} patient-record, {len(medline_chunks)} MedlinePlus)")
    print(f"Saved to {output_file}")


if __name__ == "__main__":
    chunk_all_documents()
