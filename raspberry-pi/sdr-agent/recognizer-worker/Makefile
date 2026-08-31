CXX ?= c++
CXXFLAGS ?= -O2 -std=c++20 -Wall -Wextra -Wpedantic -Werror
CPPFLAGS ?= -Iinclude

.PHONY: all test clean

all: build/backend_test

build/backend_test: src/backend.cpp tests/backend_test.cpp include/sdr/recognizer/backend.hpp
	@mkdir -p build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/backend.cpp tests/backend_test.cpp -o $@

test: build/backend_test
	./build/backend_test

clean:
	rm -rf build
