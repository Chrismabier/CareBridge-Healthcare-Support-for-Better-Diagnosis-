CXX      ?= g++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O2
SRC      := src/main.cpp src/HealthcareSystem.cpp
WEB_DIR  := web

all: carebridge

carebridge: $(SRC) $(wildcard src/*.h)
	$(CXX) $(CXXFLAGS) -o $@ $(SRC)

test_structures: tests/test_structures.cpp $(wildcard src/*.h)
	$(CXX) $(CXXFLAGS) -Isrc -o $@ tests/test_structures.cpp

test: test_structures
	./test_structures

run: carebridge
	./carebridge

# ---- web deployment -------------------------------------------------------
# Builds the C++ binary if needed, then serves the browser console.
web: carebridge
	cd $(WEB_DIR) && npm run build

serve: web
	cd $(WEB_DIR) && npm start

docker-build:
	docker build -t carebridge:latest .

docker-run: docker-build
	docker run --rm -p 3000:3000 carebridge:latest


# ---- Bridge AI Assistant (assistant/, Python/FastAPI) ---------------------
assistant-setup:
	cd assistant && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

assistant: ## run the AI assistant on http://localhost:8000
	cd assistant && .venv/bin/python run.py

assistant-test:
	cd assistant && .venv/bin/python tests/test_assistant.py

.PHONY: all test run clean web serve docker-build docker-run assistant-setup assistant assistant-test

clean:
	rm -f carebridge test_structures carebridge.exe test_structures.exe
