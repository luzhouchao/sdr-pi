CC ?= cc
CPPFLAGS ?=
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror
LDFLAGS ?=
BUILD_DIR ?= build
FPGA_NATIVE_DIR ?= ../../fpga/nx_experiments/sdr_fpga_offload_test/native

CPPFLAGS += -Iinclude -I$(FPGA_NATIVE_DIR)
COMMON_SOURCES := src/sdrd.c src/sdrd_iio.c src/sdrd_fpga.c $(FPGA_NATIVE_DIR)/p201_native_mmio.c
LDLIBS += -ldl -pthread
DAEMON := $(BUILD_DIR)/sdrd
TEST := $(BUILD_DIR)/test_sdrd

.PHONY: all test clean

all: $(DAEMON)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(DAEMON): src/main.c $(COMMON_SOURCES) include/sdrd.h include/sdrd_iio.h include/sdrd_fpga.h $(FPGA_NATIVE_DIR)/p201_native_mmio.h | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ src/main.c $(COMMON_SOURCES) $(LDFLAGS) $(LDLIBS)

$(TEST): tests/test_sdrd.c $(COMMON_SOURCES) include/sdrd.h include/sdrd_iio.h include/sdrd_fpga.h $(FPGA_NATIVE_DIR)/p201_native_mmio.h | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ tests/test_sdrd.c $(COMMON_SOURCES) $(LDFLAGS) $(LDLIBS)

test: $(TEST)
	./$(TEST)

clean:
	rm -rf $(BUILD_DIR)
