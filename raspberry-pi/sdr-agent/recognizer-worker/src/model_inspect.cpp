#include "sdr/recognizer/model_loader.hpp"

#include <iostream>

int main(int argc, char** argv) {
  if (argc != 2 && argc != 3) {
    std::cerr << "usage: sdr-model-inspect PACKAGE_ROOT [MANIFEST_FILE]\n";
    return 2;
  }
  sdr::recognizer::FilesystemModelPackageLoader loader;
  sdr::recognizer::ModelPackage package;
  const sdr::recognizer::ModelLoadRequest request{
      argv[1], argc == 3 ? argv[2] : "model.manifest"};
  const sdr::recognizer::Status status = loader.Load(request, package);
  if (!status.ok()) {
    std::cerr << "model_load_error=" << status.message << '\n';
    return 1;
  }
  std::cout << "model_load=ok\n"
            << "model_id=" << package.manifest.model_id << '\n'
            << "runtime=" << package.manifest.runtime << '\n'
            << "model_sha256=" << package.manifest.model_sha256 << '\n'
            << "model_bytes=" << package.manifest.model_bytes << '\n'
            << "samples_per_channel=" << package.manifest.samples_per_channel << '\n'
            << "sample_rate_hz=" << package.manifest.sample_rate_hz << '\n'
            << "classes=" << package.labels.size() << '\n'
            << "threads=" << package.manifest.threads << '\n';
  return 0;
}
