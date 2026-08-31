#define _POSIX_C_SOURCE 200809L

#include "sdrd.h"

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static void must_mkdir(const char *path) {
  assert(mkdir(path, 0700) == 0);
}

static void write_text(const char *path, const char *text) {
  FILE *stream = fopen(path, "w");
  assert(stream != NULL);
  assert(fputs(text, stream) >= 0);
  assert(fclose(stream) == 0);
}

static void write_u32(int fd, off_t offset, uint32_t value) {
  assert(pwrite(fd, &value, sizeof(value), offset) == (ssize_t)sizeof(value));
}

static void create_iio_tree(const char *root) {
  char path[512];
  (void)snprintf(path, sizeof(path), "%s/iio:device0", root);
  must_mkdir(path);
  (void)snprintf(path, sizeof(path), "%s/iio:device0/name", root);
  write_text(path, "ad9361-phy\n");
  (void)snprintf(path, sizeof(path), "%s/iio:device1", root);
  must_mkdir(path);
  (void)snprintf(path, sizeof(path), "%s/iio:device1/name", root);
  write_text(path, "cf-ad9361-lpc\n");
}

static void test_shadow_config_and_protocol(const char *root) {
  char config_path[512];
  char iio_root[512];
  char config_text[2048];
  char response[SDRD_MAX_RESPONSE];
  char error[256];
  sdrd_config_t config;
  (void)snprintf(iio_root, sizeof(iio_root), "%s/iio", root);
  must_mkdir(iio_root);
  create_iio_tree(iio_root);
  (void)snprintf(config_path, sizeof(config_path), "%s/sdrd.conf", root);
  (void)snprintf(
      config_text,
      sizeof(config_text),
      "mode=shadow\nlisten_address=127.0.0.1\nlisten_port=43110\nclient_timeout_ms=5000\niio_sysfs_root=%s\nfpga_backend=disabled\nfpga_device=/dev/mem\nfpga_base=0x43c00000\nfpga_span=0x10000\nrequire_iomem_region=true\nallow_devmem=false\n",
      iio_root);
  write_text(config_path, config_text);
  assert(sdrd_config_load(config_path, &config, error, sizeof(error)) == 0);
  assert(config.fpga_backend == SDRD_FPGA_DISABLED);
  assert(sdrd_format_response(&config, "SDRD/1 HELLO 41", response, sizeof(response)) == 0);
  assert(strstr(response, "\"request_id\":41") != NULL);
  assert(strstr(response, "\"mutating_commands\":false") != NULL);
  assert(sdrd_format_response(&config, "SDRD/1 HEALTH 42", response, sizeof(response)) == 0);
  assert(strstr(response, "\"healthy\":true") != NULL);
  assert(strstr(response, "\"iio_phy_visible\":true") != NULL);
  assert(sdrd_format_response(&config, "SDRD/1 APPLY_PROFILE 43", response, sizeof(response)) == 0);
  assert(strstr(response, "\"error\":\"read_only_shadow\"") != NULL);
}

static void test_fake_uio_identity(const char *root) {
  char register_path[512];
  char iio_root[512];
  char response[SDRD_MAX_RESPONSE];
  char error[256];
  sdrd_config_t config;
  int fd;
  (void)snprintf(iio_root, sizeof(iio_root), "%s/iio-fpga", root);
  must_mkdir(iio_root);
  create_iio_tree(iio_root);
  (void)snprintf(register_path, sizeof(register_path), "%s/registers.bin", root);
  fd = open(register_path, O_CREAT | O_RDWR | O_TRUNC, 0600);
  assert(fd >= 0);
  assert(ftruncate(fd, 0x10000) == 0);
  write_u32(fd, 0x040, 0x53554D38u);
  write_u32(fd, 0x0EC, 0x00010002u);
  write_u32(fd, 0x0F0, 0x000003FFu);
  write_u32(fd, 0x0FC, 0x56380001u);
  write_u32(fd, 0x180, 0x41474738u);
  write_u32(fd, 0x1F4, 0x0000001Fu);
  write_u32(fd, 0x1F8, 0x41380001u);
  assert(close(fd) == 0);
  sdrd_config_defaults(&config);
  assert(snprintf(config.iio_sysfs_root, sizeof(config.iio_sysfs_root), "%s", iio_root) > 0);
  assert(snprintf(config.fpga_device, sizeof(config.fpga_device), "%s", register_path) > 0);
  config.fpga_backend = SDRD_FPGA_UIO;
  assert(sdrd_config_validate(&config, error, sizeof(error)) == 0);
  assert(sdrd_format_response(&config, "SDRD/1 CAPABILITIES 9", response, sizeof(response)) == 0);
  assert(strstr(response, "\"fpga_identity_valid\":true") != NULL);
  assert(strstr(response, "\"fpga_aggregate\":true") != NULL);
}

static void test_devmem_requires_explicit_gate(void) {
  sdrd_config_t config;
  char error[256];
  sdrd_config_defaults(&config);
  config.fpga_backend = SDRD_FPGA_DEVMEM;
  assert(sdrd_config_validate(&config, error, sizeof(error)) == -EACCES);
  assert(strstr(error, "allow_devmem=true") != NULL);
}

static void remove_test_tree(const char *root) {
  char path[512];
  (void)snprintf(path, sizeof(path), "%s/iio/iio:device0/name", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio/iio:device1/name", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio/iio:device0", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio/iio:device1", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga/iio:device0/name", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga/iio:device1/name", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga/iio:device0", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga/iio:device1", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/iio-fpga", root);
  assert(rmdir(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/sdrd.conf", root);
  assert(unlink(path) == 0);
  (void)snprintf(path, sizeof(path), "%s/registers.bin", root);
  assert(unlink(path) == 0);
  assert(rmdir(root) == 0);
}

int main(void) {
  char root[] = "/tmp/sdrd-test-XXXXXX";
  assert(mkdtemp(root) != NULL);
  test_shadow_config_and_protocol(root);
  test_fake_uio_identity(root);
  test_devmem_requires_explicit_gate();
  remove_test_tree(root);
  puts("sdrd_tests=pass");
  return 0;
}
