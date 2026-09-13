#define _POSIX_C_SOURCE 200809L

#include "sdrd.h"

#include <arpa/inet.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

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
  (void)copy_text(
      config->development_data_root,
      sizeof(config->development_data_root),
      "/tmp/sdr-agent-dev");
  config->iio_timeout_ms = 2000u;
  config->iio_buffer_samples = 4096u;
  config->retune_settle_ms = 5u;
  (void)copy_text(config->rx_input, sizeof(config->rx_input), "RX1");
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

int sdrd_rx_input_for_port(const char *port, int verified, sdrd_rx_input_identity_t *identity) {
  if (port == NULL || identity == NULL) return -EINVAL;
  const int second = strcmp(port, "RX2") == 0;
  if (!second && strcmp(port, "RX1") != 0) return -ENOTSUP;
  memset(identity, 0, sizeof(*identity));
  identity->identity_version = SDRD_RX_INPUT_IDENTITY_VERSION;
  identity->verified = verified != 0;
  (void)copy_text(identity->front_panel_port, sizeof(identity->front_panel_port), second ? "RX2" : "RX1");
  (void)copy_text(identity->logical_channel, sizeof(identity->logical_channel), second ? "RX1" : "RX0");
  (void)copy_text(identity->phy_channel, sizeof(identity->phy_channel), second ? "voltage1" : "voltage0");
  (void)copy_text(identity->scan_i_channel, sizeof(identity->scan_i_channel), second ? "voltage2" : "voltage0");
  (void)copy_text(identity->scan_q_channel, sizeof(identity->scan_q_channel), second ? "voltage3" : "voltage1");
  (void)copy_text(identity->rf_port_select, sizeof(identity->rf_port_select), "A_BALANCED");
  return 0;
}

int sdrd_rx_input_identity_valid(const sdrd_rx_input_identity_t *identity) {
  sdrd_rx_input_identity_t expected;
  if (identity == NULL || identity->verified != 1 ||
      memchr(identity->front_panel_port, '\0', sizeof(identity->front_panel_port)) == NULL ||
      sdrd_rx_input_for_port(identity->front_panel_port, 1, &expected) != 0) return 0;
  return identity->identity_version == expected.identity_version &&
         memcmp(identity->logical_channel, expected.logical_channel, sizeof(identity->logical_channel)) == 0 &&
         memcmp(identity->phy_channel, expected.phy_channel, sizeof(identity->phy_channel)) == 0 &&
         memcmp(identity->scan_i_channel, expected.scan_i_channel, sizeof(identity->scan_i_channel)) == 0 &&
         memcmp(identity->scan_q_channel, expected.scan_q_channel, sizeof(identity->scan_q_channel)) == 0 &&
         memcmp(identity->rf_port_select, expected.rf_port_select, sizeof(identity->rf_port_select)) == 0;
}

static int set_config_value(
    sdrd_config_t *config,
    const char *key,
    const char *value,
  char *error,
  size_t error_size) {
  uint32_t parsed_u32;
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
  if (strcmp(key, "rx_input") == 0) {
    return copy_text(config->rx_input, sizeof(config->rx_input), value);
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
  {
    sdrd_rx_input_identity_t selected;
    if (sdrd_rx_input_for_port(config->rx_input, 0, &selected) != 0) {
      set_error(error, error_size, "rx_input must be RX1 or RX2; TRX1/TRX2 receive routing is not verified");
      return -ENOTSUP;
    }
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
  return radio != NULL && radio->probe_rx_input != NULL && radio->begin_session != NULL &&
         radio->snapshot != NULL &&
         radio->apply_profile != NULL && radio->capture_iq != NULL && radio->cancel != NULL &&
         radio->stop != NULL && radio->restore != NULL;
}

static int power_ops_available(const sdrd_radio_ops_t *radio) {
  return radio != NULL && radio->capture_power != NULL;
}

static void expected_rx_input(
    sdrd_rx_input_identity_t *identity,
    int verified) {
  if (identity == NULL) {
    return;
  }
  memset(identity, 0, sizeof(*identity));
  identity->identity_version = SDRD_RX_INPUT_IDENTITY_VERSION;
  identity->verified = verified;
  (void)copy_text(
      identity->front_panel_port, sizeof(identity->front_panel_port), SDRD_RX_FRONT_PANEL_PORT);
  (void)copy_text(
      identity->logical_channel, sizeof(identity->logical_channel), SDRD_RX_LOGICAL_CHANNEL);
  (void)copy_text(identity->phy_channel, sizeof(identity->phy_channel), SDRD_RX_PHY_CHANNEL);
  (void)copy_text(
      identity->scan_i_channel, sizeof(identity->scan_i_channel), SDRD_RX_SCAN_I_CHANNEL);
  (void)copy_text(
      identity->scan_q_channel, sizeof(identity->scan_q_channel), SDRD_RX_SCAN_Q_CHANNEL);
  (void)copy_text(
      identity->rf_port_select, sizeof(identity->rf_port_select), SDRD_RX_RF_PORT_SELECT);
}

static int probe_selected_rx_input(
    const sdrd_radio_ops_t *radio,
    sdrd_rx_input_identity_t *identity) {
  sdrd_rx_input_identity_t observed;
  int rc;
  expected_rx_input(identity, 0);
  if (radio == NULL || radio->probe_rx_input == NULL) {
    return -ENODEV;
  }
  memset(&observed, 0, sizeof(observed));
  rc = radio->probe_rx_input(radio->context, &observed);
  if (rc != 0 || sdrd_rx_input_identity_valid(&observed) == 0) {
    return rc != 0 ? rc : -EPROTO;
  }
  *identity = observed;
  return 0;
}

static int format_rx_input_json(
    const sdrd_rx_input_identity_t *identity,
    char *output,
    size_t output_size) {
  const int verified = sdrd_rx_input_identity_valid(identity);
  sdrd_rx_input_identity_t selected;
  expected_rx_input(&selected, 0);
  if (verified) selected = *identity;
  const int written = snprintf(
      output,
      output_size,
      "\"rx_input\":{\"identity_version\":%u,\"verified\":%s,"
      "\"front_panel_port\":\"%s\",\"logical_channel\":\"%s\","
      "\"phy_channel\":\"%s\",\"scan_i_channel\":\"%s\","
      "\"scan_q_channel\":\"%s\",\"rf_port_select\":\"%s\","
      "\"source\":\"iio_channel_attr\"}",
      SDRD_RX_INPUT_IDENTITY_VERSION,
      verified != 0 ? "true" : "false",
      selected.front_panel_port,
      selected.logical_channel,
      selected.phy_channel,
      selected.scan_i_channel,
      selected.scan_q_channel,
      selected.rf_port_select);
  return written < 0 || (size_t)written >= output_size ? -ENOSPC : 0;
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

static void normalize_capture_error(
    sdrd_capture_result_t *result,
    int rc,
    uint32_t timeout_ms) {
  if (result->timeout_ms == 0u) {
    result->timeout_ms = timeout_ms;
  }
  if (rc == -ETIMEDOUT) {
    result->timed_out = 1;
    result->health_flags |= SDRD_EXEC_HEALTH_TIMEOUT;
  } else if (rc == -EOVERFLOW || rc == -EPIPE) {
    result->overflow = 1;
    result->health_flags |= SDRD_EXEC_HEALTH_OVERFLOW;
  } else if (rc == -ECANCELED) {
    result->health_flags |= SDRD_EXEC_HEALTH_CANCELLED;
  } else if (result->health_flags == 0u) {
    result->health_flags = SDRD_EXEC_HEALTH_IO_ERROR;
  }
}

static void normalize_summary_error(
    sdrd_summary_result_t *result,
    int rc,
    uint32_t timeout_ms) {
  if (result->timeout_ms == 0u) {
    result->timeout_ms = timeout_ms;
  }
  if (rc == -ETIMEDOUT) {
    result->timed_out = 1;
    result->health_flags |= SDRD_EXEC_HEALTH_TIMEOUT;
  } else if (rc == -EOVERFLOW || rc == -EPIPE) {
    result->overflow = 1;
    result->health_flags |= SDRD_EXEC_HEALTH_OVERFLOW;
  } else if (rc == -ECANCELED) {
    result->health_flags |= SDRD_EXEC_HEALTH_CANCELLED;
  } else if (result->health_flags == 0u) {
    result->health_flags = SDRD_EXEC_HEALTH_IO_ERROR;
  }
  result->status_flags = result->health_flags;
}

static int format_capture_error(
    uint64_t request_id,
    uint64_t generation,
    const char *code,
    const sdrd_capture_result_t *result,
    char *response,
    size_t response_size) {
  const int written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64
      ",\"status\":\"error\",\"error\":\"%s\",\"generation\":%" PRIu64
      ",\"session_generation\":%" PRIu64 ",\"sequence\":%" PRIu64
      ",\"dropped_samples\":%" PRIu64 ",\"overflow\":%s"
      ",\"timeout\":{\"limit_ms\":%u,\"elapsed_us\":%" PRIu64
      ",\"timed_out\":%s},\"health\":{\"healthy\":false,\"flags\":%u"
      ",\"source\":\"iio_adapter\"}}\n",
      request_id,
      code,
      generation,
      generation,
      result->sequence,
      result->dropped_samples,
      result->overflow != 0 ? "true" : "false",
      result->timeout_ms,
      result->elapsed_us,
      result->timed_out != 0 ? "true" : "false",
      result->health_flags);
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

static int format_summary_error(
    uint64_t request_id,
    uint64_t generation,
    const char *code,
    const sdrd_summary_result_t *result,
    char *response,
    size_t response_size) {
  const int written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64
      ",\"status\":\"error\",\"error\":\"%s\",\"generation\":%" PRIu64
      ",\"session_generation\":%" PRIu64 ",\"sequence\":%" PRIu64
      ",\"dropped_samples\":%" PRIu64 ",\"overflow\":%s"
      ",\"timeout\":{\"limit_ms\":%u,\"elapsed_us\":%" PRIu64
      ",\"timed_out\":%s},\"health\":{\"healthy\":false,\"flags\":%u"
      ",\"source\":\"iio_adapter\"}}\n",
      request_id,
      code,
      generation,
      generation,
      result->sequence,
      result->dropped_samples,
      result->overflow != 0 ? "true" : "false",
      result->timeout_ms,
      result->elapsed_us,
      result->timed_out != 0 ? "true" : "false",
      result->health_flags);
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
  int identity_rc = 0;
  sdrd_rx_input_identity_t identity;
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
  memset(&identity, 0, sizeof(identity));
  identity_rc = probe_selected_rx_input(radio, &identity);
  if (identity_rc == 0 &&
      sdrd_rx_input_identity_valid(&session->saved_state.rx_input) != 0 &&
      memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
    identity_rc = -EPROTO;
  }
  session->active = 0;
  session->profile_applied = 0;
  if (restore_rc == 0 && identity_rc == 0) {
    session->restore_required = 0;
    memset(&session->current_state, 0, sizeof(session->current_state));
  } else {
    session->faulted = 1;
  }
  if (restore_rc != 0) {
    return restore_rc;
  }
  if (identity_rc != 0) {
    return identity_rc;
  }
  return stop_rc;
}

static int handle_start_session(
    const sdrd_config_t *config,
    const parsed_request_t *request,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    char *response,
    size_t response_size) {
  uint64_t generation;
  sdrd_rx_input_identity_t identity;
  char rx_input_json[384];
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
  memset(&identity, 0, sizeof(identity));
  rc = probe_selected_rx_input(radio, &identity);
  if (rc != 0 || strcmp(identity.front_panel_port, config->rx_input) != 0) {
    return format_error(request->request_id, "rx_input_unavailable", response, response_size);
  }
  rc = radio->snapshot(radio->context, &session->saved_state);
  if (rc != 0 || sdrd_rx_input_identity_valid(&session->saved_state.rx_input) == 0 ||
      memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
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
  if (format_rx_input_json(&identity, rx_input_json, sizeof(rx_input_json)) != 0) {
    (void)sdrd_session_close(session, radio);
    return -ENOSPC;
  }
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"session_generation\":%" PRIu64 ",\"session_state\":\"owned\",\"restore_armed\":true,%s}\n",
      request->request_id,
      generation,
      generation,
      rx_input_json);
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
  uint32_t hardware_gain_db = 0u;
  uint32_t enabled_channels;
  sdrd_rx_input_identity_t identity;
  char rx_input_json[384];
  size_t expected_fields;
  int rc;
  int written;
  memset(&state, 0, sizeof(state));
  if (request->field_count < 8u) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  expected_fields = strcmp(request->fields[7], "manual") == 0 ? 10u : 9u;
  if (request_has_fields(request, expected_fields) != 0 ||
      parse_u64(request->fields[3], &generation) != 0 ||
      parse_u64(request->fields[4], &state.center_hz) != 0 ||
      parse_u32(request->fields[5], &state.sample_rate_hz) != 0 ||
      parse_u32(request->fields[6], &state.rf_bandwidth_hz) != 0 ||
      valid_gain_mode(request->fields[7]) == 0 ||
      (expected_fields == 10u &&
       (parse_u32(request->fields[8], &hardware_gain_db) != 0 || hardware_gain_db > 60u)) ||
      parse_u32(request->fields[expected_fields - 1u], &enabled_channels) != 0) {
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
  if (expected_fields == 10u) {
    (void)snprintf(state.hardware_gain, sizeof(state.hardware_gain), "%u", hardware_gain_db);
  }
  state.enabled_channels = enabled_channels;
  state.rx_input = session->saved_state.rx_input;
  memset(&identity, 0, sizeof(identity));
  rc = probe_selected_rx_input(radio, &identity);
  if (rc != 0 || memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
    (void)sdrd_session_close(session, radio);
    return format_error(request->request_id, "rx_input_changed", response, response_size);
  }
  rc = radio->apply_profile(radio->context, &state);
  if (rc == 0) {
    rc = probe_selected_rx_input(radio, &identity);
    if (rc == 0 && memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
      rc = -EPROTO;
    }
  }
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
  if (format_rx_input_json(&identity, rx_input_json, sizeof(rx_input_json)) != 0) {
    (void)sdrd_session_close(session, radio);
    return -ENOSPC;
  }
  if (expected_fields == 10u) {
    written = snprintf(
        response,
        response_size,
        "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"session_generation\":%" PRIu64 ",\"center_hz\":%" PRIu64 ",\"sample_rate_hz\":%u,\"rf_bandwidth_hz\":%u,\"gain_mode\":\"%s\",\"hardware_gain_db\":%u,\"enabled_channels\":%u,%s}\n",
        request->request_id,
        generation,
        generation,
        state.center_hz,
        state.sample_rate_hz,
        state.rf_bandwidth_hz,
        state.gain_mode,
        hardware_gain_db,
        state.enabled_channels,
        rx_input_json);
  } else {
    written = snprintf(
        response,
        response_size,
        "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"session_generation\":%" PRIu64 ",\"center_hz\":%" PRIu64 ",\"sample_rate_hz\":%u,\"rf_bandwidth_hz\":%u,\"gain_mode\":\"%s\",\"enabled_channels\":%u,%s}\n",
        request->request_id,
        generation,
        generation,
        state.center_hz,
        state.sample_rate_hz,
        state.rf_bandwidth_hz,
        state.gain_mode,
        state.enabled_channels,
        rx_input_json);
  }
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
  sdrd_rx_input_identity_t identity;
  char rx_input_json[384];
  uint64_t required_bytes;
  int rc;
  int written;
  memset(&capture, 0, sizeof(capture));
  memset(&result, 0, sizeof(result));
  memset(&identity, 0, sizeof(identity));
  if ((request->field_count != 7u && request->field_count != 8u) ||
      parse_u64(request->fields[3], &capture.generation) != 0 ||
      parse_u64(request->fields[4], &capture.sample_count) != 0 ||
      parse_u64(request->fields[5], &capture.max_bytes) != 0 ||
      valid_feature_id(request->fields[6]) == 0 ||
      (request->field_count == 8u && parse_u32(request->fields[7], &capture.timeout_ms) != 0)) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  if (session->active == 0 || session->profile_applied == 0 ||
      capture.generation != session->generation) {
    return format_error(request->request_id, "stale_or_missing_session", response, response_size);
  }
  if (capture.sample_count == 0u || capture.sample_count > UINT64_MAX / 4u) {
    return format_error(request->request_id, "capture_out_of_bounds", response, response_size);
  }
  if (capture.timeout_ms == 0u) {
    capture.timeout_ms = config->iio_timeout_ms;
  }
  if (capture.timeout_ms > 5000u) {
    return format_error(
        request->request_id, "capture_timeout_out_of_bounds", response, response_size);
  }
  required_bytes = capture.sample_count * 4u;
  if (capture.max_bytes == 0u || capture.max_bytes > config->max_capture_bytes ||
      required_bytes > capture.max_bytes) {
    return format_error(request->request_id, "capture_out_of_bounds", response, response_size);
  }
  (void)copy_text(capture.feature_id, sizeof(capture.feature_id), request->fields[6]);
  rc = probe_selected_rx_input(radio, &identity);
  if (rc == 0 && memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
    rc = -EPROTO;
  }
  if (rc == 0) {
    rc = radio->capture_iq(radio->context, &capture, &result);
  }
  if (rc == 0) {
    rc = probe_selected_rx_input(radio, &identity);
    if (rc == 0 && memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
      rc = -EPROTO;
    }
    if (rc != 0) {
      result.health_flags |= SDRD_EXEC_HEALTH_RADIO_STATE;
    }
  }
  if (rc != 0) {
    const int restore_rc = sdrd_session_close(session, radio);
    normalize_capture_error(&result, rc, capture.timeout_ms);
    return format_capture_error(
        request->request_id,
        capture.generation,
        restore_rc == 0 ? "capture_failed_restored" : "capture_failed_restore_fault",
        &result,
        response,
        response_size);
  }
  if (result.samples_captured > capture.sample_count || result.bytes_written > capture.max_bytes ||
      result.timeout_ms == 0u || result.timed_out != 0 ||
      valid_relative_path(result.relative_path) == 0) {
    (void)sdrd_session_close(session, radio);
    return format_error(request->request_id, "adapter_contract_violation", response, response_size);
  }
  if (format_rx_input_json(&identity, rx_input_json, sizeof(rx_input_json)) != 0) {
    (void)sdrd_session_close(session, radio);
    return -ENOSPC;
  }
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"session_generation\":%" PRIu64 ",\"feature_id\":\"%s\",\"samples_captured\":%" PRIu64 ",\"bytes_written\":%" PRIu64 ",\"sequence\":%" PRIu64 ",\"dropped_samples\":%" PRIu64 ",\"overflow\":%s,\"timeout\":{\"limit_ms\":%u,\"elapsed_us\":%" PRIu64 ",\"timed_out\":%s},\"health\":{\"healthy\":%s,\"flags\":%u,\"source\":\"iio_adapter\"},%s,\"relative_path\":\"%s\"}\n",
      request->request_id,
      capture.generation,
      capture.generation,
      capture.feature_id,
      result.samples_captured,
      result.bytes_written,
      result.sequence,
      result.dropped_samples,
      result.overflow != 0 ? "true" : "false",
      result.timeout_ms,
      result.elapsed_us,
      result.timed_out != 0 ? "true" : "false",
      result.health_flags == 0u ? "true" : "false",
      result.health_flags,
      rx_input_json,
      result.relative_path);
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

static int append_base64_file(
    const char *path,
    uint64_t expected_bytes,
    char *response,
    size_t response_size,
    size_t *offset) {
  static const char alphabet[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  unsigned char *bytes;
  struct stat status;
  size_t input_size;
  size_t encoded_size;
  size_t input = 0u;
  size_t output;
  int fd;
  if (expected_bytes == 0u || expected_bytes > SDRD_MAX_INLINE_CAPTURE_BYTES ||
      expected_bytes > SIZE_MAX) {
    return -ERANGE;
  }
  input_size = (size_t)expected_bytes;
  encoded_size = ((input_size + 2u) / 3u) * 4u;
  if (*offset > response_size || encoded_size > response_size - *offset) {
    return -ENOSPC;
  }
  fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
  if (fd < 0) {
    return -errno;
  }
  if (fstat(fd, &status) != 0 || !S_ISREG(status.st_mode) || status.st_size < 0 ||
      (uint64_t)status.st_size != expected_bytes) {
    (void)close(fd);
    return -EPROTO;
  }
  bytes = malloc(input_size);
  if (bytes == NULL) {
    (void)close(fd);
    return -ENOMEM;
  }
  while (input < input_size) {
    const ssize_t count = read(fd, bytes + input, input_size - input);
    if (count < 0 && errno == EINTR) {
      continue;
    }
    if (count <= 0) {
      free(bytes);
      (void)close(fd);
      return count == 0 ? -EPROTO : -errno;
    }
    input += (size_t)count;
  }
  if (close(fd) != 0) {
    free(bytes);
    return -errno;
  }
  output = *offset;
  for (input = 0u; input < input_size; input += 3u) {
    const uint32_t first = bytes[input];
    const uint32_t second = input + 1u < input_size ? bytes[input + 1u] : 0u;
    const uint32_t third = input + 2u < input_size ? bytes[input + 2u] : 0u;
    const uint32_t packed = (first << 16u) | (second << 8u) | third;
    response[output++] = alphabet[(packed >> 18u) & 0x3fu];
    response[output++] = alphabet[(packed >> 12u) & 0x3fu];
    response[output++] = input + 1u < input_size ? alphabet[(packed >> 6u) & 0x3fu] : '=';
    response[output++] = input + 2u < input_size ? alphabet[packed & 0x3fu] : '=';
  }
  free(bytes);
  *offset = output;
  return 0;
}

static int handle_capture_iq_inline(
    const sdrd_config_t *config,
    const parsed_request_t *request,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    char *response,
    size_t response_size) {
  sdrd_capture_request_t capture;
  sdrd_capture_result_t result;
  sdrd_rx_input_identity_t identity;
  char rx_input_json[384];
  char full_path[SDRD_MAX_PATH * 2u];
  char feature_path[SDRD_MAX_PATH * 2u];
  uint64_t required_bytes;
  size_t offset;
  int rc;
  int written;
  memset(&capture, 0, sizeof(capture));
  memset(&result, 0, sizeof(result));
  memset(&identity, 0, sizeof(identity));
  if ((request->field_count != 7u && request->field_count != 8u) ||
      parse_u64(request->fields[3], &capture.generation) != 0 ||
      parse_u64(request->fields[4], &capture.sample_count) != 0 ||
      parse_u64(request->fields[5], &capture.max_bytes) != 0 ||
      valid_feature_id(request->fields[6]) == 0 ||
      (request->field_count == 8u && parse_u32(request->fields[7], &capture.timeout_ms) != 0)) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  if (session->active == 0 || session->profile_applied == 0 ||
      capture.generation != session->generation) {
    return format_error(request->request_id, "stale_or_missing_session", response, response_size);
  }
  if (capture.sample_count == 0u || capture.sample_count > UINT64_MAX / 4u) {
    return format_error(request->request_id, "capture_out_of_bounds", response, response_size);
  }
  if (capture.timeout_ms == 0u) {
    capture.timeout_ms = config->iio_timeout_ms;
  }
  if (capture.timeout_ms > 5000u) {
    return format_error(
        request->request_id, "capture_timeout_out_of_bounds", response, response_size);
  }
  required_bytes = capture.sample_count * 4u;
  if (capture.max_bytes != required_bytes || required_bytes > SDRD_MAX_INLINE_CAPTURE_BYTES ||
      required_bytes > config->max_capture_bytes) {
    return format_error(request->request_id, "inline_capture_out_of_bounds", response, response_size);
  }
  (void)copy_text(capture.feature_id, sizeof(capture.feature_id), request->fields[6]);
  rc = probe_selected_rx_input(radio, &identity);
  if (rc == 0 && memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
    rc = -EPROTO;
  }
  if (rc == 0) {
    rc = radio->capture_iq(radio->context, &capture, &result);
  }
  if (rc == 0) {
    rc = probe_selected_rx_input(radio, &identity);
    if (rc == 0 && memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
      rc = -EPROTO;
    }
    if (rc != 0) {
      result.health_flags |= SDRD_EXEC_HEALTH_RADIO_STATE;
    }
  }
  if (rc != 0) {
    const int restore_rc = sdrd_session_close(session, radio);
    normalize_capture_error(&result, rc, capture.timeout_ms);
    return format_capture_error(
        request->request_id,
        capture.generation,
        restore_rc == 0 ? "capture_failed_restored" : "capture_failed_restore_fault",
        &result,
        response,
        response_size);
  }
  if (result.samples_captured != capture.sample_count || result.bytes_written != required_bytes ||
      result.dropped_samples != 0u || result.overflow != 0 || result.timeout_ms == 0u ||
      result.timed_out != 0 || result.health_flags != 0u ||
      valid_relative_path(result.relative_path) == 0) {
    (void)sdrd_session_close(session, radio);
    return format_error(request->request_id, "adapter_contract_violation", response, response_size);
  }
  if (format_rx_input_json(&identity, rx_input_json, sizeof(rx_input_json)) != 0) {
    (void)sdrd_session_close(session, radio);
    return -ENOSPC;
  }
  written = snprintf(full_path, sizeof(full_path), "%s/%s", config->development_data_root,
                     result.relative_path);
  if (written < 0 || (size_t)written >= sizeof(full_path)) {
    (void)sdrd_session_close(session, radio);
    return format_error(request->request_id, "inline_path_invalid", response, response_size);
  }
  written = snprintf(feature_path, sizeof(feature_path), "%s/%s", config->development_data_root,
                     capture.feature_id);
  if (written < 0 || (size_t)written >= sizeof(feature_path)) {
    (void)unlink(full_path);
    (void)sdrd_session_close(session, radio);
    return format_error(request->request_id, "inline_path_invalid", response, response_size);
  }
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64
      ",\"status\":\"ok\",\"generation\":%" PRIu64
      ",\"session_generation\":%" PRIu64
      ",\"samples_captured\":%" PRIu64 ",\"bytes_transferred\":%" PRIu64
      ",\"sequence\":%" PRIu64 ",\"dropped_samples\":%" PRIu64
      ",\"overflow\":%s,\"timeout\":{\"limit_ms\":%u,\"elapsed_us\":%" PRIu64
      ",\"timed_out\":%s},\"health\":{\"healthy\":%s,\"flags\":%u"
      ",\"source\":\"iio_adapter\"},%s,\"iq_base64\":\"",
      request->request_id,
      capture.generation,
      capture.generation,
      result.samples_captured,
      result.bytes_written,
      result.sequence,
      result.dropped_samples,
      result.overflow != 0 ? "true" : "false",
      result.timeout_ms,
      result.elapsed_us,
      result.timed_out != 0 ? "true" : "false",
      result.health_flags == 0u ? "true" : "false",
      result.health_flags,
      rx_input_json);
  if (written < 0 || (size_t)written >= response_size) {
    rc = -ENOSPC;
  } else {
    offset = (size_t)written;
    rc = append_base64_file(full_path, result.bytes_written, response, response_size, &offset);
    if (rc == 0) {
      if (response_size - offset < 4u) {
        rc = -ENOSPC;
      } else {
        response[offset++] = '"';
        response[offset++] = '}';
        response[offset++] = '\n';
        response[offset] = '\0';
      }
    }
  }
  if (unlink(full_path) != 0 && rc == 0) {
    rc = -errno;
  }
  if (rmdir(feature_path) != 0 && errno != ENOENT && rc == 0) {
    rc = -errno;
  }
  if (rc != 0) {
    const int restore_rc = sdrd_session_close(session, radio);
    return format_error(
        request->request_id,
        restore_rc == 0 ? "inline_transfer_failed_restored" : "inline_transfer_restore_fault",
        response,
        response_size);
  }
  return 0;
}

static int handle_capture_power(
    const parsed_request_t *request,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    char *response,
    size_t response_size) {
  sdrd_summary_request_t summary;
  sdrd_summary_result_t result;
  sdrd_rx_input_identity_t identity;
  char rx_input_json[384];
  int rc;
  int written;
  memset(&summary, 0, sizeof(summary));
  memset(&result, 0, sizeof(result));
  memset(&identity, 0, sizeof(identity));
  if (request_has_fields(request, 7u) != 0 ||
      parse_u64(request->fields[3], &summary.generation) != 0 ||
      parse_u32(request->fields[4], &summary.frame_samples) != 0 ||
      parse_u32(request->fields[5], &summary.aggregate_frames) != 0 ||
      parse_u32(request->fields[6], &summary.timeout_ms) != 0) {
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  }
  if (session->active == 0 || session->profile_applied == 0 ||
      summary.generation != session->generation) {
    return format_error(request->request_id, "stale_or_missing_session", response, response_size);
  }
  if (summary.frame_samples < 64u || summary.frame_samples > 65535u ||
      summary.aggregate_frames == 0u || summary.aggregate_frames > 65535u ||
      (uint64_t)summary.frame_samples * (uint64_t)summary.aggregate_frames > 1048576u ||
      summary.timeout_ms == 0u || summary.timeout_ms > 5000u) {
    return format_error(request->request_id, "summary_out_of_bounds", response, response_size);
  }
  if (power_ops_available(radio) == 0) {
    return format_error(request->request_id, "software_summary_unavailable", response, response_size);
  }
  rc = probe_selected_rx_input(radio, &identity);
  if (rc == 0 && memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
    rc = -EPROTO;
  }
  if (rc == 0) {
    rc = radio->capture_power(radio->context, &summary, &result);
  }
  if (rc == 0) {
    rc = probe_selected_rx_input(radio, &identity);
    if (rc == 0 && memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) {
      rc = -EPROTO;
    }
    if (rc != 0) {
      result.health_flags |= SDRD_EXEC_HEALTH_RADIO_STATE;
      result.status_flags = result.health_flags;
    }
  }
  if (rc != 0) {
    const int restore_rc = sdrd_session_close(session, radio);
    const char *code = rc == -ETIMEDOUT ? "power_timeout_restored" : "power_failed_restored";
    if (restore_rc != 0) {
      code = "power_failed_restore_fault";
    }
    normalize_summary_error(&result, rc, summary.timeout_ms);
    return format_summary_error(
        request->request_id,
        summary.generation,
        code,
        &result,
        response,
        response_size);
  }
  if (format_rx_input_json(&identity, rx_input_json, sizeof(rx_input_json)) != 0) {
    (void)sdrd_session_close(session, radio);
    return -ENOSPC;
  }
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64
      ",\"status\":\"ok\",\"generation\":%" PRIu64
      ",\"session_generation\":%" PRIu64
      ",\"sequence\":%" PRIu64 ",\"aggregate_samples\":%" PRIu64
      ",\"rx0_power_lo\":%u,\"rx0_power_mid\":%u,\"rx0_power_hi\":%u"
      ",\"rx0_clip_count\":%" PRIu64 ",\"status_flags\":%u,\"elapsed_us\":%" PRIu64
      ",\"dropped_samples\":%" PRIu64 ",\"overflow\":%s"
      ",\"timeout\":{\"limit_ms\":%u,\"elapsed_us\":%" PRIu64
      ",\"timed_out\":%s},\"health\":{\"healthy\":%s,\"flags\":%u"
      ",\"source\":\"iio_adapter\"},%s}\n",
      request->request_id,
      summary.generation,
      summary.generation,
      result.sequence,
      result.aggregate_samples,
      result.rx0_power_lo,
      result.rx0_power_mid,
      result.rx0_power_hi,
      result.rx0_clip_count,
      result.status_flags,
      result.elapsed_us,
      result.dropped_samples,
      result.overflow != 0 ? "true" : "false",
      result.timeout_ms,
      result.elapsed_us,
      result.timed_out != 0 ? "true" : "false",
      result.health_flags == 0u ? "true" : "false",
      result.health_flags,
      rx_input_json);
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
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"session_generation\":%" PRIu64 ",\"active\":%s,\"profile_applied\":%s,\"restore_armed\":%s,\"faulted\":%s}\n",
      request->request_id,
      session->generation,
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
  char rx_input_json[384];
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
  if (format_rx_input_json(
          &session->saved_state.rx_input, rx_input_json, sizeof(rx_input_json)) != 0) {
    return -ENOSPC;
  }
  written = snprintf(
      response,
      response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"generation\":%" PRIu64 ",\"session_generation\":%" PRIu64 ",\"stopped\":true,\"restored\":true,%s}\n",
      request->request_id,
      generation,
      generation,
      rx_input_json);
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}

typedef struct stream_sink_context {
  const sdrd_radio_ops_t *radio;
  uint64_t id, generation, offset, sequence, maximum;
  int ready;
} stream_sink_context_t;

static int stream_sink(void *context, const void *data, size_t bytes) {
  stream_sink_context_t *s = context;
  char header[384];
  int written, rc;
  if (data == NULL && bytes == 0u) {
    if (s->ready != 0) return -EPROTO;
    s->ready = 1;
    written = snprintf(header, sizeof(header),
        "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"event\":\"rx_ready\",\"generation\":%" PRIu64 ",\"maximum_bytes\":%" PRIu64 "}\n",
        s->id, s->generation, s->maximum);
  } else {
    if (s->ready == 0 || data == NULL || bytes == 0u || bytes % 4u != 0u ||
        bytes > SDRD_MAX_INLINE_CAPTURE_BYTES || s->offset > s->maximum || bytes > s->maximum - s->offset) return -EPROTO;
    written = snprintf(header, sizeof(header),
        "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"event\":\"rx_chunk\",\"generation\":%" PRIu64 ",\"sequence\":%" PRIu64 ",\"sample_offset\":%" PRIu64 ",\"bytes\":%zu}\n",
        s->id, s->generation, s->sequence, s->offset / 4u, bytes);
  }
  if (written < 0 || (size_t)written >= sizeof(header)) return -ENOSPC;
  rc = s->radio->stream_write(s->radio->stream_context, header, (size_t)written);
  if (rc == 0 && bytes != 0u) {
    rc = s->radio->stream_write(s->radio->stream_context, data, bytes);
    if (rc == 0) { s->offset += bytes; ++s->sequence; }
  }
  return rc;
}

static int handle_capture_stream(const sdrd_config_t *config, const parsed_request_t *request,
    sdrd_session_t *session, const sdrd_radio_ops_t *radio, char *response, size_t response_size) {
  sdrd_capture_request_t capture;
  sdrd_capture_result_t result;
  sdrd_rx_input_identity_t identity;
  stream_sink_context_t sink;
  int rc, restored, written;
  memset(&capture, 0, sizeof(capture)); memset(&result, 0, sizeof(result)); memset(&sink, 0, sizeof(sink));
  if (request->field_count != 7u || parse_u64(request->fields[3], &capture.generation) != 0 ||
      parse_u64(request->fields[4], &capture.sample_count) != 0 ||
      parse_u64(request->fields[5], &capture.max_bytes) != 0 ||
      parse_u32(request->fields[6], &capture.timeout_ms) != 0)
    return format_error(request->request_id, "invalid_arguments", response, response_size);
  if (session->active == 0 || session->profile_applied == 0 || session->generation != capture.generation)
    return format_error(request->request_id, "stale_or_missing_session", response, response_size);
  if (radio->capture_stream == NULL || radio->stream_write == NULL)
    return format_error(request->request_id, "stream_unavailable", response, response_size);
  if (capture.sample_count == 0u || capture.sample_count > UINT64_MAX / 4u ||
      capture.max_bytes != capture.sample_count * 4u || capture.max_bytes > config->max_capture_bytes ||
      capture.timeout_ms < 100u || capture.timeout_ms > 120000u ||
      config->iio_buffer_samples > SDRD_MAX_INLINE_CAPTURE_BYTES / 4u)
    return format_error(request->request_id, "stream_out_of_bounds", response, response_size);
  sink.radio = radio; sink.id = request->request_id; sink.generation = capture.generation; sink.maximum = capture.max_bytes;
  rc = probe_selected_rx_input(radio, &identity);
  if (rc == 0 && memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0) rc = -EPROTO;
  if (rc == 0) rc = radio->capture_stream(radio->context, &capture, stream_sink, &sink, &result);
  if (rc == 0) rc = probe_selected_rx_input(radio, &identity);
  if (rc == 0 && (memcmp(&identity, &session->saved_state.rx_input, sizeof(identity)) != 0 ||
      sink.ready == 0 || sink.offset != capture.max_bytes || result.bytes_written != capture.max_bytes ||
      result.samples_captured != capture.sample_count || result.health_flags != 0u ||
      result.dropped_samples != 0u || result.overflow != 0 || result.timed_out != 0)) rc = -EPROTO;
  restored = sdrd_session_close(session, radio) == 0;
  written = snprintf(response, response_size,
      "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"%s\",\"event\":\"rx_end\",\"generation\":%" PRIu64 ",\"bytes_transferred\":%" PRIu64 ",\"chunks\":%" PRIu64 ",\"elapsed_us\":%" PRIu64 ",\"restored\":%s,\"error_code\":%d,\"health_flags\":%u,\"dropped_samples\":%" PRIu64 "}\n",
      request->request_id, rc == 0 && restored != 0 ? "ok" : "error", capture.generation,
      sink.offset, sink.sequence, result.elapsed_us, restored != 0 ? "true" : "false", rc,
      result.health_flags, result.dropped_samples);
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
  sdrd_rx_input_identity_t rx_input;
  char rx_input_json[384];
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
    memset(&rx_input, 0, sizeof(rx_input));
    rc = probe_selected_rx_input(radio, &rx_input);
    if (rc == 0 && strcmp(rx_input.front_panel_port, config->rx_input) != 0) {
      rc = -EPROTO;
      rx_input.verified = 0;
    }
    if (config->mode == SDRD_MODE_CONTROLLED && rc != 0) {
      status.health_flags |= SDRD_HEALTH_RX_INPUT_IDENTITY_INVALID;
    }
    if (format_rx_input_json(&rx_input, rx_input_json, sizeof(rx_input_json)) != 0) {
      return -ENOSPC;
    }
    if (strcmp(request.command, "CAPABILITIES") == 0) {
      const int control = config->mode == SDRD_MODE_CONTROLLED && radio_ops_available(radio) != 0 &&
                          sdrd_rx_input_identity_valid(&rx_input) != 0 &&
                          session->faulted == 0;
      written = snprintf(
          response,
          response_size,
          "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"mode\":\"%s\",\"iio_visible\":%s,\"radio_control\":%s,\"raw_iq_capture\":%s,\"software_summary\":%s,\"max_capture_bytes\":%" PRIu64 ",%s,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
          request.request_id,
          sdrd_mode_name(config->mode),
          status.iio_phy_visible != 0 && status.iio_rx_visible != 0 ? "true" : "false",
          control != 0 ? "true" : "false",
          control != 0 ? "true" : "false",
          control != 0 && power_ops_available(radio) != 0 ? "true" : "false",
          config->max_capture_bytes,
          rx_input_json);
    } else {
      const int healthy = status.health_flags == 0u && session->faulted == 0;
      written = snprintf(
          response,
          response_size,
          "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"healthy\":%s,\"health_flags\":%u,\"iio_phy_visible\":%s,\"iio_rx_visible\":%s,%s,\"fpga_configured\":false,\"fpga_mapped\":false,\"fpga_identity_valid\":false,\"session_faulted\":%s}\n",
          request.request_id,
          healthy != 0 ? "true" : "false",
          status.health_flags,
          status.iio_phy_visible != 0 ? "true" : "false",
          status.iio_rx_visible != 0 ? "true" : "false",
          rx_input_json,
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
  } else if (strcmp(request.command, "CAPTURE_SUMMARY") == 0) {
    return format_error(request.request_id, "retired_command", response, response_size);
  } else if (strcmp(request.command, "START_SESSION") == 0 ||
             strcmp(request.command, "APPLY_PROFILE") == 0 ||
             strcmp(request.command, "CAPTURE_IQ") == 0 ||
             strcmp(request.command, "CAPTURE_IQ_INLINE") == 0 ||
             strcmp(request.command, "CAPTURE_IQ_STREAM") == 0 ||
             strcmp(request.command, "CAPTURE_POWER") == 0 ||
             strcmp(request.command, "EXECUTION_STATUS") == 0 ||
             strcmp(request.command, "STOP_SESSION") == 0) {
    if (config->mode != SDRD_MODE_CONTROLLED) {
      return format_error(request.request_id, "read_only_shadow", response, response_size);
    }
    if (radio_ops_available(radio) == 0) {
      return format_error(request.request_id, "radio_backend_unavailable", response, response_size);
    }
    if (strcmp(request.command, "START_SESSION") == 0) {
      return handle_start_session(config, &request, session, radio, response, response_size);
    }
    if (strcmp(request.command, "APPLY_PROFILE") == 0) {
      return handle_apply_profile(config, &request, session, radio, response, response_size);
    }
    if (strcmp(request.command, "CAPTURE_IQ") == 0) {
      return handle_capture_iq(config, &request, session, radio, response, response_size);
    }
    if (strcmp(request.command, "CAPTURE_IQ_INLINE") == 0) {
      return handle_capture_iq_inline(config, &request, session, radio, response, response_size);
    }
    if (strcmp(request.command, "CAPTURE_IQ_STREAM") == 0) {
      return handle_capture_stream(config, &request, session, radio, response, response_size);
    }
    if (strcmp(request.command, "CAPTURE_POWER") == 0) {
      return handle_capture_power(&request, session, radio, response, response_size);
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
