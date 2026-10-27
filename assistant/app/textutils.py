"""Text utilities: tokenisation, chunking, extractive summarisation and a
small natural-language date/time parser for reminders.

Pure standard library - deterministic and offline, which is what makes the
assistant useful even with no LLM API key configured.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, time, timedelta, timezone

STOPWORDS = set("""
a an the and or but if then else when at by for with about into through after
over between out against during without before under around among is are was
were be been being have has had do does did will would shall should can could
may might must i you he she it we they me him her us them my your his its our
their mine yours ours theirs this that these those what which who whom whose
how when where why as of on in to from up down so than too very just also not
no yes s t don now there here all any both each few more most other some such
only own same one two
""".split())

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-_]*[a-z0-9]|[a-z0-9]")


def _stem(token: str) -> str:
    """Very light suffix stripping so 'sorted'/'sorting' match 'sort'."""
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es") and not token.endswith(("ss", "us")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase, lightly stemmed word tokens, stopwords removed."""
    return [_stem(t) for t in TOKEN_RE.findall(text.lower())
            if t not in STOPWORDS and len(t) > 1]


def term_counts(text: str) -> dict[str, int]:
    return dict(Counter(tokenize(text)))


def split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", cleaned)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, max_chars: int = 850, overlap_chars: int = 130) -> list[str]:
    """Split text into overlapping, sentence-aware chunks for retrieval."""
    sentences = split_sentences(text)
    if not sentences:
        text = text.strip()
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:  # very long sentence: hard-split it
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(sentence), max_chars - overlap_chars):
                chunks.append(sentence[i:i + max_chars].strip())
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            chunks.append(current.strip())
            overlap = current[-overlap_chars:] if overlap_chars else ""
            # Start the next chunk at a word boundary of the overlap.
            if " " in overlap:
                overlap = overlap.split(" ", 1)[1]
            current = f"{overlap} {sentence}".strip()
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) >= 20] or chunks


def extractive_summary(text: str, max_sentences: int = 5) -> str:
    """Pick the most information-dense sentences (TF scored, order preserved)."""
    sentences = split_sentences(text)
    if not sentences:
        return "No readable text was found to summarise."
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
    freq = Counter(tokenize(text))
    if not freq:
        return " ".join(sentences[:max_sentences])
    scored = []
    for idx, sentence in enumerate(sentences):
        tokens = tokenize(sentence)
        if not tokens:
            continue
        score = sum(freq[t] for t in tokens) / (len(tokens) ** 0.7)
        score *= 1.15 if idx < 3 else 1.0            # slight lead bias
        if len(sentence) < 25:                        # skip fragments/headings
            score *= 0.4
        scored.append((score, idx, sentence))
    top = sorted(scored, reverse=True)[:max_sentences]
    top.sort(key=lambda item: item[1])
    return " ".join(sentence for _, _, sentence in top)


def best_sentences_for_query(text: str, query: str, max_sentences: int = 3) -> list[str]:
    """Sentences of ``text`` most relevant to ``query`` (for offline answers)."""
    query_terms = set(tokenize(query))
    if not query_terms:
        return split_sentences(text)[:max_sentences]
    scored = []
    for idx, sentence in enumerate(split_sentences(text)):
        hits = len(query_terms & set(tokenize(sentence)))
        if hits:
            scored.append((hits, -idx, sentence))
    scored.sort(reverse=True)
    return [s for _, _, s in scored[:max_sentences]]


def snippet(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ------------------------------------------------- natural-language date/time

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_IN_RE = re.compile(r"\bin\s+(\d+)\s*(minute|minutes|min|hour|hours|hr|day|days|week|weeks)\b", re.I)
_AT_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
_TIME_ANY_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b", re.I)
_ISO_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})(?:[T\s]+(\d{2}):(\d{2}))?\b")
_DAY_RE = re.compile(
    r"\b(today|tomorrow|tonight|next\s+week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I
)


def _apply_time(hour: int, minute: int, ampm: str | None) -> tuple[int, int]:
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    return hour % 24, minute % 60


def parse_when(text: str, now: datetime | None = None) -> tuple[datetime | None, str]:
    """Extract a date/time from natural language.

    Returns ``(datetime_in_utc, matched_text)`` or ``(None, "")``.
    Understands: "in 30 minutes", "in 2 hours", "tomorrow at 9am",
    "today at 17:30", "on Friday at 10", "2026-11-02 14:00", "tonight".
    Times without an explicit timezone are treated as UTC - the web UI passes
    its own offset-adjusted "now" so times line up with the user's clock
    closely enough for a personal assistant (see README "Timezones").
    """
    now = now or datetime.now(timezone.utc)
    lowered = text.lower()

    # ISO date first - most explicit.
    m = _ISO_RE.search(text)
    if m:
        try:
            base = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if m.group(2):
                base = base.replace(hour=int(m.group(2)), minute=int(m.group(3)))
            else:
                base = base.replace(hour=9, minute=0)
            return base, [m.group(0)]
        except ValueError:
            pass

    # Relative: "in 30 minutes" / "in 2 days"
    m = _IN_RE.search(lowered)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        if unit.startswith(("min",)):
            delta = timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            delta = timedelta(hours=amount)
        elif unit.startswith("day"):
            delta = timedelta(days=amount)
        else:
            delta = timedelta(weeks=amount)
        return now + delta, [m.group(0)]

    # Day word + optional time.
    day_match = _DAY_RE.search(lowered)
    at_match = _AT_RE.search(text) or _TIME_ANY_RE.search(text)

    hour, minute = 9, 0
    have_time = False
    matched_parts = []
    if at_match:
        groups = at_match.groups()
        if groups[0] is not None and len(groups) >= 3 and at_match.re is _TIME_ANY_RE and groups[2]:
            hour, minute = _apply_time(int(groups[0]), int(groups[1] or 0), groups[2])
        elif len(groups) >= 5 and groups[3] is not None:
            hour, minute = int(groups[3]), int(groups[4])
        elif len(groups) >= 3:
            hour, minute = _apply_time(int(groups[0]), int(groups[1] or 0), groups[2])
        have_time = True
        matched_parts.append(at_match.group(0))

    target_date = now.date()
    if day_match:
        word = re.sub(r"\s+", " ", day_match.group(1).lower())
        matched_parts.append(day_match.group(0))
        if word == "tomorrow":
            target_date += timedelta(days=1)
        elif word == "tonight":
            if not have_time:
                hour, minute, have_time = 20, 0, True
        elif word == "next week":
            target_date += timedelta(days=7)
        elif word in WEEKDAYS:
            delta = (WEEKDAYS[word] - now.weekday()) % 7
            if delta == 0:
                delta = 7  # "on Friday" said on a Friday means next Friday
            target_date += timedelta(days=delta)
        # "today" keeps target_date as-is

    if day_match or have_time:
        result = datetime.combine(target_date, time(hour, minute), tzinfo=timezone.utc)
        if not day_match and result <= now:  # "at 9am" when it's already 10am -> tomorrow
            result += timedelta(days=1)
        return result, matched_parts
    return None, []


def humanize_dt(iso: str | None) -> str:
    if not iso:
        return "no date set"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return dt.strftime("%a %d %b %Y, %H:%M UTC")
