// HealthcareSystem.h - CareBridge application core (menus, business logic, file storage).
#pragma once
#include <string>
#include <vector>
#include "DataStructures.h"
#include "Models.h"

class HealthcareSystem {
public:
    explicit HealthcareSystem(const std::string& dataDir = "data");
    void run();

private:
    // ---- storage ----
    std::string dataDir_;
    std::string path(const std::string& file) const { return dataDir_ + "/" + file; }
    void load();
    void save() const;
    void seedSampleData();
    void loadFile(const std::string& file,
                  const std::function<void(const std::vector<std::string>&)>& handler) const;
    void recomputeIds();

    // ---- data (linked lists / queues / stack) ----
    LinkedList<Hospital> hospitals_;
    LinkedList<Doctor> doctors_;
    LinkedList<Patient> patients_;
    LinkedList<Appointment> appointments_;
    LinkedList<HealthRecord> records_;
    Queue<Notification> notifications_;
    PriorityQueue<QueueEntry> requestQueue_;
    Stack<int> recentPatients_;

    int nextHospitalId_ = 1, nextDoctorId_ = 1, nextPatientId_ = 1, nextApptId_ = 1, nextRecordId_ = 1;

    // ---- lookups ----
    Doctor* findDoctor(int id) { return doctors_.findIf([id](const Doctor& d) { return d.id() == id; }); }
    const Doctor* findDoctor(int id) const { return doctors_.findIf([id](const Doctor& d) { return d.id() == id; }); }
    Patient* findPatient(int id) { return patients_.findIf([id](const Patient& p) { return p.id() == id; }); }
    const Hospital* findHospital(int id) const { return hospitals_.findIf([id](const Hospital& h) { return h.hid == id; }); }
    Appointment* findAppointment(int id) { return appointments_.findIf([id](const Appointment& a) { return a.id == id; }); }
    HealthRecord* findRecord(int id) { return records_.findIf([id](const HealthRecord& r) { return r.id == id; }); }

    // ---- shared helpers ----
    void notify(int patientId, const std::string& msg) { notifications_.enqueue({patientId, msg}); }
    void deliverNotifications(int patientId);
    Locality chooseLocality(const std::string& savedName) const;
    void listHospitals() const;
    void printDoctors(const std::vector<Doctor>& docs) const;
    void printRecord(const HealthRecord& r) const;
    std::string patientName(int id) const;

    // ---- main menu / auth ----
    void registerPatient();
    void registerDoctor();
    void patientLogin();
    void doctorLogin();

    // ---- patient features ----
    void patientMenu(Patient& p);
    void showNearbyHospitals(const Patient& p) const;
    void browseDoctors() const;
    void bookAppointment(Patient& p);
    void myAppointments(Patient& p);
    void viewMyRecords(const Patient& p) const;
    void findDoctorById() const;

    // ---- doctor features ----
    void doctorMenu(Doctor& d);
    void viewPendingRequests(const Doctor& d) const;
    void processNextRequest(Doctor& d);
    void viewSchedule(const Doctor& d) const;
    void addSlot(Doctor& d);
    void removeSlot(Doctor& d);
    void searchPatient(const Doctor& d);
    void addRecord(Doctor& d);
    void updateRecord(Doctor& d);
    void showRecentPatients() const;
};
