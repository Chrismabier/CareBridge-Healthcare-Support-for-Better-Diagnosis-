#include "HealthcareSystem.h"

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>

using std::cout;
using std::string;
using std::vector;
namespace fs = std::filesystem;

// =====================================================================
//  Construction, storage, seed data
// =====================================================================
HealthcareSystem::HealthcareSystem(const string& dataDir)
    : dataDir_(dataDir), requestQueue_(QueueEntry::before) {
    fs::create_directories(dataDir_);
    if (!fs::exists(path("hospitals.txt"))) {
        seedSampleData();
    } else {
        load();
    }
}

void HealthcareSystem::loadFile(const string& file,
                                const std::function<void(const vector<string>&)>& handler) const {
    std::ifstream in(path(file));
    string line;
    while (std::getline(in, line)) {
        line = util::trim(line);
        if (line.empty() || line[0] == '#') continue;
        handler(util::split(line, '|'));
    }
}

void HealthcareSystem::load() {
    loadFile("hospitals.txt", [&](const vector<string>& f) { if (f.size() >= 6) hospitals_.pushBack(Hospital::fromFields(f)); });
    loadFile("doctors.txt", [&](const vector<string>& f) { if (f.size() >= 6) doctors_.pushBack(Doctor::fromFields(f)); });
    loadFile("patients.txt", [&](const vector<string>& f) { if (f.size() >= 7) patients_.pushBack(Patient::fromFields(f)); });
    loadFile("appointments.txt", [&](const vector<string>& f) { if (f.size() >= 8) appointments_.pushBack(Appointment::fromFields(f)); });
    loadFile("records.txt", [&](const vector<string>& f) { if (f.size() >= 8) records_.pushBack(HealthRecord::fromFields(f)); });
    loadFile("notifications.txt", [&](const vector<string>& f) {
        if (f.size() >= 2) notifications_.enqueue({util::toInt(f[0]), f[1]});
    });
    // Rebuild the priority queue from pending appointments.
    appointments_.forEach([&](const Appointment& a) {
        if (a.status == Status::Pending)
            requestQueue_.push(QueueEntry{a.id, a.doctorId, static_cast<int>(a.urgency), a.id});
    });
    recomputeIds();
}

void HealthcareSystem::save() const {
    { std::ofstream o(path("hospitals.txt")); hospitals_.forEach([&](const Hospital& h) { o << h.serialize() << "\n"; }); }
    { std::ofstream o(path("doctors.txt")); doctors_.forEach([&](const Doctor& d) { o << d.serialize() << "\n"; }); }
    { std::ofstream o(path("patients.txt")); patients_.forEach([&](const Patient& p) { o << p.serialize() << "\n"; }); }
    { std::ofstream o(path("appointments.txt")); appointments_.forEach([&](const Appointment& a) { o << a.serialize() << "\n"; }); }
    { std::ofstream o(path("records.txt")); records_.forEach([&](const HealthRecord& r) { o << r.serialize() << "\n"; }); }
    {
        std::ofstream o(path("notifications.txt"));
        notifications_.forEach([&](const Notification& n) { o << n.patientId << "|" << n.message << "\n"; });
    }
}

void HealthcareSystem::recomputeIds() {
    hospitals_.forEach([&](const Hospital& h) { nextHospitalId_ = std::max(nextHospitalId_, h.hid + 1); });
    doctors_.forEach([&](const Doctor& d) { nextDoctorId_ = std::max(nextDoctorId_, d.id() + 1); });
    patients_.forEach([&](const Patient& p) { nextPatientId_ = std::max(nextPatientId_, p.id() + 1); });
    appointments_.forEach([&](const Appointment& a) { nextApptId_ = std::max(nextApptId_, a.id + 1); });
    records_.forEach([&](const HealthRecord& r) { nextRecordId_ = std::max(nextRecordId_, r.id + 1); });
}

void HealthcareSystem::seedSampleData() {
    // Fictional hospitals with approximate sample coordinates.
    hospitals_.pushBack({1, "CareBridge City Hospital", "Dehradun", "Clock Tower", 30.3250, 78.0420});
    hospitals_.pushBack({2, "Doon Medical Centre", "Dehradun", "Rajpur Road", 30.3555, 78.0630});
    hospitals_.pushBack({3, "Himalaya Care Hospital", "Dehradun", "ISBT", 30.2890, 78.0440});
    hospitals_.pushBack({4, "Bell Road Health Clinic", "Dehradun", "Bell Road", 30.2705, 77.9985});
    hospitals_.pushBack({5, "Valley Heart & Care", "Dehradun", "Premnagar", 30.3310, 77.9660});

    struct D { const char* name; int hosp; const char* spec; int fee; };
    const D docs[] = {
        {"Dr. Anil Sharma", 1, "General Medicine", 500}, {"Dr. Meera Rawat", 1, "Cardiology", 900},
        {"Dr. Rohit Negi", 2, "Orthopedics", 800},       {"Dr. Sana Khan", 2, "Pediatrics", 600},
        {"Dr. Vikram Joshi", 3, "Neurology", 1000},      {"Dr. Priya Bisht", 4, "General Medicine", 400},
        {"Dr. Karan Mehta", 5, "Dermatology", 700}};
    const char* times[] = {"10:00", "11:00", "15:00"};
    for (const auto& d : docs) {
        Doctor doc(nextDoctorId_++, d.name, util::hashPassword("doctor123"), d.hosp, d.spec, d.fee);
        for (int day = 1; day <= 3; ++day)
            for (const char* t : times) doc.addSlot(util::todayPlus(day) + " " + t);
        doctors_.pushBack(doc);
    }
    patients_.pushBack(Patient(nextPatientId_++, "Demo Patient", util::hashPassword("patient123"), 21,
                               "Other", "9000000000", "Bell Road"));
    nextHospitalId_ = 6;
    save();
}

// =====================================================================
//  Shared helpers
// =====================================================================
string HealthcareSystem::patientName(int id) const {
    const Patient* p = patients_.findIf([id](const Patient& x) { return x.id() == id; });
    return p ? p->name() : "Unknown";
}

void HealthcareSystem::deliverNotifications(int patientId) {
    Notification n;
    int count = 0;
    while (notifications_.extractIf([patientId](const Notification& x) { return x.patientId == patientId; }, n)) {
        if (count++ == 0) cout << "\n*** Notifications ***\n";
        cout << "  - " << n.message << "\n";
    }
    if (count == 0) cout << "  No new notifications.\n";
    else save();
}

Locality HealthcareSystem::chooseLocality(const string& savedName) const {
    const auto& L = localities();
    cout << "\nAvailable areas:\n";
    for (size_t i = 0; i < L.size(); ++i) cout << "  " << (i + 1) << ". " << L[i].name << "\n";
    int lo = savedName.empty() ? 1 : 0;
    string prompt = savedName.empty() ? "Choose your area: " : "Choose area (0 = saved: " + savedName + "): ";
    int c = util::readInt(prompt, lo, static_cast<int>(L.size()));
    if (c == 0) {
        for (const auto& l : L) if (l.name == savedName) return l;
        return L[0];
    }
    return L[c - 1];
}

void HealthcareSystem::listHospitals() const {
    cout << "\n" << std::left << std::setw(5) << "ID" << std::setw(30) << "Hospital" << "Area\n";
    hospitals_.forEach([&](const Hospital& h) {
        cout << std::left << std::setw(5) << h.hid << std::setw(30) << h.hname << h.locality << ", " << h.city << "\n";
    });
}

void HealthcareSystem::printDoctors(const vector<Doctor>& docs) const {
    if (docs.empty()) { cout << "  No doctors found.\n"; return; }
    cout << "\n" << std::left << std::setw(5) << "ID" << std::setw(20) << "Name" << std::setw(18) << "Specialization"
         << std::setw(26) << "Hospital" << std::setw(7) << "Fee" << "Open slots\n";
    for (const auto& d : docs) {
        const Hospital* h = findHospital(d.hospitalId);
        cout << std::left << std::setw(5) << d.id() << std::setw(20) << d.name() << std::setw(18) << d.specialization
             << std::setw(26) << (h ? h->hname : "?") << std::setw(7) << d.fee << d.openSlots().size() << "\n";
    }
}

void HealthcareSystem::printRecord(const HealthRecord& r) const {
    const Doctor* d = findDoctor(r.doctorId);
    cout << "  ------------------------------------------\n"
         << "  Record #" << r.id << "  Date: " << r.date << "\n"
         << "  Patient : " << patientName(r.patientId) << " (#" << r.patientId << ")\n"
         << "  Doctor  : " << (d ? d->name() : "Unknown") << "\n"
         << "  Symptoms: " << r.symptoms << "\n"
         << "  Diagnosis: " << r.diagnosis << "\n"
         << "  Tests   : " << r.tests << "\n"
         << "  Follow-up: " << r.followUp << "\n";
}

// =====================================================================
//  Main menu / authentication
// =====================================================================
void HealthcareSystem::run() {
    cout << "==========================================\n"
         << "   CareBridge - Healthcare Management\n"
         << "   Academic prototype (sample data only)\n"
         << "==========================================\n";
    while (true) {
        cout << "\n=== Main Menu ===\n"
             << " 1. Patient login\n 2. Doctor login\n 3. Register as patient\n"
             << " 4. Register as doctor\n 0. Exit\n";
        switch (util::readInt("Choose: ", 0, 4)) {
            case 1: patientLogin(); break;
            case 2: doctorLogin(); break;
            case 3: registerPatient(); break;
            case 4: registerDoctor(); break;
            case 0: cout << "Goodbye!\n"; return;
        }
    }
}

static string readPassword() {
    while (true) {
        string pw = util::readLine("Password (min 4 chars): ");
        if (pw.size() >= 4) return pw;
        cout << "  Password too short.\n";
    }
}

void HealthcareSystem::registerPatient() {
    cout << "\n--- Patient Registration ---\n";
    string name = util::readNonEmpty("Full name: ");
    int age = util::readInt("Age: ", 0, 120);
    cout << " 1. Male  2. Female  3. Other\n";
    int g = util::readInt("Gender: ", 1, 3);
    string gender = g == 1 ? "Male" : (g == 2 ? "Female" : "Other");
    string phone = util::readNonEmpty("Phone: ");
    Locality loc = chooseLocality("");
    string pw = readPassword();
    Patient p(nextPatientId_++, name, util::hashPassword(pw), age, gender, phone, loc.name);
    patients_.pushBack(p);
    save();
    cout << "Registered! Your Patient ID is " << p.id() << " - use it to log in.\n";
}

void HealthcareSystem::registerDoctor() {
    cout << "\n--- Doctor Registration ---\n";
    string name = util::readNonEmpty("Full name (e.g. Dr. A. Singh): ");
    listHospitals();
    int hid;
    while (true) {
        hid = util::readInt("Hospital ID: ", 1, 1000000);
        if (findHospital(hid)) break;
        cout << "  No such hospital.\n";
    }
    string spec = util::readNonEmpty("Specialization: ");
    int fee = util::readInt("Consultation fee: ", 0, 1000000);
    string pw = readPassword();
    Doctor d(nextDoctorId_++, name, util::hashPassword(pw), hid, spec, fee);
    doctors_.pushBack(d);
    save();
    cout << "Registered! Your Doctor ID is " << d.id() << " - add slots from the doctor menu.\n";
}

void HealthcareSystem::patientLogin() {
    int id = util::readInt("Patient ID: ", 1, 1000000);
    string pw = util::readLine("Password: ");
    Patient* p = findPatient(id);
    if (!p || !p->checkPassword(pw)) { cout << "Invalid ID or password.\n"; return; }
    patientMenu(*p);
}

void HealthcareSystem::doctorLogin() {
    int id = util::readInt("Doctor ID: ", 1, 1000000);
    string pw = util::readLine("Password: ");
    Doctor* d = findDoctor(id);
    if (!d || !d->checkPassword(pw)) { cout << "Invalid ID or password.\n"; return; }
    doctorMenu(*d);
}

// =====================================================================
//  Patient features
// =====================================================================
void HealthcareSystem::patientMenu(Patient& p) {
    cout << "\nWelcome, " << p.name() << "!\n";
    deliverNotifications(p.id());
    while (true) {
        cout << "\n--- Patient Menu ---\n"
             << " 1. Find nearby hospitals\n 2. Browse doctors\n 3. Book an appointment\n"
             << " 4. My appointments (view / cancel)\n 5. My health records\n"
             << " 6. Find doctor by ID (binary search)\n 7. Check notifications\n 0. Logout\n";
        switch (util::readInt("Choose: ", 0, 7)) {
            case 1: showNearbyHospitals(p); break;
            case 2: browseDoctors(); break;
            case 3: bookAppointment(p); break;
            case 4: myAppointments(p); break;
            case 5: viewMyRecords(p); break;
            case 6: findDoctorById(); break;
            case 7: deliverNotifications(p.id()); break;
            case 0: return;
        }
    }
}

void HealthcareSystem::showNearbyHospitals(const Patient& p) const {
    Locality loc = chooseLocality(p.locality);
    struct HD { Hospital h; double km; };
    vector<HD> v;
    hospitals_.forEach([&](const Hospital& h) {
        v.push_back({h, util::haversineKm(loc.lat, loc.lon, h.lat, h.lon)});
    });
    util::mergeSort(v, [](const HD& a, const HD& b) { return a.km < b.km; });
    cout << "\nHospitals near " << loc.name << " (nearest first):\n";
    cout << std::left << std::setw(5) << "ID" << std::setw(30) << "Hospital" << std::setw(16) << "Area" << "Distance\n";
    for (const auto& x : v)
        cout << std::left << std::setw(5) << x.h.hid << std::setw(30) << x.h.hname << std::setw(16) << x.h.locality
             << std::fixed << std::setprecision(1) << x.km << " km\n";
}

void HealthcareSystem::browseDoctors() const {
    cout << "\n 1. By hospital\n 2. By specialization\n 3. All, sorted by fee\n 4. All, sorted by name\n";
    int c = util::readInt("Choose: ", 1, 4);
    vector<Doctor> all = doctors_.toVector(), out;
    if (c == 1) {
        listHospitals();
        int hid = util::readInt("Hospital ID: ", 1, 1000000);
        for (const auto& d : all) if (d.hospitalId == hid) out.push_back(d);
    } else if (c == 2) {
        string s = util::readNonEmpty("Specialization (e.g. cardio): ");
        for (const auto& d : all) if (util::containsIgnoreCase(d.specialization, s)) out.push_back(d);
    } else if (c == 3) {
        out = all;
        util::mergeSort(out, [](const Doctor& a, const Doctor& b) { return a.fee < b.fee; });
    } else {
        out = all;
        util::mergeSort(out, [](const Doctor& a, const Doctor& b) { return a.name() < b.name(); });
    }
    printDoctors(out);
}

void HealthcareSystem::findDoctorById() const {
    vector<Doctor> docs = doctors_.toVector();  // IDs are assigned in ascending order => sorted
    util::mergeSort(docs, [](const Doctor& a, const Doctor& b) { return a.id() < b.id(); });
    int id = util::readInt("Doctor ID: ", 1, 1000000);
    int idx = util::binarySearchById(docs, id);
    if (idx < 0) { cout << "  Doctor not found.\n"; return; }
    printDoctors({docs[idx]});
    cout << "  Open slots:\n";
    for (const auto& s : docs[idx].openSlots()) cout << "    " << s << "\n";
}

void HealthcareSystem::bookAppointment(Patient& p) {
    printDoctors(doctors_.toVector());
    int did = util::readInt("\nDoctor ID (0 to cancel): ", 0, 1000000);
    if (did == 0) return;
    Doctor* d = findDoctor(did);
    if (!d) { cout << "  No such doctor.\n"; return; }
    vector<string> open = d->openSlots();
    if (open.empty()) { cout << "  This doctor has no open slots right now.\n"; return; }
    cout << "Open slots for " << d->name() << ":\n";
    for (size_t i = 0; i < open.size(); ++i) cout << "  " << (i + 1) << ". " << open[i] << "\n";
    int sel = util::readInt("Pick a slot (0 to cancel): ", 0, static_cast<int>(open.size()));
    if (sel == 0) return;
    string when = open[sel - 1];

    bool clash = false;
    appointments_.forEach([&](const Appointment& a) {
        if (a.patientId == p.id() && a.when == when &&
            (a.status == Status::Pending || a.status == Status::Confirmed)) clash = true;
    });
    if (clash) { cout << "  You already have an appointment at that time.\n"; return; }

    cout << " Urgency: 1. Emergency  2. Urgent  3. Routine\n";
    int u = util::readInt("Choose: ", 1, 3);
    string reason = util::readNonEmpty("Symptoms / reason for visit: ");

    d->bookSlot(when);
    Appointment a{nextApptId_++, p.id(), d->id(), d->hospitalId, when, urgencyFromInt(u), Status::Pending, reason};
    appointments_.pushBack(a);
    QueueEntry entry{a.id, d->id(), u, a.id};
    requestQueue_.push(entry);
    save();

    int pos = 1;
    requestQueue_.forEach([&](const QueueEntry& e) {
        if (e.doctorId == d->id() && e.apptId != a.id && QueueEntry::before(e, entry)) ++pos;
    });
    cout << "  Request #" << a.id << " submitted for " << when << " (" << toString(a.urgency)
         << "). Position in " << d->name() << "'s queue: " << pos << ".\n";
}

void HealthcareSystem::myAppointments(Patient& p) {
    vector<Appointment> mine;
    appointments_.forEach([&](const Appointment& a) { if (a.patientId == p.id()) mine.push_back(a); });
    if (mine.empty()) { cout << "  You have no appointments.\n"; return; }
    util::mergeSort(mine, [](const Appointment& a, const Appointment& b) { return a.when < b.when; });
    cout << "\n" << std::left << std::setw(6) << "ID" << std::setw(18) << "When" << std::setw(20) << "Doctor"
         << std::setw(11) << "Urgency" << "Status\n";
    for (const auto& a : mine) {
        const Doctor* d = findDoctor(a.doctorId);
        cout << std::left << std::setw(6) << a.id << std::setw(18) << a.when << std::setw(20) << (d ? d->name() : "?")
             << std::setw(11) << toString(a.urgency) << toString(a.status) << "\n";
    }
    int id = util::readInt("\nEnter appointment ID to cancel (0 = none): ", 0, 1000000);
    if (id == 0) return;
    Appointment* a = findAppointment(id);
    if (!a || a->patientId != p.id()) { cout << "  Not found.\n"; return; }
    if (a->status != Status::Pending && a->status != Status::Confirmed) {
        cout << "  Only pending or confirmed appointments can be cancelled.\n";
        return;
    }
    a->status = Status::Cancelled;
    if (Doctor* d = findDoctor(a->doctorId)) d->freeSlot(a->when);
    requestQueue_.removeIf([id](const QueueEntry& e) { return e.apptId == id; });
    save();
    cout << "  Appointment #" << id << " cancelled and the slot was released.\n";
}

void HealthcareSystem::viewMyRecords(const Patient& p) const {
    vector<HealthRecord> mine;
    records_.forEach([&](const HealthRecord& r) { if (r.patientId == p.id()) mine.push_back(r); });
    if (mine.empty()) { cout << "  No health records yet.\n"; return; }
    util::mergeSort(mine, [](const HealthRecord& a, const HealthRecord& b) { return a.date > b.date; });  // newest first
    cout << "\nYour health records (newest first):\n";
    for (const auto& r : mine) printRecord(r);
}

// =====================================================================
//  Doctor features
// =====================================================================
void HealthcareSystem::doctorMenu(Doctor& d) {
    cout << "\nWelcome, " << d.name() << "!\n";
    while (true) {
        cout << "\n--- Doctor Menu ---\n"
             << " 1. View pending requests (priority order)\n 2. Process next request\n"
             << " 3. My confirmed schedule\n 4. Add availability slot\n 5. Remove an open slot\n"
             << " 6. Search patient / view profile\n 7. Add health record\n 8. Update health record\n"
             << " 9. Recently viewed patients\n 0. Logout\n";
        switch (util::readInt("Choose: ", 0, 9)) {
            case 1: viewPendingRequests(d); break;
            case 2: processNextRequest(d); break;
            case 3: viewSchedule(d); break;
            case 4: addSlot(d); break;
            case 5: removeSlot(d); break;
            case 6: searchPatient(d); break;
            case 7: addRecord(d); break;
            case 8: updateRecord(d); break;
            case 9: showRecentPatients(); break;
            case 0: return;
        }
    }
}

void HealthcareSystem::viewPendingRequests(const Doctor& d) const {
    int n = 0;
    cout << "\nPending requests (highest priority first):\n";
    requestQueue_.forEach([&](const QueueEntry& e) {
        if (e.doctorId != d.id()) return;
        const Appointment* a = appointments_.findIf([&](const Appointment& x) { return x.id == e.apptId; });
        if (!a) return;
        cout << "  " << ++n << ". [#" << a->id << "] " << std::left << std::setw(10) << toString(a->urgency)
             << std::setw(18) << a->when << std::setw(18) << patientName(a->patientId) << a->reason << "\n";
    });
    if (n == 0) cout << "  No pending requests.\n";
}

void HealthcareSystem::processNextRequest(Doctor& d) {
    QueueEntry e;
    int did = d.id();
    if (!requestQueue_.extractIf([did](const QueueEntry& x) { return x.doctorId == did; }, e)) {
        cout << "  No pending requests.\n";
        return;
    }
    Appointment* a = findAppointment(e.apptId);
    if (!a) return;
    cout << "\nNext request: #" << a->id << " | " << toString(a->urgency) << " | " << a->when << "\n"
         << "  Patient: " << patientName(a->patientId) << " (#" << a->patientId << ")\n"
         << "  Reason : " << a->reason << "\n 1. Confirm  2. Reject  3. Put back in queue\n";
    int c = util::readInt("Choose: ", 1, 3);
    if (c == 1) {
        a->status = Status::Confirmed;
        notify(a->patientId, "Your appointment #" + std::to_string(a->id) + " with " + d.name() + " on " + a->when + " is CONFIRMED.");
        cout << "  Confirmed.\n";
    } else if (c == 2) {
        a->status = Status::Rejected;
        d.freeSlot(a->when);
        notify(a->patientId, "Your appointment #" + std::to_string(a->id) + " with " + d.name() + " on " + a->when + " was REJECTED. Please book another slot.");
        cout << "  Rejected; slot released.\n";
    } else {
        requestQueue_.push(e);
        cout << "  Request returned to the queue.\n";
    }
    save();
}

void HealthcareSystem::viewSchedule(const Doctor& d) const {
    vector<Appointment> mine;
    appointments_.forEach([&](const Appointment& a) {
        if (a.doctorId == d.id() && a.status == Status::Confirmed) mine.push_back(a);
    });
    if (mine.empty()) { cout << "  No confirmed appointments.\n"; return; }
    util::mergeSort(mine, [](const Appointment& a, const Appointment& b) { return a.when < b.when; });
    cout << "\nConfirmed schedule:\n";
    for (const auto& a : mine)
        cout << "  [#" << a.id << "] " << a.when << " | " << patientName(a.patientId) << " (#" << a.patientId
             << ") | " << a.reason << "\n";
    cout << "\nSlots: ";
    int open = 0, booked = 0;
    for (const auto& s : d.slots) (s.booked ? booked : open)++;
    cout << open << " open, " << booked << " booked.\n";
}

void HealthcareSystem::addSlot(Doctor& d) {
    string date, time;
    while (true) {
        date = util::readLine("Date (YYYY-MM-DD): ");
        if (util::validDate(date)) break;
        cout << "  Invalid date format.\n";
    }
    while (true) {
        time = util::readLine("Time (HH:MM, 24h): ");
        if (util::validTime(time)) break;
        cout << "  Invalid time format.\n";
    }
    if (d.addSlot(date + " " + time)) { save(); cout << "  Slot added.\n"; }
    else cout << "  That slot already exists.\n";
}

void HealthcareSystem::removeSlot(Doctor& d) {
    vector<string> open = d.openSlots();
    if (open.empty()) { cout << "  No open slots to remove.\n"; return; }
    for (size_t i = 0; i < open.size(); ++i) cout << "  " << (i + 1) << ". " << open[i] << "\n";
    int sel = util::readInt("Remove which slot (0 to cancel): ", 0, static_cast<int>(open.size()));
    if (sel == 0) return;
    if (d.removeOpenSlot(open[sel - 1])) { save(); cout << "  Slot removed (closed).\n"; }
}

void HealthcareSystem::searchPatient(const Doctor&) {
    cout << " 1. By patient ID  2. By name\n";
    int c = util::readInt("Choose: ", 1, 2);
    Patient* found = nullptr;
    if (c == 1) {
        found = findPatient(util::readInt("Patient ID: ", 1, 1000000));
    } else {
        string q = util::readNonEmpty("Name contains: ");
        vector<Patient> matches;
        patients_.forEach([&](const Patient& p) { if (util::containsIgnoreCase(p.name(), q)) matches.push_back(p); });
        if (matches.empty()) { cout << "  No match.\n"; return; }
        for (const auto& m : matches) m.display();
        if (matches.size() == 1) found = findPatient(matches[0].id());
        else found = findPatient(util::readInt("Open which patient ID? ", 1, 1000000));
    }
    if (!found) { cout << "  Patient not found.\n"; return; }
    recentPatients_.push(found->id());
    cout << "\n";
    found->display();
    bool any = false;
    records_.forEach([&](const HealthRecord& r) { if (r.patientId == found->id()) { printRecord(r); any = true; } });
    if (!any) cout << "  (No health records for this patient.)\n";
}

void HealthcareSystem::addRecord(Doctor& d) {
    Patient* p = findPatient(util::readInt("Patient ID: ", 1, 1000000));
    if (!p) { cout << "  Patient not found.\n"; return; }
    recentPatients_.push(p->id());
    HealthRecord r{nextRecordId_++, p->id(), d.id(), util::todayPlus(0), "", "", "", ""};
    r.symptoms = util::readNonEmpty("Symptoms: ");
    r.diagnosis = util::readNonEmpty("Diagnosis: ");
    r.tests = util::readOptional("Tests advised (blank = none): ");
    r.followUp = util::readOptional("Future visit / follow-up (blank = none): ");
    if (r.tests.empty()) r.tests = "None";
    if (r.followUp.empty()) r.followUp = "None";
    records_.pushBack(r);

    // Mark the earliest confirmed appointment between this pair as completed.
    Appointment* best = nullptr;
    appointments_.forEach([&](Appointment& a) {
        if (a.doctorId == d.id() && a.patientId == p->id() && a.status == Status::Confirmed &&
            (!best || a.when < best->when)) best = &a;
    });
    if (best) best->status = Status::Completed;

    notify(p->id(), "New health record #" + std::to_string(r.id) + " added by " + d.name() +
                        (r.followUp != "None" ? ". Follow-up: " + r.followUp : "."));
    save();
    cout << "  Record #" << r.id << " saved." << (best ? " Appointment #" + std::to_string(best->id) + " marked completed." : "") << "\n";
}

void HealthcareSystem::updateRecord(Doctor& d) {
    HealthRecord* r = findRecord(util::readInt("Record ID: ", 1, 1000000));
    if (!r) { cout << "  Record not found.\n"; return; }
    printRecord(*r);
    cout << "Leave a field blank to keep it unchanged.\n";
    string s;
    if (!(s = util::readOptional("New symptoms: ")).empty()) r->symptoms = s;
    if (!(s = util::readOptional("New diagnosis: ")).empty()) r->diagnosis = s;
    if (!(s = util::readOptional("New tests: ")).empty()) r->tests = s;
    if (!(s = util::readOptional("New follow-up: ")).empty()) r->followUp = s;
    r->doctorId = d.id();
    notify(r->patientId, "Your health record #" + std::to_string(r->id) + " was updated by " + d.name() + ".");
    save();
    cout << "  Record updated.\n";
}

void HealthcareSystem::showRecentPatients() const {
    if (recentPatients_.empty()) { cout << "  No patients viewed this session.\n"; return; }
    cout << "Recently viewed patients (latest first):\n";
    recentPatients_.forEach([&](const int& id) { cout << "  #" << id << " " << patientName(id) << "\n"; });
}
