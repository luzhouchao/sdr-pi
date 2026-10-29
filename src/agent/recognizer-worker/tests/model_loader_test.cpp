#include "sdr/recognizer/model_loader.hpp"

#include <cassert>
#include <filesystem>
#include <fstream>
#include <string>
#include <unistd.h>

namespace {

using sdr::recognizer::ErrorCode;
using sdr::recognizer::FilesystemModelPackageLoader;
using sdr::recognizer::ModelLoadRequest;
using sdr::recognizer::ModelPackage;
using sdr::recognizer::ReplayModelPackageLoader;

constexpr const char* kModelHash =
    "ccdbfb9993be88c536b0b7cd2abe60eda83c7ce1ad530c6a2ada81510ff1548c";
constexpr const char* kLabelsHash =
    "0be8a4c34e260bb370c3dad20de07608a79a93e34b7963fd4edd6a7c728618ef";

void Write(const std::filesystem::path& path, const std::string& text) {
  std::ofstream output(path, std::ios::binary);
  assert(output);
  output << text;
  assert(output.good());
}

std::string Manifest(const std::string& model_file = "model.onnx",
                     const std::string& model_hash = kModelHash) {
  return "schema_version=1\n"
         "model_id=amr-tiny-v1\n"
         "runtime=onnxruntime\n"
         "model_file=" +
         model_file + "\nmodel_sha256=" + model_hash +
         "\nmodel_bytes=10\n"
         "labels_file=labels.txt\n"
         "labels_sha256=" +
         std::string(kLabelsHash) +
         "\npreprocessing=planar_f32_unit_rms_v1\n"
         "input_name=iq\n"
         "output_name=logits\n"
         "samples_per_channel=1024\n"
         "sample_rate_hz=2100000\n"
         "class_count=2\n"
         "threads=1\n";
}

}  // namespace

int main() {
  const std::filesystem::path root =
      std::filesystem::temp_directory_path() /
      ("sdr-model-loader-test-" + std::to_string(static_cast<long long>(getpid())));
  assert(std::filesystem::create_directory(root));
  Write(root / "model.onnx", "tiny-model");
  Write(root / "labels.txt", "BPSK\nQPSK\n");
  Write(root / "model.manifest", Manifest());

  FilesystemModelPackageLoader loader;
  ModelPackage package;
  auto status = loader.Load(ModelLoadRequest{root, "model.manifest"}, package);
  assert(status.ok());
  assert(package.manifest.model_id == "amr-tiny-v1");
  assert(package.labels.size() == 2U);
  assert(package.labels[1] == "QPSK");
  assert(package.model_path.parent_path() == std::filesystem::canonical(root));

  Write(root / "model.manifest", Manifest("model.onnx", std::string(64U, '0')));
  status = loader.Load(ModelLoadRequest{root, "model.manifest"}, package);
  assert(status.code == ErrorCode::kHashMismatch);

  Write(root / "model.manifest", Manifest("../outside.onnx"));
  status = loader.Load(ModelLoadRequest{root, "model.manifest"}, package);
  assert(status.code == ErrorCode::kInvalidInput);

  ReplayModelPackageLoader replay({package});
  status = replay.Load(ModelLoadRequest{root, "model.manifest"}, package);
  assert(status.ok());
  status = replay.Load(ModelLoadRequest{root, "model.manifest"}, package);
  assert(status.code == ErrorCode::kReplayExhausted);

  assert(std::filesystem::remove_all(root) == 4U);
  return 0;
}
