"""Vector database for document/note retrieval (advanced feature).

Design
------
* Every document page / note is split into overlapping chunks
  (:func:`app.textutils.chunk_text`), each chunk keeps its **page number**.
* Each chunk is embedded as a sparse TF-IDF vector (term -> weight) and
  persisted in SQLite (``chunks`` table). TF-IDF needs no model downloads, no
  API key and is fully deterministic, which keeps the demo reproducible.
* Search = cosine similarity between the query vector and chunk vectors,
  computed per user so data never leaks across accounts.

The public interface (``index_*`` / ``search`` / ``Hit``) is deliberately the
same shape you would use with Chroma/FAISS + a neural embedding model, so
swapping the embedder later is a localised change - see README
"Upgrading the vector store".
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field

from . import db
from .textutils import chunk_text, term_counts, tokenize


@dataclass
class Hit:
    chunk_id: int
    score: float
    text: str
    source_type: str                 # "document" | "note"
    document_id: int | None = None
    note_id: int | None = None
    page: int | None = None
    title: str = ""
    filename: str = ""

    def citation(self) -> dict:
        label = self.title or self.filename or ("Note" if self.source_type == "note" else "Document")
        if self.source_type == "document" and self.page is not None:
            label = f"{label} - page {self.page}"
        return {
            "label": label,
            "source_type": self.source_type,
            "document_id": self.document_id,
            "note_id": self.note_id,
            "page": self.page,
            "score": round(self.score, 4),
            "snippet": self.text[:320] + ("…" if len(self.text) > 320 else ""),
        }


def _tfidf_vector(counts: dict[str, int], idf: dict[str, float]) -> dict[str, float]:
    if not counts:
        return {}
    total = sum(counts.values())
    return {term: (count / total) * idf.get(term, 0.0) for term, count in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):  # iterate over the smaller vector
        a, b = b, a
    dot = sum(weight * b.get(term, 0.0) for term, weight in a.items())
    norm_a = math.sqrt(sum(w * w for w in a.values()))
    norm_b = math.sqrt(sum(w * w for w in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore:
    """Per-user TF-IDF index rebuilt from SQLite on demand (cached in memory)."""

    def __init__(self) -> None:
        self._cache: dict[int, tuple[list[dict], dict[str, float]]] = {}

    def invalidate(self, user_id: int) -> None:
        self._cache.pop(user_id, None)

    def _index(self, user_id: int) -> tuple[list[dict], dict[str, float]]:
        if user_id in self._cache:
            return self._cache[user_id]
        chunks = db.all_chunks_for_user(user_id)
        doc_freq: Counter = Counter()
        parsed: list[dict] = []
        for chunk in chunks:
            counts = json.loads(chunk.get("terms_json") or "{}")
            if not counts:  # rebuild term counts for rows written by older versions
                counts = term_counts(chunk["text"])
            chunk["_counts"] = counts
            for term in counts:
                doc_freq[term] += 1
            parsed.append(chunk)
        n = max(len(parsed), 1)
        idf = {term: math.log((n + 1) / (freq + 1)) + 1.0 for term, freq in doc_freq.items()}
        for chunk in parsed:
            chunk["_vector"] = _tfidf_vector(chunk["_counts"], idf)
        self._cache[user_id] = (parsed, idf)
        return parsed, idf

    # -------------------------------------------------------------- indexing

    def index_document(self, user_id: int, document_id: int, pages: list[tuple[int, str]]) -> int:
        """Chunk + embed a document. ``pages`` is [(page_number, text), ...]."""
        db.delete_chunks_for_document(document_id)
        rows: list[dict] = []
        index = 0
        for page_number, page_text in pages:
            for piece in chunk_text(page_text):
                rows.append({
                    "user_id": user_id, "source_type": "document", "document_id": document_id,
                    "note_id": None, "page": page_number, "chunk_index": index,
                    "text": piece, "terms_json": json.dumps(term_counts(piece)),
                })
                index += 1
        if rows:
            db.insert_chunks(rows)
        self.invalidate(user_id)
        return len(rows)

    def index_note(self, user_id: int, note: dict) -> int:
        db.delete_chunks_for_note(note["id"])
        text = f"{note['title']}\n{note.get('body', '')}".strip()
        rows = [{
            "user_id": user_id, "source_type": "note", "document_id": None,
            "note_id": note["id"], "page": None, "chunk_index": i,
            "text": piece, "terms_json": json.dumps(term_counts(piece)),
        } for i, piece in enumerate(chunk_text(text))]
        if rows:
            db.insert_chunks(rows)
        self.invalidate(user_id)
        return len(rows)

    def remove_document(self, user_id: int, document_id: int) -> None:
        db.delete_chunks_for_document(document_id)
        self.invalidate(user_id)

    def remove_note(self, user_id: int, note_id: int) -> None:
        db.delete_chunks_for_note(note_id)
        self.invalidate(user_id)

    # --------------------------------------------------------------- search

    def search(self, user_id: int, query: str, top_k: int = 5,
               source_types: tuple[str, ...] = ("document", "note"),
               document_id: int | None = None,
               min_score: float = 0.02) -> list[Hit]:
        chunks, idf = self._index(user_id)
        if not chunks:
            return []
        query_counts = Counter(tokenize(query))
        if not query_counts:
            return []
        query_vector = _tfidf_vector(dict(query_counts), idf)
        # Terms never seen in the corpus get idf=0 above; give them a neutral
        # weight of 1.0 so a query of only-new terms still scores by overlap.
        for term in query_vector:
            if query_vector[term] == 0.0:
                query_vector[term] = (query_counts[term] / sum(query_counts.values())) * 1.0

        hits: list[Hit] = []
        for chunk in chunks:
            if chunk["source_type"] not in source_types:
                continue
            if document_id is not None and chunk.get("document_id") != document_id:
                continue
            score = _cosine(query_vector, chunk["_vector"])
            if score < min_score:
                continue
            is_doc = chunk["source_type"] == "document"
            hits.append(Hit(
                chunk_id=chunk["id"], score=score, text=chunk["text"],
                source_type=chunk["source_type"],
                document_id=chunk.get("document_id"), note_id=chunk.get("note_id"),
                page=chunk.get("page"),
                title=(chunk.get("doc_title") if is_doc else chunk.get("note_title")) or "",
                filename=chunk.get("doc_filename") or "",
            ))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]


# One process-wide store (the app is single-process; see README for scaling notes).
store = VectorStore()
