#define _POSIX_C_SOURCE 200809L

#include "p201_native_mmio.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

struct p201_mmio {
  int fd;
  volatile uint8_t *map;
  volatile uint8_t *regs;
  size_t map_len;
  size_t span;
  uint64_t map_offset;
  uint32_t flags;
  uint32_t last_sequence;
  uint32_t last_frame;
  int have_last;
};

static uint64_t monotonic_ns(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
    return 0;
  }
  return ((uint64_t)ts.tv_sec * 1000000000ull) + (uint64_t)ts.tv_nsec;
}

static long page_size_or_errno(void) {
  const long page_size = sysconf(_SC_PAGESIZE);
  if (page_size <= 0) {
    return -errno;
  }
  return page_size;
}

static int is_allowed3(uint32_t value, uint32_t a, uint32_t b, uint32_t c) {
  return value == a || value == b || value == c;
}

static int is_allowed4(uint32_t value, uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
  return value == a || value == b || value == c || value == d;
}

static void sleep_us(uint32_t delay_us) {
  struct timespec ts;
  ts.tv_sec = (time_t)(delay_us / 1000000u);
  ts.tv_nsec = (long)(delay_us % 1000000u) * 1000L;
  while (nanosleep(&ts, &ts) != 0 && errno == EINTR) {
  }
}

static int ensure_ctx_open(const p201_mmio_t *ctx) {
  if (ctx == NULL || ctx->fd < 0 || ctx->map == NULL || ctx->regs == NULL || ctx->span == 0) {
    return -ENODEV;
  }
  return 0;
}

static int check_offset(const p201_mmio_t *ctx, uint32_t offset) {
  const int open_rc = ensure_ctx_open(ctx);
  if (open_rc != 0) {
    return open_rc;
  }
  if ((offset & 0x3u) != 0u) {
    return -EINVAL;
  }
  if ((uint64_t)offset + sizeof(uint32_t) > (uint64_t)ctx->span) {
    return -ERANGE;
  }
  return 0;
}

p201_mmio_t *p201_mmio_create(void) {
  p201_mmio_t *ctx = (p201_mmio_t *)calloc(1u, sizeof(*ctx));
  if (ctx == NULL) {
    return NULL;
  }
  ctx->fd = -1;
  return ctx;
}

void p201_mmio_close(p201_mmio_t *ctx) {
  if (ctx == NULL) {
    return;
  }
  if (ctx->map != NULL && ctx->map_len > 0u) {
    (void)munmap((void *)ctx->map, ctx->map_len);
  }
  if (ctx->fd >= 0) {
    (void)close(ctx->fd);
  }
  ctx->fd = -1;
  ctx->map = NULL;
  ctx->regs = NULL;
  ctx->map_len = 0u;
  ctx->span = 0u;
  ctx->map_offset = 0u;
  ctx->flags = 0u;
  ctx->last_sequence = 0u;
  ctx->last_frame = 0u;
  ctx->have_last = 0;
}

void p201_mmio_destroy(p201_mmio_t *ctx) {
  if (ctx == NULL) {
    return;
  }
  p201_mmio_close(ctx);
  free(ctx);
}

int p201_mmio_open(
    p201_mmio_t *ctx,
    const char *path,
    uint64_t target_offset,
    size_t span_bytes,
    uint32_t flags) {
  long page_size;
  uint64_t map_offset;
  uint64_t page_delta;
  uint64_t map_len64;
  int open_flags;
  int prot;

  if (ctx == NULL || path == NULL || path[0] == '\0' || span_bytes == 0u) {
    return -EINVAL;
  }
  if (span_bytes > (size_t)UINT32_MAX) {
    return -ERANGE;
  }

  page_size = page_size_or_errno();
  if (page_size < 0) {
    return (int)page_size;
  }

  p201_mmio_close(ctx);

  if ((flags & P201_MMIO_OPEN_DEVMEM) != 0u) {
    const uint64_t page_mask = (uint64_t)page_size - 1ull;
    map_offset = target_offset & ~page_mask;
    page_delta = target_offset - map_offset;
  } else {
    map_offset = target_offset;
    page_delta = 0u;
  }

  map_len64 = page_delta + (uint64_t)span_bytes;
  if (map_len64 == 0u || map_len64 > (uint64_t)SIZE_MAX) {
    return -ERANGE;
  }

  open_flags = ((flags & P201_MMIO_OPEN_READ_ONLY) != 0u) ? O_RDONLY : O_RDWR;
  if ((flags & P201_MMIO_OPEN_SYNC) != 0u) {
    open_flags |= O_SYNC;
  }
  ctx->fd = open(path, open_flags);
  if (ctx->fd < 0) {
    const int saved = errno;
    p201_mmio_close(ctx);
    return -saved;
  }

  prot = ((flags & P201_MMIO_OPEN_READ_ONLY) != 0u) ? PROT_READ : (PROT_READ | PROT_WRITE);
  ctx->map = (volatile uint8_t *)mmap(NULL, (size_t)map_len64, prot, MAP_SHARED, ctx->fd, (off_t)map_offset);
  if (ctx->map == MAP_FAILED) {
    const int saved = errno;
    ctx->map = NULL;
    p201_mmio_close(ctx);
    return -saved;
  }

  ctx->regs = ctx->map + page_delta;
  ctx->map_len = (size_t)map_len64;
  ctx->span = span_bytes;
  ctx->map_offset = map_offset;
  ctx->flags = flags;
  return 0;
}

int p201_mmio_read32(p201_mmio_t *ctx, uint32_t offset, uint32_t *value) {
  volatile const uint32_t *addr;
  const int rc = check_offset(ctx, offset);
  if (rc != 0) {
    return rc;
  }
  if (value == NULL) {
    return -EINVAL;
  }
  addr = (volatile const uint32_t *)(const volatile void *)(ctx->regs + offset);
  *value = *addr;
  return 0;
}

int p201_mmio_write32(p201_mmio_t *ctx, uint32_t offset, uint32_t value) {
  volatile uint32_t *addr;
  const int rc = check_offset(ctx, offset);
  if (rc != 0) {
    return rc;
  }
  if ((ctx->flags & P201_MMIO_OPEN_READ_ONLY) != 0u) {
    return -EACCES;
  }
  addr = (volatile uint32_t *)(volatile void *)(ctx->regs + offset);
  *addr = value;
  return 0;
}

void p201_mmio_reset_stale_state(p201_mmio_t *ctx) {
  if (ctx == NULL) {
    return;
  }
  ctx->last_sequence = 0u;
  ctx->last_frame = 0u;
  ctx->have_last = 0;
}

int p201_sum8_arm_aggregate(p201_mmio_t *ctx, uint32_t frame_len, uint32_t agg_frames) {
  int rc;
  if (frame_len == 0u || frame_len > 65535u || agg_frames == 0u || agg_frames > P201_SUM8_MAX_AGG_FRAMES) {
    return -EINVAL;
  }
  rc = p201_mmio_write32(ctx, 0x004u, frame_len);
  if (rc != 0) {
    return rc;
  }
  rc = p201_mmio_write32(ctx, 0x188u, agg_frames);
  if (rc != 0) {
    return rc;
  }
  rc = p201_mmio_write32(ctx, 0x184u, 0x00000003u);
  if (rc != 0) {
    return rc;
  }
  rc = p201_mmio_write32(ctx, 0x184u, 0x00000001u);
  if (rc != 0) {
    return rc;
  }
  rc = p201_mmio_write32(ctx, 0x000u, 0x00000002u);
  if (rc != 0) {
    return rc;
  }
  return p201_mmio_write32(ctx, 0x000u, 0x00000001u);
}

int p201_sum8_poll_done(
    p201_mmio_t *ctx,
    uint32_t timeout_us,
    uint32_t poll_sleep_us,
    uint64_t *elapsed_ns) {
  const uint64_t start_ns = monotonic_ns();
  const uint64_t timeout_ns = (uint64_t)timeout_us * 1000ull;
  uint32_t control = 0u;
  int rc;

  if (poll_sleep_us == 0u) {
    poll_sleep_us = 1000u;
  }

  for (;;) {
    const uint64_t now_ns = monotonic_ns();
    rc = p201_mmio_read32(ctx, 0x184u, &control);
    if (rc != 0) {
      return rc;
    }
    if ((control & (1u << 4)) != 0u) {
      if (elapsed_ns != NULL) {
        *elapsed_ns = now_ns - start_ns;
      }
      return 0;
    }
    if (timeout_us > 0u && now_ns - start_ns >= timeout_ns) {
      if (elapsed_ns != NULL) {
        *elapsed_ns = now_ns - start_ns;
      }
      return -ETIMEDOUT;
    }
    sleep_us(poll_sleep_us);
  }
}

#define READ_FIELD(field, offset)                 \
  do {                                            \
    rc = p201_mmio_read32(ctx, (offset), &field); \
    if (rc != 0) {                                \
      return rc;                                  \
    }                                             \
  } while (0)

int p201_sum8_read_snapshot(
    p201_mmio_t *ctx,
    uint32_t expected_frame_len,
    uint32_t expected_agg_frames,
    p201_sum8_snapshot_t *out) {
  uint64_t expected_samples;
  uint64_t start_ns;
  int rc;

  if (out == NULL) {
    return -EINVAL;
  }
  memset(out, 0, sizeof(*out));

  start_ns = monotonic_ns();
  READ_FIELD(out->summary_version, 0x040u);
  READ_FIELD(out->abi_version, 0x0ECu);
  READ_FIELD(out->capability_bitmap, 0x0F0u);
  READ_FIELD(out->build_id, 0x0FCu);
  READ_FIELD(out->quality_version, 0x100u);
  READ_FIELD(out->quality_capability, 0x138u);
  READ_FIELD(out->quality_build_id, 0x13Cu);
  READ_FIELD(out->agg_sequence, 0x17Cu);
  READ_FIELD(out->agg_version, 0x180u);
  READ_FIELD(out->agg_control, 0x184u);
  READ_FIELD(out->agg_target, 0x188u);
  READ_FIELD(out->agg_frames, 0x18Cu);
  READ_FIELD(out->agg_samples, 0x190u);
  READ_FIELD(out->rx0_corr_power_num.lo, 0x194u);
  READ_FIELD(out->rx0_corr_power_num.mid, 0x198u);
  READ_FIELD(out->rx0_corr_power_num.hi, 0x19Cu);
  READ_FIELD(out->rx1_corr_power_num.lo, 0x1A0u);
  READ_FIELD(out->rx1_corr_power_num.mid, 0x1A4u);
  READ_FIELD(out->rx1_corr_power_num.hi, 0x1A8u);
  READ_FIELD(out->corr_cross_re_num.lo, 0x1ACu);
  READ_FIELD(out->corr_cross_re_num.mid, 0x1B0u);
  READ_FIELD(out->corr_cross_re_num.hi, 0x1B4u);
  READ_FIELD(out->corr_cross_im_num.lo, 0x1B8u);
  READ_FIELD(out->corr_cross_im_num.mid, 0x1BCu);
  READ_FIELD(out->corr_cross_im_num.hi, 0x1C0u);
  READ_FIELD(out->rx0_raw_power.lo, 0x1C4u);
  READ_FIELD(out->rx0_raw_power.mid, 0x1C8u);
  READ_FIELD(out->rx0_raw_power.hi, 0x1CCu);
  READ_FIELD(out->rx1_raw_power.lo, 0x1D0u);
  READ_FIELD(out->rx1_raw_power.mid, 0x1D4u);
  READ_FIELD(out->rx1_raw_power.hi, 0x1D8u);
  READ_FIELD(out->rx0_clip_count, 0x1DCu);
  READ_FIELD(out->rx1_clip_count, 0x1E0u);
  READ_FIELD(out->rx0_zero_cross_count, 0x1E4u);
  READ_FIELD(out->rx1_zero_cross_count, 0x1E8u);
  READ_FIELD(out->same_sign_count, 0x1ECu);
  READ_FIELD(out->agg_last_frame, 0x1F0u);
  READ_FIELD(out->agg_capability, 0x1F4u);
  READ_FIELD(out->agg_build_id, 0x1F8u);
  READ_FIELD(out->agg_limit, 0x1FCu);
  out->elapsed_ns = monotonic_ns() - start_ns;

  if (out->summary_version != P201_SUM8_MAGIC ||
      out->abi_version != P201_SUM8_ABI_VERSION ||
      out->capability_bitmap != P201_SUM8_CAPABILITY ||
      !is_allowed4(out->build_id, 0x56380001u, 0x56384430u, 0x56384C31u, 0x56384C32u) ||
      out->quality_version != P201_QUA8_MAGIC ||
      out->quality_capability != P201_QUA8_CAPABILITY ||
      !is_allowed4(out->quality_build_id, 0x51380001u, 0x51384430u, 0x51384C31u, 0x51384C32u) ||
      out->agg_version != P201_AGG8_MAGIC ||
      !is_allowed3(out->agg_capability, P201_AGG8_CAPABILITY, P201_AGG8_AUTOROLL_CAPABILITY, P201_AGG8_CAPABILITY) ||
      !is_allowed4(out->agg_build_id, 0x41380001u, 0x41384430u, 0x41384C31u, 0x41384C32u) ||
      out->agg_limit != P201_SUM8_MAX_AGG_FRAMES) {
    out->status_flags |= P201_SUM8_STATUS_INVALID_IDENTITY;
  }

  if ((out->agg_control & (1u << 4)) == 0u) {
    out->status_flags |= P201_SUM8_STATUS_AGG_NOT_DONE;
  }
  if ((out->agg_control & (1u << 5)) != 0u) {
    out->status_flags |= P201_SUM8_STATUS_AGG_OVERFLOW;
  }

  if (expected_agg_frames != 0u &&
      (out->agg_target != expected_agg_frames || out->agg_frames != expected_agg_frames)) {
    out->status_flags |= P201_SUM8_STATUS_TARGET_MISMATCH;
  }

  expected_samples = 0u;
  if (expected_frame_len != 0u) {
    const uint32_t frame_count = expected_agg_frames != 0u ? expected_agg_frames : out->agg_frames;
    expected_samples = (uint64_t)expected_frame_len * (uint64_t)frame_count;
  }
  if (expected_samples != 0u && out->agg_samples != expected_samples) {
    out->status_flags |= P201_SUM8_STATUS_SAMPLE_MISMATCH;
  }

  if (ctx != NULL && ctx->have_last != 0) {
    if (out->agg_sequence != 0u) {
      if (out->agg_sequence == ctx->last_sequence) {
        out->status_flags |= P201_SUM8_STATUS_STALE_FRAME;
      }
    } else if (out->agg_last_frame == ctx->last_frame) {
      out->status_flags |= P201_SUM8_STATUS_STALE_FRAME;
    }
  }
  if (ctx != NULL) {
    ctx->last_sequence = out->agg_sequence;
    ctx->last_frame = out->agg_last_frame;
    ctx->have_last = 1;
  }

  return 0;
}

#undef READ_FIELD
