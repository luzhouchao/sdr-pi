CC ?= gcc
PYTHON ?= python3
BUILD_DIR ?= build
WITH_LIBIIO ?= 0
IIO_DLOPEN ?= 0

CFLAGS ?= -std=c11 -Wall -Wextra -Wpedantic -Werror -O2
CPPFLAGS ?=
LDFLAGS ?=
LDLIBS ?=

BENCH := $(BUILD_DIR)/p201_highres_iio_bench

ifeq ($(WITH_LIBIIO),1)
CPPFLAGS += -DP201_HIGHRES_WITH_LIBIIO=1
ifeq ($(IIO_DLOPEN),1)
CPPFLAGS += -DP201_HIGHRES_IIO_DLOPEN=1
LDLIBS += -ldl
else
IIO_CFLAGS := $(shell pkg-config --cflags libiio 2>/dev/null)
IIO_LIBS := $(shell pkg-config --libs libiio 2>/dev/null || echo -liio)
CPPFLAGS += $(IIO_CFLAGS)
LDLIBS += $(IIO_LIBS)
endif
else
CPPFLAGS += -DP201_HIGHRES_WITH_LIBIIO=0
endif

.PHONY: all bench iio smoke pycheck clean

all: bench

bench: $(BENCH)

iio:
	$(MAKE) WITH_LIBIIO=1 bench

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BENCH): src/p201_highres_iio_bench.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ $< $(LDFLAGS) $(LDLIBS)

smoke: bench pycheck
	./$(BENCH) --fake --sample-count 128 --repeat 3 > $(BUILD_DIR)/highres_iio_fake.json
	$(PYTHON) scripts/run_highres_iio_bench.py --smoke-json $(BUILD_DIR)/highres_iio_fake.json

pycheck:
	$(PYTHON) -m py_compile scripts/run_highres_iio_bench.py

clean:
	rm -rf $(BUILD_DIR)
