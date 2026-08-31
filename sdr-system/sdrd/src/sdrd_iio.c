#define _POSIX_C_SOURCE 200809L

#include "sdrd_iio.h"

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

struct iio_buffer;
struct iio_channel;
struct iio_context;
struct iio_device;

typedef struct iio_context *(*iio_create_local_context_fn)(void);
typedef void (*iio_context_destroy_fn)(struct iio_context *);
typedef int (*iio_context_set_timeout_fn)(struct iio_context *, unsigned int);
typedef struct iio_device *(*iio_context_find_device_fn)(const struct iio_context *, const char *);
typedef struct iio_channel *(*iio_device_find_channel_fn)(
    const struct iio_device *,
    const char *,
    bool);
typedef ssize_t (*iio_device_get_sample_size_fn)(const struct iio_device *);
typedef struct iio_buffer *(*iio_device_create_buffer_fn)(const struct iio_device *, size_t, bool);
typedef bool (*iio_channel_is_enabled_fn)(const struct iio_channel *);
typedef void (*iio_channel_enable_fn)(struct iio_channel *);
typedef void (*iio_channel_disable_fn)(struct iio_channel *);
typedef int (*iio_channel_attr_read_longlong_fn)(
    const struct iio_channel *,
    const char *,
    long long *);
typedef int (*iio_channel_attr_write_longlong_fn)(
    const struct iio_channel *,
    const char *,
    long long);
typedef ssize_t (*iio_channel_attr_read_fn)(
    const struct iio_channel *,
    const char *,
    char *,
    size_t);
typedef ssize_t (*iio_channel_attr_write_fn)(
    const struct iio_channel *,
    const char *,
    const char *);
typedef void (*iio_buffer_destroy_fn)(struct iio_buffer *);
typedef void (*iio_buffer_cancel_fn)(struct iio_buffer *);
typedef ssize_t (*iio_buffer_refill_fn)(struct iio_buffer *);
typedef void *(*iio_buffer_start_fn)(const struct iio_buffer *);
typedef void *(*iio_buffer_end_fn)(const struct iio_buffer *);

typedef struct sdrd_iio_api {
  iio_create_local_context_fn create_local_context;
  iio_context_destroy_fn context_destroy;
  iio_context_set_timeout_fn context_set_timeout;
  iio_context_find_device_fn context_find_device;
  iio_device_find_channel_fn device_find_channel;
  iio_device_get_sample_size_fn device_get_sample_size;
  iio_device_create_buffer_fn device_create_buffer;
  iio_channel_is_enabled_fn channel_is_enabled;
  iio_channel_enable_fn channel_enable;
  iio_channel_disable_fn channel_disable;
  iio_channel_attr_read_longlong_fn channel_attr_read_longlong;
  iio_channel_attr_write_longlong_fn channel_attr_write_longlong;
  iio_channel_attr_read_fn channel_attr_read;
  iio_channel_attr_write_fn channel_attr_write;
  iio_buffer_destroy_fn buffer_destroy;
  iio_buffer_cancel_fn buffer_cancel;
  iio_buffer_refill_fn buffer_refill;
  iio_buffer_start_fn buffer_start;
  iio_buffer_end_fn buffer_end;
} sdrd_iio_api_t;

struct sdrd_iio_adapter {
  void *library;
  sdrd_iio_api_t api;
  struct iio_context *context;
  struct iio_device *phy;
  struct iio_device *rx;
  struct iio_channel *rx_lo;
  struct iio_channel *phy_rx0;
  struct iio_channel *scan[4];
  struct iio_buffer *buffer;
  int capture_active;
  uint32_t buffer_samples;
  uint32_t retune_settle_ms;
  uint64_t sequence;
  char data_root[SDRD_MAX_PATH];
};

static void set_error(char *error, size_t error_size, const char *message) {
  if (error != NULL && error_size > 0u) {
    (void)snprintf(error, error_size, "%s", message);
  }
}

static int copy_text(char *destination, size_t destination_size, const char *source) {
  const size_t length = source == NULL ? 0u : strlen(source);
  if (source == NULL || length >= destination_size) {
    return -ENAMETOOLONG;
  }
  memcpy(destination, source, length + 1u);
  return 0;
}

static int load_symbol(void *library, void **output, const char *name) {
  void *symbol;
  if (library == NULL || output == NULL || name == NULL) {
    return -EINVAL;
  }
  dlerror();
  symbol = dlsym(library, name);
  if (symbol == NULL) {
    return -ENOSYS;
  }
  *output = symbol;
  return 0;
}

#define LOAD_API(adapter, field, type, name)                         \
  do {                                                               \
    union {                                                          \
      void *object;                                                  \
      type function;                                                 \
    } conversion;                                                    \
    conversion.function = NULL;                                      \
    if (load_symbol((adapter)->library, &conversion.object, (name)) != 0) { \
      return -ENOSYS;                                                \
    }                                                                \
    (adapter)->api.field = conversion.function;                       \
  } while (0)

static int load_api(sdrd_iio_adapter_t *adapter) {
  static const char *names[] = {"libiio.so.0", "libiio.so"};
  size_t index;
  for (index = 0u; index < sizeof(names) / sizeof(names[0]); ++index) {
    adapter->library = dlopen(names[index], RTLD_NOW | RTLD_LOCAL);
    if (adapter->library != NULL) {
      break;
    }
  }
  if (adapter->library == NULL) {
    return -ENODEV;
  }
  LOAD_API(adapter, create_local_context, iio_create_local_context_fn, "iio_create_local_context");
  LOAD_API(adapter, context_destroy, iio_context_destroy_fn, "iio_context_destroy");
  LOAD_API(adapter, context_set_timeout, iio_context_set_timeout_fn, "iio_context_set_timeout");
  LOAD_API(adapter, context_find_device, iio_context_find_device_fn, "iio_context_find_device");
  LOAD_API(adapter, device_find_channel, iio_device_find_channel_fn, "iio_device_find_channel");
  LOAD_API(adapter, device_get_sample_size, iio_device_get_sample_size_fn, "iio_device_get_sample_size");
  LOAD_API(adapter, device_create_buffer, iio_device_create_buffer_fn, "iio_device_create_buffer");
  LOAD_API(adapter, channel_is_enabled, iio_channel_is_enabled_fn, "iio_channel_is_enabled");
  LOAD_API(adapter, channel_enable, iio_channel_enable_fn, "iio_channel_enable");
  LOAD_API(adapter, channel_disable, iio_channel_disable_fn, "iio_channel_disable");
  LOAD_API(adapter, channel_attr_read_longlong, iio_channel_attr_read_longlong_fn, "iio_channel_attr_read_longlong");
  LOAD_API(adapter, channel_attr_write_longlong, iio_channel_attr_write_longlong_fn, "iio_channel_attr_write_longlong");
  LOAD_API(adapter, channel_attr_read, iio_channel_attr_read_fn, "iio_channel_attr_read");
  LOAD_API(adapter, channel_attr_write, iio_channel_attr_write_fn, "iio_channel_attr_write");
  LOAD_API(adapter, buffer_destroy, iio_buffer_destroy_fn, "iio_buffer_destroy");
  LOAD_API(adapter, buffer_cancel, iio_buffer_cancel_fn, "iio_buffer_cancel");
  LOAD_API(adapter, buffer_refill, iio_buffer_refill_fn, "iio_buffer_refill");
  LOAD_API(adapter, buffer_start, iio_buffer_start_fn, "iio_buffer_start");
  LOAD_API(adapter, buffer_end, iio_buffer_end_fn, "iio_buffer_end");
  return 0;
}

static int read_text_attr(
    sdrd_iio_adapter_t *adapter,
    struct iio_channel *channel,
    const char *attribute,
    char *output,
    size_t output_size) {
  ssize_t rc;
  if (output == NULL || output_size == 0u) {
    return -EINVAL;
  }
  memset(output, 0, output_size);
  rc = adapter->api.channel_attr_read(channel, attribute, output, output_size - 1u);
  if (rc < 0) {
    return (int)rc;
  }
  if ((size_t)rc >= output_size) {
    return -ENOSPC;
  }
  output[output_size - 1u] = '\0';
  return 0;
}

static int read_u64_attr(
    sdrd_iio_adapter_t *adapter,
    struct iio_channel *channel,
    const char *attribute,
    uint64_t *output) {
  long long value;
  const int rc = adapter->api.channel_attr_read_longlong(channel, attribute, &value);
  if (rc != 0) {
    return rc;
  }
  if (value < 0) {
    return -ERANGE;
  }
  *output = (uint64_t)value;
  return 0;
}

static int read_u32_attr(
    sdrd_iio_adapter_t *adapter,
    struct iio_channel *channel,
    const char *attribute,
    uint32_t *output) {
  uint64_t value;
  const int rc = read_u64_attr(adapter, channel, attribute, &value);
  if (rc != 0 || value > UINT32_MAX) {
    return rc != 0 ? rc : -ERANGE;
  }
  *output = (uint32_t)value;
  return 0;
}

static int set_scan_mask(sdrd_iio_adapter_t *adapter, uint32_t mask) {
  size_t index;
  if ((mask & ~0x0fu) != 0u) {
    return -ERANGE;
  }
  for (index = 0u; index < 4u; ++index) {
    if ((mask & (1u << index)) != 0u) {
      adapter->api.channel_enable(adapter->scan[index]);
    } else {
      adapter->api.channel_disable(adapter->scan[index]);
    }
  }
  return 0;
}

static uint32_t get_scan_mask(sdrd_iio_adapter_t *adapter) {
  uint32_t mask = 0u;
  size_t index;
  for (index = 0u; index < 4u; ++index) {
    if (adapter->api.channel_is_enabled(adapter->scan[index])) {
      mask |= 1u << index;
    }
  }
  return mask;
}

static void destroy_buffer(sdrd_iio_adapter_t *adapter, int cancel) {
  if (adapter->buffer != NULL) {
    if (cancel != 0) {
      adapter->api.buffer_cancel(adapter->buffer);
    }
    adapter->api.buffer_destroy(adapter->buffer);
    adapter->buffer = NULL;
  }
}

static int adapter_snapshot(void *context, sdrd_radio_state_t *state) {
  sdrd_iio_adapter_t *adapter = context;
  int rc;
  if (adapter == NULL || state == NULL || adapter->buffer != NULL) {
    return -EBUSY;
  }
  memset(state, 0, sizeof(*state));
  rc = read_u64_attr(adapter, adapter->rx_lo, "frequency", &state->center_hz);
  if (rc == 0) {
    rc = read_u32_attr(adapter, adapter->phy_rx0, "sampling_frequency", &state->sample_rate_hz);
  }
  if (rc == 0) {
    rc = read_u32_attr(adapter, adapter->phy_rx0, "rf_bandwidth", &state->rf_bandwidth_hz);
  }
  if (rc == 0) {
    rc = read_text_attr(
        adapter, adapter->phy_rx0, "gain_control_mode", state->gain_mode, sizeof(state->gain_mode));
  }
  if (rc == 0) {
    rc = read_text_attr(
        adapter, adapter->phy_rx0, "hardwaregain", state->hardware_gain, sizeof(state->hardware_gain));
  }
  if (rc != 0) {
    return rc;
  }
  state->scan_channel_mask = get_scan_mask(adapter);
  state->enabled_channels = (state->scan_channel_mask & 0x03u) == 0x03u ? 1u : 0u;
  return 0;
}

static int verify_profile(sdrd_iio_adapter_t *adapter, const sdrd_radio_state_t *state) {
  sdrd_radio_state_t observed;
  uint64_t center_delta;
  int rc;
  memset(&observed, 0, sizeof(observed));
  rc = read_u64_attr(adapter, adapter->rx_lo, "frequency", &observed.center_hz);
  if (rc == 0) {
    rc = read_u32_attr(adapter, adapter->phy_rx0, "sampling_frequency", &observed.sample_rate_hz);
  }
  if (rc == 0) {
    rc = read_u32_attr(adapter, adapter->phy_rx0, "rf_bandwidth", &observed.rf_bandwidth_hz);
  }
  if (rc == 0) {
    rc = read_text_attr(
        adapter,
        adapter->phy_rx0,
        "gain_control_mode",
        observed.gain_mode,
        sizeof(observed.gain_mode));
  }
  if (rc != 0) {
    return rc;
  }
  center_delta = observed.center_hz > state->center_hz
                     ? observed.center_hz - state->center_hz
                     : state->center_hz - observed.center_hz;
  if (center_delta > 10u ||
      observed.sample_rate_hz != state->sample_rate_hz ||
      observed.rf_bandwidth_hz != state->rf_bandwidth_hz ||
      strcmp(observed.gain_mode, state->gain_mode) != 0 ||
      get_scan_mask(adapter) != 0x03u) {
    fprintf(
        stderr,
        "iio_operation=apply stage=verify requested_center=%" PRIu64
        " observed_center=%" PRIu64 " requested_rate=%u observed_rate=%u"
        " requested_bandwidth=%u observed_bandwidth=%u requested_gain=%s"
        " observed_gain=%s observed_scan_mask=%u\n",
        state->center_hz,
        observed.center_hz,
        state->sample_rate_hz,
        observed.sample_rate_hz,
        state->rf_bandwidth_hz,
        observed.rf_bandwidth_hz,
        state->gain_mode,
        observed.gain_mode,
        get_scan_mask(adapter));
    return -EIO;
  }
  return 0;
}

static int adapter_apply_profile(void *context, const sdrd_radio_state_t *state) {
  sdrd_iio_adapter_t *adapter = context;
  int rc;
  if (adapter == NULL || state == NULL || state->enabled_channels != 1u) {
    return -EINVAL;
  }
  destroy_buffer(adapter, 0);
  rc = adapter->api.channel_attr_write_longlong(
      adapter->phy_rx0, "sampling_frequency", (long long)state->sample_rate_hz);
  if (rc != 0) {
    fprintf(stderr, "iio_operation=apply stage=sampling_frequency rc=%d\n", rc);
    return rc;
  }
  rc = adapter->api.channel_attr_write_longlong(
      adapter->phy_rx0, "rf_bandwidth", (long long)state->rf_bandwidth_hz);
  if (rc != 0) {
    fprintf(stderr, "iio_operation=apply stage=rf_bandwidth rc=%d\n", rc);
    return rc;
  }
  {
    const ssize_t written = adapter->api.channel_attr_write(
        adapter->phy_rx0, "gain_control_mode", state->gain_mode);
    rc = written < 0 ? (int)written : 0;
  }
  if (rc != 0) {
    fprintf(stderr, "iio_operation=apply stage=gain_control_mode rc=%d\n", rc);
    return rc;
  }
  rc = adapter->api.channel_attr_write_longlong(
      adapter->rx_lo, "frequency", (long long)state->center_hz);
  if (rc != 0) {
    fprintf(stderr, "iio_operation=apply stage=frequency rc=%d\n", rc);
    return rc;
  }
  if (adapter->retune_settle_ms > 0u) {
    struct timespec settle;
    settle.tv_sec = (time_t)(adapter->retune_settle_ms / 1000u);
    settle.tv_nsec = (long)(adapter->retune_settle_ms % 1000u) * 1000000L;
    if (nanosleep(&settle, NULL) != 0) {
      rc = -errno;
      fprintf(stderr, "iio_operation=apply stage=settle rc=%d\n", rc);
      return rc;
    }
  }
  rc = set_scan_mask(adapter, 0x03u);
  if (rc != 0) {
    fprintf(stderr, "iio_operation=apply stage=scan_mask rc=%d\n", rc);
    return rc;
  }
  rc = verify_profile(adapter, state);
  if (rc != 0) {
    fprintf(stderr, "iio_operation=apply stage=readback rc=%d\n", rc);
  }
  return rc;
}

static int write_all(int fd, const void *data, size_t length) {
  const unsigned char *bytes = data;
  size_t offset = 0u;
  while (offset < length) {
    const ssize_t written = write(fd, bytes + offset, length - offset);
    if (written < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -errno;
    }
    if (written == 0) {
      return -EIO;
    }
    offset += (size_t)written;
  }
  return 0;
}

static int ensure_directory(const char *path) {
  struct stat status;
  if (mkdir(path, 0700) == 0) {
    return 0;
  }
  if (errno != EEXIST || stat(path, &status) != 0 || !S_ISDIR(status.st_mode)) {
    return -errno;
  }
  return 0;
}

static int adapter_capture_iq(
    void *context,
    const sdrd_capture_request_t *request,
    sdrd_capture_result_t *result) {
  sdrd_iio_adapter_t *adapter = context;
  struct statvfs filesystem;
  char feature_path[SDRD_MAX_PATH * 2u];
  char full_path[SDRD_MAX_PATH * 2u];
  uint64_t remaining;
  int fd = -1;
  int rc;
  int written;
  if (adapter == NULL || request == NULL || result == NULL) {
    return -EINVAL;
  }
  if (adapter->api.device_get_sample_size(adapter->rx) != 4) {
    return -EPROTO;
  }
  rc = ensure_directory(adapter->data_root);
  if (rc != 0) {
    return rc;
  }
  written = snprintf(
      feature_path, sizeof(feature_path), "%s/%s", adapter->data_root, request->feature_id);
  if (written < 0 || (size_t)written >= sizeof(feature_path)) {
    return -ENAMETOOLONG;
  }
  rc = ensure_directory(feature_path);
  if (rc != 0) {
    return rc;
  }
  if (statvfs(feature_path, &filesystem) != 0 ||
      (uint64_t)filesystem.f_bavail * (uint64_t)filesystem.f_frsize < request->max_bytes) {
    return -ENOSPC;
  }
  ++adapter->sequence;
  memset(result, 0, sizeof(*result));
  written = snprintf(
          result->relative_path,
          sizeof(result->relative_path),
          "%s/capture-%" PRIu64 "-%" PRIu64 ".ci16",
          request->feature_id,
          request->generation,
          adapter->sequence);
  if (written < 0 || (size_t)written >= sizeof(result->relative_path)) {
    return -ENAMETOOLONG;
  }
  written = snprintf(full_path, sizeof(full_path), "%s/%s", adapter->data_root, result->relative_path);
  if (written < 0 || (size_t)written >= sizeof(full_path)) {
    return -ENAMETOOLONG;
  }
  fd = open(full_path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  if (fd < 0) {
    return -errno;
  }
  if (adapter->buffer == NULL) {
    adapter->buffer = adapter->api.device_create_buffer(adapter->rx, adapter->buffer_samples, false);
    if (adapter->buffer == NULL) {
      rc = errno != 0 ? -errno : -EIO;
      goto failed;
    }
  }
  remaining = request->sample_count * 4u;
  adapter->capture_active = 1;
  while (remaining > 0u) {
    const ssize_t refill = adapter->api.buffer_refill(adapter->buffer);
    unsigned char *start;
    unsigned char *end;
    size_t available;
    size_t to_write;
    if (refill < 0) {
      rc = (int)refill;
      goto failed;
    }
    start = adapter->api.buffer_start(adapter->buffer);
    end = adapter->api.buffer_end(adapter->buffer);
    if (start == NULL || end == NULL || end <= start) {
      rc = -EIO;
      goto failed;
    }
    available = (size_t)(end - start);
    to_write = available;
    if ((uint64_t)to_write > remaining) {
      to_write = (size_t)remaining;
    }
    rc = write_all(fd, start, to_write);
    if (rc != 0) {
      goto failed;
    }
    remaining -= (uint64_t)to_write;
  }
  if (close(fd) != 0) {
    fd = -1;
    rc = -errno;
    goto failed;
  }
  fd = -1;
  adapter->capture_active = 0;
  result->samples_captured = request->sample_count;
  result->bytes_written = request->sample_count * 4u;
  result->sequence = adapter->sequence;
  return 0;

failed:
  adapter->capture_active = 0;
  if (fd >= 0) {
    (void)close(fd);
  }
  (void)unlink(full_path);
  return rc;
}

static int adapter_stop(void *context) {
  sdrd_iio_adapter_t *adapter = context;
  if (adapter == NULL) {
    return -EINVAL;
  }
  destroy_buffer(adapter, adapter->capture_active);
  return 0;
}

static int adapter_restore(void *context, const sdrd_radio_state_t *state) {
  sdrd_iio_adapter_t *adapter = context;
  int rc;
  if (adapter == NULL || state == NULL) {
    return -EINVAL;
  }
  destroy_buffer(adapter, adapter->capture_active);
  rc = adapter->api.channel_attr_write_longlong(
      adapter->phy_rx0, "sampling_frequency", (long long)state->sample_rate_hz);
  if (rc == 0) {
    rc = adapter->api.channel_attr_write_longlong(
        adapter->phy_rx0, "rf_bandwidth", (long long)state->rf_bandwidth_hz);
  }
  if (rc == 0) {
    const ssize_t written = adapter->api.channel_attr_write(
        adapter->phy_rx0, "gain_control_mode", state->gain_mode);
    rc = written < 0 ? (int)written : 0;
  }
  if (rc == 0 && strcmp(state->gain_mode, "manual") == 0 && state->hardware_gain[0] != '\0') {
    const ssize_t written = adapter->api.channel_attr_write(
        adapter->phy_rx0, "hardwaregain", state->hardware_gain);
    rc = written < 0 ? (int)written : 0;
  }
  if (rc == 0) {
    rc = adapter->api.channel_attr_write_longlong(
        adapter->rx_lo, "frequency", (long long)state->center_hz);
  }
  if (rc == 0) {
    rc = set_scan_mask(adapter, state->scan_channel_mask);
  }
  return rc;
}

int sdrd_iio_adapter_create(
    const sdrd_config_t *config,
    sdrd_iio_adapter_t **adapter_output,
    char *error,
    size_t error_size) {
  sdrd_iio_adapter_t *adapter;
  size_t index;
  int rc;
  if (config == NULL || adapter_output == NULL) {
    set_error(error, error_size, "missing IIO adapter configuration");
    return -EINVAL;
  }
  *adapter_output = NULL;
  adapter = calloc(1u, sizeof(*adapter));
  if (adapter == NULL) {
    set_error(error, error_size, "IIO adapter allocation failed");
    return -ENOMEM;
  }
  adapter->buffer_samples = config->iio_buffer_samples;
  adapter->retune_settle_ms = config->retune_settle_ms;
  if (copy_text(adapter->data_root, sizeof(adapter->data_root), config->development_data_root) != 0) {
    set_error(error, error_size, "IIO data root is too long");
    sdrd_iio_adapter_destroy(adapter);
    return -ENAMETOOLONG;
  }
  rc = load_api(adapter);
  if (rc != 0) {
    set_error(error, error_size, "libiio 0.x runtime API is unavailable");
    sdrd_iio_adapter_destroy(adapter);
    return rc;
  }
  adapter->context = adapter->api.create_local_context();
  if (adapter->context == NULL) {
    set_error(error, error_size, "local IIO context creation failed");
    sdrd_iio_adapter_destroy(adapter);
    return -ENODEV;
  }
  rc = adapter->api.context_set_timeout(adapter->context, config->iio_timeout_ms);
  if (rc != 0) {
    set_error(error, error_size, "local IIO timeout configuration failed");
    sdrd_iio_adapter_destroy(adapter);
    return rc;
  }
  adapter->phy = adapter->api.context_find_device(adapter->context, "ad9361-phy");
  adapter->rx = adapter->api.context_find_device(adapter->context, "cf-ad9361-lpc");
  if (adapter->phy == NULL || adapter->rx == NULL) {
    set_error(error, error_size, "required AD9361 IIO devices are unavailable");
    sdrd_iio_adapter_destroy(adapter);
    return -ENODEV;
  }
  adapter->rx_lo = adapter->api.device_find_channel(adapter->phy, "altvoltage0", true);
  adapter->phy_rx0 = adapter->api.device_find_channel(adapter->phy, "voltage0", false);
  for (index = 0u; index < 4u; ++index) {
    char name[16];
    (void)snprintf(name, sizeof(name), "voltage%zu", index);
    adapter->scan[index] = adapter->api.device_find_channel(adapter->rx, name, false);
  }
  if (adapter->rx_lo == NULL || adapter->phy_rx0 == NULL || adapter->scan[0] == NULL ||
      adapter->scan[1] == NULL || adapter->scan[2] == NULL || adapter->scan[3] == NULL) {
    set_error(error, error_size, "required AD9361 IIO channels are unavailable");
    sdrd_iio_adapter_destroy(adapter);
    return -ENODEV;
  }
  *adapter_output = adapter;
  return 0;
}

void sdrd_iio_adapter_destroy(sdrd_iio_adapter_t *adapter) {
  if (adapter == NULL) {
    return;
  }
  destroy_buffer(adapter, adapter->capture_active);
  if (adapter->context != NULL && adapter->api.context_destroy != NULL) {
    adapter->api.context_destroy(adapter->context);
  }
  if (adapter->library != NULL) {
    (void)dlclose(adapter->library);
  }
  free(adapter);
}

void sdrd_iio_adapter_ops(sdrd_iio_adapter_t *adapter, sdrd_radio_ops_t *ops) {
  if (ops == NULL) {
    return;
  }
  memset(ops, 0, sizeof(*ops));
  if (adapter == NULL) {
    return;
  }
  ops->context = adapter;
  ops->snapshot = adapter_snapshot;
  ops->apply_profile = adapter_apply_profile;
  ops->capture_iq = adapter_capture_iq;
  ops->stop = adapter_stop;
  ops->restore = adapter_restore;
}
