#pragma once

#include "sdr/recognizer/backend.hpp"

#include <cstdint>
#include <deque>
#include <filesystem>
#include <string>
#include <vector>

namespace sdr::recognizer {

inline constexpr std::uint64_t kMaxModelBytes = 32ULL * 1024ULL * 1024ULL;
inline constexpr std::size_t kMaxLabels = 256U;

struct ModelManifest {
  std::uint32_t schema_version{};
  std::string model_id;
  std::string runtime;
  std::string model_file;
  std::string model_sha256;
  std::uint64_t model_bytes{};
  std::string labels_file;
  std::string labels_sha256;
  std::string preprocessing;
  std::string input_name;
  std::string output_name;
  std::uint32_t samples_per_channel{};
  std::uint32_t sample_rate_hz{};
  std::uint32_t class_count{};
  std::uint16_t threads{};
};

struct ModelLoadRequest {
  std::filesystem::path package_root;
  std::string manifest_file{"model.manifest"};
};

struct ModelPackage {
  ModelManifest manifest;
  std::filesystem::path package_root;
  std::filesystem::path model_path;
  std::filesystem::path labels_path;
  std::vector<std::string> labels;
};

class ModelPackageLoader {
 public:
  virtual ~ModelPackageLoader() = default;
  virtual Status Load(const ModelLoadRequest& request, ModelPackage& output) = 0;
};

class FilesystemModelPackageLoader final : public ModelPackageLoader {
 public:
  Status Load(const ModelLoadRequest& request, ModelPackage& output) override;
};

class ReplayModelPackageLoader final : public ModelPackageLoader {
 public:
  explicit ReplayModelPackageLoader(std::vector<ModelPackage> packages);
  Status Load(const ModelLoadRequest& request, ModelPackage& output) override;

 private:
  std::deque<ModelPackage> packages_;
};

Status ValidateManifest(const ModelManifest& manifest);

}  // namespace sdr::recognizer
