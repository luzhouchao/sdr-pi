CC ?= cc
CPPFLAGS ?=
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic -Werror
LDFLAGS ?=
BUILD_DIR ?= build
ENABLE_FPGA ?= 0

ifneq ($(ENABLE_FPGA),0)
$(error ENABLE_FPGA was retired from the SDR Agent project on 2026-09-02; use the Linux/IIO RX to AGX software path)
endif

CPPFLAGS += -Iinclude
BASE_SOURCES := src/sdrd.c src/sdrd_iio.c
DAEMON_SOURCES := $(BASE_SOURCES)
TEST_SOURCES := $(DAEMON_SOURCES)
LDLIBS += -ldl -pthread
DAEMON := $(BUILD_DIR)/sdrd
TEST := $(BUILD_DIR)/test_sdrd
LIVE_TIMEOUT_TEST := $(BUILD_DIR)/live_timeout_restore

.PHONY: all test live-timeout-test clean

all: $(DAEMON)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(DAEMON): src/main.c $(DAEMON_SOURCES) include/sdrd.h include/sdrd_iio.h | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ src/main.c $(DAEMON_SOURCES) $(LDFLAGS) $(LDLIBS)

$(TEST): tests/test_sdrd.c $(TEST_SOURCES) include/sdrd.h include/sdrd_iio.h | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ tests/test_sdrd.c $(TEST_SOURCES) $(LDFLAGS) $(LDLIBS)

test: $(TEST)
	$(TEST)

$(LIVE_TIMEOUT_TEST): tests/live_timeout_restore.c $(TEST_SOURCES) include/sdrd.h include/sdrd_iio.h | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ tests/live_timeout_restore.c $(TEST_SOURCES) $(LDFLAGS) $(LDLIBS)

live-timeout-test: $(LIVE_TIMEOUT_TEST)

clean:
	rm -rf $(BUILD_DIR)
