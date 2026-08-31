#define _POSIX_C_SOURCE 200809L

#include "sdrd.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static void must_mkdir(const char *path) {
  assert(mkdir(path, 0700) == 0);
}

static void write_text(const char *path, const char *text) {
  FILE *stream = fopen(path, "w");
  assert(stream != NULL);
  assert(fputs(text, stream) >= 0);
  assert(fclose(stream) == 0);
}

static void write_u32(int fd, off_t offset, uint32_t value) {
  assert(pwrite(fd, &value, sizeof(value), offset) == (ssize_t)sizeof(value));
}

static void create_iio_tree(const char *root) {
  char path[512];
  (void)snprintf(path, sizeof(path), "%s/iio:device0", root);
  must_mkdir(path);
  (void)snprintf(path, sizeof(path), "%s/iio:device0/name", root);
  write_text(path, "ad9361-phy\n");
  (void)snprintf(path, sizeof(path), "%s/iio:device1", root);
  must_mkdir(path);
  (void)snprintf(path, sizeof(path), "%s/iio:device1/name", root);
  write_text(path, "cf-ad9361-lpc\n");
}

typedef struct fake_radio {
  sdrd_radio_state_t state;
  sdrd_radio_state_t restored_state;
  unsigned int snapshot_calls;
  unsigned int begin_session_calls;
  unsigned int apply_calls;
  unsigned int capture_calls;
  unsigned int cancel_calls;
  unsigned int stop_calls;
  unsigned int restore_calls;
  int apply_result;
  int capture_result;
  int restore_result;
} fake_radio_t;

static int fake_snapshot(void *context, sdrd_radio_state_t *state) {
  fake_radio_t *fake = context;
  ++fake->snapshot_calls;
  *state = fake->state;
  return 0;
}

static int fake_begin_session(void *context) {
  fake_radio_t *fake = context;
  ++fake->begin_session_calls;
  return 0;
}

static int fake_apply(void *context, const sdrd_radio_state_t *state) {
  fake_radio_t *fake = context;
  ++fake->apply_calls;
  if (fake->apply_result == 0) {
    fake->state = *state;
  }
  return fake->apply_result;
}

static int fake_capture(
    void *context,
    const sdrd_capture_request_t *request,
    sdrd_capture_result_t *result) {
  fake_radio_t *fake = context;
  ++fake->capture_calls;
  if (fake->capture_result != 0) {
    return fake->capture_result;
  }
  result->samples_captured = request->sample_count;
  result->bytes_written = request->sample_count * 4u;
  result->sequence = 17u;
  assert(snprintf(
             result->relative_path,
             sizeof(result->relative_path),
             "%s/capture-17.iq",
             request->feature_id) > 0);
  return 0;
}

static int fake_stop(void *context) {
  fake_radio_t *fake = context;
  ++fake->stop_calls;
  return 0;
}

static int fake_cancel(void *context) {
  fake_radio_t *fake = context;
  ++fake->cancel_calls;
  return 0;
}

static int fake_restore(void *context, const sdrd_radio_state_t *state) {
  fake_radio_t *fake = context;
  ++fake->restore_calls;
  fake->restored_state = *state;
  if (fake->restore_result == 0) {
    fake->state = *state;
  }
  return fake->restore_result;
}

static sdrd_radio_ops_t fake_ops(fake_radio_t *fake) {
  sdrd_radio_ops_t ops;
  memset(&ops, 0, sizeof(ops));
  ops.context = fake;
  ops.begin_session = fake_begin_session;
  ops.snapshot = fake_snapshot;
  ops.apply_profile = fake_apply;
  ops.capture_iq = fake_capture;
  ops.cancel = fake_cancel;
  ops.stop = fake_stop;
  ops.restore = fake_restore;
  return ops;
}

static void test_shadow_config_and_protocol(const char *root) {
  char config_path[512];
  char iio_root[512];
  char config_text[2048];
  char response[SDRD_MAX_RESPONSE];
  char error[256];
  sdrd_config_t config;
  (void)snprintf(iio_root, sizeof(iio_root), "%s/iio", root);
  must_mkdir(iio_root);
  create_iio_tree(iio_root);
  (void)snprintf(config_path, sizeof(config_path), "%s/sdrd.conf", root);
  (void)snprintf(
      config_text,
      sizeof(config_text),
      "mode=shadow\nlisten_address=127.0.0.1\nlisten_port=43110\nclient_timeout_ms=5000\niio_sysfs_root=%s\nfpga_backend=disabled\nfpga_device=/dev/mem\nfpga_base=0x43c00000\nfpga_span=0x10000\nrequire_iomem_region=true\nallow_devmem=false\n",
      iio_root);
  write_text(config_path, config_text);
  assert(sdrd_config_load(config_path, &config, error, sizeof(error)) == 0);
  assert(config.fpga_backend == SDRD_FPGA_DISABLED);
  assert(sdrd_format_response(&config, "SDRD/1 HELLO 41", response, sizeof(response)) == 0);
  assert(strstr(response, "\"request_id\":41") != NULL);
  assert(strstr(response, "\"mutating_commands\":false") != NULL);
  assert(sdrd_format_response(&config, "SDRD/1 HEALTH 42", response, sizeof(response)) == 0);
  assert(strstr(response, "\"healthy\":true") != NULL);
  assert(strstr(response, "\"iio_phy_visible\":true") != NULL);
  assert(sdrd_format_response(&config, "SDRD/1 APPLY_PROFILE 43", response, sizeof(response)) == 0);
  assert(strstr(response, "\"error\":\"read_only_shadow\"") != NULL);
}

static void test_fake_uio_identity(const char *root) {
  char register_path[512];
  char iio_root[512];
  char response[SDRD_MAX_RESPONSE];
  char error[256];
  sdrd_config_t config;
  int fd;
  (void)snprintf(iio_root, sizeof(iio_root), "%s/iio-fpga", root);
  must_mkdir(iio_root);
  create_iio_tree(iio_root);
  (void)snprintf(register_path, sizeof(register_path), "%s/registers.bin", root);
  fd = open(register_path, O_CREAT | O_RDWR | O_TRUNC, 0600);
  assert(fd >= 0);
  assert(ftruncate(fd, 0x10000) == 0);
  write_u32(fd, 0x040, 0x53554D38u);
  write_u32(fd, 0x0EC, 0x00010002u);
  write_u32(fd, 0x0F0, 0x000003FFu);
  write_u32(fd, 0x0FC, 0x56380001u);
  write_u32(fd, 0x180, 0x41474738u);
  write_u32(fd, 0x1F4, 0x0000001Fu);
  write_u32(fd, 0x1F8, 0x41380001u);
  assert(close(fd) == 0);
  sdrd_config_defaults(&config);
  assert(snprintf(config.iio_sysfs_root, sizeof(config.iio_sysfs_root), "%s", iio_root) > 0);
  assert(snprintf(config.fpga_device, sizeof(config.fpga_device), "%s", register_path) > 0);
  config.fpga_backend = SDRD_FPGA_UIO;
  assert(sdrd_config_validate(&config, error, sizeof(error)) == 0);
  assert(sdrd_format_response(&config, "SDRD/1 CAPABILITIES 9", response, sizeof(response)) == 0);
  assert(strstr(response, "\"fpga_identity_valid\":true") != NULL);
  assert(strstr(response, "\"fpga_aggregate\":true") != NULL);
}

static void test_devmem_requires_explicit_gate(void) {
  sdrd_config_t config;
  char error[256];
  sdrd_config_defaults(&config);
  config.fpga_backend = SDRD_FPGA_DEVMEM;
  assert(sdrd_config_validate(&config, error, sizeof(error)) == -EACCES);
  assert(strstr(error, "allow_devmem=true") != NULL);
}

static void test_iio_control_limits(void) {
  sdrd_config_t config;
  char error[256];
  sdrd_config_defaults(&config);
  assert(config.iio_timeout_ms == 2000u);
  assert(config.iio_buffer_samples == 4096u);
  assert(config.retune_settle_ms == 5u);
  config.iio_buffer_samples = 128u;
  assert(sdrd_config_validate(&config, error, sizeof(error)) == -ERANGE);
  config.iio_buffer_samples = 4096u;
  config.retune_settle_ms = 1001u;
  assert(sdrd_config_validate(&config, error, sizeof(error)) == -ERANGE);
  config.retune_settle_ms = 5u;
  assert(snprintf(
             config.development_data_root,
             sizeof(config.development_data_root),
             "/tmp/sdr-agent-development") > 0);
  assert(sdrd_config_validate(&config, error, sizeof(error)) == -EINVAL);
}

static void test_controlled_allowlist_and_restore(void) {
  sdrd_config_t config;
  sdrd_session_t session;
  fake_radio_t fake;
  sdrd_radio_ops_t ops;
  char response[SDRD_MAX_RESPONSE];
  memset(&fake, 0, sizeof(fake));
  fake.state.center_hz = 915000000u;
  fake.state.sample_rate_hz = 4000000u;
  fake.state.rf_bandwidth_hz = 3000000u;
  fake.state.enabled_channels = 1u;
  assert(snprintf(fake.state.gain_mode, sizeof(fake.state.gain_mode), "slow_attack") > 0);
  ops = fake_ops(&fake);
  sdrd_config_defaults(&config);
  config.mode = SDRD_MODE_CONTROLLED;
  sdrd_session_init(&session);

  assert(sdrd_handle_request(
             &config, &session, &ops, "SDRD/1 HELLO 1", response, sizeof(response)) == 0);
  assert(strstr(response, "\"mode\":\"controlled\"") != NULL);
  assert(strstr(response, "\"mutating_commands\":true") != NULL);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 START_SESSION 2 1001",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "\"restore_armed\":true") != NULL);
  assert(fake.snapshot_calls == 1u);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 START_SESSION 2 1001",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "stale_or_duplicate_request") != NULL);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 APPLY_PROFILE 3 1001 2400000000 10000000 8000000 slow_attack 3",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "profile_out_of_bounds") != NULL);
  assert(fake.apply_calls == 0u);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 APPLY_PROFILE 4 1001 2400000000 10000000 8000000 slow_attack 1",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "\"center_hz\":2400000000") != NULL);
  assert(fake.apply_calls == 1u);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 CAPTURE_IQ 5 1001 1024 4096 sdrd-schema-v1",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "\"bytes_written\":4096") != NULL);
  assert(strstr(response, "\"relative_path\":\"sdrd-schema-v1/capture-17.iq\"") != NULL);
  assert(fake.capture_calls == 1u);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 EXECUTION_STATUS 6 1001",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "\"active\":true") != NULL);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 STOP_SESSION 7 1001",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "\"restored\":true") != NULL);
  assert(fake.stop_calls == 1u);
  assert(fake.restore_calls == 1u);
  assert(fake.state.center_hz == 915000000u);
  assert(session.active == 0);
  assert(session.restore_required == 0);
}

static void test_disconnect_and_failure_restore(void) {
  sdrd_config_t config;
  sdrd_session_t session;
  fake_radio_t fake;
  sdrd_radio_ops_t ops;
  char response[SDRD_MAX_RESPONSE];
  memset(&fake, 0, sizeof(fake));
  fake.state.center_hz = 433920000u;
  fake.state.sample_rate_hz = 3000000u;
  fake.state.rf_bandwidth_hz = 2000000u;
  fake.state.enabled_channels = 1u;
  assert(snprintf(fake.state.gain_mode, sizeof(fake.state.gain_mode), "fast_attack") > 0);
  ops = fake_ops(&fake);
  sdrd_config_defaults(&config);
  config.mode = SDRD_MODE_CONTROLLED;
  sdrd_session_init(&session);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 START_SESSION 10 2002",
             response,
             sizeof(response)) == 0);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 APPLY_PROFILE 11 2002 2450000000 5000000 4000000 fast_attack 1",
             response,
             sizeof(response)) == 0);
  assert(sdrd_session_close(&session, &ops) == 0);
  assert(fake.stop_calls == 1u && fake.restore_calls == 1u);
  assert(fake.state.center_hz == 433920000u);

  fake.capture_result = -ETIMEDOUT;
  sdrd_session_init(&session);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 START_SESSION 15 2500",
             response,
             sizeof(response)) == 0);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 APPLY_PROFILE 16 2500 2450000000 5000000 4000000 fast_attack 1",
             response,
             sizeof(response)) == 0);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 CAPTURE_IQ 17 2500 1024 4096 capture-timeout",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "capture_failed_restored") != NULL);
  assert(session.active == 0 && session.restore_required == 0);
  fake.capture_result = 0;

  fake.apply_result = -EIO;
  fake.restore_result = -EIO;
  sdrd_session_init(&session);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 START_SESSION 20 3003",
             response,
             sizeof(response)) == 0);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 APPLY_PROFILE 21 3003 1000000000 4000000 3000000 manual 1",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "apply_failed_restore_fault") != NULL);
  assert(session.faulted != 0);
  assert(session.restore_required != 0);
  assert(sdrd_handle_request(
             &config,
             &session,
             &ops,
             "SDRD/1 START_SESSION 22 4004",
             response,
             sizeof(response)) == 0);
  assert(strstr(response, "restore_fault") != NULL);
}

static void remove_test_tree(const char *root) {
  char path[512];
  (void)snprintf(path, sizeof(path), "%s/iio/iio:device0/name", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio/iio:device1/name", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio/iio:device0", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio/iio:device1", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga/iio:device0/name", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga/iio:device1/name", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga/iio:device0", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga/iio:device1", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/sdrd.conf", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/registers.bin", root);
  assert(unlink(path) == 0);
  assert(rmdir(root) == 0);
}

int main(void) {
  char root[] = "/tmp/sdrd-test-XXXXXX";
  assert(mkdtemp(root) != NULL);
  test_shadow_config_and_protocol(root);
  test_fake_uio_identity(root);
  test_devmem_requires_explicit_gate();
  test_iio_control_limits();
  test_controlled_allowlist_and_restore();
  test_disconnect_and_failure_restore();
  remove_test_tree(root);
  puts("sdrd_tests=pass");
  return 0;
}
