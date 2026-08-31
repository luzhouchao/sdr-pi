#ifndef SDRD_IIO_H
#define SDRD_IIO_H

#include "sdrd.h"

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct sdrd_iio_adapter sdrd_iio_adapter_t;

int sdrd_iio_adapter_create(
    const sdrd_config_t *config,
    sdrd_iio_adapter_t **adapter,
    char *error,
    size_t error_size);
void sdrd_iio_adapter_destroy(sdrd_iio_adapter_t *adapter);
void sdrd_iio_adapter_ops(sdrd_iio_adapter_t *adapter, sdrd_radio_ops_t *ops);

#ifdef __cplusplus
}
#endif

#endif
