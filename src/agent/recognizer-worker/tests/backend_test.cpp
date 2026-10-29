#include "sdr/recognizer/backend.hpp"

#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

using sdr::recognizer::Alternative;
using sdr::recognizer::BackendDescriptor;
using sdr::recognizer::Classification;
using sdr::recognizer::ErrorCode;
using sdr::recognizer::IqView;
using sdr::recognizer::ReplayBackend;
using sdr::recognizer::Timing;

BackendDescriptor Descriptor() {
  return BackendDescriptor{
      .runtime = "replay",
      .runtime_version = "1",
      .model_id = "amr-test",
      .model_sha256 = std::string(64U, '0'),
      .samples_per_channel = 2'048,
      .sample_rate_hz = 1'000'000,
      .threads = 1,
  };
}

Classification Output() {
  return Classification{
      .label = "GFSK",
      .confidence = 0.91F,
      .alternatives = {Alternative{.label = "FSK", .confidence = 0.07F}},
      .timing = Timing{.preprocess_us = 100, .inference_us = 2'000},
  };
}

IqView Input(const std::vector<float>& i, const std::vector<float>& q) {
  return IqView{
      .i = i,
      .q = q,
      .sample_rate_hz = 1'000'000,
      .center_hz = 433'920'000,
  };
}

void AcceptsValidReplay() {
  std::vector<float> i(2'048, 0.5F);
  std::vector<float> q(2'048, -0.5F);
  ReplayBackend backend(Descriptor(), {Output()});
  Classification observed;
  assert(backend.Classify(Input(i, q), observed).ok());
  assert(observed.label == "GFSK");
  assert(observed.confidence == 0.91F);
  assert(backend.Classify(Input(i, q), observed).code == ErrorCode::kReplayExhausted);
}

void RejectsWrongShape() {
  std::vector<float> i(1'024, 0.5F);
  std::vector<float> q(1'024, -0.5F);
  ReplayBackend backend(Descriptor(), {Output()});
  Classification observed;
  assert(backend.Classify(Input(i, q), observed).code == ErrorCode::kInvalidInput);
}

void RejectsNonFiniteIq() {
  std::vector<float> i(2'048, 0.5F);
  std::vector<float> q(2'048, -0.5F);
  i[17] = std::numeric_limits<float>::quiet_NaN();
  ReplayBackend backend(Descriptor(), {Output()});
  Classification observed;
  assert(backend.Classify(Input(i, q), observed).code == ErrorCode::kInvalidInput);
}

void RejectsDuplicateLabels() {
  std::vector<float> i(2'048, 0.5F);
  std::vector<float> q(2'048, -0.5F);
  Classification invalid = Output();
  invalid.alternatives[0].label = invalid.label;
  ReplayBackend backend(Descriptor(), {invalid});
  Classification observed;
  assert(backend.Classify(Input(i, q), observed).code == ErrorCode::kInvalidOutput);
}

}  // namespace

int main() {
  AcceptsValidReplay();
  RejectsWrongShape();
  RejectsNonFiniteIq();
  RejectsDuplicateLabels();
  std::cout << "backend tests passed\n";
  return 0;
}
