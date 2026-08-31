#!/usr/bin/env bash
set -u

SDR_IP="${SDR_IP:-192.168.1.10}"
SDR_URI="${SDR_URI:-ip:${SDR_IP}}"
SDR_INTERFACE="${SDR_INTERFACE:-eth0}"

echo "=== Raspberry Pi ==="
hostname
uname -a

echo "=== Direct Ethernet ==="
ip -br addr show "${SDR_INTERFACE}" || true
ip route || true

echo "=== libiio tools ==="
if command -v iio_info >/dev/null 2>&1; then
  iio_info --version || true
else
  echo "iio_info=missing"
fi

echo "=== P201 Pro ping ${SDR_IP} ==="
ping -c 3 -W 1 "${SDR_IP}" || true

echo "=== P201 Pro IIO context ${SDR_URI} ==="
if command -v iio_info >/dev/null 2>&1; then
  timeout 15 iio_info -u "${SDR_URI}" | sed -n '1,120p' || true
else
  echo "skip: iio_info missing"
fi
