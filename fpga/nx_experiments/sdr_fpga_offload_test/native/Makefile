CC ?= gcc
CFLAGS ?= -std=c11 -Wall -Wextra -Wpedantic -Werror -O2 -fPIC
LDFLAGS ?=
BUILD_DIR ?= build

LIB := $(BUILD_DIR)/libp201_native_mmio.so
TEST := $(BUILD_DIR)/test_p201_native_mmio
PROBE := $(BUILD_DIR)/p201_sum8_native_probe

.PHONY: all lib test probe clean

all: lib test probe

lib: $(LIB)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(LIB): p201_native_mmio.c p201_native_mmio.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -shared -o $@ p201_native_mmio.c $(LDFLAGS)

$(TEST): test_p201_native_mmio.c p201_native_mmio.c p201_native_mmio.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ test_p201_native_mmio.c p201_native_mmio.c $(LDFLAGS)

$(PROBE): p201_sum8_native_probe.c p201_native_mmio.c p201_native_mmio.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -o $@ p201_sum8_native_probe.c p201_native_mmio.c $(LDFLAGS)

test: $(TEST)
	./$(TEST)

probe: $(PROBE)

clean:
	rm -rf $(BUILD_DIR)
