#include "sdr/recognizer/model_loader.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <string_view>
#include <system_error>
#include <unordered_set>
#include <utility>

namespace sdr::recognizer {
namespace {

constexpr std::size_t kMaxManifestBytes = 16U * 1024U;
constexpr std::size_t kMaxLabelsBytes = 64U * 1024U;
constexpr std::array<std::uint32_t, 64> kSha256Round{
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU,
    0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U, 0xd807aa98U, 0x12835b01U,
    0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U,
    0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
    0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U,
    0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U,
    0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
    0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U, 0xd192e819U,
    0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U, 0x1e376c08U,
    0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU,
    0x682e6ff3U, 0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U};

class Sha256 {
 public:
  void Update(const std::uint8_t* data, std::size_t size) {
    total_bytes_ += size;
    while (size > 0U) {
      const std::size_t copy = std::min(size, block_.size() - block_size_);
      std::copy_n(data, copy, block_.begin() + static_cast<std::ptrdiff_t>(block_size_));
      block_size_ += copy;
      data += copy;
      size -= copy;
      if (block_size_ == block_.size()) {
        Transform(block_.data());
        block_size_ = 0U;
      }
    }
  }

  std::string FinalHex() {
    const std::uint64_t bit_count = total_bytes_ * 8U;
    block_[block_size_++] = 0x80U;
    if (block_size_ > 56U) {
      std::fill(block_.begin() + static_cast<std::ptrdiff_t>(block_size_), block_.end(), 0U);
      Transform(block_.data());
      block_size_ = 0U;
    }
    std::fill(block_.begin() + static_cast<std::ptrdiff_t>(block_size_), block_.begin() + 56, 0U);
    for (std::size_t index = 0; index < 8U; ++index) {
      block_[63U - index] = static_cast<std::uint8_t>(bit_count >> (index * 8U));
    }
    Transform(block_.data());
    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (const std::uint32_t word : state_) {
      output << std::setw(8) << word;
    }
    return output.str();
  }

 private:
  static std::uint32_t RotateRight(const std::uint32_t value, const unsigned bits) {
    return (value >> bits) | (value << (32U - bits));
  }

  void Transform(const std::uint8_t* block) {
    std::array<std::uint32_t, 64> words{};
    for (std::size_t index = 0; index < 16U; ++index) {
      const std::size_t offset = index * 4U;
      words[index] = (static_cast<std::uint32_t>(block[offset]) << 24U) |
                     (static_cast<std::uint32_t>(block[offset + 1U]) << 16U) |
                     (static_cast<std::uint32_t>(block[offset + 2U]) << 8U) |
                     static_cast<std::uint32_t>(block[offset + 3U]);
    }
    for (std::size_t index = 16U; index < words.size(); ++index) {
      const std::uint32_t s0 = RotateRight(words[index - 15U], 7U) ^
                               RotateRight(words[index - 15U], 18U) ^
                               (words[index - 15U] >> 3U);
      const std::uint32_t s1 = RotateRight(words[index - 2U], 17U) ^
                               RotateRight(words[index - 2U], 19U) ^
                               (words[index - 2U] >> 10U);
      words[index] = words[index - 16U] + s0 + words[index - 7U] + s1;
    }
    std::uint32_t a = state_[0];
    std::uint32_t b = state_[1];
    std::uint32_t c = state_[2];
    std::uint32_t d = state_[3];
    std::uint32_t e = state_[4];
    std::uint32_t f = state_[5];
    std::uint32_t g = state_[6];
    std::uint32_t h = state_[7];
    for (std::size_t index = 0; index < words.size(); ++index) {
      const std::uint32_t sum1 = RotateRight(e, 6U) ^ RotateRight(e, 11U) ^
                                 RotateRight(e, 25U);
      const std::uint32_t choose = (e & f) ^ ((~e) & g);
      const std::uint32_t temp1 = h + sum1 + choose + kSha256Round[index] + words[index];
      const std::uint32_t sum0 = RotateRight(a, 2U) ^ RotateRight(a, 13U) ^
                                 RotateRight(a, 22U);
      const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t temp2 = sum0 + majority;
      h = g;
      g = f;
      f = e;
      e = d + temp1;
      d = c;
      c = b;
      b = a;
      a = temp1 + temp2;
    }
    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
  }

  std::array<std::uint32_t, 8> state_{0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U,
                                       0xa54ff53aU, 0x510e527fU, 0x9b05688cU,
                                       0x1f83d9abU, 0x5be0cd19U};
  std::array<std::uint8_t, 64> block_{};
  std::size_t block_size_{};
  std::uint64_t total_bytes_{};
};

bool ValidIdentifier(const std::string_view value, const std::size_t max_bytes) {
  return !value.empty() && value.size() <= max_bytes &&
         std::all_of(value.begin(), value.end(), [](const unsigned char character) {
           return std::isalnum(character) != 0 || character == '-' || character == '_' ||
                  character == '.';
         });
}

bool ValidSha256(const std::string_view value) {
  return value.size() == 64U &&
         std::all_of(value.begin(), value.end(), [](const unsigned char character) {
           return (character >= '0' && character <= '9') ||
                  (character >= 'a' && character <= 'f');
         });
}

bool IsPowerOfTwo(const std::uint32_t value) {
  return value != 0U && (value & (value - 1U)) == 0U;
}

bool SafePackageFile(const std::string_view value) {
  return ValidIdentifier(value, 128U) && value != "." && value != "..";
}

template <typename Integer>
bool ParseInteger(const std::string_view value, Integer& output) {
  const auto [end, error] =
      std::from_chars(value.data(), value.data() + value.size(), output);
  return error == std::errc{} && end == value.data() + value.size();
}

Status ReadBounded(const std::filesystem::path& path,
                   const std::size_t maximum,
                   std::string& output) {
  std::error_code error;
  const std::uintmax_t size = std::filesystem::file_size(path, error);
  if (error || size > maximum) {
    return Status::Error(ErrorCode::kIo, "file is missing or exceeds its size limit");
  }
  std::ifstream input(path, std::ios::binary);
  if (!input) {
    return Status::Error(ErrorCode::kIo, "file could not be opened");
  }
  output.assign(std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>());
  if (input.bad()) {
    return Status::Error(ErrorCode::kIo, "file read failed");
  }
  return Status::Ok();
}

Status HashFile(const std::filesystem::path& path, std::string& output) {
  std::ifstream input(path, std::ios::binary);
  if (!input) {
    return Status::Error(ErrorCode::kIo, "artifact could not be opened for hashing");
  }
  Sha256 hash;
  std::array<char, 64U * 1024U> buffer{};
  while (input) {
    input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const std::streamsize count = input.gcount();
    if (count > 0) {
      hash.Update(reinterpret_cast<const std::uint8_t*>(buffer.data()),
                  static_cast<std::size_t>(count));
    }
  }
  if (!input.eof()) {
    return Status::Error(ErrorCode::kIo, "artifact hash read failed");
  }
  output = hash.FinalHex();
  return Status::Ok();
}

Status CanonicalRegularFile(const std::filesystem::path& root,
                            const std::string& name,
                            std::filesystem::path& output) {
  if (!SafePackageFile(name)) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "package file name must be one safe path component");
  }
  const std::filesystem::path candidate = root / name;
  std::error_code error;
  if (std::filesystem::is_symlink(std::filesystem::symlink_status(candidate, error)) || error) {
    return Status::Error(ErrorCode::kInvalidInput, "package files must not be symlinks");
  }
  output = std::filesystem::canonical(candidate, error);
  if (error || output.parent_path() != root ||
      !std::filesystem::is_regular_file(output, error) || error) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "package file must be a regular file inside the package root");
  }
  return Status::Ok();
}

Status ParseManifest(const std::string& text, ModelManifest& manifest) {
  std::map<std::string, std::string> fields;
  std::istringstream input(text);
  std::string line;
  while (std::getline(input, line)) {
    if (line.empty() || line.front() == '#') {
      continue;
    }
    const std::size_t separator = line.find('=');
    if (separator == std::string::npos || separator == 0U || separator + 1U >= line.size()) {
      return Status::Error(ErrorCode::kInvalidInput, "manifest contains an invalid line");
    }
    std::string key = line.substr(0U, separator);
    std::string value = line.substr(separator + 1U);
    if (!fields.emplace(std::move(key), std::move(value)).second) {
      return Status::Error(ErrorCode::kInvalidInput, "manifest contains a duplicate key");
    }
  }
  const std::array<std::string_view, 15> required{
      "schema_version",       "model_id",           "runtime",
      "model_file",          "model_sha256",       "model_bytes",
      "labels_file",         "labels_sha256",      "preprocessing",
      "input_name",          "output_name",        "samples_per_channel",
      "sample_rate_hz",      "class_count",        "threads"};
  if (fields.size() != required.size() ||
      std::any_of(required.begin(), required.end(), [&](const std::string_view key) {
        return !fields.contains(std::string(key));
      })) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "manifest keys do not match schema version one");
  }
  if (!ParseInteger(fields["schema_version"], manifest.schema_version) ||
      !ParseInteger(fields["model_bytes"], manifest.model_bytes) ||
      !ParseInteger(fields["samples_per_channel"], manifest.samples_per_channel) ||
      !ParseInteger(fields["sample_rate_hz"], manifest.sample_rate_hz) ||
      !ParseInteger(fields["class_count"], manifest.class_count) ||
      !ParseInteger(fields["threads"], manifest.threads)) {
    return Status::Error(ErrorCode::kInvalidInput, "manifest integer is invalid");
  }
  manifest.model_id = fields["model_id"];
  manifest.runtime = fields["runtime"];
  manifest.model_file = fields["model_file"];
  manifest.model_sha256 = fields["model_sha256"];
  manifest.labels_file = fields["labels_file"];
  manifest.labels_sha256 = fields["labels_sha256"];
  manifest.preprocessing = fields["preprocessing"];
  manifest.input_name = fields["input_name"];
  manifest.output_name = fields["output_name"];
  return ValidateManifest(manifest);
}

Status ParseLabels(const std::string& text,
                   const std::uint32_t expected,
                   std::vector<std::string>& labels) {
  std::istringstream input(text);
  std::string label;
  std::unordered_set<std::string> unique;
  while (std::getline(input, label)) {
    if (!ValidIdentifier(label, 128U) || !unique.insert(label).second) {
      return Status::Error(ErrorCode::kInvalidInput,
                           "labels must be unique safe identifiers");
    }
    labels.push_back(label);
  }
  if (labels.size() != expected || labels.empty() || labels.size() > kMaxLabels) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "label count does not match the manifest");
  }
  return Status::Ok();
}

}  // namespace

Status ValidateManifest(const ModelManifest& manifest) {
  if (manifest.schema_version != 1U || !ValidIdentifier(manifest.model_id, 128U) ||
      manifest.runtime != "onnxruntime" || !SafePackageFile(manifest.model_file) ||
      manifest.model_file.size() < 6U ||
      manifest.model_file.substr(manifest.model_file.size() - 5U) != ".onnx" ||
      !ValidSha256(manifest.model_sha256) || manifest.model_bytes == 0U ||
      manifest.model_bytes > kMaxModelBytes || !SafePackageFile(manifest.labels_file) ||
      !ValidSha256(manifest.labels_sha256) ||
      manifest.preprocessing != "planar_f32_unit_rms_v1" ||
      !ValidIdentifier(manifest.input_name, 128U) ||
      !ValidIdentifier(manifest.output_name, 128U) ||
      manifest.samples_per_channel < 256U ||
      manifest.samples_per_channel > kMaxSamplesPerChannel ||
      !IsPowerOfTwo(manifest.samples_per_channel) || manifest.sample_rate_hz == 0U ||
      manifest.sample_rate_hz > 30'720'000U || manifest.class_count == 0U ||
      manifest.class_count > kMaxLabels || manifest.threads == 0U || manifest.threads > 4U) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "model manifest violates the recognizer contract");
  }
  return Status::Ok();
}

Status FilesystemModelPackageLoader::Load(const ModelLoadRequest& request,
                                          ModelPackage& output) {
  std::error_code error;
  const std::filesystem::path root = std::filesystem::canonical(request.package_root, error);
  if (error || !std::filesystem::is_directory(root, error) || error) {
    return Status::Error(ErrorCode::kInvalidInput, "package root is not a directory");
  }
  std::filesystem::path manifest_path;
  Status status = CanonicalRegularFile(root, request.manifest_file, manifest_path);
  if (!status.ok()) {
    return status;
  }
  std::string manifest_text;
  status = ReadBounded(manifest_path, kMaxManifestBytes, manifest_text);
  if (!status.ok()) {
    return status;
  }
  ModelPackage next;
  status = ParseManifest(manifest_text, next.manifest);
  if (!status.ok()) {
    return status;
  }
  next.package_root = root;
  status = CanonicalRegularFile(root, next.manifest.model_file, next.model_path);
  if (!status.ok()) {
    return status;
  }
  status = CanonicalRegularFile(root, next.manifest.labels_file, next.labels_path);
  if (!status.ok()) {
    return status;
  }
  const std::uintmax_t model_size = std::filesystem::file_size(next.model_path, error);
  if (error || model_size != next.manifest.model_bytes || model_size > kMaxModelBytes) {
    return Status::Error(ErrorCode::kInvalidInput,
                         "model size does not match the bounded manifest");
  }
  std::string actual_hash;
  status = HashFile(next.model_path, actual_hash);
  if (!status.ok()) {
    return status;
  }
  if (actual_hash != next.manifest.model_sha256) {
    return Status::Error(ErrorCode::kHashMismatch, "model SHA-256 does not match");
  }
  std::string labels_text;
  status = ReadBounded(next.labels_path, kMaxLabelsBytes, labels_text);
  if (!status.ok()) {
    return status;
  }
  status = HashFile(next.labels_path, actual_hash);
  if (!status.ok()) {
    return status;
  }
  if (actual_hash != next.manifest.labels_sha256) {
    return Status::Error(ErrorCode::kHashMismatch, "labels SHA-256 does not match");
  }
  status = ParseLabels(labels_text, next.manifest.class_count, next.labels);
  if (!status.ok()) {
    return status;
  }
  output = std::move(next);
  return Status::Ok();
}

ReplayModelPackageLoader::ReplayModelPackageLoader(std::vector<ModelPackage> packages)
    : packages_(std::make_move_iterator(packages.begin()),
                std::make_move_iterator(packages.end())) {}

Status ReplayModelPackageLoader::Load(const ModelLoadRequest& request,
                                      ModelPackage& output) {
  if (request.package_root.empty() || request.manifest_file.empty()) {
    return Status::Error(ErrorCode::kInvalidInput, "replay load request is invalid");
  }
  if (packages_.empty()) {
    return Status::Error(ErrorCode::kReplayExhausted, "no replay model packages remain");
  }
  output = std::move(packages_.front());
  packages_.pop_front();
  return Status::Ok();
}

}  // namespace sdr::recognizer
