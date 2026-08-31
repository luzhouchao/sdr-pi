#ifndef SDRD_H
#define SDRD_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SDRD_SCHEMA_VERSION 1u
#define SDRD_PROTOCOL_VERSION 1u
#define SDRD_DEFAULT_PORT 43110u
#define SDRD_MAX_PATH 256u
#define SDRD_MAX_ADDRESS 64u
#define SDRD_MAX_LINE 256u
#define SDRD_MAX_RESPONSE 2048u

typedef enum sdrd_fpga_backend {
  SDRD_FPGA_DISABLED = 0,
  SDRD_FPGA_UIO = 1,
  SDRD_FPGA_DEVMEM = 2
} sdrd_fpga_backend_t;

enum sdrd_health_flag {
  SDRD_HEALTH_IIO_PHY_MISSING = 1u << 0,
  SDRD_HEALTH_IIO_RX_MISSING = 1u << 1,
  SDRD_HEALTH_FPGA_UNAVAILABLE = 1u << 2,
  SDRD_HEALTH_FPGA_IDENTITY_INVALID = 1u << 3,
  SDRD_HEALTH_CONFIG_INVALID = 1u << 4
};

typedef struct sdrd_config {
  char listen_address[SDRD_MAX_ADDRESS];
  uint16_t listen_port;
  uint32_t client_timeout_ms;
  char iio_sysfs_root[SDRD_MAX_PATH];
  sdrd_fpga_backend_t fpga_backend;
  char fpga_device[SDRD_MAX_PATH];
  uint64_t fpga_base;
  uint32_t fpga_span;
  int require_iomem_region;
  int allow_devmem;
} sdrd_config_t;

typedef struct sdrd_status {
  uint32_t health_flags;
  int iio_phy_visible;
  int iio_rx_visible;
  int fpga_configured;
  int fpga_mapped;
  int fpga_identity_valid;
  uint32_t summary_version;
  uint32_t fpga_abi_version;
  uint32_t fpga_capability;
  uint32_t fpga_build_id;
  uint32_t aggregate_version;
  uint32_t aggregate_capability;
  uint32_t aggregate_build_id;
} sdrd_status_t;

void sdrd_config_defaults(sdrd_config_t *config);
int sdrd_config_load(
    const char *path,
    sdrd_config_t *config,
    char *error,
    size_t error_size);
int sdrd_config_validate(
    const sdrd_config_t *config,
    char *error,
    size_t error_size);
const char *sdrd_fpga_backend_name(sdrd_fpga_backend_t backend);

int sdrd_probe_status(
    const sdrd_config_t *config,
    sdrd_status_t *status,
    char *error,
    size_t error_size);

int sdrd_format_response(
    const sdrd_config_t *config,
    const char *request_line,
    char *response,
    size_t response_size);

#ifdef __cplusplus
}
#endif

#endif
