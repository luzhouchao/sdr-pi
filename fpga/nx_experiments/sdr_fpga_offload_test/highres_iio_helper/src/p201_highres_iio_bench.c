#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <time.h>

#ifndef P201_HIGHRES_WITH_LIBIIO
#define P201_HIGHRES_WITH_LIBIIO 0
#endif

#ifndef P201_HIGHRES_IIO_DLOPEN
#define P201_HIGHRES_IIO_DLOPEN 0
#endif

#if P201_HIGHRES_WITH_LIBIIO
#if P201_HIGHRES_IIO_DLOPEN
#include <dlfcn.h>

struct iio_buffer;
struct iio_channel;
struct iio_context;
struct iio_device;

typedef struct iio_context *(*p201_iio_create_local_context_fn)(void);
typedef void (*p201_iio_context_destroy_fn)(struct iio_context *);
typedef struct iio_device *(*p201_iio_context_find_device_fn)(const struct iio_context *, const char *);
typedef unsigned int (*p201_iio_device_get_channels_count_fn)(const struct iio_device *);
typedef struct iio_channel *(*p201_iio_device_get_channel_fn)(const struct iio_device *, unsigned int);
typedef const char *(*p201_iio_channel_get_id_fn)(const struct iio_channel *);
typedef bool (*p201_iio_channel_is_output_fn)(const struct iio_channel *);
typedef bool (*p201_iio_channel_is_enabled_fn)(const struct iio_channel *);
typedef void (*p201_iio_channel_enable_fn)(struct iio_channel *);
typedef void (*p201_iio_channel_disable_fn)(struct iio_channel *);
typedef ssize_t (*p201_iio_device_get_sample_size_fn)(const struct iio_device *);
typedef struct iio_buffer *(*p201_iio_device_create_buffer_fn)(const struct iio_device *, size_t, bool);
typedef void (*p201_iio_buffer_destroy_fn)(struct iio_buffer *);
typedef ssize_t (*p201_iio_buffer_refill_fn)(struct iio_buffer *);
typedef void *(*p201_iio_buffer_start_fn)(const struct iio_buffer *);
typedef void *(*p201_iio_buffer_end_fn)(const struct iio_buffer *);

typedef struct {
  p201_iio_create_local_context_fn create_local_context;
  p201_iio_context_destroy_fn context_destroy;
  p201_iio_context_find_device_fn context_find_device;
  p201_iio_device_get_channels_count_fn device_get_channels_count;
  p201_iio_device_get_channel_fn device_get_channel;
  p201_iio_channel_get_id_fn channel_get_id;
  p201_iio_channel_is_output_fn channel_is_output;
  p201_iio_channel_is_enabled_fn channel_is_enabled;
  p201_iio_channel_enable_fn channel_enable;
  p201_iio_channel_disable_fn channel_disable;
  p201_iio_device_get_sample_size_fn device_get_sample_size;
  p201_iio_device_create_buffer_fn device_create_buffer;
  p201_iio_buffer_destroy_fn buffer_destroy;
  p201_iio_buffer_refill_fn buffer_refill;
  p201_iio_buffer_start_fn buffer_start;
  p201_iio_buffer_end_fn buffer_end;
} p201_iio_api_t;

static p201_iio_api_t g_iio;
static void *g_iio_handle = NULL;
#else
#include <iio.h>
#endif
#endif

#define MAX_NOTES 12
#define NOTE_LEN 192

typedef struct {
  const char *operation;
  const char *rx_device;
  uint32_t sample_count;
  uint32_t repeat;
  uint32_t fake_bytes_per_sample;
  int fake;
  int copy_enabled;
  int allow_scan_enable;
} bench_options_t;

typedef struct {
  double *refill_ms;
  double *copy_ms;
  uint32_t refill_count;
  uint32_t copy_count;
  uint64_t bytes_per_refill;
  double context_open_ms;
  double buffer_create_ms;
  int passed;
  char notes[MAX_NOTES][NOTE_LEN];
  size_t note_count;
} bench_result_t;

static uint64_t monotonic_ns(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
    return 0u;
  }
  return ((uint64_t)ts.tv_sec * 1000000000ull) + (uint64_t)ts.tv_nsec;
}

static double elapsed_ms(uint64_t start_ns, uint64_t end_ns) {
  if (end_ns < start_ns) {
    return 0.0;
  }
  return (double)(end_ns - start_ns) / 1000000.0;
}

static void add_note(bench_result_t *result, const char *fmt, ...) {
  va_list ap;
  if (result == NULL || result->note_count >= MAX_NOTES) {
    return;
  }
  va_start(ap, fmt);
  (void)vsnprintf(result->notes[result->note_count], NOTE_LEN, fmt, ap);
  va_end(ap);
  result->notes[result->note_count][NOTE_LEN - 1] = '\0';
  result->note_count++;
}

static int parse_u32(const char *text, uint32_t *out) {
  char *end = NULL;
  unsigned long value;
  if (text == NULL || text[0] == '\0' || out == NULL) {
    return -EINVAL;
  }
  errno = 0;
  value = strtoul(text, &end, 0);
  if (errno != 0 || end == text || end == NULL || *end != '\0' || value > UINT32_MAX) {
    return -EINVAL;
  }
  *out = (uint32_t)value;
  return 0;
}

static void usage(const char *argv0) {
  fprintf(stderr,
          "Usage: %s [--sample-count N] [--repeat N] [--rx-device NAME]\n"
          "          [--fake] [--fake-bytes-per-sample N] [--no-copy]\n"
          "          [--allow-scan-enable]\n",
          argv0);
}

static int parse_args(int argc, char **argv, bench_options_t *opts) {
  int i;
  if (opts == NULL) {
    return -EINVAL;
  }
  opts->operation = "p201_highres_iio_refill_bench";
  opts->rx_device = "cf-ad9361-lpc";
  opts->sample_count = 8192u;
  opts->repeat = 20u;
  opts->fake_bytes_per_sample = 8u;
  opts->fake = 0;
  opts->copy_enabled = 1;
  opts->allow_scan_enable = 0;

  for (i = 1; i < argc; i++) {
    if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
      usage(argv[0]);
      exit(0);
    } else if (strcmp(argv[i], "--fake") == 0) {
      opts->fake = 1;
      opts->operation = "p201_highres_iio_refill_bench_fake";
    } else if (strcmp(argv[i], "--no-copy") == 0) {
      opts->copy_enabled = 0;
    } else if (strcmp(argv[i], "--allow-scan-enable") == 0) {
      opts->allow_scan_enable = 1;
    } else if (strcmp(argv[i], "--sample-count") == 0) {
      if (++i >= argc || parse_u32(argv[i], &opts->sample_count) != 0) {
        return -EINVAL;
      }
    } else if (strcmp(argv[i], "--repeat") == 0) {
      if (++i >= argc || parse_u32(argv[i], &opts->repeat) != 0) {
        return -EINVAL;
      }
    } else if (strcmp(argv[i], "--fake-bytes-per-sample") == 0) {
      if (++i >= argc || parse_u32(argv[i], &opts->fake_bytes_per_sample) != 0) {
        return -EINVAL;
      }
    } else if (strcmp(argv[i], "--rx-device") == 0) {
      if (++i >= argc || argv[i][0] == '\0') {
        return -EINVAL;
      }
      opts->rx_device = argv[i];
    } else {
      fprintf(stderr, "Unknown argument: %s\n", argv[i]);
      return -EINVAL;
    }
  }

  if (opts->sample_count == 0u || opts->repeat == 0u || opts->repeat > 100000u) {
    return -EINVAL;
  }
  if (opts->fake_bytes_per_sample == 0u || opts->fake_bytes_per_sample > 1024u) {
    return -EINVAL;
  }
  return 0;
}

static int cmp_double(const void *a, const void *b) {
  const double da = *(const double *)a;
  const double db = *(const double *)b;
  if (da < db) {
    return -1;
  }
  if (da > db) {
    return 1;
  }
  return 0;
}

static double stat_min(double *values, uint32_t count) {
  if (values == NULL || count == 0u) {
    return 0.0;
  }
  qsort(values, count, sizeof(values[0]), cmp_double);
  return values[0];
}

static double stat_median(const double *values, uint32_t count) {
  if (values == NULL || count == 0u) {
    return 0.0;
  }
  if ((count & 1u) != 0u) {
    return values[count / 2u];
  }
  return (values[(count / 2u) - 1u] + values[count / 2u]) / 2.0;
}

static double stat_max(const double *values, uint32_t count) {
  if (values == NULL || count == 0u) {
    return 0.0;
  }
  return values[count - 1u];
}

static void json_string(FILE *stream, const char *text) {
  const unsigned char *p = (const unsigned char *)(text == NULL ? "" : text);
  fputc('"', stream);
  while (*p != '\0') {
    switch (*p) {
      case '"':
        fputs("\\\"", stream);
        break;
      case '\\':
        fputs("\\\\", stream);
        break;
      case '\b':
        fputs("\\b", stream);
        break;
      case '\f':
        fputs("\\f", stream);
        break;
      case '\n':
        fputs("\\n", stream);
        break;
      case '\r':
        fputs("\\r", stream);
        break;
      case '\t':
        fputs("\\t", stream);
        break;
      default:
        if (*p < 0x20u) {
          fprintf(stream, "\\u%04x", (unsigned int)*p);
        } else {
          fputc((int)*p, stream);
        }
        break;
    }
    p++;
  }
  fputc('"', stream);
}

static void print_json(const bench_options_t *opts, bench_result_t *result) {
  double refill_min = 0.0;
  double refill_median = 0.0;
  double refill_max = 0.0;
  double copy_min = 0.0;
  double copy_median = 0.0;
  double copy_max = 0.0;
  size_t i;

  if (result->refill_count > 0u) {
    refill_min = stat_min(result->refill_ms, result->refill_count);
    refill_median = stat_median(result->refill_ms, result->refill_count);
    refill_max = stat_max(result->refill_ms, result->refill_count);
  }
  if (result->copy_count > 0u) {
    copy_min = stat_min(result->copy_ms, result->copy_count);
    copy_median = stat_median(result->copy_ms, result->copy_count);
    copy_max = stat_max(result->copy_ms, result->copy_count);
  }

  printf("{\n");
  printf("  \"operation\": ");
  json_string(stdout, opts->operation);
  printf(",\n");
  printf("  \"passed\": %s,\n", result->passed ? "true" : "false");
  printf("  \"sample_count\": %" PRIu32 ",\n", opts->sample_count);
  printf("  \"bytes_per_refill\": %" PRIu64 ",\n", result->bytes_per_refill);
  printf("  \"repeat\": %" PRIu32 ",\n", opts->repeat);
  printf("  \"context_open_ms\": %.6f,\n", result->context_open_ms);
  printf("  \"buffer_create_ms\": %.6f,\n", result->buffer_create_ms);
  printf("  \"refill_min_ms\": %.6f,\n", refill_min);
  printf("  \"refill_median_ms\": %.6f,\n", refill_median);
  printf("  \"refill_max_ms\": %.6f,\n", refill_max);
  printf("  \"copy_min_ms\": %.6f,\n", copy_min);
  printf("  \"copy_median_ms\": %.6f,\n", copy_median);
  printf("  \"copy_max_ms\": %.6f,\n", copy_max);
  printf("  \"notes\": [");
  for (i = 0u; i < result->note_count; i++) {
    if (i != 0u) {
      printf(", ");
    }
    json_string(stdout, result->notes[i]);
  }
  printf("]\n");
  printf("}\n");
}

static int allocate_arrays(const bench_options_t *opts, bench_result_t *result) {
  result->refill_ms = (double *)calloc(opts->repeat, sizeof(result->refill_ms[0]));
  result->copy_ms = (double *)calloc(opts->repeat, sizeof(result->copy_ms[0]));
  if (result->refill_ms == NULL || result->copy_ms == NULL) {
    return -ENOMEM;
  }
  return 0;
}

static int run_fake_bench(const bench_options_t *opts, bench_result_t *result) {
  uint8_t *src = NULL;
  uint8_t *dst = NULL;
  uint64_t total_bytes;
  uint32_t i;
  volatile uint8_t sink = 0u;

  total_bytes = (uint64_t)opts->sample_count * (uint64_t)opts->fake_bytes_per_sample;
  if (total_bytes == 0u || total_bytes > (uint64_t)SIZE_MAX) {
    add_note(result, "fake byte count overflow");
    return -ERANGE;
  }
  src = (uint8_t *)malloc((size_t)total_bytes);
  dst = (uint8_t *)malloc((size_t)total_bytes);
  if (src == NULL || dst == NULL) {
    free(src);
    free(dst);
    add_note(result, "fake buffer allocation failed");
    return -ENOMEM;
  }
  memset(src, 0x5a, (size_t)total_bytes);
  result->bytes_per_refill = total_bytes;
  result->context_open_ms = 0.0;
  result->buffer_create_ms = 0.0;

  for (i = 0u; i < opts->repeat; i++) {
    const uint64_t refill_start = monotonic_ns();
    sink ^= src[(size_t)i % (size_t)total_bytes];
    result->refill_ms[result->refill_count++] = elapsed_ms(refill_start, monotonic_ns());
    if (opts->copy_enabled) {
      const uint64_t copy_start = monotonic_ns();
      memcpy(dst, src, (size_t)total_bytes);
      sink ^= dst[((size_t)i * 17u) % (size_t)total_bytes];
      result->copy_ms[result->copy_count++] = elapsed_ms(copy_start, monotonic_ns());
    }
  }

  (void)sink;
  result->passed = 1;
  add_note(result, "fake/no-IIO smoke path; no SDR or IIO device was opened");
  add_note(result, "fake bytes_per_refill assumes %" PRIu32 " bytes per sample group", opts->fake_bytes_per_sample);
  free(src);
  free(dst);
  return 0;
}

#if P201_HIGHRES_WITH_LIBIIO
#if P201_HIGHRES_IIO_DLOPEN
static int load_iio_symbol(void **target, const char *name, bench_result_t *result) {
  void *sym;
  if (target == NULL || name == NULL || result == NULL) {
    return -EINVAL;
  }
  dlerror();
  sym = dlsym(g_iio_handle, name);
  if (sym == NULL) {
    const char *err = dlerror();
    add_note(result, "dlsym failed for %s: %s", name, err != NULL ? err : "unknown error");
    return -ENOSYS;
  }
  *target = sym;
  return 0;
}

#define LOAD_IIO_SYMBOL(field, type, symbol_name)                    \
  do {                                                               \
    union {                                                          \
      void *object;                                                  \
      type function;                                                 \
    } conv;                                                          \
    conv.function = NULL;                                            \
    if (load_iio_symbol(&conv.object, (symbol_name), result) != 0) { \
      return -ENOSYS;                                                \
    }                                                                \
    g_iio.field = conv.function;                                     \
  } while (0)

static int load_iio_api(bench_result_t *result) {
  static const char *names[] = {"libiio.so.0", "libiio.so"};
  size_t i;
  if (g_iio_handle != NULL) {
    return 0;
  }
  memset(&g_iio, 0, sizeof(g_iio));
  for (i = 0u; i < sizeof(names) / sizeof(names[0]); i++) {
    g_iio_handle = dlopen(names[i], RTLD_NOW | RTLD_LOCAL);
    if (g_iio_handle != NULL) {
      add_note(result, "loaded libiio runtime with dlopen(%s)", names[i]);
      break;
    }
  }
  if (g_iio_handle == NULL) {
    add_note(result, "dlopen failed for libiio.so.0/libiio.so: %s", dlerror());
    return -ENODEV;
  }

  LOAD_IIO_SYMBOL(create_local_context, p201_iio_create_local_context_fn, "iio_create_local_context");
  LOAD_IIO_SYMBOL(context_destroy, p201_iio_context_destroy_fn, "iio_context_destroy");
  LOAD_IIO_SYMBOL(context_find_device, p201_iio_context_find_device_fn, "iio_context_find_device");
  LOAD_IIO_SYMBOL(device_get_channels_count, p201_iio_device_get_channels_count_fn, "iio_device_get_channels_count");
  LOAD_IIO_SYMBOL(device_get_channel, p201_iio_device_get_channel_fn, "iio_device_get_channel");
  LOAD_IIO_SYMBOL(channel_get_id, p201_iio_channel_get_id_fn, "iio_channel_get_id");
  LOAD_IIO_SYMBOL(channel_is_output, p201_iio_channel_is_output_fn, "iio_channel_is_output");
  LOAD_IIO_SYMBOL(channel_is_enabled, p201_iio_channel_is_enabled_fn, "iio_channel_is_enabled");
  LOAD_IIO_SYMBOL(channel_enable, p201_iio_channel_enable_fn, "iio_channel_enable");
  LOAD_IIO_SYMBOL(channel_disable, p201_iio_channel_disable_fn, "iio_channel_disable");
  LOAD_IIO_SYMBOL(device_get_sample_size, p201_iio_device_get_sample_size_fn, "iio_device_get_sample_size");
  LOAD_IIO_SYMBOL(device_create_buffer, p201_iio_device_create_buffer_fn, "iio_device_create_buffer");
  LOAD_IIO_SYMBOL(buffer_destroy, p201_iio_buffer_destroy_fn, "iio_buffer_destroy");
  LOAD_IIO_SYMBOL(buffer_refill, p201_iio_buffer_refill_fn, "iio_buffer_refill");
  LOAD_IIO_SYMBOL(buffer_start, p201_iio_buffer_start_fn, "iio_buffer_start");
  LOAD_IIO_SYMBOL(buffer_end, p201_iio_buffer_end_fn, "iio_buffer_end");
  return 0;
}

static void unload_iio_api(void) {
  if (g_iio_handle != NULL) {
    dlclose(g_iio_handle);
    g_iio_handle = NULL;
  }
  memset(&g_iio, 0, sizeof(g_iio));
}

#define iio_create_local_context g_iio.create_local_context
#define iio_context_destroy g_iio.context_destroy
#define iio_context_find_device g_iio.context_find_device
#define iio_device_get_channels_count g_iio.device_get_channels_count
#define iio_device_get_channel g_iio.device_get_channel
#define iio_channel_get_id g_iio.channel_get_id
#define iio_channel_is_output g_iio.channel_is_output
#define iio_channel_is_enabled g_iio.channel_is_enabled
#define iio_channel_enable g_iio.channel_enable
#define iio_channel_disable g_iio.channel_disable
#define iio_device_get_sample_size g_iio.device_get_sample_size
#define iio_device_create_buffer g_iio.device_create_buffer
#define iio_buffer_destroy g_iio.buffer_destroy
#define iio_buffer_refill g_iio.buffer_refill
#define iio_buffer_start g_iio.buffer_start
#define iio_buffer_end g_iio.buffer_end
#else
static int load_iio_api(bench_result_t *result) {
  (void)result;
  return 0;
}

static void unload_iio_api(void) {
}
#endif

static int starts_with_voltage(const char *id) {
  return id != NULL && strncmp(id, "voltage", 7u) == 0;
}

static struct iio_device *find_rx_device(struct iio_context *ctx, const char *preferred) {
  static const char *fallbacks[] = {
      "cf-ad9361-lpc",
      "axi-ad9361-rx-lpc",
      "axi-ad9361-rx-hpc",
      "cf-ad9361-A",
  };
  size_t i;
  if (ctx == NULL) {
    return NULL;
  }
  if (preferred != NULL && preferred[0] != '\0') {
    struct iio_device *dev = iio_context_find_device(ctx, preferred);
    if (dev != NULL) {
      return dev;
    }
  }
  for (i = 0u; i < sizeof(fallbacks) / sizeof(fallbacks[0]); i++) {
    struct iio_device *dev = iio_context_find_device(ctx, fallbacks[i]);
    if (dev != NULL) {
      return dev;
    }
  }
  return NULL;
}

static unsigned int enable_rx_voltage_channels(struct iio_device *rx) {
  unsigned int enabled = 0u;
  unsigned int i;
  const unsigned int count = iio_device_get_channels_count(rx);
  for (i = 0u; i < count; i++) {
    struct iio_channel *ch = iio_device_get_channel(rx, i);
    const char *id = iio_channel_get_id(ch);
    if (ch != NULL && !iio_channel_is_output(ch) && starts_with_voltage(id)) {
      iio_channel_enable(ch);
      enabled++;
    }
  }
  return enabled;
}

static void disable_rx_voltage_channels(struct iio_device *rx) {
  unsigned int i;
  const unsigned int count = iio_device_get_channels_count(rx);
  for (i = 0u; i < count; i++) {
    struct iio_channel *ch = iio_device_get_channel(rx, i);
    const char *id = iio_channel_get_id(ch);
    if (ch != NULL && !iio_channel_is_output(ch) && starts_with_voltage(id)) {
      iio_channel_disable(ch);
    }
  }
}

static unsigned int count_enabled_rx_voltage_channels(struct iio_device *rx) {
  unsigned int enabled = 0u;
  unsigned int i;
  const unsigned int count = iio_device_get_channels_count(rx);
  for (i = 0u; i < count; i++) {
    struct iio_channel *ch = iio_device_get_channel(rx, i);
    const char *id = iio_channel_get_id(ch);
    if (ch != NULL && !iio_channel_is_output(ch) && starts_with_voltage(id) && iio_channel_is_enabled(ch)) {
      enabled++;
    }
  }
  return enabled;
}

static int run_iio_bench(const bench_options_t *opts, bench_result_t *result) {
  struct iio_context *ctx = NULL;
  struct iio_device *rx = NULL;
  struct iio_buffer *buffer = NULL;
  uint8_t *copy_buffer = NULL;
  size_t copy_capacity = 0u;
  ptrdiff_t sample_size;
  unsigned int enabled_channels;
  int modified_scan_channels = 0;
  uint32_t i;
  volatile uint8_t sink = 0u;
  uint64_t t0;

  if (load_iio_api(result) != 0) {
    return -ENODEV;
  }

  t0 = monotonic_ns();
  ctx = iio_create_local_context();
  result->context_open_ms = elapsed_ms(t0, monotonic_ns());
  if (ctx == NULL) {
    add_note(result, "iio_create_local_context failed");
    unload_iio_api();
    return -ENODEV;
  }

  rx = find_rx_device(ctx, opts->rx_device);
  if (rx == NULL) {
    add_note(result, "RX IIO device not found; requested %s", opts->rx_device);
    iio_context_destroy(ctx);
    unload_iio_api();
    return -ENODEV;
  }

  enabled_channels = count_enabled_rx_voltage_channels(rx);
  if (enabled_channels == 0u && opts->allow_scan_enable) {
    enabled_channels = enable_rx_voltage_channels(rx);
    modified_scan_channels = enabled_channels > 0u;
  }
  if (enabled_channels == 0u) {
    add_note(result, "no RX voltage scan channels are currently enabled");
    add_note(result, "default real-IIO mode preserves current scan-channel state; use --allow-scan-enable only for an approved isolated benchmark");
    iio_context_destroy(ctx);
    unload_iio_api();
    return -ENODEV;
  }

  sample_size = iio_device_get_sample_size(rx);
  if (sample_size <= 0) {
    add_note(result, "iio_device_get_sample_size returned %td", sample_size);
  } else {
    result->bytes_per_refill = (uint64_t)opts->sample_count * (uint64_t)sample_size;
  }

  t0 = monotonic_ns();
  buffer = iio_device_create_buffer(rx, opts->sample_count, false);
  result->buffer_create_ms = elapsed_ms(t0, monotonic_ns());
  if (buffer == NULL) {
    add_note(result, "iio_device_create_buffer failed for sample_count=%" PRIu32, opts->sample_count);
    if (modified_scan_channels) {
      disable_rx_voltage_channels(rx);
    }
    iio_context_destroy(ctx);
    unload_iio_api();
    return -ENODEV;
  }

  if (opts->copy_enabled && result->bytes_per_refill > 0u && result->bytes_per_refill <= (uint64_t)SIZE_MAX) {
    copy_capacity = (size_t)result->bytes_per_refill;
    copy_buffer = (uint8_t *)malloc(copy_capacity);
    if (copy_buffer == NULL) {
      add_note(result, "copy buffer allocation failed; continuing with refill-only timing");
      copy_capacity = 0u;
    }
  }

  for (i = 0u; i < opts->repeat; i++) {
    const uint64_t refill_start = monotonic_ns();
    const ssize_t refill_rc = iio_buffer_refill(buffer);
    const uint64_t refill_end = monotonic_ns();
    size_t available = 0u;
    char *start = NULL;
    char *end = NULL;
    result->refill_ms[result->refill_count++] = elapsed_ms(refill_start, refill_end);
    if (refill_rc < 0) {
      add_note(result, "iio_buffer_refill failed at repeat %" PRIu32 " rc=%zd", i, refill_rc);
      break;
    }
    if (result->bytes_per_refill == 0u) {
      result->bytes_per_refill = (uint64_t)refill_rc;
    }
    start = (char *)iio_buffer_start(buffer);
    end = (char *)iio_buffer_end(buffer);
    if (start != NULL && end != NULL && end >= start) {
      available = (size_t)(end - start);
    }
    if (opts->copy_enabled && copy_buffer != NULL && available > 0u) {
      size_t to_copy = available;
      const uint64_t copy_start = monotonic_ns();
      if (to_copy > copy_capacity) {
        to_copy = copy_capacity;
      }
      memcpy(copy_buffer, start, to_copy);
      sink ^= copy_buffer[((size_t)i * 31u) % to_copy];
      result->copy_ms[result->copy_count++] = elapsed_ms(copy_start, monotonic_ns());
    }
  }

  (void)sink;
  if (result->refill_count == opts->repeat) {
    result->passed = 1;
  }
  add_note(result, "libiio local context path; no PHY attrs, LO, gain, sample-rate, clock, driver, or FPGA state writes");
  add_note(result, "using %u RX voltage scan channel(s); scan-channel state %s", enabled_channels,
           modified_scan_channels ? "was temporarily enabled by explicit option" : "was left unchanged");
  if (!opts->copy_enabled) {
    add_note(result, "copy timing disabled by --no-copy");
  }

  free(copy_buffer);
  iio_buffer_destroy(buffer);
  if (modified_scan_channels) {
    disable_rx_voltage_channels(rx);
  }
  iio_context_destroy(ctx);
  unload_iio_api();
  return result->passed ? 0 : -EIO;
}
#else
static int run_iio_bench(const bench_options_t *opts, bench_result_t *result) {
  (void)opts;
  result->passed = 0;
  add_note(result, "binary built without libiio; rebuild with WITH_LIBIIO=1 on SDR Linux");
  add_note(result, "use --fake for Windows/WSL CLI and JSON smoke checks");
  return -ENOSYS;
}
#endif

int main(int argc, char **argv) {
  bench_options_t opts;
  bench_result_t result;
  int rc;

  memset(&result, 0, sizeof(result));
  rc = parse_args(argc, argv, &opts);
  if (rc != 0) {
    usage(argv[0]);
    return 2;
  }
  rc = allocate_arrays(&opts, &result);
  if (rc != 0) {
    fprintf(stderr, "allocation failed\n");
    return 2;
  }

  if (opts.fake) {
    rc = run_fake_bench(&opts, &result);
  } else {
    rc = run_iio_bench(&opts, &result);
  }

  print_json(&opts, &result);
  free(result.refill_ms);
  free(result.copy_ms);
  return (rc == 0 && result.passed) ? 0 : 2;
}
