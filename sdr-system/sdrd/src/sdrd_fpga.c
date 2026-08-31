#define _POSIX_C_SOURCE 200809L

#include "sdrd_fpga.h"

#include "p201_native_mmio.h"

#include <errno.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct sdrd_fpga_adapter {
  p201_mmio_t *mmio;
  atomic_int cancel_requested;
};

static uint64_t monotonic_ns(void) {
  struct timespec now;
  if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
    return 0u;
  }
  return (uint64_t)now.tv_sec * 1000000000u + (uint64_t)now.tv_nsec;
}

static void sleep_one_ms(void) {
  struct timespec wait = {0, 1000000L};
  while (nanosleep(&wait, &wait) != 0 && errno == EINTR) {
  }
}

static int adapter_begin_summary(void *context) {
  sdrd_fpga_adapter_t *adapter = context;
  if (adapter == NULL) {
    return -EINVAL;
  }
  atomic_store(&adapter->cancel_requested, 0);
  return 0;
}

static int adapter_cancel_summary(void *context) {
  sdrd_fpga_adapter_t *adapter = context;
  if (adapter == NULL) {
    return -EINVAL;
  }
  atomic_store(&adapter->cancel_requested, 1);
  return 0;
}

static void set_error(char *error, size_t error_size, const char *message) {
  if (error != NULL && error_size > 0u) {
    (void)snprintf(error, error_size, "%s", message);
  }
}

static int adapter_capture_summary(
    void *context,
    const sdrd_summary_request_t *request,
    sdrd_summary_result_t *result) {
  sdrd_fpga_adapter_t *adapter = context;
  p201_sum8_snapshot_t snapshot;
  uint64_t poll_elapsed_ns = 0u;
  uint64_t poll_started_ns;
  uint64_t timeout_ns;
  uint64_t samples;
  uint32_t control = 0u;
  int rc;
  if (adapter == NULL || request == NULL || result == NULL) {
    return -EINVAL;
  }
  if (request->frame_samples < 64u || request->frame_samples > 65535u ||
      request->aggregate_frames == 0u ||
      request->aggregate_frames > P201_SUM8_MAX_AGG_FRAMES ||
      request->timeout_ms == 0u || request->timeout_ms > 5000u) {
    return -ERANGE;
  }
  samples = (uint64_t)request->frame_samples * (uint64_t)request->aggregate_frames;
  if (atomic_load(&adapter->cancel_requested) != 0) {
    return -ECANCELED;
  }
  p201_mmio_reset_stale_state(adapter->mmio);
  rc = p201_sum8_arm_aggregate(
      adapter->mmio, request->frame_samples, request->aggregate_frames);
  if (rc != 0) {
    return rc;
  }
  poll_started_ns = monotonic_ns();
  timeout_ns = (uint64_t)request->timeout_ms * 1000000u;
  for (;;) {
    const uint64_t now_ns = monotonic_ns();
    if (atomic_load(&adapter->cancel_requested) != 0) {
      return -ECANCELED;
    }
    rc = p201_mmio_read32(adapter->mmio, 0x184u, &control);
    if (rc != 0) {
      return rc;
    }
    if ((control & (1u << 4)) != 0u) {
      poll_elapsed_ns = now_ns - poll_started_ns;
      break;
    }
    if (now_ns - poll_started_ns >= timeout_ns) {
      return -ETIMEDOUT;
    }
    sleep_one_ms();
  }
  rc = p201_sum8_read_snapshot(
      adapter->mmio, request->frame_samples, request->aggregate_frames, &snapshot);
  if (rc != 0) {
    return rc;
  }
  memset(result, 0, sizeof(*result));
  result->sequence = snapshot.agg_sequence;
  result->aggregate_samples = snapshot.agg_samples;
  result->rx0_power_lo = snapshot.rx0_raw_power.lo;
  result->rx0_power_mid = snapshot.rx0_raw_power.mid;
  result->rx0_power_hi = snapshot.rx0_raw_power.hi;
  result->rx0_clip_count = snapshot.rx0_clip_count;
  result->status_flags = snapshot.status_flags;
  result->elapsed_us = (poll_elapsed_ns + snapshot.elapsed_ns) / 1000u;
  if (result->aggregate_samples != samples) {
    result->status_flags |= P201_SUM8_STATUS_SAMPLE_MISMATCH;
  }
  return 0;
}

int sdrd_fpga_adapter_create(
    const sdrd_config_t *config,
    sdrd_fpga_adapter_t **out,
    char *error,
    size_t error_size) {
  sdrd_fpga_adapter_t *adapter;
  sdrd_status_t status;
  uint32_t flags = P201_MMIO_OPEN_SYNC;
  uint64_t offset = 0u;
  int rc;
  if (config == NULL || out == NULL) {
    return -EINVAL;
  }
  *out = NULL;
  if (config->fpga_backend == SDRD_FPGA_DISABLED) {
    return -ENODEV;
  }
  rc = sdrd_probe_status(config, &status, error, error_size);
  if (rc != 0 || status.fpga_identity_valid == 0) {
    set_error(error, error_size, "FPGA aggregate identity probe failed");
    return rc != 0 ? rc : -ENODEV;
  }
  adapter = calloc(1u, sizeof(*adapter));
  if (adapter == NULL) {
    set_error(error, error_size, "FPGA adapter allocation failed");
    return -ENOMEM;
  }
  atomic_init(&adapter->cancel_requested, 0);
  adapter->mmio = p201_mmio_create();
  if (adapter->mmio == NULL) {
    free(adapter);
    set_error(error, error_size, "FPGA MMIO allocation failed");
    return -ENOMEM;
  }
  if (config->fpga_backend == SDRD_FPGA_DEVMEM) {
    flags |= P201_MMIO_OPEN_DEVMEM;
    offset = config->fpga_base;
  }
  rc = p201_mmio_open(
      adapter->mmio, config->fpga_device, offset, config->fpga_span, flags);
  if (rc != 0) {
    sdrd_fpga_adapter_destroy(adapter);
    set_error(error, error_size, "FPGA writable MMIO open failed");
    return rc;
  }
  *out = adapter;
  return 0;
}

void sdrd_fpga_adapter_destroy(sdrd_fpga_adapter_t *adapter) {
  if (adapter == NULL) {
    return;
  }
  p201_mmio_destroy(adapter->mmio);
  free(adapter);
}

void sdrd_fpga_adapter_attach(sdrd_fpga_adapter_t *adapter, sdrd_radio_ops_t *ops) {
  if (adapter == NULL || ops == NULL) {
    return;
  }
  ops->summary_context = adapter;
  ops->begin_summary = adapter_begin_summary;
  ops->capture_summary = adapter_capture_summary;
  ops->cancel_summary = adapter_cancel_summary;
}
