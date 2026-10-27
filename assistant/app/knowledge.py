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
        "aliases": ["machine learning", "ml", "llm", "ai", "artificial intelligence", "neural network", "embedding", "embeddings", "vector database", "rag"],
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

    "cpu": {
        "title": "CPU (Central Processing Unit)",
        "aliases": ["cpu", "processor", "central processing unit", "microprocessor"],
        "body": (
            "The **CPU** is the computer's 'brain' - the chip that executes program instructions. "
            "It repeatedly runs a **fetch -> decode -> execute** cycle billions of times per second: fetch an instruction "
            "from memory, work out what it means, do it (add, compare, jump, load/store).\n\n"
            "- **Clock speed** (e.g. 3.5 GHz) = cycles per second; **cores** (4, 8, 16...) = how many instruction streams run "
            "truly in parallel; **cache** (L1/L2/L3) = tiny, very fast memory on the chip that avoids slow trips to RAM.\n"
            "- It only understands **machine code** - compilers/interpreters translate your Python/C++ down to it.\n\n"
            "Analogy: the CPU is a chef who follows one recipe step at a time, incredibly fast. More cores = more "
            "chefs; a bigger cache = ingredients on the counter instead of in the storeroom (RAM) or warehouse (disk)."
        ),
    },
    "gpu": {
        "title": "GPU (Graphics Processing Unit)",
        "aliases": ["gpu", "graphics card", "graphics processing unit", "video card"],
        "body": (
            "A **GPU** is a processor with *thousands* of small cores designed to do the same simple maths on huge amounts "
            "of data at once - originally to colour millions of pixels per frame in games.\n\n"
            "- CPU: a few powerful cores, great at *sequential* logic and branching ('if this, then that').\n"
            "- GPU: massively *parallel* arithmetic (matrices/vectors), weaker at branching.\n\n"
            "That parallelism is exactly what training and running AI models needs (matrix multiplications), which is why "
            "GPUs power modern machine learning, video encoding and scientific simulation - not just graphics."
        ),
    },
    "ram and storage": {
        "title": "RAM vs storage (memory)",
        "aliases": ["ram", "random access memory", "volatile memory", "ssd", "hard disk", "storage vs memory"],
        "body": (
            "**RAM** is the computer's short-term working memory: fast, but **volatile** - everything in it vanishes when "
            "power goes off. Running programs and their data live in RAM so the CPU can reach them quickly.\n\n"
            "**Storage** (SSD/HDD) is long-term and non-volatile: files, apps and the OS live there permanently, but it is "
            "much slower than RAM.\n\n"
            "Desk analogy: storage is the filing cabinet, RAM is your desktop. You work with papers *on the desk*; a bigger "
            "desk (more RAM) lets you keep more documents open at once without slowing down, but clearing the desk "
            "(switching off) loses anything you did not file away (save)."
        ),
    },
    "operating system": {
        "title": "Operating systems",
        "aliases": ["operating system", "os", "kernel", "windows", "linux", "macos", "android"],
        "body": (
            "An **operating system** (Windows, macOS, Linux, Android, iOS) is the software layer between your programs and "
            "the hardware. Its core, the **kernel**, is in charge of:\n\n"
            "- **Scheduling** - sharing CPU time between running processes (multitasking).\n"
            "- **Memory** - giving each program its own protected address space.\n"
            "- **Files and devices** - disks, keyboards, network cards behind uniform APIs (drivers).\n"
            "- **Security** - users, permissions, isolation between programs.\n\n"
            "Programs ask the OS for everything via *system calls* ('open this file', 'send this packet') instead of "
            "talking to hardware directly - that is why the same Python script runs on very different machines."
        ),
    },
    "compiler vs interpreter": {
        "title": "Compiler vs interpreter",
        "aliases": ["compiler", "interpreter", "compiled language", "interpreted language", "bytecode"],
        "body": (
            "CPUs only run machine code, so human-written code must be translated:\n\n"
            "- A **compiler** translates the *whole* program ahead of time into a binary (C++, Rust, Go). Result: fast, "
            "stand-alone executable; many errors caught before running; slower edit-run cycle. CareBridge's `make` does this.\n"
            "- An **interpreter** translates *while running*, step by step (Python, JavaScript in the browser). "
            "Result: instant feedback and portability, generally slower execution.\n\n"
            "Many languages blur the line: Java/C#/Python compile to **bytecode** that a virtual machine then interprets or "
            "JIT-compiles at runtime - portable *and* fast."
        ),
    },
    "algorithm": {
        "title": "Algorithms",
        "aliases": ["algorithm", "algorithms"],
        "body": (
            "An **algorithm** is a precise, step-by-step recipe for solving a problem: given some input, produce the correct "
            "output, always finishing. 'Sort these names', 'find the shortest route', 'is this number prime?' - each has many "
            "algorithms that differ wildly in speed (see Big-O).\n\n"
            "Same dish, different recipes: finding a word in a dictionary by checking page 1, 2, 3... (linear search, O(n)) "
            "versus repeatedly halving the book (binary search, O(log n)). Programs = algorithms + data structures, so "
            "choosing well is most of what 'writing efficient code' means. Try asking me about *binary search*, *sorting* "
            "or *recursion* for concrete examples."
        ),
    },
    "functions": {
        "title": "Functions",
        "aliases": ["function", "functions", "method", "methods", "parameter", "argument", "return value"],
        "body": (
            "A **function** is a named, reusable block of code: it takes inputs (**parameters/arguments**), does a job, and "
            "usually **returns** a result.\n\n"
            "```python\ndef average(numbers):      # parameter: numbers\n    return sum(numbers) / len(numbers)   # return value\n\n"
            "score = average([80, 90, 100])   # argument: the list\n```\n\n"
            "Why bother? **Reuse** (write once, call anywhere), **readability** (a good name says what the code does), and "
            "**testability** (small pieces are easy to check). A *pure* function - output depends only on inputs, no side "
            "effects - is the easiest kind to reason about. A function attached to a class/object is usually called a "
            "**method**."
        ),
    },
    "loops and conditionals": {
        "title": "Loops & conditionals",
        "aliases": ["loop", "loops", "for loop", "while loop", "if else", "conditional", "conditionals", "iteration"],
        "body": (
            "Programs make decisions with **conditionals** and repeat work with **loops** - together they are called *control flow*.\n\n"
            "```python\nfor student in students:        # loop: once per item\n    if student.marks >= 40:     # conditional\n"
            "        print('pass')\n    else:\n        print('retry')\n```\n\n"
            "- `for` - repeat a known number of times / over a collection.\n"
            "- `while` - repeat *until a condition changes* (careful: if it never changes, you get an infinite loop).\n"
            "- `if / elif / else` - pick a branch based on true/false tests combined with `and`, `or`, `not`.\n\n"
            "Nested loops are the classic source of O(n-squared) slowness - one loop inside another multiplies the work."
        ),
    },
    "arrays": {
        "title": "Arrays (and Python lists)",
        "aliases": ["array", "arrays", "list vs array"],
        "body": (
            "An **array** stores items side-by-side in memory, numbered from index **0**. Because the address of item *i* is "
            "just `start + i x item_size`, access by index is **O(1)** - instant for any size.\n\n"
            "- Trade-offs: inserting/deleting in the middle means shifting everything after it - **O(n)**. Fixed-size arrays "
            "(C/C++) cannot grow; *dynamic arrays* (Python `list`, Java `ArrayList`, C++ `std::vector`) resize automatically "
            "by occasionally copying into a bigger block (amortised O(1) append).\n"
            "- Contrast with a **linked list**: O(1) insert at a known node, but O(n) to reach the i-th item.\n\n"
            "Arrays' cache-friendly layout is why they are the default choice in most programs."
        ),
    },
    "how the web works": {
        "title": "How the internet & web work",
        "aliases": ["internet", "how the web works", "website", "browser", "web server", "dns", "ip address", "url", "client server"],
        "body": (
            "When you open a website, roughly this happens in under a second:\n\n"
            "1. **DNS** translates the name (`example.com`) into an **IP address** - the phone book of the internet.\n"
            "2. Your browser (**client**) opens a connection to that machine (**server**) and sends an **HTTP(S) request**: "
            "`GET /page`.\n"
            "3. The server runs code (like this FastAPI app), maybe queries a database, and replies with HTML/CSS/JS or JSON "
            "plus a status code (200 OK, 404 Not Found...).\n"
            "4. The browser renders HTML+CSS and runs the JavaScript, which can fetch more data from APIs without reloading.\n\n"
            "You are using exactly this right now: your browser talking to this assistant's server, exchanging JSON over HTTPS."
        ),
    },
    "frontend vs backend": {
        "title": "Frontend vs backend (full-stack)",
        "aliases": ["frontend", "backend", "full stack", "fullstack", "front end", "back end"],
        "body": (
            "- **Frontend** = what runs in the user's browser/app: layout, styling, interactions (HTML, CSS, JavaScript, "
            "frameworks like React). This assistant's chat UI, mic button and panels are frontend.\n"
            "- **Backend** = what runs on a server: business logic, databases, authentication, APIs (Python/FastAPI here, "
            "also Node, Java, Go...). The backend is where data is stored and rules are enforced - never trust the frontend "
            "for security, users can modify it.\n\n"
            "They talk over HTTP APIs (usually JSON). **Full-stack** means working on both sides. This project is a small "
            "full-stack example: `static/` (frontend) + `app/` (backend) + SQLite (database)."
        ),
    },
    "programming languages": {
        "title": "Popular programming languages",
        "aliases": ["programming language", "programming languages", "python", "javascript", "java language", "c++", "which language"],
        "body": (
            "Languages are tools - each trades speed, safety and convenience differently:\n\n"
            "- **Python** - readable, huge ecosystem; data science, AI, backends (this assistant), scripting. Interpreted, "
            "so slower per operation but very productive.\n"
            "- **JavaScript/TypeScript** - the language of the browser; also servers via Node.js. Every website uses it.\n"
            "- **C++** - compiled, manual memory control, maximum performance; games, systems, and CareBridge's core. "
            "Powerful but unforgiving.\n"
            "- **Java / C#** - compiled to bytecode on a VM; large enterprise systems, Android (Java/Kotlin), Unity games (C#).\n"
            "- **Go / Rust** - modern systems languages: Go for simple, concurrent servers; Rust for C++-level speed *with* "
            "compile-time memory safety.\n\n"
            "Beginners usually start with Python or JavaScript because feedback is instant; concepts (variables, loops, "
            "functions, data structures) transfer between all of them."
        ),
    },
    "debugging": {
        "title": "Bugs, errors & debugging",
        "aliases": ["debugging", "debug", "bug", "syntax error", "exception", "stack trace", "error types"],
        "body": (
            "Three classic error families:\n\n"
            "- **Syntax errors** - the code will not even parse (missing colon/bracket). Caught before running.\n"
            "- **Runtime errors / exceptions** - crashes mid-run: divide by zero, `None` where a value was expected, file "
            "not found. The **stack trace** shows the chain of calls that led there - read it bottom-up, the last line is "
            "the actual error.\n"
            "- **Logic errors** - runs fine, wrong answer. The hardest kind; hunt with small tests and prints.\n\n"
            "**Debugging method**: reproduce reliably, shrink to the smallest failing case, form a hypothesis, check "
            "actual values (print/logging or a debugger's breakpoints), fix, then re-run *all* tests so you did not break "
            "something else (that is what this project's test suite is for)."
        ),
    },
    "cloud computing": {
        "title": "Cloud computing",
        "aliases": ["cloud computing", "cloud", "aws", "azure", "saas", "iaas", "paas", "hosting"],
        "body": (
            "**Cloud computing** = renting computing (servers, storage, databases) over the internet, paid by usage, "
            "instead of owning machines. Providers: AWS, Microsoft Azure, Google Cloud.\n\n"
            "- **IaaS** (Infrastructure as a Service) - rent raw virtual machines; you manage the OS upwards.\n"
            "- **PaaS** (Platform) - push code, the platform runs it (Render, Fly.io, Heroku-style). This repo ships "
            "configs for exactly that.\n"
            "- **SaaS** (Software) - finished apps you just use: Gmail, Google Docs.\n\n"
            "Why it won: start in minutes, scale up/down with demand, someone else maintains hardware - at the cost of "
            "ongoing rent and dependence on the provider."
        ),
    },
    "cybersecurity": {
        "title": "Cybersecurity basics",
        "aliases": ["cybersecurity", "malware", "phishing", "encryption", "hacker", "ransomware", "online safety"],
        "body": (
            "Core ideas that prevent most real-world harm:\n\n"
            "- **Authentication vs authorisation** - proving who you are vs what you are allowed to do. Unique passwords + "
            "a password manager + **two-factor authentication (2FA)** stop most account takeovers.\n"
            "- **Phishing** - fake messages/sites stealing credentials; check sender and URL, be suspicious of urgency.\n"
            "- **Malware/ransomware** - malicious software that steals or locks data; updates + backups are the antidote.\n"
            "- **Encryption** - scrambling data so only key-holders can read it; HTTPS does this for web traffic.\n"
            "- **Least privilege and patching** - give accounts/apps only the access they need, and install updates - most "
            "breaches exploit known, already-fixed holes."
        ),
    },
    "computer basics": {
        "title": "What is a computer? Hardware vs software",
        "aliases": ["computer", "how does a computer work", "hardware", "software", "hardware vs software"],
        "body": (
            "A **computer** is a machine that takes input, processes it by following instructions, stores data, and "
            "produces output - unbelievably fast and literal-minded.\n\n"
            "- **Hardware** = the physical parts you can touch: CPU (executes instructions), RAM (working memory), SSD "
            "(storage), motherboard, input/output devices (keyboard, screen, network).\n"
            "- **Software** = the instructions: the operating system (manages the hardware) and applications on top of it "
            "- including this assistant.\n\n"
            "Everything - text, photos, videos, programs - is ultimately stored as numbers in **binary** (bits: 0s and 1s; "
            "8 bits = 1 byte). Different kinds of software just interpret those numbers differently."
        ),
    },
    "binary": {
        "title": "Binary, bits & bytes",
        "aliases": ["binary", "bits and bytes", "bit", "byte", "binary number"],
        "body": (
            "Computers store everything as **bits** - single 0/1 values (two states are easy to build with electricity: "
            "off/on). **8 bits = 1 byte**, enough for a character or a number 0-255.\n\n"
            "**Binary** is counting in base 2: each position is worth double the previous (1, 2, 4, 8, 16...). So `1010` = "
            "8 + 2 = **10**. Bigger units: KB ~ 10^3 bytes, MB ~ 10^6, GB ~ 10^9 (your phone's storage), TB ~ 10^12.\n\n"
            "Text = numbers mapped to characters (Unicode/UTF-8); images = grids of pixel numbers; sound = sampled "
            "waveform numbers. One representation - binary - underneath them all."
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
            # Boundary-aware match: 'ml' must not match inside 'html',
            # nor 'os' inside 'most'.
            if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", lowered):
                score = max(score, 10 + len(alias))
        overlap = len(set(tokenize(concept["title"])) & query_terms)
        if overlap >= 2:
            score = max(score, overlap * 3)
        if score > best_score:
            best, best_score = concept, score
    return best if best_score >= 6 else None


def suggest_topics(query: str, limit: int = 4) -> list[str]:
    """Closest KB titles for an unmatched question (stemmed token overlap
    with title + aliases + body) - used to make offline fallbacks helpful
    instead of dead ends."""
    query_terms = set(tokenize(query))
    if not query_terms:
        return []
    scored = []
    for concept in CONCEPTS.values():
        haystack = set(tokenize(concept["title"] + " " + " ".join(concept["aliases"])))
        overlap = len(query_terms & haystack) * 3
        overlap += len(query_terms & set(tokenize(concept["body"])))
        if overlap:
            scored.append((overlap, concept["title"]))
    scored.sort(reverse=True)
    return [title for _, title in scored[:limit]]


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
