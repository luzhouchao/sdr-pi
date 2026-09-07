/* Real Adapter apply/snapshot/restore against two distinct fake PHY channels. */
#include "../src/sdrd_iio.c"
#include <assert.h>

struct iio_channel {
  int enabled;
  long long frequency, rate, bandwidth;
  char mode[32], gain[32], port[32];
  int fail_gain_write;
};

static bool enabled(const struct iio_channel *c) { return c->enabled != 0; }
static void enable(struct iio_channel *c) { c->enabled = 1; }
static void disable(struct iio_channel *c) { c->enabled = 0; }
static int read_number(const struct iio_channel *c, const char *attr, long long *out) {
  if (strcmp(attr, "frequency") == 0) *out = c->frequency;
  else if (strcmp(attr, "sampling_frequency") == 0) *out = c->rate;
  else if (strcmp(attr, "rf_bandwidth") == 0) *out = c->bandwidth;
  else return -EINVAL;
  return 0;
}
static int write_number(const struct iio_channel *channel, const char *attr, long long value) {
  struct iio_channel *c = (struct iio_channel *)channel;
  if (strcmp(attr, "frequency") == 0) c->frequency = value;
  else if (strcmp(attr, "sampling_frequency") == 0) c->rate = value;
  else if (strcmp(attr, "rf_bandwidth") == 0) c->bandwidth = value;
  else return -EINVAL;
  return 0;
}
static ssize_t read_text(const struct iio_channel *c, const char *attr, char *out, size_t size) {
  const char *value;
  if (strcmp(attr, "rf_port_select") == 0) value = c->port;
  else if (strcmp(attr, "gain_control_mode") == 0) value = c->mode;
  else if (strcmp(attr, "hardwaregain") == 0) value = c->gain;
  else return -EINVAL;
  return snprintf(out, size, "%s", value);
}
static ssize_t write_text(const struct iio_channel *channel, const char *attr, const char *value) {
  struct iio_channel *c = (struct iio_channel *)channel;
  if (strcmp(attr, "gain_control_mode") == 0) return snprintf(c->mode, sizeof(c->mode), "%s", value);
  if (strcmp(attr, "hardwaregain") == 0) {
    if (c->fail_gain_write) { c->fail_gain_write = 0; return -EIO; }
    return snprintf(c->gain, sizeof(c->gain), "%s", value);
  }
  return -EINVAL; /* No RF switch or TX attribute write is implemented. */
}

int main(void) {
  for (unsigned int selected = 0; selected < 2; ++selected) {
    struct iio_channel phy[2] = {
      {.rate=30720000, .bandwidth=30000000, .mode="manual", .gain="31.000000", .port="A_BALANCED"},
      {.rate=30720000, .bandwidth=30000000, .mode="manual", .gain="52.000000", .port="A_BALANCED"},
    };
    struct iio_channel scan[4] = {{0}}, lo = {.frequency=5985999996LL};
    sdrd_iio_adapter_t a = {0};
    a.selected_phy_rx = &phy[selected]; a.rx_lo = &lo;
    a.selected_scan_mask = selected ? 12u : 3u;
    assert(sdrd_rx_input_for_port(selected ? "RX2" : "RX1", 0, &a.selected_input) == 0);
    for (size_t i = 0; i < 4; ++i) a.scan[i] = &scan[i];
    a.api.channel_is_enabled = enabled; a.api.channel_enable = enable; a.api.channel_disable = disable;
    a.api.channel_attr_read_longlong = read_number; a.api.channel_attr_write_longlong = write_number;
    a.api.channel_attr_read = read_text; a.api.channel_attr_write = write_text;
    assert(pthread_mutex_init(&a.cancel_mutex, NULL) == 0);
    sdrd_radio_state_t saved, requested, after;
    const struct iio_channel untouched = phy[1 - selected];
    assert(adapter_snapshot(&a, &saved) == 0);
    assert(sdrd_rx_input_identity_valid(&saved.rx_input));
    assert(saved.scan_channel_mask == 0);
    assert(adapter_begin_session(&a) == 0);
    requested = saved;
    requested.center_hz = 2455000000; requested.sample_rate_hz = 2100000;
    requested.rf_bandwidth_hz = 1500000; requested.enabled_channels = 1;
    strcpy(requested.hardware_gain, "40");
    assert(adapter_apply_profile(&a, &requested) == 0);
    assert(get_scan_mask(&a) == (selected ? 12u : 3u));
    assert(strcmp(phy[selected].gain, "40") == 0);
    assert(memcmp(&phy[1-selected], &untouched, sizeof(untouched)) == 0);
    sdrd_radio_ops_t ops; sdrd_iio_adapter_ops(&a, &ops);
    assert((ops.capture_power == NULL) == (selected == 1));
    assert(adapter_restore(&a, &saved) == 0);
    assert(adapter_snapshot(&a, &after) == 0);
    assert(memcmp(&saved, &after, sizeof(saved)) == 0);
    phy[selected].fail_gain_write = 1;
    assert(adapter_apply_profile(&a, &requested) == -EIO);
    assert(adapter_restore(&a, &saved) == 0);
    assert(adapter_snapshot(&a, &after) == 0 && memcmp(&saved, &after, sizeof(saved)) == 0);
    assert(memcmp(&phy[1-selected], &untouched, sizeof(untouched)) == 0);
    strcpy(phy[selected].port, "B_BALANCED");
    assert(adapter_probe_rx_input(&a, &after.rx_input) == -EPROTO);
    assert(!sdrd_rx_input_identity_valid(&after.rx_input));
    assert(pthread_mutex_destroy(&a.cancel_mutex) == 0);
  }
  puts("iio_ports=RX1,RX2 apply_snapshot_restore_failure_identity=pass");
  return 0;
}
