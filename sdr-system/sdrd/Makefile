CC ?= cc
CPPFLAGS ?=
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror
LDFLAGS ?=
BUILD_DIR ?= build
FPGA_NATIVE_DIR ?= ../../fpga/nx_experiments/sdr_fpga_offload_test/native
ENABLE_FPGA ?= 0

CPPFLAGS += -Iinclude
BASE_SOURCES := src/sdrd.c src/sdrd_iio.c
FPGA_SOURCES := src/sdrd_fpga.c $(FPGA_NATIVE_DIR)/p201_native_mmio.c
ifeq ($(ENABLE_FPGA),1)
DAEMON_SOURCES := $(BASE_SOURCES) $(FPGA_SOURCES)
DAEMON_CPPFLAGS := -DSDRD_ENABLE_FPGA=1 -I$(FPGA_NATIVE_DIR)
DAEMON_HEADERS := $(FPGA_NATIVE_DIR)/p201_native_mmio.h
else
DAEMON_SOURCES := $(BASE_SOURCES) src/sdrd_fpga_disabled.c
DAEMON_CPPFLAGS :=
DAEMON_HEADERS :=
endif
TEST_SOURCES := $(BASE_SOURCES) $(FPGA_SOURCES)
TEST_CPPFLAGS := -DSDRD_ENABLE_FPGA=1 -I$(FPGA_NATIVE_DIR)
LDLIBS += -ldl -pthread
DAEMON := $(BUILD_DIR)/sdrd
TEST := $(BUILD_DIR)/test_sdrd

.PHONY: all test clean

all: $(DAEMON)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(DAEMON): src/main.c $(DAEMON_SOURCES) include/sdrd.h include/sdrd_iio.h include/sdrd_fpga.h $(DAEMON_HEADERS) | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(DAEMON_CPPFLAGS) $(CFLAGS) -o $@ src/main.c $(DAEMON_SOURCES) $(LDFLAGS) $(LDLIBS)

$(TEST): tests/test_sdrd.c $(TEST_SOURCES) include/sdrd.h include/sdrd_iio.h include/sdrd_fpga.h $(FPGA_NATIVE_DIR)/p201_native_mmio.h | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(TEST_CPPFLAGS) $(CFLAGS) -o $@ tests/test_sdrd.c $(TEST_SOURCES) $(LDFLAGS) $(LDLIBS)

test: $(TEST)
	$(TEST)

clean:
	rm -rf $(BUILD_DIR)
