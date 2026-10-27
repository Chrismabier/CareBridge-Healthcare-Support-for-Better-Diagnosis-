"""Built-in programming knowledge base (offline "Explain" feature) + seed data.

When an LLM API key is configured, explanations come from the model. Without
one, the assistant answers from this curated KB so *Explain a programming
concept* always works. Entries are keyed by canonical topic with aliases.
"""
from __future__ import annotations

import re
from .textutils import tokenize

CONCEPTS: dict[str, dict] = {
    "recursion": {
        "title": "Recursion",
        "aliases": ["recursive", "base case", "recursion"],
        "body": (
            "**Recursion** is when a function calls itself with a smaller version of the same problem "
            "until it reaches a *base case* that can be answered directly.\n\n"
            "```python\ndef factorial(n):\n    if n <= 1:          # base case\n        return 1\n"
            "    return n * factorial(n - 1)   # smaller sub-problem\n```\n\n"
            "Every recursive function needs (1) a base case and (2) progress towards it - forget either "
            "and you get a stack overflow. Recursion shines on naturally self-similar problems: walking "
            "trees and folders, divide-and-conquer sorts (merge sort, quick sort), backtracking and parsers. "
            "Costs: each call uses stack memory (O(depth)), so deep recursion may need an iterative version "
            "with an explicit stack instead."
        ),
    },
    "big o notation": {
        "title": "Big-O notation",
        "aliases": ["big o", "time complexity", "space complexity", "complexity", "o(n)", "asymptotic"],
        "body": (
            "**Big-O notation** describes how an algorithm's running time (or memory) grows as the input "
            "size *n* grows, ignoring constant factors.\n\n"
            "| Complexity | Meaning | Example |\n|---|---|---|\n"
            "| O(1) | constant | array index, hash-map lookup |\n"
            "| O(log n) | halves each step | binary search |\n"
            "| O(n) | touches everything once | linear search |\n"
            "| O(n log n) | efficient sorting | merge sort |\n"
            "| O(n²) | nested loops | bubble sort, naive duplicate check |\n"
            "| O(2ⁿ) | exponential | naive recursive Fibonacci |\n\n"
            "Rule of thumb: drop constants and keep the fastest-growing term - O(2n + 5) is just O(n). "
            "In this very project, TF-IDF document search is O(chunks × query terms), which is why real "
            "vector databases use approximate nearest-neighbour indexes instead of scanning everything."
        ),
    },
    "object oriented programming": {
        "title": "Object-oriented programming (OOP)",
        "aliases": ["oop", "object oriented", "encapsulation", "inheritance", "polymorphism", "abstraction", "class", "classes"],
        "body": (
            "**OOP** organises code into *objects* that bundle data (fields) with the behaviour that acts on it "
            "(methods). Four pillars:\n\n"
            "1. **Encapsulation** - hide internal state behind a public interface (private fields + getters/setters).\n"
            "2. **Abstraction** - expose *what* something does, not *how* (abstract classes / interfaces).\n"
            "3. **Inheritance** - a subclass reuses and extends a parent class (`Patient` and `Doctor` extend `Person` in CareBridge).\n"
            "4. **Polymorphism** - the same call behaves differently per type (``display()`` overridden per subclass, dispatched at runtime).\n\n"
            "OOP pays off when your domain has clear entities with shared behaviour; prefer composition over deep "
            "inheritance trees, and keep classes focused on one responsibility."
        ),
    },
    "linked list": {
        "title": "Linked lists",
        "aliases": ["linked list", "singly linked", "doubly linked"],
        "body": (
            "A **linked list** stores data in nodes scattered in memory, each node pointing to the next one "
            "(and, in a *doubly* linked list, to the previous one too).\n\n"
            "- Insert/delete at a known position: **O(1)** - just rewire pointers.\n"
            "- Access by index / search: **O(n)** - you must walk from the head.\n"
            "- No wasted capacity, grows one node at a time, but each node pays pointer overhead and cache locality is poor.\n\n"
            "CareBridge's C++ core uses a hand-written singly linked list for patients, doctors and appointments - "
            "great for learning pointer manipulation, while production code usually reaches for a dynamic array "
            "(`std::vector`) unless insertions in the middle dominate."
        ),
    },
    "stack and queue": {
        "title": "Stacks vs queues (vs priority queues)",
        "aliases": ["stack", "queue", "priority queue", "lifo", "fifo"],
        "body": (
            "Both are *restricted* lists - the restriction is the point:\n\n"
            "- **Stack (LIFO)** - last in, first out. `push`/`pop` at one end. Used for undo history, the call stack, "
            "bracket matching, backtracking. CareBridge uses one for a doctor's recently viewed patients.\n"
            "- **Queue (FIFO)** - first in, first out. `enqueue` at the back, `dequeue` at the front. Used for print jobs, "
            "BFS, task scheduling - and patient notifications in CareBridge.\n"
            "- **Priority queue** - the *most urgent* item leaves first, regardless of arrival order. CareBridge triages "
            "appointment requests this way (Emergency > Urgent > Routine, then FIFO). Usually implemented with a binary heap: "
            "O(log n) insert/remove, O(1) peek."
        ),
    },
    "sorting algorithms": {
        "title": "Sorting algorithms",
        "aliases": ["sorting", "merge sort", "quick sort", "bubble sort", "sort algorithm"],
        "body": (
            "| Algorithm | Average | Worst | Stable? | Idea |\n|---|---|---|---|---|\n"
            "| Bubble sort | O(n²) | O(n²) | yes | swap neighbouring out-of-order pairs |\n"
            "| Merge sort | O(n log n) | O(n log n) | yes | split, sort halves, merge |\n"
            "| Quick sort | O(n log n) | O(n²) | no | partition around a pivot, recurse |\n"
            "| Heap sort | O(n log n) | O(n log n) | no | build a heap, pop the max repeatedly |\n\n"
            "**Merge sort** guarantees O(n log n) and stability at the cost of O(n) extra memory - CareBridge uses it to "
            "order hospitals by distance and doctors by fee. In practice you call the standard library sort (usually a "
            "hybrid like Timsort/introsort); knowing the trade-offs matters more than re-implementing them."
        ),
    },
    "binary search": {
        "title": "Binary search",
        "aliases": ["binary search", "linear search", "searching algorithms"],
        "body": (
            "**Binary search** finds a value in a *sorted* collection by halving the search space each step: "
            "look at the middle, go left or right. That gives **O(log n)** - a million items need ~20 comparisons - "
            "versus **O(n)** for linear search.\n\n"
            "```python\ndef binary_search(a, target):\n    lo, hi = 0, len(a) - 1\n    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n        if a[mid] == target: return mid\n"
            "        lo, hi = (mid + 1, hi) if a[mid] < target else (lo, mid - 1)\n    return -1\n```\n\n"
            "Catch: the data must be sorted and randomly accessible (arrays, not linked lists). "
            "CareBridge binary-searches doctors by ID after sorting, and linear-searches by name/specialisation."
        ),
    },
    "hash map": {
        "title": "Hash maps (dictionaries)",
        "aliases": ["hash map", "hashmap", "dictionary", "hash table", "hashing"],
        "body": (
            "A **hash map** stores key→value pairs by running the key through a *hash function* that picks a bucket. "
            "Lookups, inserts and deletes are **O(1) on average**.\n\n"
            "- Two keys hashing to the same bucket = a *collision*, handled by chaining (a small list per bucket) or "
            "open addressing (probe for the next free slot).\n"
            "- When the table gets ~70% full it *resizes* (usually doubles) and rehashes everything - an occasional O(n) "
            "that amortises away.\n"
            "- Iteration order is bucket order (Python dicts additionally remember insertion order).\n\n"
            "Hash maps power caches, indexes, counting (`Counter`), de-duplication and this assistant's TF-IDF vectors."
        ),
    },
    "api and rest": {
        "title": "APIs and REST",
        "aliases": ["api", "rest", "rest api", "http", "endpoint", "json"],
        "body": (
            "An **API** is a contract that lets two programs talk. A **REST API** exposes *resources* over HTTP:\n\n"
            "- Nouns in URLs (`/api/notes/12`), verbs as HTTP methods: `GET` read, `POST` create, `PUT`/`PATCH` update, `DELETE` remove.\n"
            "- Stateless requests, JSON bodies, meaningful status codes (200 OK, 201 Created, 400 bad input, 401 unauthorised, 404 not found, 422 validation failed).\n"
            "- Auth via a bearer token in the `Authorization` header - exactly how this assistant's frontend talks to FastAPI.\n\n"
            "Try it: open `/docs` on this server - FastAPI generates interactive OpenAPI documentation from the code."
        ),
    },
    "sql vs nosql": {
        "title": "SQL vs NoSQL databases",
        "aliases": ["sql", "nosql", "database", "sqlite", "mongodb", "relational"],
        "body": (
            "**SQL (relational)** databases store structured rows in tables with a fixed schema, enforce relationships "
            "with foreign keys and give you ACID transactions and powerful JOINs (PostgreSQL, MySQL, SQLite - this "
            "assistant uses SQLite).\n\n"
            "**NoSQL** is a family, not one thing: document stores (MongoDB - flexible JSON-ish records), key-value "
            "(Redis - blazing fast lookups/caches), wide-column (Cassandra - huge write scale) and graph (Neo4j - "
            "relationships first).\n\n"
            "Rule of thumb: start relational unless you have a concrete reason not to - most app data *is* relational, "
            "and 'we might need web scale' is rarely that reason. Choose NoSQL for its data model, not fashion."
        ),
    },
    "async programming": {
        "title": "Asynchronous programming",
        "aliases": ["async", "await", "asynchronous", "concurrency", "thread", "threads", "event loop", "promise"],
        "body": (
            "**Async** code keeps working while waiting. Instead of blocking a thread on I/O (network, disk), the program "
            "registers 'wake me when done' and does other work.\n\n"
            "- *Concurrency* = juggling many tasks; *parallelism* = running them simultaneously on multiple cores. "
            "Async gives concurrency on one thread via an **event loop**.\n"
            "- Python: `async def` + `await` (FastAPI runs on this - one process serves many requests while they wait on I/O).\n"
            "- JavaScript: Promises + `async`/`await`; browsers are single-threaded so *all* UI code is effectively async.\n\n"
            "Async helps I/O-bound work (APIs, databases). CPU-heavy work (video encoding, big ML) needs processes/threads instead - "
            "awaiting won't make a slow calculation faster."
        ),
    },
    "git and version control": {
        "title": "Git & version control",
        "aliases": ["git", "github", "version control", "commit", "branch", "merge conflict"],
        "body": (
            "**Git** records snapshots (*commits*) of your project so you can revisit or undo anything.\n\n"
            "- `git status` / `git diff` - what changed? `git add` + `git commit` - save a snapshot with a message.\n"
            "- **Branches** are cheap parallel timelines: build a feature on a branch, open a **pull request**, review, merge.\n"
            "- A **merge conflict** just means two branches edited the same lines - Git marks both versions and you choose.\n"
            "- `.gitignore` keeps build output, secrets and data files (like this app's `data/` folder) out of history.\n\n"
            "Habits that pay off: small focused commits, messages that explain *why*, and never committing API keys."
        ),
    },
    "machine learning basics": {
        "title": "Machine learning & LLMs (basics)",
        "aliases": ["machine learning", "ml", "llm", "neural network", "embedding", "embeddings", "vector database", "rag"],
        "body": (
            "**Machine learning** fits a model's parameters to examples instead of hand-written rules. Three flavours: "
            "*supervised* (labelled examples), *unsupervised* (find structure), *reinforcement* (learn from rewards).\n\n"
            "A **large language model (LLM)** is a neural network (a Transformer) trained to predict the next token; scale + "
            "instruction tuning turn that into a useful assistant.\n\n"
            "**Embeddings** map text to vectors so similar meanings sit close together. **RAG (retrieval-augmented generation)** - "
            "what this assistant does - retrieves the most relevant chunks from *your* documents first, then has the model answer "
            "*grounded in those chunks with citations*, instead of relying on what it memorised in training. It cuts hallucination "
            "and lets the model use private data it was never trained on."
        ),
    },
    "variables and data types": {
        "title": "Variables & data types",
        "aliases": ["variable", "variables", "data type", "data types", "integer", "string", "boolean"],
        "body": (
            "A **variable** is a named box for a value; its **data type** says what kind of value and which operations make sense.\n\n"
            "- Numbers: `int` (whole), `float` (decimal) - `7`, `3.14`\n"
            "- Text: `str` - `\"hello\"`; truth values: `bool` - `True`/`False`\n"
            "- Collections: `list` (ordered, mutable), `tuple` (ordered, immutable), `dict` (key→value), `set` (unique items)\n\n"
            "Python is *dynamically* typed (types are checked at runtime, variables can change type); C++/Java are *statically* "
            "typed (checked at compile time - catches bugs earlier, needs more declarations). Type hints (`def f(x: int) -> str`) "
            "give Python much of the benefit without a compiler."
        ),
    },
    "pointers and memory": {
        "title": "Pointers & memory (C/C++)",
        "aliases": ["pointer", "pointers", "memory", "heap", "stack memory", "segfault", "null pointer"],
        "body": (
            "A **pointer** is a variable that stores a memory *address*. `*p` dereferences it (follow the address), "
            "`&x` takes an address.\n\n"
            "- **Stack**: automatic, fast, freed when a function returns - local variables live here.\n"
            "- **Heap**: manual (`new`/`malloc`), lives until you free it - linked-list nodes live here. Forgetting = a *memory leak*; "
            "freeing twice or using freed memory = undefined behaviour / segfaults.\n"
            "- A `nullptr` is an address that points nowhere - dereferencing it crashes (the classic segfault).\n\n"
            "Modern C++ avoids raw owning pointers: use `std::unique_ptr`/`std::shared_ptr` (RAII) so memory frees itself. "
            "Python/Java hide pointers behind references + a garbage collector."
        ),
    },
    "authentication and security": {
        "title": "Authentication & password security",
        "aliases": ["authentication", "password hashing", "jwt", "token", "login security", "hashing password"],
        "body": (
            "**Authentication** proves who you are; **authorisation** decides what you may do.\n\n"
            "- Never store passwords - store a slow, salted *hash* (bcrypt/argon2, or PBKDF2 like this app). A unique random "
            "**salt** per user defeats rainbow tables; slowness defeats brute force.\n"
            "- After login the server issues a signed **token** (e.g. a JWT: header.payload.HMAC-signature). The client sends it "
            "as `Authorization: Bearer …`; the server verifies the signature and expiry on every request - no session table needed.\n"
            "- Compare secrets in constant time, rate-limit login attempts, serve everything over HTTPS, and scope every "
            "database query by the logged-in user id (this app does all of the above except TLS, which your host provides)."
        ),
    },
}


def find_concept(query: str) -> dict | None:
    """Best KB match for a free-text question ('explain merge sort to me').

    Deliberately strict - a single shared generic word ("data", "memory")
    must not hijack a question that belongs to document retrieval. A match
    needs a known alias phrase, or at least two title terms.
    """
    lowered = query.lower()
    query_terms = set(tokenize(lowered))
    best, best_score = None, 0
    for concept in CONCEPTS.values():
        score = 0
        for alias in concept["aliases"]:
            if alias in lowered:
                score = max(score, 10 + len(alias))
        overlap = len(set(tokenize(concept["title"])) & query_terms)
        if overlap >= 2:
            score = max(score, overlap * 3)
        if score > best_score:
            best, best_score = concept, score
    return best if best_score >= 6 else None


def concept_titles() -> list[str]:
    return [c["title"] for c in CONCEPTS.values()]


# ------------------------------------------------------------ demo seed data

SAMPLE_DOCUMENT_TITLE = "CareBridge & Data Structures - Study Notes"
SAMPLE_DOCUMENT_PAGES: list[tuple[int, str]] = [
    (1, "CareBridge is a healthcare management prototype written in C++17. It lets patients find nearby "
        "hospitals, browse doctors and book appointments, while doctors triage requests and maintain health "
        "records. The project deliberately avoids the C++ standard containers for its core structures: every "
        "list, queue and stack in src/DataStructures.h is hand-written to demonstrate how the abstractions work "
        "under the hood. Patients, doctors, hospitals, appointments and health records are all stored in a "
        "singly linked list, which gives O(1) insertion at the head but O(n) search."),
    (2, "Appointment requests are handled by a priority queue. Emergency requests are served before Urgent "
        "ones, which are served before Routine ones, and ties are broken first-come-first-served. This mirrors "
        "real hospital triage. Patient notifications use a plain FIFO queue so messages arrive in the order "
        "they were sent. A stack remembers each doctor's recently viewed patients, which makes it O(1) to jump "
        "back to the last patient opened. Merge sort orders hospitals by haversine distance and doctors by fee "
        "or name in O(n log n) time, and binary search finds a doctor by ID in O(log n) once the list is sorted."),
    (3, "The object-oriented design centres on an abstract Person class. Patient and Doctor inherit from Person "
        "and override the polymorphic display, serialize and role methods, demonstrating abstraction, "
        "inheritance, polymorphism and encapsulation. Data is persisted to pipe-delimited text files in a data "
        "directory and reloaded on startup. Demo credentials are patient ID 1 with password patient123 and "
        "doctor IDs 1 to 7 with password doctor123. The web console streams the same C++ binary to a browser "
        "terminal using a zero-dependency Node.js server and Server-Sent Events, with one sandboxed process per "
        "browser tab."),
]

SAMPLE_NOTES = [
    {"title": "Exam revision - data structures",
     "body": "Revise: linked lists O(n) search, priority queue triage order, merge sort O(n log n) stable, "
             "binary search needs sorted data. Make flashcards for stack vs queue examples from CareBridge.",
     "tags": "study,exam"},
    {"title": "Project ideas",
     "body": "Ideas: add PDF question answering to the assistant, try Groq free tier for the LLM API key, "
             "record a 2 minute demo video of the voice commands for the portfolio.",
     "tags": "ideas,portfolio"},
    {"title": "Weekly meal prep",
     "body": "Sunday: cook rice, dal and two curries. Portion into 5 boxes. Buy curd and fruit on Wednesday.",
     "tags": "personal"},
]
