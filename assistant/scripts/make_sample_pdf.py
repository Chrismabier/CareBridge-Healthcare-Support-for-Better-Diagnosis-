#!/usr/bin/env python3
"""Generate a 3-page sample PDF (sample.pdf) for trying document Q&A.

    python scripts/make_sample_pdf.py [output-path]

Writes a minimal, valid PDF with the standard library only (uncompressed
content streams, Helvetica core font) - handy for demos and tests.
"""
import sys
from pathlib import Path

PAGES = [
    [
        "CareBridge Project Report - Sample PDF",
        "",
        "Chapter 1: Introduction",
        "CareBridge is a healthcare management system written in modern C++.",
        "Patients can register, find nearby hospitals, browse doctors and",
        "book appointments. Doctors can triage appointment requests and",
        "maintain electronic health records for their patients.",
        "The system serves two hospitals in the demo data set: CityCare",
        "General Hospital and Riverbend Medical Center.",
    ],
    [
        "Chapter 2: Data Structures Used",
        "",
        "A singly linked list stores patients, doctors and appointments,",
        "giving constant-time insertion but linear-time search.",
        "A priority queue orders appointment requests so that Emergency",
        "cases are seen first, then Urgent, then Routine requests.",
        "A queue delivers patient notifications in first-in first-out order,",
        "while a stack tracks each doctor's recently viewed patients.",
        "Merge sort ranks hospitals by distance in O(n log n) time.",
    ],
    [
        "Chapter 3: Results and Future Work",
        "",
        "The prototype handles one thousand synthetic patients with ease.",
        "Booking a slot and confirming it takes under fifty milliseconds.",
        "Future work includes a real database such as SQLite or Postgres,",
        "proper password hashing with bcrypt, and a mobile application.",
        "Telemedicine video calls are planned for the second release,",
        "scheduled for March 2027 according to the project roadmap.",
    ],
]


def escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        objects.append(body.encode() if isinstance(body, str) else body)
        return len(objects)  # 1-based object number

    font_id = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    content_ids: list[int] = []
    for lines in pages:
        stream_lines = ["BT /F1 13 Tf 56 760 Td 18 TL"]
        for line in lines:
            stream_lines.append(f"({escape(line)}) Tj T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode()
        content_ids.append(add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"))
        page_ids.append(0)  # placeholder, filled below (needs Pages id first)

    pages_id = len(objects) + 1 + len(pages)  # pages node comes after page objs
    for i, content_id in enumerate(content_ids):
        page_ids[i] = add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    real_pages_id = add(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    assert real_pages_id == pages_id, (real_pages_id, pages_id)
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("sample.pdf")
    target.write_bytes(build_pdf(PAGES))
    print(f"Wrote {target} ({target.stat().st_size} bytes, {len(PAGES)} pages)")
