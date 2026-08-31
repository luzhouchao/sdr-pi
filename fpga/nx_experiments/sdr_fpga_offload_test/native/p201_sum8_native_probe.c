#define _POSIX_C_SOURCE 200809L

#include "p201_native_mmio.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct probe_options {
  const char *device;
  uint32_t frame_len;
  uint32_t agg_frames;
  uint32_t timeout_us;
  uint32_t poll_us;
  int arm;
} probe_options_t;

static void usage(const char *argv0) {
  fprintf(
      stderr,
      "Usage: %s [--device /dev/mem] [--arm] [--frame-len N] [--agg-frames N] "
      "[--timeout-us N] [--poll-us N]\n",
      argv0);
}

static int parse_u32(const char *text, uint32_t *out) {
  char *end = NULL;
  unsigned long value;
  errno = 0;
  if (text == NULL || out == NULL || text[0] == '\0') {
    return -EINVAL;
  }
  value = strtoul(text, &end, 0);
  if (errno != 0 || end == text || *end != '\0' || value > UINT32_MAX) {
    return -EINVAL;
  }
  *out = (uint32_t)value;
  return 0;
}

static int parse_args(int argc, char **argv, probe_options_t *opts) {
  int index;
  if (opts == NULL) {
    return -EINVAL;
  }
  opts->device = "/dev/mem";
  opts->frame_len = 64u;
  opts->agg_frames = 64u;
  opts->timeout_us = 500000u;
  opts->poll_us = 1000u;
  opts->arm = 0;

  for (index = 1; index < argc; ++index) {
    if (strcmp(argv[index], "--arm") == 0) {
      opts->arm = 1;
    } else if (strcmp(argv[index], "--device") == 0 && index + 1 < argc) {
      opts->device = argv[++index];
    } else if (strcmp(argv[index], "--frame-len") == 0 && index + 1 < argc) {
      if (parse_u32(argv[++index], &opts->frame_len) != 0) {
        return -EINVAL;
      }
    } else if (strcmp(argv[index], "--agg-frames") == 0 && index + 1 < argc) {
      if (parse_u32(argv[++index], &opts->agg_frames) != 0) {
        return -EINVAL;
      }
    } else if (strcmp(argv[index], "--timeout-us") == 0 && index + 1 < argc) {
      if (parse_u32(argv[++index], &opts->timeout_us) != 0) {
        return -EINVAL;
      }
    } else if (strcmp(argv[index], "--poll-us") == 0 && index + 1 < argc) {
      if (parse_u32(argv[++index], &opts->poll_us) != 0) {
        return -EINVAL;
      }
    } else if (strcmp(argv[index], "--help") == 0) {
      usage(argv[0]);
      exit(0);
    } else {
      return -EINVAL;
    }
  }
  return 0;
}

static void print_u96_json(const char *name, p201_u96_words_t value, const char *suffix) {
  printf(
      "    \"%s\": {\"hi\": \"0x%08" PRIX32 "\", \"mid\": \"0x%08" PRIX32 "\", \"lo\": \"0x%08" PRIX32 "\"}%s\n",
      name,
      value.hi,
      value.mid,
      value.lo,
      suffix);
}

static int identity_ok(const p201_sum8_snapshot_t *snap) {
  if (snap == NULL) {
    return 0;
  }
  if ((snap->status_flags & P201_SUM8_STATUS_INVALID_IDENTITY) != 0u) {
    return 0;
  }
  return snap->summary_version == P201_SUM8_MAGIC &&
         snap->abi_version == 0x00010002u &&
         snap->capability_bitmap == 0x000003FFu &&
         snap->quality_version == P201_QUA8_MAGIC &&
         snap->quality_capability == P201_QUA8_CAPABILITY &&
         snap->agg_version == P201_AGG8_MAGIC &&
         snap->agg_limit == P201_SUM8_MAX_AGG_FRAMES &&
         (snap->agg_capability == P201_AGG8_CAPABILITY ||
          snap->agg_capability == P201_AGG8_AUTOROLL_CAPABILITY);
}

static void print_snapshot_json(
    const probe_options_t *opts,
    const p201_sum8_snapshot_t *snap,
    int open_rc,
    int arm_rc,
    int poll_rc,
    uint64_t poll_elapsed_ns) {
  const int id_ok = identity_ok(snap);
  const int aggregate_ok =
      opts->arm &&
      snap != NULL &&
      (snap->status_flags & (P201_SUM8_STATUS_INVALID_IDENTITY |
                             P201_SUM8_STATUS_AGG_NOT_DONE |
                             P201_SUM8_STATUS_AGG_OVERFLOW |
                             P201_SUM8_STATUS_SAMPLE_MISMATCH |
                             P201_SUM8_STATUS_TARGET_MISMATCH)) == 0u;
  const int passed = (open_rc == 0) && (arm_rc == 0) && (poll_rc == 0) && id_ok && (!opts->arm || aggregate_ok);

  printf("{\n");
  printf("  \"operation\": \"p201_sum8_native_probe\",\n");
  printf("  \"device\": \"%s\",\n", opts->device);
  printf("  \"armed\": %s,\n", opts->arm ? "true" : "false");
  printf("  \"requested\": {\"frame_len\": %" PRIu32 ", \"agg_frames\": %" PRIu32 "},\n", opts->frame_len, opts->agg_frames);
  printf("  \"return_codes\": {\"open\": %d, \"arm\": %d, \"poll\": %d},\n", open_rc, arm_rc, poll_rc);
  printf("  \"passed\": %s,\n", passed ? "true" : "false");
  printf("  \"identity_ok\": %s,\n", id_ok ? "true" : "false");
  printf("  \"aggregate_ok\": %s,\n", aggregate_ok ? "true" : "false");
  printf("  \"poll_elapsed_ns\": %" PRIu64 ",\n", poll_elapsed_ns);
  if (snap == NULL) {
    printf("  \"snapshot\": null\n");
    printf("}\n");
    return;
  }
  printf("  \"snapshot\": {\n");
  printf("    \"summary_version\": \"0x%08" PRIX32 "\",\n", snap->summary_version);
  printf("    \"abi_version\": \"0x%08" PRIX32 "\",\n", snap->abi_version);
  printf("    \"capability_bitmap\": \"0x%08" PRIX32 "\",\n", snap->capability_bitmap);
  printf("    \"build_id\": \"0x%08" PRIX32 "\",\n", snap->build_id);
  printf("    \"quality_version\": \"0x%08" PRIX32 "\",\n", snap->quality_version);
  printf("    \"quality_capability\": \"0x%08" PRIX32 "\",\n", snap->quality_capability);
  printf("    \"quality_build_id\": \"0x%08" PRIX32 "\",\n", snap->quality_build_id);
  printf("    \"agg_sequence\": %" PRIu32 ",\n", snap->agg_sequence);
  printf("    \"agg_version\": \"0x%08" PRIX32 "\",\n", snap->agg_version);
  printf("    \"agg_control\": \"0x%08" PRIX32 "\",\n", snap->agg_control);
  printf("    \"agg_target\": %" PRIu32 ",\n", snap->agg_target);
  printf("    \"agg_frames\": %" PRIu32 ",\n", snap->agg_frames);
  printf("    \"agg_samples\": %" PRIu32 ",\n", snap->agg_samples);
  print_u96_json("rx0_corr_power_num", snap->rx0_corr_power_num, ",");
  print_u96_json("rx1_corr_power_num", snap->rx1_corr_power_num, ",");
  print_u96_json("corr_cross_re_num", snap->corr_cross_re_num, ",");
  print_u96_json("corr_cross_im_num", snap->corr_cross_im_num, ",");
  print_u96_json("rx0_raw_power", snap->rx0_raw_power, ",");
  print_u96_json("rx1_raw_power", snap->rx1_raw_power, ",");
  printf("    \"rx0_clip_count\": %" PRIu32 ",\n", snap->rx0_clip_count);
  printf("    \"rx1_clip_count\": %" PRIu32 ",\n", snap->rx1_clip_count);
  printf("    \"rx0_zero_cross_count\": %" PRIu32 ",\n", snap->rx0_zero_cross_count);
  printf("    \"rx1_zero_cross_count\": %" PRIu32 ",\n", snap->rx1_zero_cross_count);
  printf("    \"same_sign_count\": %" PRIu32 ",\n", snap->same_sign_count);
  printf("    \"agg_last_frame\": %" PRIu32 ",\n", snap->agg_last_frame);
  printf("    \"agg_capability\": \"0x%08" PRIX32 "\",\n", snap->agg_capability);
  printf("    \"agg_build_id\": \"0x%08" PRIX32 "\",\n", snap->agg_build_id);
  printf("    \"agg_limit\": %" PRIu32 ",\n", snap->agg_limit);
  printf("    \"status_flags\": \"0x%08" PRIX32 "\",\n", snap->status_flags);
  printf("    \"snapshot_elapsed_ns\": %" PRIu64 "\n", snap->elapsed_ns);
  printf("  }\n");
  printf("}\n");
}

int main(int argc, char **argv) {
  probe_options_t opts;
  p201_mmio_t *ctx = NULL;
  p201_sum8_snapshot_t snap;
  uint64_t poll_elapsed_ns = 0u;
  int open_rc = 0;
  int arm_rc = 0;
  int poll_rc = 0;
  int snap_rc = 0;
  uint32_t open_flags = P201_MMIO_OPEN_DEVMEM | P201_MMIO_OPEN_SYNC;

  if (parse_args(argc, argv, &opts) != 0) {
    usage(argv[0]);
    return 2;
  }

  ctx = p201_mmio_create();
  if (ctx == NULL) {
    print_snapshot_json(&opts, NULL, -ENOMEM, 0, 0, 0u);
    return 1;
  }

  if (!opts.arm) {
    open_flags |= P201_MMIO_OPEN_READ_ONLY;
  }

  open_rc = p201_mmio_open(ctx, opts.device, P201_TAP_BASE, P201_TAP_SPAN_BYTES, open_flags);
  if (open_rc == 0 && opts.arm) {
    arm_rc = p201_sum8_arm_aggregate(ctx, opts.frame_len, opts.agg_frames);
    if (arm_rc == 0) {
      poll_rc = p201_sum8_poll_done(ctx, opts.timeout_us, opts.poll_us, &poll_elapsed_ns);
    }
  }
  if (open_rc == 0) {
    snap_rc = p201_sum8_read_snapshot(
        ctx,
        opts.arm ? opts.frame_len : 0u,
        opts.arm ? opts.agg_frames : 0u,
        &snap);
  }

  print_snapshot_json(
      &opts,
      (open_rc == 0 && snap_rc == 0) ? &snap : NULL,
      open_rc,
      arm_rc,
      poll_rc != 0 ? poll_rc : snap_rc,
      poll_elapsed_ns);
  p201_mmio_destroy(ctx);

  if (open_rc != 0 || arm_rc != 0 || poll_rc != 0 || snap_rc != 0) {
    return 1;
  }
  if (!identity_ok(&snap)) {
    return 1;
  }
  if (opts.arm && (snap.status_flags & (P201_SUM8_STATUS_INVALID_IDENTITY |
                                        P201_SUM8_STATUS_AGG_NOT_DONE |
                                        P201_SUM8_STATUS_AGG_OVERFLOW |
                                        P201_SUM8_STATUS_SAMPLE_MISMATCH |
                                        P201_SUM8_STATUS_TARGET_MISMATCH)) != 0u) {
    return 1;
  }
  return 0;
}
