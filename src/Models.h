// Models.h - OOP model classes: Person (abstract) -> Patient / Doctor, Hospital,
// Appointment, HealthRecord, Notification, QueueEntry.
#pragma once
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>
#include "Utils.h"

enum class Urgency { Emergency = 1, Urgent = 2, Routine = 3 };
enum class Status { Pending = 0, Confirmed = 1, Completed = 2, Rejected = 3, Cancelled = 4 };

inline std::string toString(Urgency u) {
    switch (u) {
        case Urgency::Emergency: return "Emergency";
        case Urgency::Urgent:    return "Urgent";
        default:                 return "Routine";
    }
}
inline std::string toString(Status s) {
    switch (s) {
        case Status::Pending:   return "Pending";
        case Status::Confirmed: return "Confirmed";
        case Status::Completed: return "Completed";
        case Status::Rejected:  return "Rejected";
        case Status::Cancelled: return "Cancelled";
    }
    return "Unknown";
}
inline Urgency urgencyFromInt(int v) {
    if (v == 1) return Urgency::Emergency;
    if (v == 2) return Urgency::Urgent;
    return Urgency::Routine;
}
inline Status statusFromInt(int v) {
    return (v < 0 || v > 4) ? Status::Pending : static_cast<Status>(v);
}

// ---------------------------------------------------------------- Locality
struct Locality {
    std::string name;
    double lat, lon;
};

// Predefined localities (sample data, no real-time GPS).
inline const std::vector<Locality>& localities() {
    static const std::vector<Locality> L = {
        {"Clock Tower", 30.3243, 78.0415}, {"Rajpur Road", 30.3560, 78.0640},
        {"Bell Road", 30.2700, 77.9980},   {"Premnagar", 30.3300, 77.9650},
        {"ISBT", 30.2880, 78.0430},        {"Ballupur", 30.3400, 78.0100}};
    return L;
}

// ---------------------------------------------------------------- Person
class Person {
public:
    Person(int id, std::string name, std::string passHash)
        : id_(id), name_(std::move(name)), passHash_(std::move(passHash)) {}
    virtual ~Person() = default;

    int id() const { return id_; }
    const std::string& name() const { return name_; }
    const std::string& passHash() const { return passHash_; }
    bool checkPassword(const std::string& pw) const { return passHash_ == util::hashPassword(pw); }

    virtual std::string role() const = 0;
    virtual void display() const = 0;           // polymorphic profile print
    virtual std::string serialize() const = 0;  // polymorphic file format

protected:
    int id_;
    std::string name_;
    std::string passHash_;
};

// ---------------------------------------------------------------- Patient
class Patient : public Person {
public:
    int age;
    std::string gender, phone, locality;

    Patient(int id, const std::string& name, const std::string& hash, int age_,
            const std::string& gender_, const std::string& phone_, const std::string& locality_)
        : Person(id, name, hash), age(age_), gender(gender_), phone(phone_), locality(locality_) {}

    std::string role() const override { return "Patient"; }

    void display() const override {
        std::cout << "  Patient #" << id_ << ": " << name_ << " | Age " << age << " | " << gender
                  << " | Phone " << phone << " | Area " << locality << "\n";
    }

    std::string serialize() const override {
        return std::to_string(id_) + "|" + name_ + "|" + passHash_ + "|" + std::to_string(age) + "|" +
               gender + "|" + phone + "|" + locality;
    }

    static Patient fromFields(const std::vector<std::string>& f) {
        return Patient(util::toInt(f[0]), f[1], f[2], util::toInt(f[3]), f[4], f[5], f[6]);
    }
};

// ---------------------------------------------------------------- Doctor
struct Slot {
    std::string when;  // "YYYY-MM-DD HH:MM"
    bool booked;
};

class Doctor : public Person {
public:
    int hospitalId;
    std::string specialization;
    int fee;
    std::vector<Slot> slots;

    Doctor(int id, const std::string& name, const std::string& hash, int hospitalId_,
           const std::string& spec, int fee_)
        : Person(id, name, hash), hospitalId(hospitalId_), specialization(spec), fee(fee_) {}

    std::string role() const override { return "Doctor"; }

    void display() const override {
        std::cout << "  Doctor #" << id_ << ": " << name_ << " | " << specialization << " | Fee "
                  << fee << " | Open slots " << openSlots().size() << "\n";
    }

    std::string serialize() const override {
        std::string s;
        for (size_t i = 0; i < slots.size(); ++i) {
            if (i) s += ";";
            s += slots[i].when + "#" + (slots[i].booked ? "1" : "0");
        }
        return std::to_string(id_) + "|" + name_ + "|" + passHash_ + "|" + std::to_string(hospitalId) +
               "|" + specialization + "|" + std::to_string(fee) + "|" + s;
    }

    static Doctor fromFields(const std::vector<std::string>& f) {
        Doctor d(util::toInt(f[0]), f[1], f[2], util::toInt(f[3]), f[4], util::toInt(f[5]));
        if (f.size() > 6 && !f[6].empty()) {
            for (const auto& tok : util::split(f[6], ';')) {
                auto parts = util::split(tok, '#');
                if (parts.size() == 2) d.slots.push_back({parts[0], parts[1] == "1"});
            }
        }
        return d;
    }

    bool addSlot(const std::string& when) {
        for (const auto& s : slots) if (s.when == when) return false;
        slots.push_back({when, false});
        util::mergeSort(slots, [](const Slot& a, const Slot& b) { return a.when < b.when; });
        return true;
    }
    bool bookSlot(const std::string& when) {
        for (auto& s : slots) if (s.when == when && !s.booked) { s.booked = true; return true; }
        return false;
    }
    void freeSlot(const std::string& when) {
        for (auto& s : slots) if (s.when == when) s.booked = false;
    }
    bool removeOpenSlot(const std::string& when) {
        for (size_t i = 0; i < slots.size(); ++i)
            if (slots[i].when == when && !slots[i].booked) { slots.erase(slots.begin() + i); return true; }
        return false;
    }
    std::vector<std::string> openSlots() const {
        std::vector<std::string> v;
        for (const auto& s : slots) if (!s.booked) v.push_back(s.when);
        return v;
    }
};

// ---------------------------------------------------------------- Hospital
struct Hospital {
    int hid;
    std::string hname, city, locality;
    double lat, lon;

    int id() const { return hid; }
    std::string serialize() const {
        return std::to_string(hid) + "|" + hname + "|" + city + "|" + locality + "|" +
               std::to_string(lat) + "|" + std::to_string(lon);
    }
    static Hospital fromFields(const std::vector<std::string>& f) {
        return Hospital{util::toInt(f[0]), f[1], f[2], f[3], util::toDouble(f[4]), util::toDouble(f[5])};
    }
};

// ---------------------------------------------------------------- Appointment
struct Appointment {
    int id;
    int patientId, doctorId, hospitalId;
    std::string when;
    Urgency urgency;
    Status status;
    std::string reason;

    std::string serialize() const {
        return std::to_string(id) + "|" + std::to_string(patientId) + "|" + std::to_string(doctorId) + "|" +
               std::to_string(hospitalId) + "|" + when + "|" + std::to_string(static_cast<int>(urgency)) +
               "|" + std::to_string(static_cast<int>(status)) + "|" + reason;
    }
    static Appointment fromFields(const std::vector<std::string>& f) {
        return Appointment{util::toInt(f[0]), util::toInt(f[1]), util::toInt(f[2]), util::toInt(f[3]), f[4],
                           urgencyFromInt(util::toInt(f[5])), statusFromInt(util::toInt(f[6])), f[7]};
    }
};

// ---------------------------------------------------------------- HealthRecord
struct HealthRecord {
    int id;
    int patientId, doctorId;
    std::string date, symptoms, diagnosis, tests, followUp;

    std::string serialize() const {
        return std::to_string(id) + "|" + std::to_string(patientId) + "|" + std::to_string(doctorId) + "|" +
               date + "|" + symptoms + "|" + diagnosis + "|" + tests + "|" + followUp;
    }
    static HealthRecord fromFields(const std::vector<std::string>& f) {
        return HealthRecord{util::toInt(f[0]), util::toInt(f[1]), util::toInt(f[2]), f[3], f[4], f[5], f[6], f[7]};
    }
};

// ---------------------------------------------------------------- Notification
struct Notification {
    int patientId = 0;
    std::string message;
};

// ---------------------------------------------------------------- QueueEntry
// Entry of the appointment-request priority queue: lower urgency number first,
// then first-come-first-served (seq = appointment id).
struct QueueEntry {
    int apptId = 0;
    int doctorId = 0;
    int urgency = 3;
    int seq = 0;

    static bool before(const QueueEntry& a, const QueueEntry& b) {
        if (a.urgency != b.urgency) return a.urgency < b.urgency;
        return a.seq < b.seq;
    }
};
