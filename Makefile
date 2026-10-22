CXX      ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O2
SRC      := src/main.cpp src/HealthcareSystem.cpp

all: carebridge

carebridge: $(SRC) $(wildcard src/*.h)
	$(CXX) $(CXXFLAGS) -o $@ $(SRC)

test_structures: tests/test_structures.cpp $(wildcard src/*.h)
	$(CXX) $(CXXFLAGS) -Isrc -o $@ tests/test_structures.cpp

test: test_structures
	./test_structures

run: carebridge
	./carebridge

clean:
	rm -f carebridge test_structures carebridge.exe test_structures.exe

.PHONY: all test run clean
