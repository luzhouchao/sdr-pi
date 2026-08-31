CXX ?= c++
CXXFLAGS ?= -O2 -std=c++20 -Wall -Wextra -Wpedantic -Werror
CPPFLAGS ?= -Iinclude

.PHONY: all test clean

all: build/sdr-model-inspect

build/backend_test: src/backend.cpp tests/backend_test.cpp include/sdr/recognizer/backend.hpp
	@mkdir -p build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/backend.cpp tests/backend_test.cpp -o $@

build/model_loader_test: src/backend.cpp src/model_loader.cpp tests/model_loader_test.cpp include/sdr/recognizer/backend.hpp include/sdr/recognizer/model_loader.hpp
	@mkdir -p build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/backend.cpp src/model_loader.cpp tests/model_loader_test.cpp -o $@

build/sdr-model-inspect: src/backend.cpp src/model_loader.cpp src/model_inspect.cpp include/sdr/recognizer/backend.hpp include/sdr/recognizer/model_loader.hpp
	@mkdir -p build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) src/backend.cpp src/model_loader.cpp src/model_inspect.cpp -o $@

test: build/backend_test build/model_loader_test
	./build/backend_test
	./build/model_loader_test

clean:
	rm -rf build
