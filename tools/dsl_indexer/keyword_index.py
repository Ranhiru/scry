from collections import Counter, defaultdict
from typing import Dict, List
import math

from .text_utils import tokenize


def build_keyword_index(chunks: List[Dict]) -> Dict:
    postings = defaultdict(dict)
    doc_len = {}
    doc_meta = {}
    doc_freq = Counter()

    for chunk in chunks:
        doc_id = chunk["chunk_id"]
        tokens = tokenize(chunk["content"])
        tf = Counter(tokens)
        doc_len[doc_id] = len(tokens)
        doc_meta[doc_id] = chunk
        for term, freq in tf.items():
            postings[term][doc_id] = freq
            doc_freq[term] += 1

    doc_count = len(chunks)
    avg_doc_len = (sum(doc_len.values()) / doc_count) if doc_count else 0

    return {
        "postings": postings,
        "doc_len": doc_len,
        "doc_meta": doc_meta,
        "doc_freq": dict(doc_freq),
        "doc_count": doc_count,
        "avg_doc_len": avg_doc_len,
    }


def search_keyword_index(index: Dict, query: str, top_k: int, repo_filter: List[str]) -> List[Dict]:
    terms = tokenize(query)
    if not terms:
        return []

    postings = index.get("postings", {})
    doc_len = index.get("doc_len", {})
    doc_meta = index.get("doc_meta", {})
    doc_freq = index.get("doc_freq", {})
    doc_count = index.get("doc_count", 0)
    avg_doc_len = index.get("avg_doc_len", 1) or 1

    k1 = 1.5
    b = 0.75
    scores = defaultdict(float)

    for term in terms:
        term_postings = postings.get(term, {})
        n_t = doc_freq.get(term, 0)
        if n_t == 0:
            continue
        idf = math.log(1 + (doc_count - n_t + 0.5) / (n_t + 0.5))
        for doc_id, tf in term_postings.items():
            d_len = doc_len.get(doc_id, 0) or 1
            denom = tf + k1 * (1 - b + b * (d_len / avg_doc_len))
            score = idf * ((tf * (k1 + 1)) / denom)
            scores[doc_id] += score

    if not scores:
        return []

    rows = []
    repo_filter_set = set(repo_filter or [])
    for doc_id, score in scores.items():
        row = doc_meta.get(doc_id)
        if not row:
            continue
        if repo_filter_set and row["repo"] not in repo_filter_set:
            continue
        rows.append(
            {
                "chunk_id": row["chunk_id"],
                "repo": row["repo"],
                "path": row["path"],
                "section": row["section"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "score": round(score, 6),
                "snippet": row["content"],
            }
        )

    rows.sort(key=lambda r: (-r["score"], r["path"], r["line_start"]))
    return rows[:top_k]

