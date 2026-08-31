# Raspberry Pi 4B client

The Raspberry Pi uses its Ethernet port as a direct P201 Pro link and Wi-Fi for
management:

```text
wlan0: management network
eth0:  192.168.1.20/24, no default gateway
SDR:   192.168.1.10
IIOD:  ip:192.168.1.10
```

Contents:

- `p201pro-rust/`: Rust/libiio probe and capture benchmark.
- `config/`: network/device configuration examples and read-only checks.
- `docs/`: design research and measured results.

No Python runtime is required for the Rust client. The target only needs the
libiio v0.x shared library.
