/* Exercise the real Adapter loops via their existing libiio function table.
 * Including the implementation keeps injection private to this test binary. */
#include "../src/sdrd_iio.c"
#include <assert.h>

struct iio_channel { int enabled; };
struct iio_buffer {
  unsigned char data[2048];
  ssize_t returned;
  size_t span;
  unsigned int calls;
  unsigned int bad_call;
  int pointer_fault;
};

static ssize_t fake_refill(struct iio_buffer *buffer) {
  ++buffer->calls;
  memset(buffer->data, (int)buffer->calls, sizeof(buffer->data));
  return buffer->calls == buffer->bad_call ? buffer->returned : 1024;
}

static void *fake_start(const struct iio_buffer *buffer) {
  if (buffer->calls == buffer->bad_call && buffer->pointer_fault == 1) return NULL;
  return (void *)(buffer->data + 16);
}

static void *fake_end(const struct iio_buffer *buffer) {
  if (buffer->calls == buffer->bad_call) {
    if (buffer->pointer_fault == 2) return NULL;
    if (buffer->pointer_fault == 3) return (void *)buffer->data;
    return (void *)(buffer->data + 16 + buffer->span);
  }
  return (void *)(buffer->data + 16 + 1024);
}

static ssize_t fake_sample_size(const struct iio_device *device) {
  (void)device;
  return 4;
}

static bool fake_enabled(const struct iio_channel *channel) { return channel->enabled != 0; }

static ssize_t fake_attr(const struct iio_channel *channel, const char *attribute,
                         char *output, size_t size) {
  (void)channel;
  assert(strcmp(attribute, "rf_port_select") == 0);
  return snprintf(output, size, "A_BALANCED");
}

static void initialize(sdrd_iio_adapter_t *adapter, struct iio_buffer *buffer,
                       struct iio_channel *channels, const char *root) {
  memset(adapter, 0, sizeof(*adapter));
  adapter->buffer = buffer;
  adapter->buffer_samples = 256;
  adapter->iio_timeout_ms = 1000;
  adapter->phy_rx0 = &channels[0];
  for (unsigned int i = 0; i < 4; ++i) {
    channels[i].enabled = i < 2;
    adapter->scan[i] = &channels[i];
  }
  assert(copy_text(adapter->data_root, sizeof(adapter->data_root), root) == 0);
  assert(pthread_mutex_init(&adapter->cancel_mutex, NULL) == 0);
  adapter->api.buffer_refill = fake_refill;
  adapter->api.buffer_start = fake_start;
  adapter->api.buffer_end = fake_end;
  adapter->api.device_get_sample_size = fake_sample_size;
  adapter->api.channel_attr_read = fake_attr;
  adapter->api.channel_is_enabled = fake_enabled;
}

static void exercise(const char *root, ssize_t returned, size_t span, int pointer_fault,
                     unsigned int bad_call, int expected_rc, uint32_t expected_flags,
                     uint64_t expected_missing) {
  sdrd_iio_adapter_t adapter;
  struct iio_buffer buffer = {.returned=returned, .span=span, .bad_call=bad_call,
                              .pointer_fault=pointer_fault};
  struct iio_channel channels[4];
  sdrd_capture_request_t request = {.generation=1, .sample_count=300, .max_bytes=1200,
                                   .timeout_ms=1000, .feature_id="capture"};
  sdrd_capture_result_t result;
  char path[1024], directory[1024];
  initialize(&adapter, &buffer, channels, root);
  const int rc = adapter_capture_iq(&adapter, &request, &result);
  assert(rc == expected_rc);
  assert(adapter.capture_active == 0);
  assert(result.health_flags == expected_flags);
  assert(result.dropped_samples == expected_missing);
  assert(snprintf(directory, sizeof(directory), "%s/capture", root) > 0);
  if (rc == 0) {
    unsigned char bytes[1201];
    assert(result.samples_captured == 300 && result.bytes_written == 1200);
    assert(buffer.calls == 2);
    assert(snprintf(path, sizeof(path), "%s/%s", root, result.relative_path) > 0);
    FILE *stream = fopen(path, "rb");
    assert(stream != NULL);
    assert(fread(bytes, 1, sizeof(bytes), stream) == 1200);
    assert(fclose(stream) == 0);
    for (size_t i = 0; i < 1200; ++i) assert(bytes[i] == (i < 1024 ? 1 : 2));
    assert(unlink(path) == 0);
    assert(rmdir(directory) == 0);
  } else {
    assert(result.samples_captured == 0 && result.bytes_written == 0);
    assert(buffer.calls == bad_call);
    assert(access(directory, F_OK) != 0 && errno == ENOENT);
    assert(result.timed_out == (rc == -ETIMEDOUT));
    assert(result.overflow == (rc == -EOVERFLOW || rc == -EPIPE));
  }
  assert(pthread_mutex_destroy(&adapter.cancel_mutex) == 0);

  buffer.calls = 0;
  initialize(&adapter, &buffer, channels, root);
  sdrd_summary_request_t power_request = {.generation=1, .frame_samples=300,
                                         .aggregate_frames=1, .timeout_ms=1000};
  sdrd_summary_result_t power;
  assert(adapter_capture_power(&adapter, &power_request, &power) == expected_rc);
  assert(adapter.capture_active == 0);
  assert(power.health_flags == expected_flags && power.dropped_samples == expected_missing);
  if (expected_rc == 0) {
    const uint64_t expected = 256u * 2u * 257u * 257u + 44u * 2u * 514u * 514u;
    assert(power.aggregate_samples == 300);
    assert((((uint64_t)power.rx0_power_mid << 32u) | power.rx0_power_lo) == expected);
    assert(buffer.calls == 2);
  } else {
    assert(power.aggregate_samples == 0 && power.rx0_power_lo == 0 && power.rx0_power_mid == 0);
    assert(buffer.calls == bad_call);
    assert(power.timed_out == (expected_rc == -ETIMEDOUT));
    assert(power.overflow == (expected_rc == -EOVERFLOW || expected_rc == -EPIPE));
  }
  assert(pthread_mutex_destroy(&adapter.cancel_mutex) == 0);
}

int main(void) {
  char root[1024];
  const char *temporary = getenv("TMPDIR");
  assert(snprintf(root, sizeof(root), "%s/iio-refill-test-XXXXXX",
                  temporary != NULL ? temporary : "/tmp") < (int)sizeof(root));
  assert(mkdtemp(root) != NULL);
  /* First case reproduces silent acceptance of contradictory length reports. */
  exercise(root, 512, 1024, 0, 1, -EPROTO, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0);
  exercise(root, 1024, 1024, 0, 0, 0, 0, 0);
  unsigned int cases = 2;
  for (unsigned int bad_call = 1; bad_call <= 2; ++bad_call) {
    const struct { ssize_t returned; size_t span; int pointer_fault; uint32_t flags; uint64_t missing; } bad[] = {
      {512, 512, 0, SDRD_EXEC_HEALTH_SHAPE_ERROR | SDRD_EXEC_HEALTH_SHORT_REFILL, 128},
      {0, 0, 0, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {0, 1024, 0, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {1024, 512, 0, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {512, 1024, 0, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {1023, 1023, 0, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {1028, 1028, 0, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {1024, 1028, 0, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {1024, 1024, 1, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {1024, 1024, 2, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
      {1024, 1024, 3, SDRD_EXEC_HEALTH_SHAPE_ERROR, 0},
    };
    for (size_t i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) {
      exercise(root, bad[i].returned, bad[i].span, bad[i].pointer_fault, bad_call,
               -EPROTO, bad[i].flags, bad[i].missing);
      ++cases;
    }
    const struct { int error; uint32_t flag; } errors[] = {
      {-ETIMEDOUT, SDRD_EXEC_HEALTH_TIMEOUT}, {-EOVERFLOW, SDRD_EXEC_HEALTH_OVERFLOW},
      {-EPIPE, SDRD_EXEC_HEALTH_OVERFLOW}, {-ECANCELED, SDRD_EXEC_HEALTH_CANCELLED},
      {-EIO, SDRD_EXEC_HEALTH_IO_ERROR},
    };
    for (size_t i = 0; i < sizeof(errors)/sizeof(errors[0]); ++i) {
      exercise(root, errors[i].error, 1024, 0, bad_call, errors[i].error, errors[i].flag, 0);
      ++cases;
    }
  }
  assert(rmdir(root) == 0);
  printf("iio_refill_cases=%u raw_and_power=pass cleanup=pass\n", cases);
  return 0;
}
