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
#define SDRD_MAX_LINE 512u
#define SDRD_MAX_INLINE_CAPTURE_BYTES (256u * 1024u)
#define SDRD_MAX_RESPONSE (384u * 1024u)
#define SDRD_MAX_FEATURE_ID 64u
#define SDRD_RX_INPUT_IDENTITY_VERSION 1u
#define SDRD_RX_FRONT_PANEL_PORT "RX1"
#define SDRD_RX_LOGICAL_CHANNEL "RX0"
#define SDRD_RX_PHY_CHANNEL "voltage0"
#define SDRD_RX_SCAN_I_CHANNEL "voltage0"
#define SDRD_RX_SCAN_Q_CHANNEL "voltage1"
#define SDRD_RX_RF_PORT_SELECT "A_BALANCED"

typedef enum sdrd_mode {
  SDRD_MODE_SHADOW = 0,
  SDRD_MODE_CONTROLLED = 1
} sdrd_mode_t;

enum sdrd_health_flag {
  SDRD_HEALTH_IIO_PHY_MISSING = 1u << 0,
  SDRD_HEALTH_IIO_RX_MISSING = 1u << 1,
  SDRD_HEALTH_RX_INPUT_IDENTITY_INVALID = 1u << 2,
  SDRD_HEALTH_CONFIG_INVALID = 1u << 4
};

enum sdrd_execution_health_flag {
  SDRD_EXEC_HEALTH_SHORT_REFILL = 1u << 0,
  SDRD_EXEC_HEALTH_OVERFLOW = 1u << 1,
  SDRD_EXEC_HEALTH_TIMEOUT = 1u << 2,
  SDRD_EXEC_HEALTH_CANCELLED = 1u << 3,
  SDRD_EXEC_HEALTH_IO_ERROR = 1u << 4,
  SDRD_EXEC_HEALTH_SHAPE_ERROR = 1u << 5,
  SDRD_EXEC_HEALTH_RADIO_STATE = 1u << 6
};

typedef struct sdrd_config {
  sdrd_mode_t mode;
  char listen_address[SDRD_MAX_ADDRESS];
  uint16_t listen_port;
  uint32_t client_timeout_ms;
  char iio_sysfs_root[SDRD_MAX_PATH];
  char development_data_root[SDRD_MAX_PATH];
  uint32_t iio_timeout_ms;
  uint32_t iio_buffer_samples;
  uint32_t retune_settle_ms;
  char rx_input[16]; /* Startup selection; one complex RX channel per session. */
  uint64_t min_center_hz;
  uint64_t max_center_hz;
  uint32_t min_sample_rate_hz;
  uint32_t max_sample_rate_hz;
  uint32_t min_rf_bandwidth_hz;
  uint32_t max_rf_bandwidth_hz;
  uint64_t max_capture_bytes;
} sdrd_config_t;

typedef struct sdrd_rx_input_identity {
  uint32_t identity_version;
  int verified;
  char front_panel_port[16];
  char logical_channel[16];
  char phy_channel[16];
  char scan_i_channel[16];
  char scan_q_channel[16];
  char rf_port_select[32];
} sdrd_rx_input_identity_t;

int sdrd_rx_input_for_port(const char *port, int verified, sdrd_rx_input_identity_t *identity);

typedef struct sdrd_radio_state {
  uint64_t center_hz;
  uint32_t sample_rate_hz;
  uint32_t rf_bandwidth_hz;
  char gain_mode[32];
  char hardware_gain[32];
  uint32_t enabled_channels;
  uint32_t scan_channel_mask;
  sdrd_rx_input_identity_t rx_input;
} sdrd_radio_state_t;

typedef struct sdrd_capture_request {
  uint64_t generation;
  uint64_t sample_count;
  uint64_t max_bytes;
  uint32_t timeout_ms;
  char feature_id[SDRD_MAX_FEATURE_ID];
} sdrd_capture_request_t;

typedef struct sdrd_capture_result {
  uint64_t samples_captured;
  uint64_t bytes_written;
  uint64_t sequence;
  uint64_t dropped_samples;
  int overflow;
  uint32_t timeout_ms;
  uint64_t elapsed_us;
  int timed_out;
  uint32_t health_flags;
  char relative_path[SDRD_MAX_PATH];
} sdrd_capture_result_t;

typedef struct sdrd_summary_request {
  uint64_t generation;
  uint32_t frame_samples;
  uint32_t aggregate_frames;
  uint32_t timeout_ms;
} sdrd_summary_request_t;

typedef struct sdrd_summary_result {
  uint64_t sequence;
  uint64_t aggregate_samples;
  uint32_t rx0_power_lo;
  uint32_t rx0_power_mid;
  uint32_t rx0_power_hi;
  uint64_t rx0_clip_count;
  uint32_t status_flags;
  uint64_t elapsed_us;
  uint64_t dropped_samples;
  int overflow;
  uint32_t timeout_ms;
  int timed_out;
  uint32_t health_flags;
} sdrd_summary_result_t;

typedef struct sdrd_radio_ops {
  void *context;
  int (*probe_rx_input)(void *context, sdrd_rx_input_identity_t *identity);
  int (*begin_session)(void *context);
  int (*snapshot)(void *context, sdrd_radio_state_t *state);
  int (*apply_profile)(void *context, const sdrd_radio_state_t *state);
  int (*capture_iq)(
      void *context,
      const sdrd_capture_request_t *request,
      sdrd_capture_result_t *result);
  int (*capture_power)(
      void *context,
      const sdrd_summary_request_t *request,
      sdrd_summary_result_t *result);
  int (*cancel)(void *context);
  int (*stop)(void *context);
  int (*restore)(void *context, const sdrd_radio_state_t *state);
} sdrd_radio_ops_t;

typedef struct sdrd_session {
  uint64_t generation;
  uint64_t last_request_id;
  int active;
  int profile_applied;
  int restore_required;
  int faulted;
  sdrd_radio_state_t saved_state;
  sdrd_radio_state_t current_state;
} sdrd_session_t;

typedef struct sdrd_status {
  uint32_t health_flags;
  int iio_phy_visible;
  int iio_rx_visible;
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
const char *sdrd_mode_name(sdrd_mode_t mode);
int sdrd_rx_input_identity_valid(const sdrd_rx_input_identity_t *identity);

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

void sdrd_session_init(sdrd_session_t *session);
int sdrd_handle_request(
    const sdrd_config_t *config,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *radio,
    const char *request_line,
    char *response,
    size_t response_size);
int sdrd_session_close(sdrd_session_t *session, const sdrd_radio_ops_t *radio);

#ifdef __cplusplus
}
#endif

#endif
