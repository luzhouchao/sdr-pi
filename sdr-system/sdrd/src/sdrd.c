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
    if (strcmp(value, "shadow") != 0) {
      set_error(error, error_size, "only mode=shadow is supported");
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

static int parse_request(const char *line, char *command, size_t command_size, uint64_t *request_id) {
  char copy[SDRD_MAX_LINE];
  char protocol[32];
  char id_text[32];
  char extra[2];
  char *clean;
  int fields;
  if (line == NULL || strlen(line) >= sizeof(copy)) {
    return -EMSGSIZE;
  }
  (void)copy_text(copy, sizeof(copy), line);
  clean = trim(copy);
  fields = sscanf(clean, "%31s %31s %31s %1s", protocol, command, id_text, extra);
  if (fields != 3 || strcmp(protocol, "SDRD/1") != 0 || strlen(command) >= command_size) {
    return -EINVAL;
  }
  return parse_u64(id_text, request_id);
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

int sdrd_format_response(
    const sdrd_config_t *config,
    const char *request_line,
    char *response,
    size_t response_size) {
  char command[32];
  uint64_t request_id = 0u;
  sdrd_status_t status;
  char error[256];
  int rc;
  int written;
  if (response == NULL || response_size == 0u) {
    return -EINVAL;
  }
  rc = parse_request(request_line, command, sizeof(command), &request_id);
  if (rc != 0) {
    return format_error(0u, "invalid_request", response, response_size);
  }
  if (strcmp(command, "HELLO") == 0) {
    written = snprintf(
        response,
        response_size,
        "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"shadow\",\"mutating_commands\":false}\n",
        request_id);
  } else if (strcmp(command, "CAPABILITIES") == 0 || strcmp(command, "HEALTH") == 0) {
    rc = sdrd_probe_status(config, &status, error, sizeof(error));
    if (rc != 0) {
      return format_error(request_id, "probe_failed", response, response_size);
    }
    if (strcmp(command, "CAPABILITIES") == 0) {
      written = snprintf(
          response,
          response_size,
          "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"mode\":\"shadow\",\"iio_visible\":%s,\"radio_control\":false,\"raw_iq_capture\":false,\"fpga_backend\":\"%s\",\"fpga_identity_valid\":%s,\"fpga_summary_version\":%u,\"fpga_abi_version\":%u,\"fpga_capability\":%u,\"fpga_aggregate\":%s}\n",
          request_id,
          status.iio_phy_visible != 0 && status.iio_rx_visible != 0 ? "true" : "false",
          sdrd_fpga_backend_name(config->fpga_backend),
          status.fpga_identity_valid != 0 ? "true" : "false",
          status.summary_version,
          status.fpga_abi_version,
          status.fpga_capability,
          status.fpga_identity_valid != 0 ? "true" : "false");
    } else {
      const int healthy = status.health_flags == 0u;
      written = snprintf(
          response,
          response_size,
          "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"healthy\":%s,\"health_flags\":%u,\"iio_phy_visible\":%s,\"iio_rx_visible\":%s,\"fpga_configured\":%s,\"fpga_mapped\":%s,\"fpga_identity_valid\":%s}\n",
          request_id,
          healthy != 0 ? "true" : "false",
          status.health_flags,
          status.iio_phy_visible != 0 ? "true" : "false",
          status.iio_rx_visible != 0 ? "true" : "false",
          status.fpga_configured != 0 ? "true" : "false",
          status.fpga_mapped != 0 ? "true" : "false",
          status.fpga_identity_valid != 0 ? "true" : "false");
    }
  } else if (strcmp(command, "QUIT") == 0) {
    written = snprintf(
        response,
        response_size,
        "{\"schema_version\":1,\"request_id\":%" PRIu64 ",\"status\":\"ok\",\"closing\":true}\n",
        request_id);
  } else if (strcmp(command, "APPLY_PROFILE") == 0 || strcmp(command, "RETUNE") == 0 ||
             strcmp(command, "CAPTURE_IQ") == 0 || strcmp(command, "START_SESSION") == 0 ||
             strcmp(command, "STOP_SESSION") == 0) {
    return format_error(request_id, "read_only_shadow", response, response_size);
  } else {
    return format_error(request_id, "unknown_command", response, response_size);
  }
  return written < 0 || (size_t)written >= response_size ? -ENOSPC : 0;
}
