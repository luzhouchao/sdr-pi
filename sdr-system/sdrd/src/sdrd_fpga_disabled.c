#include "sdrd_fpga.h"

#include <errno.h>
#include <stdio.h>

int sdrd_fpga_adapter_create(
    const sdrd_config_t *config,
    sdrd_fpga_adapter_t **out,
    char *error,
    size_t error_size) {
  (void)config;
  if (out != NULL) {
    *out = NULL;
  }
  if (error != NULL && error_size > 0u) {
    (void)snprintf(error, error_size, "%s", "FPGA backend is not compiled into this sdrd build");
  }
  return -ENOTSUP;
}

void sdrd_fpga_adapter_destroy(sdrd_fpga_adapter_t *adapter) {
  (void)adapter;
}

void sdrd_fpga_adapter_attach(sdrd_fpga_adapter_t *adapter, sdrd_radio_ops_t *ops) {
  (void)adapter;
  (void)ops;
}
