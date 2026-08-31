#define _POSIX_C_SOURCE 200809L

#include "p201_native_mmio.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void require_true(int condition, const char *message) {
  if (!condition) {
    fprintf(stderr, "FAIL: %s\n", message);
    exit(1);
  }
}

static void require_rc(int rc, const char *message) {
  if (rc != 0) {
    fprintf(stderr, "FAIL: %s: rc=%d errno_name=%s\n", message, rc, strerror(-rc));
    exit(1);
  }
}

static void put32(p201_mmio_t *ctx, uint32_t offset, uint32_t value) {
  require_rc(p201_mmio_write32(ctx, offset, value), "write32 fixture");
}

static void seed_sum8_fixture(p201_mmio_t *ctx, uint32_t sequence, uint32_t last_frame, uint32_t control) {
  put32(ctx, 0x040u, P201_SUM8_MAGIC);
  put32(ctx, 0x0ECu, P201_SUM8_ABI_VERSION);
  put32(ctx, 0x0F0u, P201_SUM8_CAPABILITY);
  put32(ctx, 0x0FCu, 0x56384430u);
  put32(ctx, 0x100u, P201_QUA8_MAGIC);
  put32(ctx, 0x138u, P201_QUA8_CAPABILITY);
  put32(ctx, 0x13Cu, 0x51384430u);
  put32(ctx, 0x17Cu, sequence);
  put32(ctx, 0x180u, P201_AGG8_MAGIC);
  put32(ctx, 0x184u, control);
  put32(ctx, 0x188u, 16u);
  put32(ctx, 0x18Cu, 16u);
  put32(ctx, 0x190u, 1024u);
  put32(ctx, 0x194u, 0x00001000u);
  put32(ctx, 0x198u, 0x00000020u);
  put32(ctx, 0x19Cu, 0x00000000u);
  put32(ctx, 0x1A0u, 0x00002000u);
  put32(ctx, 0x1A4u, 0x00000030u);
  put32(ctx, 0x1A8u, 0x00000000u);
  put32(ctx, 0x1ACu, 0x00000011u);
  put32(ctx, 0x1B0u, 0x00000022u);
  put32(ctx, 0x1B4u, 0x00000000u);
  put32(ctx, 0x1B8u, 0x00000033u);
  put32(ctx, 0x1BCu, 0x00000044u);
  put32(ctx, 0x1C0u, 0x00000000u);
  put32(ctx, 0x1C4u, 0x00000055u);
  put32(ctx, 0x1C8u, 0x00000066u);
  put32(ctx, 0x1CCu, 0x00000000u);
  put32(ctx, 0x1D0u, 0x00000077u);
  put32(ctx, 0x1D4u, 0x00000088u);
  put32(ctx, 0x1D8u, 0x00000000u);
  put32(ctx, 0x1DCu, 1u);
  put32(ctx, 0x1E0u, 2u);
  put32(ctx, 0x1E4u, 3u);
  put32(ctx, 0x1E8u, 4u);
  put32(ctx, 0x1ECu, 5u);
  put32(ctx, 0x1F0u, last_frame);
  put32(ctx, 0x1F4u, P201_AGG8_AUTOROLL_CAPABILITY);
  put32(ctx, 0x1F8u, 0x41384430u);
  put32(ctx, 0x1FCu, P201_SUM8_MAX_AGG_FRAMES);
}

int main(void) {
  char path[] = "/tmp/p201_native_mmio_test_XXXXXX";
  int fd = mkstemp(path);
  p201_mmio_t *ctx = NULL;
  p201_sum8_snapshot_t snap;
  uint32_t value = 0u;

  require_true(fd >= 0, "mkstemp");
  require_true(ftruncate(fd, P201_TAP_SPAN_BYTES) == 0, "ftruncate fake register file");
  require_true(close(fd) == 0, "close fake register seed fd");

  ctx = p201_mmio_create();
  require_true(ctx != NULL, "p201_mmio_create");
  require_rc(p201_mmio_open(ctx, path, 0u, P201_TAP_SPAN_BYTES, P201_MMIO_OPEN_PLAIN), "open fake register file");

  seed_sum8_fixture(ctx, 7u, 100u, (1u << 4));
  require_rc(p201_mmio_read32(ctx, 0x040u, &value), "read summary magic");
  require_true(value == P201_SUM8_MAGIC, "read32 returns seeded SUM8 magic");

  require_rc(p201_sum8_read_snapshot(ctx, 64u, 16u, &snap), "read first SUM8 snapshot");
  require_true(snap.status_flags == 0u, "first snapshot status is clean");
  require_true(snap.agg_samples == 1024u, "snapshot sample count");
  require_true(snap.rx0_corr_power_num.mid == 0x20u, "snapshot U96 field");
  require_true(snap.elapsed_ns > 0u, "snapshot has elapsed time");

  require_rc(p201_sum8_read_snapshot(ctx, 64u, 16u, &snap), "read repeated SUM8 snapshot");
  require_true((snap.status_flags & P201_SUM8_STATUS_STALE_FRAME) != 0u, "repeated snapshot is stale");

  p201_mmio_reset_stale_state(ctx);
  seed_sum8_fixture(ctx, 8u, 101u, (1u << 4) | (1u << 5));
  require_rc(p201_sum8_read_snapshot(ctx, 64u, 16u, &snap), "read overflow SUM8 snapshot");
  require_true((snap.status_flags & P201_SUM8_STATUS_AGG_OVERFLOW) != 0u, "overflow flag detected");

  put32(ctx, 0x040u, 0xDEADBEEFu);
  require_rc(p201_sum8_read_snapshot(ctx, 64u, 16u, &snap), "read invalid identity snapshot");
  require_true((snap.status_flags & P201_SUM8_STATUS_INVALID_IDENTITY) != 0u, "invalid identity detected");

  require_true(p201_mmio_read32(ctx, P201_TAP_SPAN_BYTES, &value) == -ERANGE, "out-of-range read rejected");

  p201_mmio_destroy(ctx);
  require_true(unlink(path) == 0, "unlink fake register file");
  puts("p201_native_mmio fake-register tests PASS");
  return 0;
}
