# CareBridge - Healthcare Support for Better Diagnosis

A console-based **Healthcare Management System** in **C++17** that demonstrates
**Data Structures** and **Object-Oriented Programming**.
Team DSCPP-III-2026-T404 - Mentor: Mr. Kuldeep Nautiyal.

> Academic prototype. It uses sample data only and is **not** a replacement for real hospital software.

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
  src/  main.cpp  HealthcareSystem.{h,cpp}  Models.h  DataStructures.h  Utils.h
  tests/test_structures.cpp
  data/   (created automatically on first run)
  Makefile
```

## Build and run
Requires a C++17 compiler (g++ 9+, clang, or MSVC).
```bash
make            # build
./carebridge    # run (use carebridge.exe on Windows)
make test       # run unit tests
```
Without `make`:
```bash
g++ -std=c++17 -O2 -o carebridge src/main.cpp src/HealthcareSystem.cpp
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

## Storage
Plain text files in `data/` (`|` delimited), saved after every change. Delete `data/` to reset to sample data.

## Limitations
Passwords use a simple non-secure hash (prototype only). Nearby hospitals use predefined coordinates, not real GPS.
No encryption, concurrency, or real patient data.
