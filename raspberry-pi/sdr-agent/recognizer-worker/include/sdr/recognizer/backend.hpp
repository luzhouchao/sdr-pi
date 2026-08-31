#pragma once

#include <cstdint>
#include <deque>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace sdr::recognizer {

inline constexpr std::size_t kMaxAlternatives = 8;
inline constexpr std::size_t kMaxSamplesPerChannel = 16'384;

enum class ErrorCode {
  kOk,
  kInvalidInput,
  kInvalidOutput,
  kUnavailable,
  kReplayExhausted,
};

struct Status {
  ErrorCode code{ErrorCode::kOk};
  std::string message;

  [[nodiscard]] bool ok() const noexcept { return code == ErrorCode::kOk; }

  static Status Ok();
  static Status Error(ErrorCode code, std::string message);
};

struct IqView {
  std::span<const float> i;
  std::span<const float> q;
  std::uint32_t sample_rate_hz{};
  std::uint64_t center_hz{};
};

struct Alternative {
  std::string label;
  float confidence{};
};

struct Timing {
  std::uint64_t preprocess_us{};
  std::uint64_t inference_us{};
};

struct Classification {
  std::string label;
  float confidence{};
  std::vector<Alternative> alternatives;
  Timing timing;
};

struct BackendDescriptor {
  std::string runtime;
  std::string runtime_version;
  std::string model_id;
  std::string model_sha256;
  std::uint32_t samples_per_channel{};
  std::uint32_t sample_rate_hz{};
  std::uint16_t threads{};
};

class Backend {
 public:
  virtual ~Backend() = default;

  [[nodiscard]] virtual const BackendDescriptor& descriptor() const noexcept = 0;
  virtual Status Classify(const IqView& input, Classification& output) = 0;
};

Status ValidateDescriptor(const BackendDescriptor& descriptor);
Status ValidateInput(const IqView& input, const BackendDescriptor& descriptor);
Status ValidateOutput(const Classification& output);

class ReplayBackend final : public Backend {
 public:
  ReplayBackend(BackendDescriptor descriptor,
                std::vector<Classification> classifications);

  [[nodiscard]] const BackendDescriptor& descriptor() const noexcept override;
  Status Classify(const IqView& input, Classification& output) override;

 private:
  BackendDescriptor descriptor_;
  std::deque<Classification> classifications_;
  Status descriptor_status_;
};

}  // namespace sdr::recognizer
