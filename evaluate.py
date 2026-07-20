"""
Runs a set of test questions (eval_questions.json) through the full RAG
pipeline (retrieval + Claude) and scores how well it did, so you can
measure your system instead of just eyeballing individual answers.

For each question, this checks:
  - Retrieval hit: did the expected patient show up in the top-k chunks?
    (skipped for questions where expected_patient is null, e.g. general
    MedlinePlus questions)
  - Keyword hit: does the final written answer mention the expected
    keywords? (a rough stand-in for "did it get the content right")
  - Latency: how long the retrieval + Claude call took, in seconds

Usage:
    python3 evaluate.py

Requires eval_questions.json in the same folder, and everything rag_qa.py
needs (chroma_db/ built, .env with ANTHROPIC_API_KEY).

Writes a full results file (eval_results.json) and a short human-readable
summary (eval_report.md) you can paste findings from into your README.
"""

import json
import time
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from anthropic import Anthropic

# Reuse the exact same retrieval + prompting logic as rag_qa.py, rather
# than duplicating it, so the eval is testing the real pipeline.
from rag_qa import (
    CHROMA_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    TOP_K,
    retrieve,
    build_context_block,
    ask_claude,
    format_source_line,
)

EVAL_FILE = "eval_questions.json"
RESULTS_FILE = "eval_results.json"
REPORT_FILE = "eval_report.md"


def load_eval_set(path=EVAL_FILE):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_retrieval_hit(chunks, expected_patient):
    """True if the expected patient name shows up in any retrieved
    chunk's metadata. Case-insensitive, partial match (so 'Maria Gomez'
    matches a metadata value of 'Maria E. Gomez')."""
    if not expected_patient:
        return None  # not applicable, e.g. a general MedlinePlus question

    expected_lower = expected_patient.lower()
    for chunk in chunks:
        patient_name = chunk["meta"].get("patient_name", "") or ""
        if expected_lower in patient_name.lower():
            return True
    return False


def check_keyword_hits(answer_text, expected_keywords):
    """Returns (list of keywords found, list of keywords missing)."""
    answer_lower = answer_text.lower()
    found, missing = [], []
    for keyword in expected_keywords:
        if keyword.lower() in answer_lower:
            found.append(keyword)
        else:
            missing.append(keyword)
    return found, missing


def run_evaluation():
    load_dotenv()

    print(f"Loading embedding model ({EMBEDDING_MODEL})...")
    embed_model = SentenceTransformer(EMBEDDING_MODEL)

    client_db = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client_db.get_collection(COLLECTION_NAME)
    claude = Anthropic()

    eval_set = load_eval_set()
    print(f"Loaded {len(eval_set)} test questions from {EVAL_FILE}\n")

    results = []
    for i, item in enumerate(eval_set, start=1):
        question = item["question"]
        expected_patient = item.get("expected_patient")
        expected_keywords = item.get("expected_keywords", [])

        print(f"[{i}/{len(eval_set)}] {question}")

        start_time = time.time()
        chunks = retrieve(question, collection, embed_model, top_k=TOP_K)
        context_block = build_context_block(chunks)
        answer = ask_claude(claude, question, context_block)
        elapsed = round(time.time() - start_time, 2)

        retrieval_hit = check_retrieval_hit(chunks, expected_patient)
        keywords_found, keywords_missing = check_keyword_hits(answer, expected_keywords)

        results.append({
            "question": question,
            "expected_patient": expected_patient,
            "expected_keywords": expected_keywords,
            "answer": answer,
            "sources": [format_source_line(c["meta"]) for c in chunks],
            "retrieval_hit": retrieval_hit,
            "keywords_found": keywords_found,
            "keywords_missing": keywords_missing,
            "latency_seconds": elapsed,
        })

        hit_label = "n/a" if retrieval_hit is None else ("yes" if retrieval_hit else "NO")
        print(f"    retrieval hit: {hit_label} | keywords found: {len(keywords_found)}/{len(expected_keywords)} | {elapsed}s\n")

    save_results(results)
    write_report(results)
    print(f"Done. Full details in {RESULTS_FILE}, summary in {REPORT_FILE}.")


def save_results(results):
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def write_report(results):
    total = len(results)
    retrieval_applicable = [r for r in results if r["retrieval_hit"] is not None]
    retrieval_hits = sum(1 for r in retrieval_applicable if r["retrieval_hit"])

    total_keywords = sum(len(r["expected_keywords"]) for r in results)
    found_keywords = sum(len(r["keywords_found"]) for r in results)

    avg_latency = round(sum(r["latency_seconds"] for r in results) / total, 2) if total else 0

    lines = []
    lines.append("# Evaluation Report\n")
    lines.append(f"Ran {total} test questions through the full RAG pipeline.\n")
    lines.append("## Summary\n")
    if retrieval_applicable:
        lines.append(f"- Retrieval accuracy: {retrieval_hits}/{len(retrieval_applicable)} "
                      f"questions retrieved a chunk from the expected patient\n")
    lines.append(f"- Keyword coverage: {found_keywords}/{total_keywords} expected keywords "
                  f"appeared somewhere in the written answers\n")
    lines.append(f"- Average response time: {avg_latency} seconds per question\n")
    lines.append("\n## Per-question detail\n")

    for i, r in enumerate(results, start=1):
        lines.append(f"### {i}. {r['question']}\n")
        lines.append(f"- Retrieval hit: {r['retrieval_hit']}\n")
        lines.append(f"- Keywords found: {r['keywords_found']}\n")
        lines.append(f"- Keywords missing: {r['keywords_missing']}\n")
        lines.append(f"- Latency: {r['latency_seconds']}s\n")
        lines.append(f"- Answer: {r['answer']}\n")

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    run_evaluation()
