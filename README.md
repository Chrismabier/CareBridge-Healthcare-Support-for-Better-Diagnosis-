# CareBridge - Healthcare Support for Better Diagnosis

A **Healthcare Management System** in **C++17** that demonstrates
**Data Structures** and **Object-Oriented Programming**, now also runnable in the browser.
Team DSCPP-III-2026-T404 - Mentor: Mr. Kuldeep Nautiyal.

[![CI](https://github.com/Chrismabier/CareBridge-Healthcare-Support-for-Better-Diagnosis-/actions/workflows/ci.yml/badge.svg)](https://github.com/Chrismabier/CareBridge-Healthcare-Support-for-Better-Diagnosis-/actions/workflows/ci.yml)
[![Deploy to GitHub Pages](https://github.com/Chrismabier/CareBridge-Healthcare-Support-for-Better-Diagnosis-/actions/workflows/pages.yml/badge.svg)](https://github.com/Chrismabier/CareBridge-Healthcare-Support-for-Better-Diagnosis-/actions/workflows/pages.yml)

> Academic prototype. It uses sample data only and is **not** a replacement for real hospital software.

## Two ways to run it

**1. Terminal (original)**

```bash
make            # build
./carebridge    # run (use carebridge.exe on Windows)
make test       # run unit tests
```

**2. Browser (web console)** - the same C++ binary, streamed to a terminal in the browser:

```bash
make
cd web && npm start      # http://localhost:3000  (console at /console.html)
```

or with Docker:

```bash
docker compose up --build   # http://localhost:3000
```

The web runtime (`web/`) has **zero npm dependencies**: it starts one sandboxed `./carebridge`
process per browser tab, each with its own `data/` directory, pipes keystrokes into its stdin and
streams its stdout back over Server-Sent Events. No business logic is duplicated in JavaScript.
See [DEPLOY.md](DEPLOY.md) for Docker, Render, Fly.io, VPS and GitHub Pages deployments.

> **GitHub Pages note:** Pages hosts the landing page + console UI only — it cannot run the
> server or the C++ binary. If the Pages console shows
> `Could not reach the CareBridge server (HTTP 405)`, deploy the backend once (e.g. Render
> Blueprint) and open the console as `console.html?api=https://your-backend-host`, or paste
> the backend URL into the **Backend** box in the console header. [Details](DEPLOY.md#4-github-pages-static-site--ui-only-needs-a-backend).

## Features
**Patient:** register/login, find nearby hospitals (predefined areas, sorted by distance), browse doctors
(by hospital / specialization / fee / name), book appointment slots with urgency, view or cancel appointments,
view own health records, notifications.

**Doctor:** register/login, view the pending-request queue (urgent first), confirm/reject requests,
see confirmed schedule, open or close time slots, search patients, add/update health records, recently viewed patients.

## Data structures and where they are used
| Structure / algorithm | Used for |
|---|---|
| Singly linked list | Patients, doctors, hospitals, appointments, health records |
| Queue (FIFO) | Patient notifications |
| Priority queue | Appointment requests: Emergency > Urgent > Routine, then first-come-first-served |
| Stack (LIFO) | Doctor's recently viewed patients |
| Merge sort | Hospitals by distance, doctors by fee/name, schedules, records by date |
| Binary search | Find doctor by ID |
| Linear search | Patients by name, doctors by specialization |

## OOP concepts
Abstraction (`Person` is abstract), inheritance (`Patient`, `Doctor`), polymorphism (`display()`, `serialize()`, `role()`),
encapsulation (private/protected members + getters), templates (generic containers).

## Project structure
```
CareBridge/
  src/       main.cpp  HealthcareSystem.{h,cpp}  Models.h  DataStructures.h  Utils.h
  tests/     test_structures.cpp
  web/       server.js  lib/  public/     (zero-dependency Node web runtime)
  data/      created automatically on first run (local binary)
  Makefile   Docker/compose, render.yaml, fly.toml   (.github/workflows = CI + Pages)
```

## Demo logins (created on first run)
| Role | ID | Password |
|---|---|---|
| Patient | 1 | patient123 |
| Doctor | 1-7 | doctor123 |

## Typical demo flow
1. Log in as patient 1, find nearby hospitals, book Dr. Anil Sharma (ID 1) as *Emergency*.
2. Log out, log in as doctor 1, process the request (Confirm).
3. Doctor adds a health record for patient 1.
4. Log in as patient 1 again: notifications and the health record appear.

In the web console the same flow works with the keyboard or the quick-action chips under the
terminal (Login as patient 1 / Login as doctor 1).

## Storage
Plain text files in `data/` (`|` delimited), saved after every change. Delete `data/` to reset to sample data.
In the web deployment each browser session gets its own copy under `web/runtime/sessions/<id>/`;
the **Reset data** button wipes it and re-seeds the sample data.

## CI/CD
Every push builds the project on Linux (g++, clang++), macOS (clang++) and Windows (MSVC), runs
`make test`, smoke-tests the web console over HTTP, builds the Docker image and - on `main` -
publishes it to GHCR and deploys the static site to GitHub Pages.

## Limitations
Passwords use a simple non-secure hash (prototype only). Nearby hospitals use predefined coordinates, not real GPS.
No encryption, concurrency, or real patient data.
