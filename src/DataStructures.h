// DataStructures.h - hand-written generic data structures used by CareBridge.
//   LinkedList<T>     : singly linked list (patients, doctors, records, appointments)
//   Queue<T>          : FIFO queue         (patient notifications)
//   PriorityQueue<T>  : ordered linked list, stable (appointment requests, urgent first)
//   Stack<T>          : LIFO stack         (recently viewed patients)
#pragma once
#include <cstddef>
#include <functional>
#include <utility>
#include <vector>

template <typename T>
class LinkedList {
public:
    using Pred = std::function<bool(const T&)>;
    using Before = std::function<bool(const T&, const T&)>;

    LinkedList() = default;
    LinkedList(const LinkedList&) = delete;
    LinkedList& operator=(const LinkedList&) = delete;
    ~LinkedList() { clear(); }

    void pushBack(const T& v) {
        Node* n = new Node(v);
        if (!head_) head_ = tail_ = n;
        else { tail_->next = n; tail_ = n; }
        ++size_;
    }

    void pushFront(const T& v) {
        Node* n = new Node(v);
        n->next = head_;
        head_ = n;
        if (!tail_) tail_ = n;
        ++size_;
    }

    // Inserts v before the first node that v must precede (stable for equal priority).
    void insertSorted(const T& v, const Before& before) {
        Node* n = new Node(v);
        Node* prev = nullptr;
        Node* cur = head_;
        while (cur && !before(v, cur->data)) { prev = cur; cur = cur->next; }
        n->next = cur;
        if (prev) prev->next = n; else head_ = n;
        if (!cur) tail_ = n;
        ++size_;
    }

    bool popFront(T& out) {
        if (!head_) return false;
        Node* n = head_;
        out = n->data;
        head_ = n->next;
        if (!head_) tail_ = nullptr;
        delete n;
        --size_;
        return true;
    }

    T* front() { return head_ ? &head_->data : nullptr; }
    const T* front() const { return head_ ? &head_->data : nullptr; }

    T* findIf(const Pred& pred) {
        for (Node* c = head_; c; c = c->next) if (pred(c->data)) return &c->data;
        return nullptr;
    }
    const T* findIf(const Pred& pred) const {
        for (Node* c = head_; c; c = c->next) if (pred(c->data)) return &c->data;
        return nullptr;
    }

    bool removeIf(const Pred& pred) { return unlinkIf(pred, nullptr); }
    bool extractIf(const Pred& pred, T& out) { return unlinkIf(pred, &out); }

    void forEach(const std::function<void(T&)>& f) {
        for (Node* c = head_; c; c = c->next) f(c->data);
    }
    void forEach(const std::function<void(const T&)>& f) const {
        for (Node* c = head_; c; c = c->next) f(c->data);
    }

    std::vector<T> toVector() const {
        std::vector<T> v;
        v.reserve(size_);
        for (Node* c = head_; c; c = c->next) v.push_back(c->data);
        return v;
    }

    void clear() {
        while (head_) { Node* n = head_; head_ = head_->next; delete n; }
        tail_ = nullptr;
        size_ = 0;
    }

    size_t size() const { return size_; }
    bool empty() const { return size_ == 0; }

private:
    struct Node {
        T data;
        Node* next;
        explicit Node(const T& d) : data(d), next(nullptr) {}
    };

    bool unlinkIf(const Pred& pred, T* out) {
        Node* prev = nullptr;
        Node* cur = head_;
        while (cur) {
            if (pred(cur->data)) {
                if (out) *out = cur->data;
                if (prev) prev->next = cur->next; else head_ = cur->next;
                if (cur == tail_) tail_ = prev;
                delete cur;
                --size_;
                return true;
            }
            prev = cur;
            cur = cur->next;
        }
        return false;
    }

    Node* head_ = nullptr;
    Node* tail_ = nullptr;
    size_t size_ = 0;
};

template <typename T>
class Queue {
public:
    void enqueue(const T& v) { list_.pushBack(v); }
    bool dequeue(T& out) { return list_.popFront(out); }
    const T* peek() const { return list_.front(); }
    bool extractIf(const typename LinkedList<T>::Pred& p, T& out) { return list_.extractIf(p, out); }
    bool removeIf(const typename LinkedList<T>::Pred& p) { return list_.removeIf(p); }
    void forEach(const std::function<void(const T&)>& f) const { list_.forEach(f); }
    size_t size() const { return list_.size(); }
    bool empty() const { return list_.empty(); }
    void clear() { list_.clear(); }
private:
    LinkedList<T> list_;
};

template <typename T>
class PriorityQueue {
public:
    using Before = std::function<bool(const T&, const T&)>;
    explicit PriorityQueue(Before before) : before_(std::move(before)) {}

    void push(const T& v) { list_.insertSorted(v, before_); }
    bool pop(T& out) { return list_.popFront(out); }
    const T* top() const { return list_.front(); }
    bool extractIf(const typename LinkedList<T>::Pred& p, T& out) { return list_.extractIf(p, out); }
    bool removeIf(const typename LinkedList<T>::Pred& p) { return list_.removeIf(p); }
    void forEach(const std::function<void(const T&)>& f) const { list_.forEach(f); }
    size_t size() const { return list_.size(); }
    bool empty() const { return list_.empty(); }
    void clear() { list_.clear(); }
private:
    LinkedList<T> list_;
    Before before_;
};

template <typename T>
class Stack {
public:
    void push(const T& v) { list_.pushFront(v); }
    bool pop(T& out) { return list_.popFront(out); }
    const T* peek() const { return list_.front(); }
    void forEach(const std::function<void(const T&)>& f) const { list_.forEach(f); }  // top first
    size_t size() const { return list_.size(); }
    bool empty() const { return list_.empty(); }
    void clear() { list_.clear(); }
private:
    LinkedList<T> list_;
};
