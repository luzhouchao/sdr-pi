#ifndef SDRD_FPGA_H
#define SDRD_FPGA_H

#include "sdrd.h"

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct sdrd_fpga_adapter sdrd_fpga_adapter_t;

int sdrd_fpga_adapter_create(
    const sdrd_config_t *config,
    sdrd_fpga_adapter_t **out,
    char *error,
    size_t error_size);
void sdrd_fpga_adapter_destroy(sdrd_fpga_adapter_t *adapter);
void sdrd_fpga_adapter_attach(sdrd_fpga_adapter_t *adapter, sdrd_radio_ops_t *ops);

#ifdef __cplusplus
}
#endif

#endif
