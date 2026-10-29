//! Experimental finite RX stream, owned by the same Controller CLI.
//! JSON control frames plus exact ci16 binary payload go to the campaign pipe.
use crate::sdr::{RxInputIdentity, SdrError, SdrdWire};
use crate::sweep::available_storage_bytes;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::Write;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::time::Duration;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct StreamPlan {
    pub session_generation: u64,
    pub sample_count: u64,
    pub max_bytes: u64,
    pub timeout_ms: u32,
    pub storage_directory: PathBuf,
    pub reserve_bytes: u64,
}

pub fn validate(plan: &StreamPlan) -> Result<(), SdrError> {
    if plan.session_generation == 0
        || plan.sample_count == 0
        || plan.sample_count % 4096 != 0
        || plan.sample_count > 1024 * 1024 * 1024 / 4
        || plan.max_bytes != plan.sample_count * 4
        || !(1000..=120000).contains(&plan.timeout_ms)
        || plan.reserve_bytes < plan.max_bytes + 64 * 1024 * 1024
        || !plan.storage_directory.is_absolute()
        || !plan.storage_directory.is_dir()
    {
        return Err(SdrError::new("stream_plan", "finite RX/storage limits"));
    }
    if plan
        .storage_directory
        .canonicalize()
        .map_err(|e| SdrError::new("stream_path", e.to_string()))?
        != plan.storage_directory
        || available_storage_bytes(&plan.storage_directory)
            .map_err(|e| SdrError::new("stream_space", e.to_string()))?
            < plan.reserve_bytes
    {
        return Err(SdrError::new("stream_space", "canonical path/free bytes"));
    }
    Ok(())
}

fn identity(value: &Value) -> Result<(), SdrError> {
    let input: RxInputIdentity = serde_json::from_value(value["rx_input"].clone())
        .map_err(|e| SdrError::new("stream_identity", e.to_string()))?;
    if !input.is_fixed_p201_rx1() {
        return Err(SdrError::new("stream_identity", "expected P201 RX1"));
    }
    Ok(())
}

pub fn run(
    address: SocketAddr,
    plan: &StreamPlan,
    output: &mut impl Write,
) -> Result<(), SdrError> {
    validate(plan)?;
    let mut wire = SdrdWire::connect(address, Duration::from_millis(5000))?;
    let hello: Value = wire.request("HELLO", "")?;
    if hello["server"] != "p201-sdrd"
        || hello["protocol"] != "SDRD/1"
        || hello["mode"] != "controlled"
        || hello["mutating_commands"] != true
    {
        return Err(SdrError::new("stream_server", "unexpected server"));
    }
    let cap: Value = wire.request("CAPABILITIES", "")?;
    identity(&cap)?;
    if cap["radio_control"] != true || cap["raw_iq_capture"] != true {
        return Err(SdrError::new("stream_capability", "RX unavailable/budget"));
    }
    // A separate command preserves the frozen legacy CAPABILITIES schema.
    let limits: Value = wire.request("STREAM_LIMITS", "")?;
    if limits["max_stream_bytes"].as_u64().unwrap_or(0) < plan.max_bytes
        || limits["max_timeout_ms"].as_u64().unwrap_or(0) < u64::from(plan.timeout_ms)
        || limits["max_chunk_bytes"].as_u64() != Some(256 * 1024)
    {
        return Err(SdrError::new("stream_capability", "finite stream limits"));
    }
    let generation = plan.session_generation;
    let start: Value = wire.request("START_SESSION", &generation.to_string())?;
    identity(&start)?;
    if start["generation"] != generation
        || start["restore_armed"] != true
        || start["session_state"] != "owned"
    {
        return Err(SdrError::new("stream_session", "restoration not armed"));
    }
    let profile: Value = wire.request(
        "APPLY_PROFILE",
        &format!("{generation} 2455000000 2100000 1500000 manual 50 1"),
    )?;
    identity(&profile)?;
    for (key, expected) in [
        ("generation", json!(generation)),
        ("center_hz", json!(2455000000_u64)),
        ("sample_rate_hz", json!(2100000)),
        ("rf_bandwidth_hz", json!(1500000)),
        ("gain_mode", json!("manual")),
        ("hardware_gain_db", json!(50)),
        ("enabled_channels", json!(1)),
    ] {
        // JSON number equality accepts an integer or a float hardware readback.
        if profile[key] != expected
            && profile[key]
                .as_f64()
                .zip(expected.as_f64())
                .map_or(true, |(a, b)| a != b)
        {
            return Err(SdrError::new("stream_profile", format!("readback {key}")));
        }
    }
    std::thread::sleep(Duration::from_millis(500));
    wire.stream_iq(
        generation,
        plan.sample_count,
        plan.timeout_ms,
        |header, payload| {
            serde_json::to_writer(&mut *output, header)
                .map_err(|e| SdrError::new("stream_output", e.to_string()))?;
            output
                .write_all(b"\n")
                .and_then(|_| output.write_all(payload))
                .and_then(|_| output.flush())
                .map_err(|e| SdrError::new("stream_output", e.to_string()))
        },
    )?;
    let _: Value = wire.request("QUIT", "")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader};
    use std::net::TcpListener;

    #[test]
    fn binary_newlines_sequences_bounds_and_restoration_are_checked() {
        for fault in 0..6 {
            let server = TcpListener::bind("127.0.0.1:0").unwrap();
            let address = server.local_addr().unwrap();
            let child = std::thread::spawn(move || {
                let (socket, _) = server.accept().unwrap();
                let mut peer = BufReader::new(socket);
                let mut line = String::new();
                peer.read_line(&mut line).unwrap();
                assert_eq!(line, "SDRD/1 CAPTURE_IQ_STREAM 1 7 4 16 1000\n");
                let mut reply = Vec::new();
                writeln!(reply, "{}", json!({"schema_version":1,"request_id":1,"status":"ok","event":"rx_ready","generation":if fault==1 {8}else{7},"maximum_bytes":16})).unwrap();
                writeln!(reply, "{}", json!({"schema_version":1,"request_id":1,"status":"ok","event":"rx_chunk","generation":7,"sequence":if fault==2 {1}else{0},"sample_offset":0,"bytes":if fault==3 {262148}else{16}})).unwrap();
                reply.extend_from_slice(&[b'\n'; 16]);
                if fault == 4 {
                    reply.truncate(reply.len() - 8);
                } else {
                    writeln!(reply, "{}", json!({"schema_version":1,"request_id":1,"status":"ok","event":"rx_end","generation":7,"bytes_transferred":16,"chunks":1,"restored":fault!=5,"error_code":0,"health_flags":0,"dropped_samples":0})).unwrap();
                }
                let _ = peer.get_mut().write_all(&reply);
            });
            let mut wire = SdrdWire::connect(address, Duration::from_secs(1)).unwrap();
            let mut bytes = Vec::new();
            let result = wire.stream_iq(7, 4, 1000, |_, payload| {
                bytes.extend_from_slice(payload);
                Ok(())
            });
            assert_eq!(result.is_ok(), fault == 0, "fault={fault}");
            if fault == 0 {
                assert_eq!(bytes, [b'\n'; 16]);
            }
            child.join().unwrap();
        }
    }

    #[test]
    fn rejects_zero_overflow_unaligned_and_unreserved_plans() {
        let mut plan = StreamPlan {
            session_generation: 1,
            sample_count: 4096,
            max_bytes: 16384,
            timeout_ms: 1000,
            storage_directory: std::env::temp_dir(),
            reserve_bytes: 128 * 1024 * 1024,
        };
        validate(&plan).unwrap();
        plan.sample_count = 225443840;
        plan.max_bytes = plan.sample_count * 4;
        plan.reserve_bytes = 2 * 1024 * 1024 * 1024;
        plan.timeout_ms = 120000;
        validate(&plan).unwrap();
        plan.sample_count = 1024 * 1024 * 1024 / 4 + 4096;
        plan.max_bytes = plan.sample_count * 4;
        assert!(validate(&plan).is_err());
        plan.sample_count = u64::MAX;
        assert!(validate(&plan).is_err());
        plan.sample_count = 1;
        assert!(validate(&plan).is_err());
        plan.sample_count = 0;
        assert!(validate(&plan).is_err());
        plan.sample_count = 4096;
        plan.reserve_bytes = 1;
        assert!(validate(&plan).is_err());
    }
}
