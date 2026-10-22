// Utils.h - input helpers, string helpers, merge sort, binary search, geo distance.
#pragma once
#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <ctime>
#include <functional>
#include <iostream>
#include <string>
#include <vector>

namespace util {

inline std::string trim(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && std::isspace(static_cast<unsigned char>(s[a]))) ++a;
    while (b > a && std::isspace(static_cast<unsigned char>(s[b - 1]))) --b;
    return s.substr(a, b - a);
}

inline std::string toLower(std::string s) {
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

inline bool containsIgnoreCase(const std::string& hay, const std::string& needle) {
    return toLower(hay).find(toLower(needle)) != std::string::npos;
}

// Makes free text safe for the '|' delimited data files.
inline std::string sanitize(std::string s) {
    for (auto& c : s) if (c == '|' || c == '\n' || c == '\r') c = ' ';
    return trim(s);
}

// Academic-prototype hash only (NOT secure). Real systems must use bcrypt/argon2.
inline std::string hashPassword(const std::string& p) {
    return std::to_string(std::hash<std::string>{}("carebridge::" + p));
}

inline std::vector<std::string> split(const std::string& s, char d) {
    std::vector<std::string> out;
    std::string cur;
    for (char c : s) {
        if (c == d) { out.push_back(cur); cur.clear(); }
        else cur += c;
    }
    out.push_back(cur);
    return out;
}

inline int toInt(const std::string& s, int def = 0) {
    try { return std::stoi(s); } catch (...) { return def; }
}
inline double toDouble(const std::string& s, double def = 0.0) {
    try { return std::stod(s); } catch (...) { return def; }
}

// ---------- console input ----------
inline std::string readLine(const std::string& prompt) {
    std::cout << prompt << std::flush;
    std::string s;
    if (!std::getline(std::cin, s)) {
        std::cout << "\nInput closed. Goodbye!\n";
        std::exit(0);
    }
    return trim(s);
}

inline std::string readOptional(const std::string& prompt) { return sanitize(readLine(prompt)); }

inline std::string readNonEmpty(const std::string& prompt) {
    while (true) {
        std::string s = sanitize(readLine(prompt));
        if (!s.empty()) return s;
        std::cout << "  Value cannot be empty.\n";
    }
}

inline int readInt(const std::string& prompt, int lo, int hi) {
    while (true) {
        std::string s = readLine(prompt);
        try {
            size_t pos = 0;
            int v = std::stoi(s, &pos);
            if (pos == s.size() && v >= lo && v <= hi) return v;
        } catch (...) {}
        std::cout << "  Please enter a number between " << lo << " and " << hi << ".\n";
    }
}

// ---------- dates ----------
inline bool validDate(const std::string& d) {
    if (d.size() != 10 || d[4] != '-' || d[7] != '-') return false;
    for (int i : {0, 1, 2, 3, 5, 6, 8, 9})
        if (!std::isdigit(static_cast<unsigned char>(d[i]))) return false;
    int m = std::stoi(d.substr(5, 2)), day = std::stoi(d.substr(8, 2));
    return m >= 1 && m <= 12 && day >= 1 && day <= 31;
}

inline bool validTime(const std::string& t) {
    if (t.size() != 5 || t[2] != ':') return false;
    for (int i : {0, 1, 3, 4})
        if (!std::isdigit(static_cast<unsigned char>(t[i]))) return false;
    return std::stoi(t.substr(0, 2)) < 24 && std::stoi(t.substr(3, 2)) < 60;
}

inline std::string todayPlus(int days) {
    std::time_t t = std::time(nullptr) + static_cast<std::time_t>(days) * 86400;
    std::tm* tmv = std::localtime(&t);
    char buf[16];
    std::strftime(buf, sizeof(buf), "%Y-%m-%d", tmv);
    return buf;
}

// ---------- geo ----------
inline double haversineKm(double lat1, double lon1, double lat2, double lon2) {
    const double R = 6371.0, rad = 3.14159265358979323846 / 180.0;
    double dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
    double a = std::sin(dLat / 2) * std::sin(dLat / 2) +
               std::cos(lat1 * rad) * std::cos(lat2 * rad) * std::sin(dLon / 2) * std::sin(dLon / 2);
    return R * 2 * std::atan2(std::sqrt(a), std::sqrt(1 - a));
}

// ---------- algorithms ----------
template <typename T, typename Less>
void mergeSortImpl(std::vector<T>& v, std::vector<T>& tmp, size_t lo, size_t hi, Less less) {
    if (hi - lo < 2) return;
    size_t mid = lo + (hi - lo) / 2;
    mergeSortImpl(v, tmp, lo, mid, less);
    mergeSortImpl(v, tmp, mid, hi, less);
    size_t i = lo, j = mid, k = lo;
    while (i < mid && j < hi) tmp[k++] = less(v[j], v[i]) ? v[j++] : v[i++];  // stable
    while (i < mid) tmp[k++] = v[i++];
    while (j < hi) tmp[k++] = v[j++];
    for (size_t x = lo; x < hi; ++x) v[x] = tmp[x];
}

// Stable merge sort, O(n log n).
template <typename T, typename Less>
void mergeSort(std::vector<T>& v, Less less) {
    std::vector<T> tmp(v);
    mergeSortImpl(v, tmp, 0, v.size(), less);
}

// Binary search on a vector sorted ascending by .id(). Returns index or -1.
template <typename T>
int binarySearchById(const std::vector<T>& v, int id) {
    int lo = 0, hi = static_cast<int>(v.size()) - 1;
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        int cur = v[mid].id();
        if (cur == id) return mid;
        if (cur < id) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

}  // namespace util
