#pragma once

#include <cstdint>

namespace p201_sdr {

constexpr std::uint32_t kTapBase = 0x43C00000u;
constexpr std::uint32_t kSummaryVersionSum5 = 0x53554D35u;
constexpr std::uint32_t kSummaryVersionSum6 = 0x53554D36u;
constexpr std::uint32_t kSummaryVersionSum7 = 0x53554D37u;
constexpr std::uint32_t kSummaryVersionSum8 = 0x53554D38u;
constexpr std::uint32_t kMaxSum5CorrectedFrameLen = 256u;
constexpr std::uint32_t kMaxSum6CorrectedFrameLen = 65535u;
constexpr std::uint32_t kMaxSum7CorrectedFrameLen = 65535u;
constexpr std::uint32_t kMaxSum8AggregateFrames = 65535u;
constexpr std::uint32_t kSum6AbiVersion = 0x00010000u;
constexpr std::uint32_t kSum6Capability = 0x000000FFu;
constexpr std::uint32_t kSum6BuildId = 0x56360001u;
constexpr std::uint32_t kSum7AbiVersion = 0x00010001u;
constexpr std::uint32_t kSum7Capability = 0x000001FFu;
constexpr std::uint32_t kSum7BuildId = 0x56370001u;
constexpr std::uint32_t kQualityVersionQua7 = 0x51554137u;
constexpr std::uint32_t kQualityCapabilityQua7 = 0x0000000Fu;
constexpr std::uint32_t kQualityBuildIdQua7 = 0x51370001u;
constexpr std::uint32_t kSum8AbiVersion = 0x00010002u;
constexpr std::uint32_t kSum8Capability = 0x000003FFu;
constexpr std::uint32_t kSum8BuildId = 0x56380001u;
constexpr std::uint32_t kQualityVersionQua8 = 0x51554138u;
constexpr std::uint32_t kQualityCapabilityQua8 = 0x0000000Fu;
constexpr std::uint32_t kQualityBuildIdQua8 = 0x51380001u;
constexpr std::uint32_t kAggregateVersionAgg8 = 0x41474738u;
constexpr std::uint32_t kAggregateCapabilityAgg8 = 0x0000001Fu;
constexpr std::uint32_t kAggregateBuildIdAgg8 = 0x41380001u;

enum class Sum5Offset : std::uint32_t {
  SummaryVersion = 0x40,
  SummaryFlags = 0x44,
  FrameCounter = 0x48,
  SampleCount = 0x4C,
  SummarySumPowerLo = 0x50,
  SummarySumPowerHi = 0x54,
  Rx0PeakPower = 0x58,
  Rx0PeakIndex = 0x5C,
  SnapshotCount = 0x60,
  DualSamples = 0x70,
  Rx0PowerLo = 0x74,
  Rx0PowerHi = 0x78,
  Rx1PowerLo = 0x7C,
  Rx1PowerHi = 0x80,
  CrossReLo = 0x84,
  CrossReHi = 0x88,
  CrossImLo = 0x8C,
  CrossImHi = 0x90,
  Rx1PeakPower = 0x94,
  Rx1PeakIndex = 0x98,
  I0SumLo = 0x9C,
  I0SumHi = 0xA0,
  Q0SumLo = 0xA4,
  Q0SumHi = 0xA8,
  I1SumLo = 0xAC,
  I1SumHi = 0xB0,
  Q1SumLo = 0xB4,
  Q1SumHi = 0xB8,
  Rx0CorrPowerNumLo = 0xBC,
  Rx0CorrPowerNumMid = 0xC0,
  Rx0CorrPowerNumHi = 0xC4,
  Rx1CorrPowerNumLo = 0xC8,
  Rx1CorrPowerNumMid = 0xCC,
  Rx1CorrPowerNumHi = 0xD0,
  CorrCrossReNumLo = 0xD4,
  CorrCrossReNumMid = 0xD8,
  CorrCrossReNumHi = 0xDC,
  CorrCrossImNumLo = 0xE0,
  CorrCrossImNumMid = 0xE4,
  CorrCrossImNumHi = 0xE8,
  AbiVersion = 0xEC,
  CapabilityBitmap = 0xF0,
  LimitFlags = 0xF4,
  MaxCorrFrameLen = 0xF8,
  BuildId = 0xFC,
};

enum class Sum6Capability : std::uint32_t {
  DualRx = 1u << 0,
  RawPower = 1u << 1,
  Peaks = 1u << 2,
  Cross = 1u << 3,
  IqSums = 1u << 4,
  CorrectedNumerators = 1u << 5,
  SnapshotDisabled = 1u << 6,
  WideCorrectedPath = 1u << 7,
  QualityPage = 1u << 8,
  AggregatePage = 1u << 9,
};

enum class Sum6LimitFlag : std::uint32_t {
  FrameLenLimited = 1u << 0,
  ArithmeticOverflow = 1u << 1,
  CorrectedValid = 1u << 2,
  SnapshotDisabled = 1u << 3,
};

enum class Sum7QualityOffset : std::uint32_t {
  QualityVersion = 0x100,
  QualityFlags = 0x104,
  QualityFrame = 0x108,
  QualitySamples = 0x10C,
  Rx0ClipCounts = 0x110,
  Rx1ClipCounts = 0x114,
  Rx0ZeroCrossCounts = 0x118,
  Rx1ZeroCrossCounts = 0x11C,
  SignSameCounts = 0x120,
  QuadratureSameSignCounts = 0x124,
  ReservedRx0AbsISum = 0x128,
  ReservedRx0AbsQSum = 0x12C,
  ReservedRx1AbsISum = 0x130,
  ReservedRx1AbsQSum = 0x134,
  QualityCapability = 0x138,
  QualityBuildId = 0x13C,
};

enum class Sum7QualityCapability : std::uint32_t {
  ClipCounts = 1u << 0,
  ZeroCrossCounts = 1u << 1,
  SignSameCounts = 1u << 2,
  ReservedAbsSumRegsReadZero = 1u << 3,
};

enum class Sum8AggregateOffset : std::uint32_t {
  AggregateVersion = 0x180,
  AggregateControl = 0x184,
  AggregateTarget = 0x188,
  AggregateFrames = 0x18C,
  AggregateSamples = 0x190,
  Rx0CorrPowerNumLo = 0x194,
  Rx0CorrPowerNumMid = 0x198,
  Rx0CorrPowerNumHi = 0x19C,
  Rx1CorrPowerNumLo = 0x1A0,
  Rx1CorrPowerNumMid = 0x1A4,
  Rx1CorrPowerNumHi = 0x1A8,
  CorrCrossReNumLo = 0x1AC,
  CorrCrossReNumMid = 0x1B0,
  CorrCrossReNumHi = 0x1B4,
  CorrCrossImNumLo = 0x1B8,
  CorrCrossImNumMid = 0x1BC,
  CorrCrossImNumHi = 0x1C0,
  Rx0RawPowerLo = 0x1C4,
  Rx0RawPowerMid = 0x1C8,
  Rx0RawPowerHi = 0x1CC,
  Rx1RawPowerLo = 0x1D0,
  Rx1RawPowerMid = 0x1D4,
  Rx1RawPowerHi = 0x1D8,
  Rx0ClipCount = 0x1DC,
  Rx1ClipCount = 0x1E0,
  Rx0ZeroCrossCount = 0x1E4,
  Rx1ZeroCrossCount = 0x1E8,
  SameSignCount = 0x1EC,
  LastFrame = 0x1F0,
  AggregateCapability = 0x1F4,
  AggregateBuildId = 0x1F8,
  AggregateLimit = 0x1FC,
};

enum class Sum8AggregateControl : std::uint32_t {
  Enable = 1u << 0,
  ClearArm = 1u << 1,
  Done = 1u << 4,
  Overflow = 1u << 5,
};

struct Sum5Summary {
  std::uint32_t frame_counter;
  std::uint32_t sample_count;
  std::uint64_t rx0_power_raw;
  std::uint64_t rx1_power_raw;
  std::int64_t cross_re_raw;
  std::int64_t cross_im_raw;
  std::uint32_t rx0_peak_power;
  std::uint32_t rx0_peak_index;
  std::uint32_t rx1_peak_power;
  std::uint32_t rx1_peak_index;
  std::int64_t i0_sum;
  std::int64_t q0_sum;
  std::int64_t i1_sum;
  std::int64_t q1_sum;
  std::int64_t rx0_corr_power_num;
  std::int64_t rx1_corr_power_num;
  std::int64_t corr_cross_re_num;
  std::int64_t corr_cross_im_num;
};

struct U96Words {
  std::uint32_t lo;
  std::uint32_t mid;
  std::uint32_t hi;
};

struct Sum8AggregateSummary {
  std::uint32_t frame_count;
  std::uint32_t sample_count;
  std::uint32_t target_frames;
  std::uint32_t control;
  std::uint32_t last_frame;
  U96Words rx0_corr_power_num;
  U96Words rx1_corr_power_num;
  U96Words corr_cross_re_num;
  U96Words corr_cross_im_num;
  U96Words rx0_raw_power;
  U96Words rx1_raw_power;
  std::uint32_t rx0_clip_count;
  std::uint32_t rx1_clip_count;
  std::uint32_t rx0_zero_cross_count;
  std::uint32_t rx1_zero_cross_count;
  std::uint32_t same_sign_count;
};

inline std::uint64_t unsigned48(std::uint32_t lo, std::uint32_t hi) {
  return (static_cast<std::uint64_t>(hi & 0xFFFFu) << 32) | lo;
}

inline std::int64_t signed48(std::uint32_t lo, std::uint32_t hi) {
  const std::uint64_t value = unsigned48(lo, hi);
  return (value & (1ull << 47)) ? static_cast<std::int64_t>(value | 0xFFFF000000000000ull) : static_cast<std::int64_t>(value);
}

inline std::int64_t signed64_from_words(std::uint32_t lo, std::uint32_t mid) {
  const std::uint64_t value = (static_cast<std::uint64_t>(mid) << 32) | lo;
  return static_cast<std::int64_t>(value);
}

}  // namespace p201_sdr
