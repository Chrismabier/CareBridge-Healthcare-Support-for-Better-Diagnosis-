// CareBridge - Healthcare Management System (C++17, Data Structures + OOP)
// Usage: ./carebridge [data_directory]
#include <iostream>
#include "HealthcareSystem.h"

int main(int argc, char** argv) {
    std::string dataDir = (argc > 1) ? argv[1] : "data";
    try {
        HealthcareSystem system(dataDir);
        system.run();
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
