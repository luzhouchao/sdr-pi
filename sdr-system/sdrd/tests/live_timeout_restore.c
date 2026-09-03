#include "sdrd.h"
#include "sdrd_iio.h"

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static volatile sig_atomic_t stop_requested;

static void request_stop(int signal_number) {
  (void)signal_number;
  stop_requested = 1;
}

static int gain_matches(const char *expected, const char *observed) {
  char *expected_end = NULL;
  char *observed_end = NULL;
  double expected_value;
  double observed_value;
  double delta;
  errno = 0;
  expected_value = strtod(expected, &expected_end);
  if (errno != 0 || expected_end == expected) {
    return 0;
  }
  errno = 0;
  observed_value = strtod(observed, &observed_end);
  if (errno != 0 || observed_end == observed) {
    return 0;
  }
  delta = expected_value > observed_value ? expected_value - observed_value
                                          : observed_value - expected_value;
  return delta <= 0.05;
}

static int state_matches(
    const sdrd_radio_state_t *expected,
    const sdrd_radio_state_t *observed,
    int require_manual_gain) {
  const uint64_t center_delta = expected->center_hz > observed->center_hz
                                    ? expected->center_hz - observed->center_hz
                                    : observed->center_hz - expected->center_hz;
  if (center_delta > 10u ||
      expected->sample_rate_hz != observed->sample_rate_hz ||
      expected->rf_bandwidth_hz != observed->rf_bandwidth_hz ||
      strcmp(expected->gain_mode, observed->gain_mode) != 0 ||
      expected->scan_channel_mask != observed->scan_channel_mask ||
      (require_manual_gain != 0 &&
       gain_matches(expected->hardware_gain, observed->hardware_gain) == 0)) {
    fprintf(
        stderr,
        "state_mismatch expected_center=%llu observed_center=%llu"
        " expected_rate=%u observed_rate=%u expected_bandwidth=%u observed_bandwidth=%u"
        " expected_mode=%s observed_mode=%s expected_gain=%s observed_gain=%s"
        " expected_scan_mask=%u observed_scan_mask=%u\n",
        (unsigned long long)expected->center_hz,
        (unsigned long long)observed->center_hz,
        expected->sample_rate_hz,
        observed->sample_rate_hz,
        expected->rf_bandwidth_hz,
        observed->rf_bandwidth_hz,
        expected->gain_mode,
        observed->gain_mode,
        expected->hardware_gain,
        observed->hardware_gain,
        expected->scan_channel_mask,
        observed->scan_channel_mask);
    return -1;
  }
  return 0;
}

static int request_contains(
    const sdrd_config_t *config,
    sdrd_session_t *session,
    const sdrd_radio_ops_t *ops,
    const char *request,
    const char *required_text,
    char *response,
    size_t response_size) {
  const int rc = sdrd_handle_request(
      config, session, ops, request, response, response_size);
  if (rc != 0 || strstr(response, required_text) == NULL) {
    fprintf(
        stderr,
        "request_check_failed rc=%d required=%s response=%s\n",
        rc,
        required_text,
        response);
    return -1;
  }
  fputs(response, stdout);
  return 0;
}

int main(int argc, char **argv) {
  sdrd_config_t config;
  sdrd_iio_adapter_t *adapter = NULL;
  sdrd_radio_ops_t ops;
  sdrd_radio_state_t original;
  sdrd_radio_state_t manual_baseline;
  sdrd_radio_state_t observed;
  sdrd_session_t session;
  char error[256] = {0};
  char response[SDRD_MAX_RESPONSE] = {0};
  int original_saved = 0;
  int result = 1;
  int cleanup_rc;

  if (argc != 2) {
    fprintf(stderr, "usage: %s <sdrd.conf>\n", argv[0]);
    return 2;
  }
  (void)signal(SIGINT, request_stop);
  (void)signal(SIGTERM, request_stop);
  memset(&ops, 0, sizeof(ops));
  memset(&original, 0, sizeof(original));
  memset(&manual_baseline, 0, sizeof(manual_baseline));
  memset(&observed, 0, sizeof(observed));

  sdrd_config_defaults(&config);
  if (sdrd_config_load(argv[1], &config, error, sizeof(error)) != 0 ||
      config.mode != SDRD_MODE_CONTROLLED) {
    fprintf(stderr, "config_load_failed error=%s\n", error);
    goto cleanup;
  }
  if (sdrd_iio_adapter_create(&config, &adapter, error, sizeof(error)) != 0) {
    fprintf(stderr, "adapter_create_failed error=%s\n", error);
    goto cleanup;
  }
  sdrd_iio_adapter_ops(adapter, &ops);
  if (ops.snapshot(ops.context, &original) != 0) {
    fprintf(stderr, "original_snapshot_failed\n");
    goto cleanup;
  }
  original_saved = 1;
  printf(
      "original center_hz=%llu sample_rate_hz=%u rf_bandwidth_hz=%u"
      " gain_mode=%s hardware_gain=%s scan_channel_mask=%u\n",
      (unsigned long long)original.center_hz,
      original.sample_rate_hz,
      original.rf_bandwidth_hz,
      original.gain_mode,
      original.hardware_gain,
      original.scan_channel_mask);

  manual_baseline = original;
  (void)snprintf(manual_baseline.gain_mode, sizeof(manual_baseline.gain_mode), "manual");
  (void)snprintf(manual_baseline.hardware_gain, sizeof(manual_baseline.hardware_gain), "20");
  manual_baseline.enabled_channels = 1u;
  manual_baseline.scan_channel_mask = original.scan_channel_mask;
  if (ops.begin_session(ops.context) != 0 ||
      ops.apply_profile(ops.context, &manual_baseline) != 0 ||
      ops.stop(ops.context) != 0 ||
      ops.restore(ops.context, &manual_baseline) != 0 ||
      ops.snapshot(ops.context, &observed) != 0 ||
      state_matches(&manual_baseline, &observed, 1) != 0) {
    fprintf(stderr, "manual_baseline_setup_failed\n");
    goto cleanup;
  }
  printf(
      "manual_baseline center_hz=%llu sample_rate_hz=%u rf_bandwidth_hz=%u"
      " gain_mode=%s hardware_gain=%s scan_channel_mask=%u\n",
      (unsigned long long)observed.center_hz,
      observed.sample_rate_hz,
      observed.rf_bandwidth_hz,
      observed.gain_mode,
      observed.hardware_gain,
      observed.scan_channel_mask);

  sdrd_session_init(&session);
  if (request_contains(
          &config,
          &session,
          &ops,
          "SDRD/1 START_SESSION 1 2026090306",
          "\"restore_armed\":true",
          response,
          sizeof(response)) != 0 ||
      request_contains(
          &config,
          &session,
          &ops,
          "SDRD/1 APPLY_PROFILE 2 2026090306 915000000 5000000 4000000 manual 30 1",
          "\"hardware_gain_db\":30",
          response,
          sizeof(response)) != 0 ||
      request_contains(
          &config,
          &session,
          &ops,
          "SDRD/1 CAPTURE_IQ 3 2026090306 65535 262140 sdrd-manual-timeout-20260903 1",
          "\"timed_out\":true",
          response,
          sizeof(response)) != 0) {
    goto cleanup;
  }
  if (stop_requested != 0) {
    fprintf(stderr, "stop_requested=true\n");
    goto cleanup;
  }
  if (strstr(response, "\"error\":\"capture_failed_restored\"") == NULL ||
      strstr(response, "\"session_generation\":2026090306") == NULL ||
      strstr(response, "\"overflow\":false") == NULL ||
      strstr(response, "\"health\":{\"healthy\":false,\"flags\":4") == NULL ||
      session.active != 0 || session.restore_required != 0 || session.faulted != 0) {
    fprintf(stderr, "timeout_response_contract_failed response=%s\n", response);
    goto cleanup;
  }
  if (ops.snapshot(ops.context, &observed) != 0 ||
      state_matches(&manual_baseline, &observed, 1) != 0) {
    fprintf(stderr, "manual_timeout_restore_failed\n");
    goto cleanup;
  }
  printf(
      "manual_timeout_restore=pass center_hz=%llu sample_rate_hz=%u"
      " rf_bandwidth_hz=%u gain_mode=%s hardware_gain=%s scan_channel_mask=%u\n",
      (unsigned long long)observed.center_hz,
      observed.sample_rate_hz,
      observed.rf_bandwidth_hz,
      observed.gain_mode,
      observed.hardware_gain,
      observed.scan_channel_mask);
  result = 0;

cleanup:
  if (adapter != NULL && original_saved != 0) {
    cleanup_rc = ops.stop(ops.context);
    if (cleanup_rc == 0) {
      cleanup_rc = ops.restore(ops.context, &original);
    }
    if (cleanup_rc == 0) {
      cleanup_rc = ops.snapshot(ops.context, &observed);
    }
    if (cleanup_rc == 0) {
      cleanup_rc = state_matches(
          &original, &observed, strcmp(original.gain_mode, "manual") == 0);
    }
    if (cleanup_rc != 0) {
      fprintf(stderr, "original_restore_failed rc=%d\n", cleanup_rc);
      result = 1;
    } else {
      printf(
          "original_restore=pass center_hz=%llu sample_rate_hz=%u"
          " rf_bandwidth_hz=%u gain_mode=%s hardware_gain=%s scan_channel_mask=%u\n",
          (unsigned long long)observed.center_hz,
          observed.sample_rate_hz,
          observed.rf_bandwidth_hz,
          observed.gain_mode,
          observed.hardware_gain,
          observed.scan_channel_mask);
    }
  }
  sdrd_iio_adapter_destroy(adapter);
  return result;
}
