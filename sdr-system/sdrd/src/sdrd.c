#define _POSIX_C_SOURCE 200809L

#include "sdrd.h"
#include "p201_native_mmio.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define SDRD_SUM8_MAGIC 0x53554D38u
#define SDRD_SUM8_ABI 0x00010002u
#define SDRD_AGG8_MAGIC 0x41474738u
#define SDRD_AGGREGATE_CAPABILITY_BIT (1u << 9)

static void set_error(char *error, size_t error_size, const char *message) {
  if (error != NULL && error_size > 0u) {
    (void)snprintf(error, error_size, "%s", message);
  }
}

static char *trim(char *text) {
  char *end;
  while (*text != '\0' && isspace((unsigned char)*text) != 0) {
    ++text;
  }
  end = text + strlen(text);
  while (end > text && isspace((unsigned char)end[-1]) != 0) {
    --end;
  }
  *end = '\0';
  return text;
}

static int copy_text(char *destination, size_t destination_size, const char *source) {
  const size_t length = strlen(source);
  if (length >= destination_size) {
    return -ENAMETOOLONG;
  }
  memcpy(destination, source, length + 1u);
  return 0;
}

static int parse_u64(const char *text, uint64_t *value) {
  char *end = NULL;
  unsigned long long parsed;
  if (text == NULL || *text == '\0' || *text == '-') {
    return -EINVAL;
  }
  errno = 0;
  parsed = strtoull(text, &end, 0);
  if (errno != 0 || end == text || *end != '\0') {
    return -EINVAL;
  }
  *value = (uint64_t)parsed;
  return 0;
}

static int parse_u32(const char *text, uint32_t *value) {
  uint64_t parsed;
  const int rc = parse_u64(text, &parsed);
  if (rc != 0 || parsed > UINT32_MAX) {
    return -EINVAL;
  }
  *value = (uint32_t)parsed;
  return 0;
}

static int parse_bool(const char *text, int *value) {
  if (strcmp(text, "true") == 0 || strcmp(text, "1") == 0 || strcmp(text, "yes") == 0) {
    *value = 1;
    return 0;
  }
  if (strcmp(text, "false") == 0 || strcmp(text, "0") == 0 || strcmp(text, "no") == 0) {
    *value = 0;
    return 0;
  }
  return -EINVAL;
}

void sdrd_config_defaults(sdrd_config_t *config) {
  if (config == NULL) {
    return;
  }
  memset(config, 0, sizeof(*config));
  config->mode = SDRD_MODE_SHADOW;
  (void)copy_text(config->listen_address, sizeof(config->listen_address), "127.0.0.1");
  config->listen_port = SDRD_DEFAULT_PORT;
  config->client_timeout_ms = 5000u;
  (void)copy_text(config->iio_sysfs_root, sizeof(config->iio_sysfs_root), "/sys/bus/iio/devices");
  config->fpga_backend = SDRD_FPGA_DISABLED;
  (void)copy_text(config->fpga_device, sizeof(config->fpga_device), "/dev/mem");
  config->fpga_base = P201_TAP_BASE;
  config->fpga_span = P201_TAP_SPAN_BYTES;
  config->require_iomem_region = 1;
  config->allow_devmem = 0;
  (void)copy_text(
      config->development_data_root,
      sizeof(config->development_data_root),
      "/tmp/sdr-agent-dev");
  config->iio_timeout_ms = 2000u;
  config->iio_buffer_samples = 4096u;
  config->retune_settle_ms = 5u;
  config->min_center_hz = 70000000u;
  config->max_center_hz = 6000000000u;
  config->min_sample_rate_hz = 2083333u;
  config->max_sample_rate_hz = 30720000u;
  config->min_rf_bandwidth_hz = 200000u;
  config->max_rf_bandwidth_hz = 56000000u;
  config->max_capture_bytes = 64u * 1024u * 1024u;
}

const char *sdrd_mode_name(sdrd_mode_t mode) {
  switch (mode) {
    case SDRD_MODE_SHADOW:
      return "shadow";
    case SDRD_MODE_CONTROLLED:
      return "controlled";
    default:
      return "invalid";
  }
}

const char *sdrd_fpga_backend_name(sdrd_fpga_backend_t backend) {
  switch (backend) {
    case SDRD_FPGA_DISABLED:
      return "disabled";
    case SDRD_FPGA_UIO:
      return "uio";
    case SDRD_FPGA_DEVMEM:
      return "devmem";
    default:
      return "invalid";
  }
}

static int set_config_value(
    sdrd_config_t *config,
    const char *key,
    const char *value,
    char *error,
    size_t error_size) {
  uint32_t parsed_u32;
  uint64_t parsed_u64;
  if (strcmp(key, "mode") == 0) {
    if (strcmp(value, "shadow") == 0) {
      config->mode = SDRD_MODE_SHADOW;
    } else if (strcmp(value, "controlled") == 0) {
      config->mode = SDRD_MODE_CONTROLLED;
    } else {
      set_error(error, error_size, "mode must be shadow or controlled");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "listen_address") == 0) {
    return copy_text(config->listen_address, sizeof(config->listen_address), value);
  }
  if (strcmp(key, "listen_port") == 0) {
    if (parse_u32(value, &parsed_u32) != 0 || parsed_u32 > UINT16_MAX) {
      set_error(error, error_size, "invalid listen_port");
      return -EINVAL;
    }
    config->listen_port = (uint16_t)parsed_u32;
    return 0;
  }
  if (strcmp(key, "client_timeout_ms") == 0) {
    if (parse_u32(value, &config->client_timeout_ms) != 0) {
      set_error(error, error_size, "invalid client_timeout_ms");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "iio_sysfs_root") == 0) {
    return copy_text(config->iio_sysfs_root, sizeof(config->iio_sysfs_root), value);
  }
  if (strcmp(key, "fpga_backend") == 0) {
    if (strcmp(value, "disabled") == 0) {
      config->fpga_backend = SDRD_FPGA_DISABLED;
    } else if (strcmp(value, "uio") == 0) {
      config->fpga_backend = SDRD_FPGA_UIO;
    } else if (strcmp(value, "devmem") == 0) {
      config->fpga_backend = SDRD_FPGA_DEVMEM;
    } else {
      set_error(error, error_size, "fpga_backend must be disabled, uio, or devmem");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "fpga_device") == 0) {
    return copy_text(config->fpga_device, sizeof(config->fpga_device), value);
  }
  if (strcmp(key, "fpga_base") == 0) {
    if (parse_u64(value, &parsed_u64) != 0) {
      set_error(error, error_size, "invalid fpga_base");
      return -EINVAL;
    }
    config->fpga_base = parsed_u64;
    return 0;
  }
  if (strcmp(key, "fpga_span") == 0) {
    if (parse_u32(value, &config->fpga_span) != 0) {
      set_error(error, error_size, "invalid fpga_span");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "require_iomem_region") == 0) {
    if (parse_bool(value, &config->require_iomem_region) != 0) {
      set_error(error, error_size, "invalid require_iomem_region");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "allow_devmem") == 0) {
    if (parse_bool(value, &config->allow_devmem) != 0) {
      set_error(error, error_size, "invalid allow_devmem");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "development_data_root") == 0) {
    return copy_text(
        config->development_data_root,
        sizeof(config->development_data_root),
        value);
  }
  if (strcmp(key, "iio_timeout_ms") == 0) {
    if (parse_u32(value, &config->iio_timeout_ms) != 0) {
      set_error(error, error_size, "invalid iio_timeout_ms");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "iio_buffer_samples") == 0) {
    if (parse_u32(value, &config->iio_buffer_samples) != 0) {
      set_error(error, error_size, "invalid iio_buffer_samples");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "retune_settle_ms") == 0) {
    if (parse_u32(value, &config->retune_settle_ms) != 0) {
      set_error(error, error_size, "invalid retune_settle_ms");
      return -EINVAL;
    }
    return 0;
  }
  if (strcmp(key, "min_center_hz") == 0) {
    return parse_u64(value, &config->min_center_hz);
  }
  if (strcmp(key, "max_center_hz") == 0) {
    return parse_u64(value, &config->max_center_hz);
  }
  if (strcmp(key, "min_sample_rate_hz") == 0) {
    return parse_u32(value, &config->min_sample_rate_hz);
  }
  if (strcmp(key, "max_sample_rate_hz") == 0) {
    return parse_u32(value, &config->max_sample_rate_hz);
  }
  if (strcmp(key, "min_rf_bandwidth_hz") == 0) {
    return parse_u32(value, &config->min_rf_bandwidth_hz);
  }
  if (strcmp(key, "max_rf_bandwidth_hz") == 0) {
    return parse_u32(value, &config->max_rf_bandwidth_hz);
  }
  if (strcmp(key, "max_capture_bytes") == 0) {
    return parse_u64(value, &config->max_capture_bytes);
  }
  set_error(error, error_size, "unknown configuration key");
  return -EINVAL;
}

int sdrd_config_load(
    const char *path,
    sdrd_config_t *config,
    char *error,
    size_t error_size) {
  FILE *stream;
  char line[512];
  unsigned int line_number = 0u;
  if (path == NULL || config == NULL) {
    set_error(error, error_size, "missing configuration path");
    return -EINVAL;
  }
  sdrd_config_defaults(config);
  stream = fopen(path, "r");
  if (stream == NULL) {
    set_error(error, error_size, strerror(errno));
    return -errno;
  }
  while (fgets(line, sizeof(line), stream) != NULL) {
    char *key;
    char *value;
    char *equals;
    int rc;
    ++line_number;
    key = trim(line);
    if (*key == '\0' || *key == '#') {
      continue;
    }
    equals = strchr(key, '=');
    if (equals == NULL) {
      (void)snprintf(error, error_size, "line %u: expected key=value", line_number);
      (void)fclose(stream);
      return -EINVAL;
    }
    *equals = '\0';
    value = trim(equals + 1);
    key = trim(key);
    rc = set_config_value(config, key, value, error, error_size);
    if (rc != 0) {
      char detail[256];
      (void)snprintf(detail, sizeof(detail), "%s", error != NULL ? error : "invalid value");
      (void)snprintf(error, error_size, "line %u: %s", line_number, detail);
      (void)fclose(stream);
      return rc;
    }
  }
  if (ferror(stream) != 0) {
    set_error(error, error_size, "failed to read configuration");
    (void)fclose(stream);
    return -EIO;
  }
  (void)fclose(stream);
  return sdrd_config_validate(config, error, error_size);
}

int sdrd_config_validate(
    const sdrd_config_t *config,
    char *error,
    size_t error_size) {
  struct in_addr address;
  if (config == NULL) {
    set_error(error, error_size, "missing configuration");
    return -EINVAL;
  }
  if (config->mode != SDRD_MODE_SHADOW && config->mode != SDRD_MODE_CONTROLLED) {
    set_error(error, error_size, "invalid mode");
    return -EINVAL;
  }
  if (inet_pton(AF_INET, config->listen_address, &address) != 1) {
    set_error(error, error_size, "listen_address must be an IPv4 address");
    return -EINVAL;
  }
  if (config->listen_port < 1024u) {
    set_error(error, error_size, "listen_port must be between 1024 and 65535");
    return -EINVAL;
  }
  if (config->client_timeout_ms < 100u || config->client_timeout_ms > 60000u) {
    set_error(error, error_size, "client_timeout_ms must be between 100 and 60000");
    return -EINVAL;
  }
  if (config->iio_sysfs_root[0] == '\0') {
    set_error(error, error_size, "iio_sysfs_root is required");
    return -EINVAL;
  }
  if (config->development_data_root[0] != '/' ||
      strncmp(config->development_data_root, "/tmp/sdr-agent-dev", 18u) != 0 ||
      (config->development_data_root[18] != '\0' &&
       config->development_data_root[18] != '/') ||
      strstr(config->development_data_root, "..") != NULL) {
    set_error(error, error_size, "development_data_root must stay under /tmp/sdr-agent-dev");
    return -EINVAL;
  }
  if (config->iio_timeout_ms < 100u || config->iio_timeout_ms > 10000u) {
    set_error(error, error_size, "iio_timeout_ms must be between 100 and 10000");
    return -ERANGE;
  }
  if (config->iio_buffer_samples < 256u || config->iio_buffer_samples > 65536u) {
    set_error(error, error_size, "iio_buffer_samples must be between 256 and 65536");
    return -ERANGE;
  }
  if (config->retune_settle_ms > 1000u) {
    set_error(error, error_size, "retune_settle_ms must not exceed 1000");
    return -ERANGE;
  }
  if (config->min_center_hz < 70000000u || config->max_center_hz > 6000000000u ||
      config->min_center_hz > config->max_center_hz) {
    set_error(error, error_size, "center frequency limits must stay inside 70 MHz..6 GHz");
    return -ERANGE;
  }
  if (config->min_sample_rate_hz < 2083333u || config->max_sample_rate_hz > 30720000u ||
      config->min_sample_rate_hz > config->max_sample_rate_hz) {
    set_error(error, error_size, "sample-rate limits must stay inside 2.083333..30.72 MS/s");
    return -ERANGE;
  }
  if (config->min_rf_bandwidth_hz < 200000u || config->max_rf_bandwidth_hz > 56000000u ||
      config->min_rf_bandwidth_hz > config->max_rf_bandwidth_hz) {
    set_error(error, error_size, "RF-bandwidth limits must stay inside 0.2..56 MHz");
    return -ERANGE;
  }
  if (config->max_capture_bytes == 0u || config->max_capture_bytes > 64u * 1024u * 1024u) {
    set_error(error, error_size, "max_capture_bytes must be between 1 and 67108864");
    return -ERANGE;
  }
  if (config->fpga_backend != SDRD_FPGA_DISABLED) {
    if (config->fpga_device[0] == '\0' || config->fpga_span < 0x200u) {
      set_error(error, error_size, "enabled FPGA backend requires device and span >= 0x200");
      return -EINVAL;
    }
    if (config->fpga_backend == SDRD_FPGA_DEVMEM && config->allow_devmem == 0) {
      set_error(error, error_size, "devmem backend requires allow_devmem=true");
      return -EACCES;
    }
  }
  return 0;
}

static void probe_iio(const sdrd_config_t *config, sdrd_status_t *status) {
  DIR *directory = opendir(config->iio_sysfs_root);
  struct dirent *entry;
  if (directory == NULL) {
    status->health_flags |= SDRD_HEALTH_IIO_PHY_MISSING | SDRD_HEALTH_IIO_RX_MISSING;
    return;
  }
  while ((entry = readdir(directory)) != NULL) {
    char path[SDRD_MAX_PATH * 2u];
    char name[128];
    FILE *stream;
    if (strncmp(entry->d_name, "iio:device", 10u) != 0) {
      continue;
    }
    if (snprintf(path, sizeof(path), "%s/%s/name", config->iio_sysfs_root, entry->d_name) < 0) {
      continue;
    }
    stream = fopen(path, "r");
    if (stream == NULL) {
      continue;
    }
    if (fgets(name, sizeof(name), stream) != NULL) {
      char *trimmed = trim(name);
      if (strcmp(trimmed, "ad9361-phy") == 0) {
        status->iio_phy_visible = 1;
      } else if (strcmp(trimmed, "cf-ad9361-lpc") == 0) {
        status->iio_rx_visible = 1;
      }
    }
    (void)fclose(stream);
  }
  (void)closedir(directory);
  if (status->iio_phy_visible == 0) {
    status->health_flags |= SDRD_HEALTH_IIO_PHY_MISSING;
  }
  if (status->iio_rx_visible == 0) {
    status->health_flags |= SDRD_HEALTH_IIO_RX_MISSING;
  }
}

static int iomem_contains(uint64_t base, uint32_t span) {
  FILE *stream = fopen("/proc/iomem", "r");
  char line[256];
  const uint64_t requested_end = base + (uint64_t)span - 1u;
  if (stream == NULL || requested_end < base) {
    if (stream != NULL) {
      (void)fclose(stream);
    }
    return 0;
  }
  while (fgets(line, sizeof(line), stream) != NULL) {
    unsigned long long start;
    unsigned long long end;
    if (sscanf(line, "%llx-%llx", &start, &end) == 2 && base >= start && requested_end <= end) {
      (void)fclose(stream);
      return 1;
    }
  }
  (void)fclose(stream);
  return 0;
}

static void probe_fpga(const sdrd_config_t *config, sdrd_status_t *status) {
  p201_mmio_t *mmio;
  uint32_t flags = P201_MMIO_OPEN_READ_ONLY | P201_MMIO_OPEN_SYNC;
  uint64_t offset = 0u;
  int rc;
  if (config->fpga_backend == SDRD_FPGA_DISABLED) {
    return;
  }
  status->fpga_configured = 1;
  if (config->fpga_backend == SDRD_FPGA_DEVMEM) {
    if (config->require_iomem_region != 0 && iomem_contains(config->fpga_base, config->fpga_span) == 0) {
      status->health_flags |= SDRD_HEALTH_FPGA_UNAVAILABLE;
      return;
    }
    flags |= P201_MMIO_OPEN_DEVMEM;
    offset = config->fpga_base;
  }
  mmio = p201_mmio_create();
  if (mmio == NULL) {
    status->health_flags |= SDRD_HEALTH_FPGA_UNAVAILABLE;
    return;
  }
  rc = p201_mmio_open(mmio, config->fpga_device, offset, config->fpga_span, flags);
  if (rc != 0) {
    status->health_flags |= SDRD_HEALTH_FPGA_UNAVAILABLE;
    p201_mmio_destroy(mmio);
    return;
  }
  status->fpga_mapped = 1;
  if (p201_mmio_read32(mmio, 0x040u, &status->summary_version) != 0 ||
      p201_mmio_read32(mmio, 0x0ECu, &status->fpga_abi_version) != 0 ||
      p201_mmio_read32(mmio, 0x0F0u, &status->fpga_capability) != 0 ||
      p201_mmio_read32(mmio, 0x0FCu, &status->fpga_build_id) != 0 ||
      p201_mmio_read32(mmio, 0x180u, &status->aggregate_version) != 0 ||
      p201_mmio_read32(mmio, 0x1F4u, &status->aggregate_capability) != 0 ||
      p201_mmio_read32(mmio, 0x1F8u, &status->aggregate_build_id) != 0) {
    status->health_flags |= SDRD_HEALTH_FPGA_UNAVAILABLE;
    p201_mmio_destroy(mmio);
    return;
  }
  if (status->summary_version == SDRD_SUM8_MAGIC &&
      status->fpga_abi_version == SDRD_SUM8_ABI &&
      (status->fpga_capability & SDRD_AGGREGATE_CAPABILITY_BIT) != 0u &&
      status->aggregate_version == SDRD_AGG8_MAGIC) {
    status->fpga_identity_valid = 1;
  } else {
    status->health_flags |= SDRD_HEALTH_FPGA_IDENTITY_INVALID;
  }
  p201_mmio_destroy(mmio);
}

int sdrd_probe_status(
    const sdrd_config_t *config,
    sdrd_status_t *status,
    char *error,
    size_t error_size) {
  int rc;
  if (status == NULL) {
    set_error(error, error_size, "missing status output");
    return -EINVAL;
  }
  memset(status, 0, sizeof(*status));
  rc = sdrd_config_validate(config, error, error_size);
  if (rc != 0) {
    status->health_flags |= SDRD_HEALTH_CONFIG_INVALID;
    return rc;
  }
  probe_iio(config, status);
  probe_fpga(config, status);
  return 0;
}

typedef struct parsed_request {
  char storage[SDRD_MAX_LINE];
  char *fields[12];
  size_t field_count;
  const char *command;
  uint64_t request_id;
} parsed_request_t;

static int parse_request(const char *line, parsed_request_t *request) {
  char *save = NULL;
  char *token;
  if (line == NULL || request == NULL || strlen(line) >= sizeof(request->storage)) {
    return -EMSGSIZE;
  }
  memset(request, 0, sizeof(*request));
  (void)copy_text(request->storage, sizeof(request->storage), line);
  token = strtok_r(trim(request->storage), " \t", &save);
  while (token != NULL) {
    if (request->field_count >= sizeof(request->fields) / sizeof(request->fields[0])) {
      return -E2BIG;
    }
    request->fields[request->field_count++] = token;
    token = strtok_r(NULL, " \t", &save);
  }
  if (request->field_count < 3u || strcmp(request->fields[0], "SDRD/1") != 0) {
    return -EINVAL;
  }
  request->command = request->fields[1];
  return parse_u64(request->fields[2], &request->request_id);
}

static int request_has_fields(const parsed_request_t *request, size_t count) {
  return request->field_count == count ? 0 : -EINVAL;
}

static int radio_ops_available(const sdrd_radio_ops_t *radio) {
  return radio != NULL && radio->begin_session != NULL && radio->snapshot != NULL &&
         radio->apply_profile != NULL && radio->capture_iq != NULL && radio->cancel != NULL &&
         radio->stop != NULL && radio->restore != NULL;
}

static int valid_feature_id(const char *feature_id) {
  size_t index;
  const size_t length = feature_id == NULL ? 0u : strlen(feature_id);
  if (length == 0u || length >= SDRD_MAX_FEATURE_ID) {
    return 0;
  }
  for (index = 0u; index < length; ++index) {
    const unsigned char value = (unsigned char)feature_id[index];
    if (isalnum(value) == 0 && value != '-' && value != '_') {
      return 0;
    }
  }
  return 1;
}

static int valid_relative_path(const char *path) {
  size_t index;
  const size_t length = path == NULL ? 0u : strlen(path);
  if (length == 0u || length >= SDRD_MAX_PATH || path[0] == '/' ||
      strstr(path, "..") != NULL) {
    return 0;
  }
  for (index = 0u; index < length; ++index) {
    const unsigned char value = (unsigned char)path[index];
    if (isalnum(value) == 0 && value != '-' && value != '_' && value != '.' && value != '/') {
      return 0;
    }
  }
  return 1;
}

static int valid_gain_mode(const char *gain_mode) {
  return strcmp(gain_mode, "manual") == 0 || strcmp(gain_mode, "slow_attack") == 0 ||
         strcmp(gain_mode, "fast_attack") == 0 || strcmp(gain_mode, "hybrid") == 0;
}

static int format_error(
    uint64_t request_id,
    const char *code,
    char *response,
    size_t response_size) {
  const int written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"error\",\"error\":\"%s\"}\n",
      request_id,
      code);
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

void sdrd_session_init(sdrd_session_t *session) {
  if (session != NULL) {
    memset(session, 0, sizeof(*session));
  }
}

int sdrd_session_close(sdrd_session_t *session, const sdrd_radio_ops_t *radio) {
  int stop_rc = 0;
  int restore_rc = 0;
  if (session == NULL) {
    return -EINVAL;
  }
  if (session->active == 0 && session->restore_required == 0) {
    return 0;
  }
  if (radio == NULL || radio->stop == NULL || radio->restore == NULL) {
    session->faulted = 1;
    return -ENODEV;
  }
  stop_rc = radio->stop(radio->context);
  if (session->restore_required != 0) {
    restore_rc = radio->restore(radio->context, &session->saved_state);
  }
  session->active = 0;
  session->profile_applied = 0;
  if (restore_rc == 0) {
    session->restore_required = 0;
    memset(&session->current_state, 0, sizeof(session->current_state));
  } else {
    session->faulted = 1;
  }
  return restore_rc != 0 ? restore_rc : stop_rc;
}

static int handle_start_session(
    const parsed_request_t *request,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    char *response,
    size_t response_size) {
  uint64_t generation;
  int rc;
  int written;
  if (request_has_fields(request, 4u) != 0 ||
      parse_u64(request->fields[3], &generation) != 0 || generation == 0u) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  if (session->faulted != 0) {
    return format_error(request->request_id, "restore_fault", response, response_size);
  }
  if (session->active != 0) {
    return format_error(request->request_id, "session_busy", response, response_size);
  }
  rc = radio->snapshot(radio->context, &session->saved_state);
  if (rc != 0) {
    return format_error(request->request_id, "snapshot_failed", response, response_size);
  }
  rc = radio->begin_session(radio->context);
  if (rc != 0) {
    return format_error(request->request_id, "session_begin_failed", response, response_size);
  }
  session->generation = generation;
  session->active = 1;
  session->profile_applied = 0;
  session->restore_required = 1;
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"session_state\":\"owned\",\"restore_armed\":true}\n",
      request->request_id,
      generation);
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

static int handle_apply_profile(
    const sdrd_config_t *config,
    const parsed_request_t *request,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    char *response,
    size_t response_size) {
  sdrd_radio_state_t state;
  uint64_t generation;
  uint32_t enabled_channels;
  int rc;
  int written;
  memset(&state, 0, sizeof(state));
  if (request_has_fields(request, 9u) != 0 ||
      parse_u64(request->fields[3], &generation) != 0 ||
      parse_u64(request->fields[4], &state.center_hz) != 0 ||
      parse_u32(request->fields[5], &state.sample_rate_hz) != 0 ||
      parse_u32(request->fields[6], &state.rf_bandwidth_hz) != 0 ||
      valid_gain_mode(request->fields[7]) == 0 ||
      parse_u32(request->fields[8], &enabled_channels) != 0) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  if (session->active == 0 || generation != session->generation) {
    return format_error(request->request_id, "stale_or_missing_session", response, response_size);
  }
  if (state.center_hz < config->min_center_hz || state.center_hz > config->max_center_hz ||
      state.sample_rate_hz < config->min_sample_rate_hz ||
      state.sample_rate_hz > config->max_sample_rate_hz ||
      state.rf_bandwidth_hz < config->min_rf_bandwidth_hz ||
      state.rf_bandwidth_hz > config->max_rf_bandwidth_hz ||
      state.rf_bandwidth_hz > state.sample_rate_hz || enabled_channels != 1u) {
    return format_error(request->request_id, "profile_out_of_bounds", response, response_size);
  }
  (void)copy_text(state.gain_mode, sizeof(state.gain_mode), request->fields[7]);
  state.enabled_channels = enabled_channels;
  rc = radio->apply_profile(radio->context, &state);
  if (rc != 0) {
    const int restore_rc = sdrd_session_close(session, radio);
    return format_error(
        request->request_id,
        restore_rc == 0 ? "apply_failed_restored" : "apply_failed_restore_fault",
        response,
        response_size);
  }
  session->current_state = state;
  session->profile_applied = 1;
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"center_hz\":%" PRIu64 ",\"sample_rate_hz\":%u,\"rf_bandwidth_hz\":%u,\"gain_mode\":\"%s\",\"enabled_channels\":%u}\n",
      request->request_id,
      generation,
      state.center_hz,
      state.sample_rate_hz,
      state.rf_bandwidth_hz,
      state.gain_mode,
      state.enabled_channels);
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

static int handle_capture_iq(
    const sdrd_config_t *config,
    const parsed_request_t *request,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    char *response,
    size_t response_size) {
  sdrd_capture_request_t capture;
  sdrd_capture_result_t result;
  uint64_t required_bytes;
  int rc;
  int written;
  memset(&capture, 0, sizeof(capture));
  memset(&result, 0, sizeof(result));
  if (request_has_fields(request, 7u) != 0 ||
      parse_u64(request->fields[3], &capture.generation) != 0 ||
      parse_u64(request->fields[4], &capture.sample_count) != 0 ||
      parse_u64(request->fields[5], &capture.max_bytes) != 0 ||
      valid_feature_id(request->fields[6]) == 0) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  if (session->active == 0 || session->profile_applied == 0 ||
      capture.generation != session->generation) {
    return format_error(request->request_id, "stale_or_missing_session", response, response_size);
  }
  if (capture.sample_count == 0u || capture.sample_count > UINT64_MAX / 4u) {
    return format_error(request->request_id, "capture_out_of_bounds", response, response_size);
  }
  required_bytes = capture.sample_count * 4u;
  if (capture.max_bytes == 0u || capture.max_bytes > config->max_capture_bytes ||
      required_bytes > capture.max_bytes) {
    return format_error(request->request_id, "capture_out_of_bounds", response, response_size);
  }
  (void)copy_text(capture.feature_id, sizeof(capture.feature_id), request->fields[6]);
  rc = radio->capture_iq(radio->context, &capture, &result);
  if (rc != 0) {
    const int restore_rc = sdrd_session_close(session, radio);
    return format_error(
        request->request_id,
        restore_rc == 0 ? "capture_failed_restored" : "capture_failed_restore_fault",
        response,
        response_size);
  }
  if (result.samples_captured > capture.sample_count || result.bytes_written > capture.max_bytes ||
      valid_relative_path(result.relative_path) == 0) {
    (void)sdrd_session_close(session, radio);
    return format_error(request->request_id, "adapter_contract_violation", response, response_size);
  }
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"feature_id\":\"%s\",\"samples_captured\":%" PRIu64 ",\"bytes_written\":%" PRIu64 ",\"sequence\":%" PRIu64 ",\"dropped_samples\":%" PRIu64 ",\"overflow\":%s,\"relative_path\":\"%s\"}\n",
      request->request_id,
      capture.generation,
      capture.feature_id,
      result.samples_captured,
      result.bytes_written,
      result.sequence,
      result.dropped_samples,
      result.overflow != 0 ? "true" : "false",
      result.relative_path);
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

static int handle_execution_status(
    const parsed_request_t *request,
    const sdrd_session_t *session,
    char *response,
    size_t response_size) {
  uint64_t generation;
  int written;
  if (request_has_fields(request, 4u) != 0 ||
      parse_u64(request->fields[3], &generation) != 0) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  if (session->active != 0 && generation != session->generation) {
    return format_error(request->request_id, "stale_session", response, response_size);
  }
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"active\":%s,\"profile_applied\":%s,\"restore_armed\":%s,\"faulted\":%s}\n",
      request->request_id,
      session->generation,
      session->active != 0 ? "true" : "false",
      session->profile_applied != 0 ? "true" : "false",
      session->restore_required != 0 ? "true" : "false",
      session->faulted != 0 ? "true" : "false");
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

static int handle_stop_session(
    const parsed_request_t *request,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    char *response,
    size_t response_size) {
  uint64_t generation;
  int rc;
  int written;
  if (request_has_fields(request, 4u) != 0 ||
      parse_u64(request->fields[3], &generation) != 0) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  if (session->active == 0 || generation != session->generation) {
    return format_error(request->request_id, "stale_or_missing_session", response, response_size);
  }
  rc = sdrd_session_close(session, radio);
  if (rc != 0) {
    return format_error(request->request_id, "stop_or_restore_failed", response, response_size);
  }
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"stopped\":true,\"restored\":true}\n",
      request->request_id,
      generation);
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

int sdrd_handle_request(
    const sdrd_config_t *config,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    const char *request_line,
    char *response,
    size_t response_size) {
  parsed_request_t request;
  sdrd_status_t status;
  char error[256];
  int rc;
  int written;
  if (config == NULL || session == NULL || response == NULL || response_size == 0u) {
    return -EINVAL;
  }
  rc = parse_request(request_line, &request);
  if (rc != 0) {
    return format_error(0u, "invalid_request", response, response_size);
  }
  if (request.request_id == 0u) {
    return format_error(0u, "invalid_request_id", response, response_size);
  }
  if (session->last_request_id != 0u && request.request_id <= session->last_request_id) {
    return format_error(request.request_id, "stale_or_duplicate_request", response, response_size);
  }
  session->last_request_id = request.request_id;
  if (strcmp(request.command, "HELLO") == 0) {
    if (request_has_fields(&request, 3u) != 0) {
      return format_error(request.request_id, "invalid_arguments", response, response_size);
    }
    written = snprintf(
        response,
        response_size,
        "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"%s\",\"mutating_commands\":%s}\n",
        request.request_id,
        sdrd_mode_name(config->mode),
        config->mode == SDRD_MODE_CONTROLLED && radio_ops_available(radio) != 0 ? "true" : "false");
  } else if (strcmp(request.command, "CAPABILITIES") == 0 ||
             strcmp(request.command, "HEALTH") == 0) {
    if (request_has_fields(&request, 3u) != 0) {
      return format_error(request.request_id, "invalid_arguments", response, response_size);
    }
    rc = sdrd_probe_status(config, &status, error, sizeof(error));
    if (rc != 0) {
      return format_error(request.request_id, "probe_failed", response, response_size);
    }
    if (strcmp(request.command, "CAPABILITIES") == 0) {
      const int control = config->mode == SDRD_MODE_CONTROLLED && radio_ops_available(radio) != 0 &&
                          session->faulted == 0;
      written = snprintf(
          response,
          response_size,
          "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"mode\":\"%s\",\"iio_visible\":%s,\"radio_control\":%s,\"raw_iq_capture\":%s,\"max_capture_bytes\":%" PRIu64 ",\"fpga_backend\":\"%s\",\"fpga_identity_valid\":%s,\"fpga_summary_version\":%u,\"fpga_abi_version\":%u,\"fpga_capability\":%u,\"fpga_aggregate\":%s}\n",
          request.request_id,
          sdrd_mode_name(config->mode),
          status.iio_phy_visible != 0 && status.iio_rx_visible != 0 ? "true" : "false",
          control != 0 ? "true" : "false",
          control != 0 ? "true" : "false",
          config->max_capture_bytes,
          sdrd_fpga_backend_name(config->fpga_backend),
          status.fpga_identity_valid != 0 ? "true" : "false",
          status.summary_version,
          status.fpga_abi_version,
          status.fpga_capability,
          status.fpga_identity_valid != 0 ? "true" : "false");
    } else {
      const int healthy = status.health_flags == 0u && session->faulted == 0;
      written = snprintf(
          response,
          response_size,
          "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"healthy\":%s,\"health_flags\":%u,\"iio_phy_visible\":%s,\"iio_rx_visible\":%s,\"fpga_configured\":%s,\"fpga_mapped\":%s,\"fpga_identity_valid\":%s,\"session_faulted\":%s}\n",
          request.request_id,
          healthy != 0 ? "true" : "false",
          status.health_flags,
          status.iio_phy_visible != 0 ? "true" : "false",
          status.iio_rx_visible != 0 ? "true" : "false",
          status.fpga_configured != 0 ? "true" : "false",
          status.fpga_mapped != 0 ? "true" : "false",
          status.fpga_identity_valid != 0 ? "true" : "false",
          session->faulted != 0 ? "true" : "false");
    }
  } else if (strcmp(request.command, "QUIT") == 0) {
    if (request_has_fields(&request, 3u) != 0) {
      return format_error(request.request_id, "invalid_arguments", response, response_size);
    }
    rc = sdrd_session_close(session, radio);
    if (rc != 0) {
      return format_error(request.request_id, "stop_or_restore_failed", response, response_size);
    }
    written = snprintf(
        response,
        response_size,
        "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"closing\":true}\n",
        request.request_id);
  } else if (strcmp(request.command, "START_SESSION") == 0 ||
             strcmp(request.command, "APPLY_PROFILE") == 0 ||
             strcmp(request.command, "CAPTURE_IQ") == 0 ||
             strcmp(request.command, "EXECUTION_STATUS") == 0 ||
             strcmp(request.command, "STOP_SESSION") == 0) {
    if (config->mode != SDRD_MODE_CONTROLLED) {
      return format_error(request.request_id, "read_only_shadow", response, response_size);
    }
    if (radio_ops_available(radio) == 0) {
      return format_error(request.request_id, "radio_backend_unavailable", response, response_size);
    }
    if (strcmp(request.command, "START_SESSION") == 0) {
      return handle_start_session(&request, session, radio, response, response_size);
    }
    if (strcmp(request.command, "APPLY_PROFILE") == 0) {
      return handle_apply_profile(config, &request, session, radio, response, response_size);
    }
    if (strcmp(request.command, "CAPTURE_IQ") == 0) {
      return handle_capture_iq(config, &request, session, radio, response, response_size);
    }
    if (strcmp(request.command, "EXECUTION_STATUS") == 0) {
      return handle_execution_status(&request, session, response, response_size);
    }
    return handle_stop_session(&request, session, radio, response, response_size);
  } else if (strcmp(request.command, "RETUNE") == 0) {
    return format_error(request.request_id, "not_allowlisted", response, response_size);
  } else {
    return format_error(request.request_id, "unknown_command", response, response_size);
  }
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

int sdrd_format_response(
    const sdrd_config_t *config,
    const char *request_line,
    char *response,
    size_t response_size) {
  sdrd_session_t session;
  sdrd_session_init(&session);
  return sdrd_handle_request(
      config, &session, NULL, request_line, response, response_size);
}
