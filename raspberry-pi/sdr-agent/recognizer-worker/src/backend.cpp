#include "sdr/recognizer/backend.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_set>
#include <utility>

namespace sdr::recognizer {
namespace {

bool ValidText(const std::string_view value, const std::size_t max_bytes) {
  if (value.empty() || value.size() > max_bytes) {
    return false;
  }
  return std::none_of(value.begin(), value.end(), [](const unsigned char value) {
    return value < 0x20U || value == 0x7FU;
  });
}

bool ValidConfidence(const float confidence) {
  return std::isfinite(confidence) && confidence >= 0.0F && confidence <= 1.0F;
}

bool ValidSha256(const std::string_view value) {
  return value.size() == 64U &&
         std::all_of(value.begin(), value.end(), [](const unsigned char value) {
           return (value >= '0' && value <= '9') ||
                  (value >= 'a' && value <= 'f') ||
                  (value >= 'A' && value <= 'F');
         });
}

bool IsPowerOfTwo(const std::uint32_t value) {
  return value != 0U && (value & (value - 1U)) == 0U;
}

}  // namespace

Status Status::Ok() { return {}; }

Status Status::Error(const ErrorCode code, std::string message) {
  return Status{code, std::move(message)};
}

Status ValidateDescriptor(const BackendDescriptor& descriptor) {
  if (!ValidText(descriptor.runtime, 64U) ||
      !ValidText(descriptor.runtime_version, 64U) ||
      !ValidText(descriptor.model_id, 128U)) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "backend descriptor contains invalid text");
  }
  if (!ValidSha256(descriptor.model_sha256)) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "model SHA-256 must contain 64 hexadecimal characters");
  }
  if (descriptor.samples_per_channel < 256U ||
      descriptor.samples_per_channel > kMaxSamplesPerChannel ||
      !IsPowerOfTwo(descriptor.samples_per_channel)) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "model input length must be a supported power of two");
  }
  if (descriptor.sample_rate_hz == 0U || descriptor.sample_rate_hz > 30'720'000U) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "model sample rate is outside the supported range");
  }
  if (descriptor.threads == 0U || descriptor.threads > 4U) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "backend threads must be between one and four");
  }
  return Status::Ok();
}

Status ValidateInput(const IqView& input, const BackendDescriptor& descriptor) {
  const Status descriptor_status = ValidateDescriptor(descriptor);
  if (!descriptor_status.ok()) {
    return descriptor_status;
  }
  if (input.i.size() != input.q.size() ||
      input.i.size() != descriptor.samples_per_channel) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "I and Q shapes do not match the model input");
  }
  if (input.sample_rate_hz != descriptor.sample_rate_hz) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "IQ sample rate does not match the model input");
  }
  if (input.center_hz > 6'000'000'000ULL) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "center frequency exceeds 6 GHz");
  }
  const auto finite = [](const float value) { return std::isfinite(value); };
  if (!std::all_of(input.i.begin(), input.i.end(), finite) ||
      !std::all_of(input.q.begin(), input.q.end(), finite)) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "IQ window contains a non-finite sample");
  }
  return Status::Ok();
}

Status ValidateOutput(const Classification& output) {
  if (!ValidText(output.label, 128U) || !ValidConfidence(output.confidence)) {
    return Status::Error(ErrorCode::kInvalidOutput,
                         "primary classification is invalid");
  }
  if (output.alternatives.size() > kMaxAlternatives) {
    return Status::Error(ErrorCode::kInvalidOutput,
                         "classification has too many alternatives");
  }
  std::unordered_set<std::string_view> labels;
  labels.insert(output.label);
  for (const auto& alternative : output.alternatives) {
    if (!ValidText(alternative.label, 128U) ||
        !ValidConfidence(alternative.confidence)) {
      return Status::Error(ErrorCode::kInvalidOutput,
                           "classification alternative is invalid");
    }
    if (!labels.insert(alternative.label).second) {
      return Status::Error(ErrorCode::kInvalidOutput,
                           "classification contains a duplicate label");
    }
  }
  if (output.timing.preprocess_us == std::numeric_limits<std::uint64_t>::max() ||
      output.timing.inference_us == std::numeric_limits<std::uint64_t>::max()) {
    return Status::Error(ErrorCode::kInvalidOutput,
                         "classification timing is invalid");
  }
  return Status::Ok();
}

ReplayBackend::ReplayBackend(BackendDescriptor descriptor,
                             std::vector<Classification> classifications)
    : descriptor_(std::move(descriptor)),
      classifications_(std::make_move_iterator(classifications.begin()),
                       std::make_move_iterator(classifications.end())),
      descriptor_status_(ValidateDescriptor(descriptor_)) {}

const BackendDescriptor& ReplayBackend::descriptor() const noexcept {
  return descriptor_;
}

Status ReplayBackend::Classify(const IqView& input, Classification& output) {
  if (!descriptor_status_.ok()) {
    return descriptor_status_;
  }
  const Status input_status = ValidateInput(input, descriptor_);
  if (!input_status.ok()) {
    return input_status;
  }
  if (classifications_.empty()) {
    return Status::Error(ErrorCode::kReplayExhausted,
                         "no replay classifications remain");
  }
  Classification next = std::move(classifications_.front());
  classifications_.pop_front();
  const Status output_status = ValidateOutput(next);
  if (!output_status.ok()) {
    return output_status;
  }
  output = std::move(next);
  return Status::Ok();
}

}  // namespace sdr::recognizer
