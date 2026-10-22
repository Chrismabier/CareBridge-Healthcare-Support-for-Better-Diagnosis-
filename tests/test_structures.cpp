// Unit tests for the data structures and algorithms. Run: make test
#include <iostream>
#include "DataStructures.h"
#include "Models.h"

static int failures = 0;
#define CHECK(cond) do { if (cond) std::cout << "PASS: " #cond "\n"; \
    else { std::cout << "FAIL: " #cond "\n"; ++failures; } } while (0)

int main() {
    // LinkedList
    LinkedList<int> l;
    l.pushBack(1); l.pushBack(2); l.pushBack(3);
    CHECK(l.size() == 3);
    CHECK(l.findIf([](const int& x) { return x == 2; }) != nullptr);
    CHECK(l.removeIf([](const int& x) { return x == 2; }));
    CHECK(l.size() == 2);
    CHECK(!l.removeIf([](const int& x) { return x == 99; }));

    // Queue (FIFO)
    Queue<int> q;
    q.enqueue(10); q.enqueue(20);
    int v = 0;
    CHECK(q.dequeue(v) && v == 10);
    CHECK(q.dequeue(v) && v == 20);
    CHECK(!q.dequeue(v));

    // Stack (LIFO)
    Stack<int> s;
    s.push(1); s.push(2);
    CHECK(s.pop(v) && v == 2);
    CHECK(s.pop(v) && v == 1);
    CHECK(s.empty());

    // PriorityQueue: urgent first, FIFO inside same urgency
    PriorityQueue<QueueEntry> pq(QueueEntry::before);
    pq.push({1, 1, 3, 1});  // routine
    pq.push({2, 1, 1, 2});  // emergency
    pq.push({3, 1, 3, 3});  // routine
    pq.push({4, 1, 2, 4});  // urgent
    QueueEntry e;
    CHECK(pq.pop(e) && e.apptId == 2);
    CHECK(pq.pop(e) && e.apptId == 4);
    CHECK(pq.pop(e) && e.apptId == 1);
    CHECK(pq.pop(e) && e.apptId == 3);
    CHECK(pq.empty());

    // Merge sort + binary search
    std::vector<int> a = {5, 3, 9, 1, 7};
    util::mergeSort(a, [](int x, int y) { return x < y; });
    CHECK(a == std::vector<int>({1, 3, 5, 7, 9}));

    std::vector<Doctor> docs;
    for (int i = 1; i <= 5; ++i) docs.push_back(Doctor(i, "D", "h", 1, "Gen", 100));
    CHECK(util::binarySearchById(docs, 4) == 3);
    CHECK(util::binarySearchById(docs, 42) == -1);

    // Validation
    CHECK(util::validDate("2026-10-22"));
    CHECK(!util::validDate("22-10-2026"));
    CHECK(util::validTime("09:30"));
    CHECK(!util::validTime("25:00"));

    // Slots
    Doctor d(1, "Dr X", "h", 1, "Gen", 100);
    CHECK(d.addSlot("2026-10-23 10:00"));
    CHECK(!d.addSlot("2026-10-23 10:00"));
    CHECK(d.bookSlot("2026-10-23 10:00"));
    CHECK(!d.bookSlot("2026-10-23 10:00"));
    d.freeSlot("2026-10-23 10:00");
    CHECK(d.openSlots().size() == 1);

    std::cout << (failures ? "\nSOME TESTS FAILED\n" : "\nALL TESTS PASSED\n");
    return failures ? 1 : 0;
}
