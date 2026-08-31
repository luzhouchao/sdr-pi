#define _POSIX_C_SOURCE 200809L

#include "sdrd.h"

#include <arpa/inet.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

static volatile sig_atomic_t stop_requested = 0;

static void handle_signal(int signal_number) {
  (void)signal_number;
  stop_requested = 1;
}

static void usage(const char *program) {
  fprintf(stderr, "Usage: %s --config PATH --check-config|--probe|--serve\n", program);
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

static int serve_client(int fd, const sdrd_config_t *config) {
  char line[SDRD_MAX_LINE];
  char response[SDRD_MAX_RESPONSE];
  sdrd_session_t session;
  struct timeval timeout;
  int result = 0;
  sdrd_session_init(&session);
  timeout.tv_sec = (time_t)(config->client_timeout_ms / 1000u);
  timeout.tv_usec = (suseconds_t)(config->client_timeout_ms % 1000u) * 1000;
  (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  while (stop_requested == 0) {
    const int read_rc = receive_line(fd, line, sizeof(line));
    int response_rc;
    if (read_rc <= 0) {
      result = read_rc;
      break;
    }
    response_rc = sdrd_handle_request(
        config, &session, NULL, line, response, sizeof(response));
    if (response_rc != 0) {
      result = response_rc;
      break;
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
  if (sdrd_session_close(&session, NULL) != 0 && result == 0) {
    result = -EIO;
  }
  return result;
}

static int run_server(const sdrd_config_t *config) {
  int server_fd;
  int reuse = 1;
  struct sockaddr_in address;
  server_fd = socket(AF_INET, SOCK_STREAM, 0);
  if (server_fd < 0) {
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
    return -saved;
  }
  printf(
      "sdrd_listening=%s:%u mode=%s fpga_backend=%s\n",
      config->listen_address,
      (unsigned int)config->listen_port,
      sdrd_mode_name(config->mode),
      sdrd_fpga_backend_name(config->fpga_backend));
  fflush(stdout);
  while (stop_requested == 0) {
    int client_fd = accept(server_fd, NULL, NULL);
    if (client_fd < 0) {
      if (errno == EINTR) {
        continue;
      }
      (void)close(server_fd);
      return -errno;
    }
    (void)serve_client(client_fd, config);
    (void)close(client_fd);
  }
  (void)close(server_fd);
  return 0;
}

int main(int argc, char **argv) {
  const char *config_path = NULL;
  enum { ACTION_NONE, ACTION_CHECK, ACTION_PROBE, ACTION_SERVE } action = ACTION_NONE;
  sdrd_config_t config;
  char error[256];
  int index;
  int rc;
  for (index = 1; index < argc; ++index) {
    if (strcmp(argv[index], "--config") == 0 && index + 1 < argc) {
      config_path = argv[++index];
    } else if (strcmp(argv[index], "--check-config") == 0) {
      action = ACTION_CHECK;
    } else if (strcmp(argv[index], "--probe") == 0) {
      action = ACTION_PROBE;
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
        "config_result=ok listen=%s:%u mode=%s fpga_backend=%s\n",
        config.listen_address,
        (unsigned int)config.listen_port,
        sdrd_mode_name(config.mode),
        sdrd_fpga_backend_name(config.fpga_backend));
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
  (void)signal(SIGINT, handle_signal);
  (void)signal(SIGTERM, handle_signal);
  rc = run_server(&config);
  if (rc != 0) {
    fprintf(stderr, "server_error=%s rc=%d\n", strerror(-rc), rc);
    return 1;
  }
  return 0;
}
