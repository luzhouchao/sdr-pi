#ifndef P201_NATIVE_MMIO_H
#define P201_NATIVE_MMIO_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define P201_TAP_BASE 0x43C00000u
#define P201_TAP_SPAN_BYTES 0x00010000u

#define P201_MMIO_OPEN_PLAIN 0u
#define P201_MMIO_OPEN_DEVMEM (1u << 0)
#define P201_MMIO_OPEN_READ_ONLY (1u << 1)
#define P201_MMIO_OPEN_SYNC (1u << 2)

#define P201_SUM8_MAGIC 0x53554D38u
#define P201_SUM8_ABI_VERSION 0x00010002u
#define P201_SUM8_CAPABILITY 0x000003FFu
#define P201_QUA8_MAGIC 0x51554138u
#define P201_QUA8_CAPABILITY 0x0000000Fu
#define P201_AGG8_MAGIC 0x41474738u
#define P201_AGG8_CAPABILITY 0x0000001Fu
#define P201_AGG8_AUTOROLL_CAPABILITY 0x0000003Fu
#define P201_SUM8_MAX_AGG_FRAMES 65535u

#define P201_SUM8_STATUS_INVALID_IDENTITY (1u << 0)
#define P201_SUM8_STATUS_AGG_NOT_DONE (1u << 1)
#define P201_SUM8_STATUS_AGG_OVERFLOW (1u << 2)
#define P201_SUM8_STATUS_STALE_FRAME (1u << 3)
#define P201_SUM8_STATUS_SAMPLE_MISMATCH (1u << 4)
#define P201_SUM8_STATUS_TARGET_MISMATCH (1u << 5)

typedef struct p201_mmio p201_mmio_t;

typedef struct p201_u96_words {
  uint32_t lo;
  uint32_t mid;
  uint32_t hi;
} p201_u96_words_t;

typedef struct p201_sum8_snapshot {
  uint32_t summary_version;
  uint32_t abi_version;
  uint32_t capability_bitmap;
  uint32_t build_id;
  uint32_t quality_version;
  uint32_t quality_capability;
  uint32_t quality_build_id;
  uint32_t agg_sequence;
  uint32_t agg_version;
  uint32_t agg_control;
  uint32_t agg_target;
  uint32_t agg_frames;
  uint32_t agg_samples;
  p201_u96_words_t rx0_corr_power_num;
  p201_u96_words_t rx1_corr_power_num;
  p201_u96_words_t corr_cross_re_num;
  p201_u96_words_t corr_cross_im_num;
  p201_u96_words_t rx0_raw_power;
  p201_u96_words_t rx1_raw_power;
  uint32_t rx0_clip_count;
  uint32_t rx1_clip_count;
  uint32_t rx0_zero_cross_count;
  uint32_t rx1_zero_cross_count;
  uint32_t same_sign_count;
  uint32_t agg_last_frame;
  uint32_t agg_capability;
  uint32_t agg_build_id;
  uint32_t agg_limit;
  uint32_t status_flags;
  uint64_t elapsed_ns;
} p201_sum8_snapshot_t;

/*
 * Ownership: p201_mmio_create() allocates a backend handle. The caller owns it
 * and must release it with p201_mmio_destroy(). p201_mmio_close() keeps the
 * handle reusable but unmaps and closes the current device/file.
 */
p201_mmio_t *p201_mmio_create(void);
void p201_mmio_destroy(p201_mmio_t *ctx);
void p201_mmio_close(p201_mmio_t *ctx);

/*
 * Open and mmap a register aperture.
 *
 * For /dev/mem: path="/dev/mem", target_offset=P201_TAP_BASE,
 * span_bytes=P201_TAP_SPAN_BYTES, flags=P201_MMIO_OPEN_DEVMEM|P201_MMIO_OPEN_SYNC.
 *
 * For /dev/uioX or a fake register file: target_offset=0 and flags can be
 * P201_MMIO_OPEN_PLAIN. UIO mapping assumes the kernel exposes the FPGA page at
 * mmap offset 0 for that device.
 */
int p201_mmio_open(
    p201_mmio_t *ctx,
    const char *path,
    uint64_t target_offset,
    size_t span_bytes,
    uint32_t flags);

int p201_mmio_read32(p201_mmio_t *ctx, uint32_t offset, uint32_t *value);
int p201_mmio_write32(p201_mmio_t *ctx, uint32_t offset, uint32_t value);
void p201_mmio_reset_stale_state(p201_mmio_t *ctx);

int p201_sum8_arm_aggregate(p201_mmio_t *ctx, uint32_t frame_len, uint32_t agg_frames);
int p201_sum8_poll_done(
    p201_mmio_t *ctx,
    uint32_t timeout_us,
    uint32_t poll_sleep_us,
    uint64_t *elapsed_ns);
int p201_sum8_read_snapshot(
    p201_mmio_t *ctx,
    uint32_t expected_frame_len,
    uint32_t expected_agg_frames,
    p201_sum8_snapshot_t *out);

#ifdef __cplusplus
}
#endif

#endif
