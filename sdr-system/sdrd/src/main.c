#define _POSIX_C_SOURCE 200809L

#include "sdrd.h"
#include "sdrd_iio.h"

#include <arpa/inet.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stop_requested = 0;

typedef struct server_runtime {
  pthread_mutex_t mutex;
  int worker_active;
  uint64_t active_generation;
  const sdrd_radio_ops_t *radio;
} server_runtime_t;

typedef struct client_worker_args {
  int fd;
  const sdrd_config_t *config;
  const sdrd_radio_ops_t *radio;
  server_runtime_t *runtime;
  char first_line[SDRD_MAX_LINE];
} client_worker_args_t;

static void handle_signal(int signal_number) {
  (void)signal_number;
  stop_requested = 1;
}

static void usage(const char *program) {
  fprintf(
      stderr,
      "Usage: %s --config PATH --check-config|--probe|--probe-radio|--serve\n",
      program);
}

static int send_all(int fd, const char *data, size_t length) {
  size_t sent = 0u;
  while (sent < length) {
    const ssize_t count = send(fd, data + sent, length - sent, 0);
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -errno;
    }
    if (count == 0) {
      return -EPIPE;
    }
    sent += (size_t)count;
  }
  return 0;
}

static int receive_line(int fd, char *line, size_t line_size) {
  size_t used = 0u;
  while (used + 1u < line_size) {
    char byte;
    const ssize_t count = recv(fd, &byte, 1u, 0);
    if (count < 0) {
      if (errno == EINTR) {
        continue;
      }
      return -errno;
    }
    if (count == 0) {
      return used == 0u ? 0 : -ECONNRESET;
    }
    if (byte == '\n') {
      line[used] = '\0';
      return 1;
    }
    if (byte != '\r') {
      line[used++] = byte;
    }
  }
  line[line_size - 1u] = '\0';
  return -EMSGSIZE;
}

static int serve_client(
    int fd,
    const sdrd_config_t *config,
    const sdrd_radio_ops_t *radio,
    server_runtime_t *runtime,
    const char *first_line) {
  char line[SDRD_MAX_LINE];
  char response[SDRD_MAX_RESPONSE];
  sdrd_session_t session;
  struct timeval timeout;
  int result = 0;
  int use_first_line = first_line != NULL;
  sdrd_session_init(&session);
  timeout.tv_sec = (time_t)(config->client_timeout_ms / 1000u);
  timeout.tv_usec = (suseconds_t)(config->client_timeout_ms % 1000u) * 1000;
  (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  while (stop_requested == 0) {
    int read_rc;
    int response_rc;
    if (use_first_line != 0) {
      (void)snprintf(line, sizeof(line), "%s", first_line);
      use_first_line = 0;
      read_rc = 1;
    } else {
      read_rc = receive_line(fd, line, sizeof(line));
    }
    if (read_rc <= 0) {
      result = read_rc;
      break;
    }
    response_rc = sdrd_handle_request(
        config, &session, radio, line, response, sizeof(response));
    if (response_rc != 0) {
      result = response_rc;
      break;
    }
    if (strncmp(line, "SDRD/1 START_SESSION ", 21u) == 0 &&
        strstr(response, "\"session_state\":\"owned\"") != NULL) {
      char protocol[16];
      char command[32];
      uint64_t request_id;
      uint64_t generation;
      if (sscanf(
              line,
              "%15s %31s %" SCNu64 " %" SCNu64,
              protocol,
              command,
              &request_id,
              &generation) == 4) {
        (void)pthread_mutex_lock(&runtime->mutex);
        runtime->active_generation = generation;
        (void)pthread_mutex_unlock(&runtime->mutex);
      }
    }
    response_rc = send_all(fd, response, strlen(response));
    if (response_rc != 0) {
      result = response_rc;
      break;
    }
    if (strstr(response, "\"closing\":true") != NULL) {
      break;
    }
  }
  if (sdrd_session_close(&session, radio) != 0 && result == 0) {
    result = -EIO;
  }
  (void)pthread_mutex_lock(&runtime->mutex);
  runtime->active_generation = 0u;
  (void)pthread_mutex_unlock(&runtime->mutex);
  return result;
}

static int parse_control_request(
    const char *line,
    const char *expected_command,
    uint64_t *request_id,
    uint64_t *generation) {
  char protocol[16];
  char command[32];
  char extra[2];
  const int fields = sscanf(
      line,
      "%15s %31s %" SCNu64 " %" SCNu64 " %1s",
      protocol,
      command,
      request_id,
      generation,
      extra);
  return fields == 4 && strcmp(protocol, "SDRD/1") == 0 &&
                 strcmp(command, expected_command) == 0
             ? 0
             : -EINVAL;
}

static int send_control_error(int fd, uint64_t request_id, const char *error) {
  char response[256];
  const int written = snprintf(
      response,
      sizeof(response),
      "{\"schema_version\":1,\"request_id\":%" PRIu64
      ",\"status\":\"error\",\"error\":\"%s\"}\n",
      request_id,
      error);
  if (written < 0 || (size_t)written >= sizeof(response)) {
    return -ENOSPC;
  }
  return send_all(fd, response, (size_t)written);
}

static int handle_cancel_client(
    int fd,
    server_runtime_t *runtime,
    const char *line) {
  uint64_t request_id = 0u;
  uint64_t generation = 0u;
  uint64_t active_generation;
  int rc;
  char response[256];
  int written;
  if (parse_control_request(line, "CANCEL_SESSION", &request_id, &generation) != 0 ||
      request_id == 0u || generation == 0u) {
    return send_control_error(fd, request_id, "invalid_cancel_request");
  }
  (void)pthread_mutex_lock(&runtime->mutex);
  active_generation = runtime->active_generation;
  if (runtime->radio == NULL) {
    (void)pthread_mutex_unlock(&runtime->mutex);
    return send_control_error(fd, request_id, "stale_or_missing_session");
  }
  if (active_generation != generation) {
    (void)pthread_mutex_unlock(&runtime->mutex);
    return send_control_error(fd, request_id, "stale_or_missing_session");
  }
  rc = runtime->radio->cancel(runtime->radio->context);
  (void)pthread_mutex_unlock(&runtime->mutex);
  if (rc != 0) {
    return send_control_error(fd, request_id, "cancel_failed");
  }
  written = snprintf(
      response,
      sizeof(response),
      "{\"schema_version\":1,\"request_id\":%" PRIu64
      ",\"status\":\"ok\",\"generation\":%" PRIu64
      ",\"session_generation\":%" PRIu64 ",\"cancel_requested\":true}\n",
      request_id,
      generation,
      generation);
  if (written < 0 || (size_t)written >= sizeof(response)) {
    return -ENOSPC;
  }
  return send_all(fd, response, (size_t)written);
}

static void *client_worker(void *opaque) {
  client_worker_args_t *args = opaque;
  (void)serve_client(
      args->fd,
      args->config,
      args->radio,
      args->runtime,
      args->first_line);
  (void)close(args->fd);
  (void)pthread_mutex_lock(&args->runtime->mutex);
  args->runtime->active_generation = 0u;
  args->runtime->worker_active = 0;
  (void)pthread_mutex_unlock(&args->runtime->mutex);
  free(args);
  return NULL;
}

static void wait_for_worker(server_runtime_t *runtime) {
  for (;;) {
    int active;
    struct timespec wait = {0, 10000000L};
    (void)pthread_mutex_lock(&runtime->mutex);
    active = runtime->worker_active;
    (void)pthread_mutex_unlock(&runtime->mutex);
    if (active == 0) {
      return;
    }
    (void)nanosleep(&wait, NULL);
  }
}

static int run_server(const sdrd_config_t *config, const sdrd_radio_ops_t *radio) {
  int server_fd;
  int reuse = 1;
  struct sockaddr_in address;
  server_runtime_t runtime;
  int runtime_rc;
  memset(&runtime, 0, sizeof(runtime));
  runtime.radio = radio;
  runtime_rc = pthread_mutex_init(&runtime.mutex, NULL);
  if (runtime_rc != 0) {
    return -runtime_rc;
  }
  server_fd = socket(AF_INET, SOCK_STREAM, 0);
  if (server_fd < 0) {
    (void)pthread_mutex_destroy(&runtime.mutex);
    return -errno;
  }
  (void)setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
  memset(&address, 0, sizeof(address));
  address.sin_family = AF_INET;
  address.sin_port = htons(config->listen_port);
  if (inet_pton(AF_INET, config->listen_address, &address.sin_addr) != 1) {
    (void)close(server_fd);
    return -EINVAL;
  }
  if (bind(server_fd, (const struct sockaddr *)&address, sizeof(address)) != 0 ||
      listen(server_fd, 2) != 0) {
    const int saved = errno;
    (void)close(server_fd);
    (void)pthread_mutex_destroy(&runtime.mutex);
    return -saved;
  }
  printf(
      "sdrd_listening=%s:%u mode=%s\n",
      config->listen_address,
      (unsigned int)config->listen_port,
      sdrd_mode_name(config->mode));
  fflush(stdout);
  while (stop_requested == 0) {
    int client_fd = accept(server_fd, NULL, NULL);
    char first_line[SDRD_MAX_LINE];
    int read_rc;
    if (client_fd < 0) {
      if (errno == EINTR) {
        continue;
      }
      {
        const int saved = errno;
        (void)close(server_fd);
        wait_for_worker(&runtime);
        (void)pthread_mutex_destroy(&runtime.mutex);
        return -saved;
      }
    }
    {
      struct timeval timeout;
      timeout.tv_sec = (time_t)(config->client_timeout_ms / 1000u);
      timeout.tv_usec = (suseconds_t)(config->client_timeout_ms % 1000u) * 1000;
      (void)setsockopt(client_fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    }
    read_rc = receive_line(client_fd, first_line, sizeof(first_line));
    if (read_rc <= 0) {
      (void)close(client_fd);
      continue;
    }
    if (strncmp(first_line, "SDRD/1 CANCEL_SESSION ", 22u) == 0) {
      (void)handle_cancel_client(client_fd, &runtime, first_line);
      (void)close(client_fd);
      continue;
    }
    (void)pthread_mutex_lock(&runtime.mutex);
    if (runtime.worker_active != 0) {
      uint64_t request_id = 0u;
      char protocol[16];
      char command[32];
      (void)sscanf(first_line, "%15s %31s %" SCNu64, protocol, command, &request_id);
      (void)pthread_mutex_unlock(&runtime.mutex);
      (void)send_control_error(client_fd, request_id, "server_busy");
      (void)close(client_fd);
      continue;
    }
    runtime.worker_active = 1;
    (void)pthread_mutex_unlock(&runtime.mutex);
    {
      client_worker_args_t *args = calloc(1u, sizeof(*args));
      pthread_t thread;
      int thread_rc;
      if (args == NULL) {
        (void)pthread_mutex_lock(&runtime.mutex);
        runtime.worker_active = 0;
        (void)pthread_mutex_unlock(&runtime.mutex);
        (void)send_control_error(client_fd, 0u, "server_resource_exhausted");
        (void)close(client_fd);
        continue;
      }
      args->fd = client_fd;
      args->config = config;
      args->radio = radio;
      args->runtime = &runtime;
      (void)snprintf(args->first_line, sizeof(args->first_line), "%s", first_line);
      thread_rc = pthread_create(&thread, NULL, client_worker, args);
      if (thread_rc != 0) {
        free(args);
        (void)pthread_mutex_lock(&runtime.mutex);
        runtime.worker_active = 0;
        (void)pthread_mutex_unlock(&runtime.mutex);
        (void)send_control_error(client_fd, 0u, "server_thread_failed");
        (void)close(client_fd);
        continue;
      }
      (void)pthread_detach(thread);
    }
  }
  (void)close(server_fd);
  wait_for_worker(&runtime);
  (void)pthread_mutex_destroy(&runtime.mutex);
  return 0;
}

int main(int argc, char **argv) {
  const char *config_path = NULL;
  enum { ACTION_NONE, ACTION_CHECK, ACTION_PROBE, ACTION_RADIO_PROBE, ACTION_SERVE } action = ACTION_NONE;
  sdrd_config_t config;
  sdrd_iio_adapter_t *iio_adapter = NULL;
  sdrd_radio_ops_t radio;
  char error[256];
  int index;
  int rc;
  memset(&radio, 0, sizeof(radio));
  for (index = 1; index < argc; ++index) {
    if (strcmp(argv[index], "--config") == 0 && index + 1 < argc) {
      config_path = argv[++index];
    } else if (strcmp(argv[index], "--check-config") == 0) {
      action = ACTION_CHECK;
    } else if (strcmp(argv[index], "--probe") == 0) {
      action = ACTION_PROBE;
    } else if (strcmp(argv[index], "--probe-radio") == 0) {
      action = ACTION_RADIO_PROBE;
    } else if (strcmp(argv[index], "--serve") == 0) {
      action = ACTION_SERVE;
    } else {
      usage(argv[0]);
      return 2;
    }
  }
  if (config_path == NULL || action == ACTION_NONE) {
    usage(argv[0]);
    return 2;
  }
  rc = sdrd_config_load(config_path, &config, error, sizeof(error));
  if (rc != 0) {
    fprintf(stderr, "configuration_error=%s rc=%d\n", error, rc);
    return 1;
  }
  if (action == ACTION_CHECK) {
    printf(
        "config_result=ok listen=%s:%u mode=%s\n",
        config.listen_address,
        (unsigned int)config.listen_port,
        sdrd_mode_name(config.mode));
    return 0;
  }
  if (action == ACTION_PROBE) {
    char response[SDRD_MAX_RESPONSE];
    rc = sdrd_format_response(&config, "SDRD/1 CAPABILITIES 1", response, sizeof(response));
    if (rc == 0) {
      fputs(response, stdout);
      rc = sdrd_format_response(&config, "SDRD/1 HEALTH 2", response, sizeof(response));
    }
    if (rc == 0) {
      fputs(response, stdout);
    }
    return rc == 0 ? 0 : 1;
  }
  if (action == ACTION_RADIO_PROBE) {
    sdrd_radio_state_t state;
    if (config.mode != SDRD_MODE_CONTROLLED) {
      fprintf(stderr, "radio_probe_requires=mode=controlled\n");
      return 1;
    }
    rc = sdrd_iio_adapter_create(&config, &iio_adapter, error, sizeof(error));
    if (rc == 0) {
      sdrd_iio_adapter_ops(iio_adapter, &radio);
      rc = radio.snapshot(radio.context, &state);
      if (rc != 0) {
        (void)snprintf(error, sizeof(error), "radio state snapshot failed");
      }
    }
    if (rc != 0) {
      fprintf(stderr, "radio_probe_error=%s rc=%d\n", error, rc);
      sdrd_iio_adapter_destroy(iio_adapter);
      return 1;
    }
    printf(
        "{\"radio_probe\":\"ok\",\"center_hz\":%" PRIu64 ",\"sample_rate_hz\":%u,\"rf_bandwidth_hz\":%u,\"gain_mode\":\"%s\",\"scan_channel_mask\":%u}\n",
        state.center_hz,
        state.sample_rate_hz,
        state.rf_bandwidth_hz,
        state.gain_mode,
        state.scan_channel_mask);
    sdrd_iio_adapter_destroy(iio_adapter);
    return 0;
  }
  (void)signal(SIGINT, handle_signal);
  (void)signal(SIGTERM, handle_signal);
  if (config.mode == SDRD_MODE_CONTROLLED) {
    rc = sdrd_iio_adapter_create(&config, &iio_adapter, error, sizeof(error));
    if (rc != 0) {
      fprintf(stderr, "iio_adapter_error=%s rc=%d\n", error, rc);
      return 1;
    }
    sdrd_iio_adapter_ops(iio_adapter, &radio);
  }
  rc = run_server(&config, iio_adapter != NULL ? &radio : NULL);
  sdrd_iio_adapter_destroy(iio_adapter);
  if (rc != 0) {
    fprintf(stderr, "server_error=%s rc=%d\n", strerror(-rc), rc);
    return 1;
  }
  return 0;
}
