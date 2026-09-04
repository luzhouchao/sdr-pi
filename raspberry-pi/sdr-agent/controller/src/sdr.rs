use crate::protocol::HealthSummary;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::error::Error;
use std::fmt;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

const SDRD_SCHEMA_VERSION: u16 = 1;
const SDRD_MAX_RESPONSE_BYTES: usize = 384 * 1024;
pub const P201_RX_INPUT_IDENTITY_VERSION: u16 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RxInputIdentity {
    pub identity_version: u16,
    pub verified: bool,
    pub front_panel_port: String,
    pub logical_channel: String,
    pub phy_channel: String,
    pub scan_i_channel: String,
    pub scan_q_channel: String,
    pub rf_port_select: String,
    pub source: String,
}

impl RxInputIdentity {
    pub fn is_fixed_p201_rx1(&self) -> bool {
        self.identity_version == P201_RX_INPUT_IDENTITY_VERSION
            && self.verified
            && self.front_panel_port == "RX1"
            && self.logical_channel == "RX0"
            && self.phy_channel == "voltage0"
            && self.scan_i_channel == "voltage0"
            && self.scan_q_channel == "voltage1"
            && self.rf_port_select == "A_BALANCED"
            && self.source == "iio_channel_attr"
    }

    #[cfg(test)]
    pub(crate) fn fixed_p201_rx1_fixture() -> Self {
        Self {
            identity_version: P201_RX_INPUT_IDENTITY_VERSION,
            verified: true,
            front_panel_port: "RX1".to_owned(),
            logical_channel: "RX0".to_owned(),
            phy_channel: "voltage0".to_owned(),
            scan_i_channel: "voltage0".to_owned(),
            scan_q_channel: "voltage1".to_owned(),
            rf_port_select: "A_BALANCED".to_owned(),
            source: "iio_channel_attr".to_owned(),
        }
    }
}

pub trait SdrEngine {
    fn observe(&mut self) -> Result<SdrSnapshot, SdrError>;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SdrSnapshot {
    pub online: bool,
    pub healthy: bool,
    pub health_flags: u32,
    pub iio_visible: bool,
    pub can_retune: bool,
    pub can_capture_iq: bool,
    pub rx_input: Option<RxInputIdentity>,
}

impl SdrSnapshot {
    pub fn planner_health(
        &self,
        recognizer_available: bool,
        dropped_observations: u64,
    ) -> HealthSummary {
        HealthSummary {
            sdr_online: self.online && self.healthy,
            can_retune: self.online && self.healthy && self.can_retune,
            can_capture_iq: self.online && self.healthy && self.can_capture_iq,
            recognizer_available,
            dropped_observations,
        }
    }
}

pub struct ReplaySdrAdapter {
    snapshots: VecDeque<SdrSnapshot>,
}

impl ReplaySdrAdapter {
    pub fn new(snapshots: impl IntoIterator<Item = SdrSnapshot>) -> Self {
        Self {
            snapshots: snapshots.into_iter().collect(),
        }
    }
}

impl SdrEngine for ReplaySdrAdapter {
    fn observe(&mut self) -> Result<SdrSnapshot, SdrError> {
        self.snapshots
            .pop_front()
            .ok_or_else(|| SdrError::new("replay_exhausted", "no replay snapshots remain"))
    }
}

pub struct SdrdAdapter {
    address: SocketAddr,
    timeout: Duration,
}

impl SdrdAdapter {
    pub fn new(address: SocketAddr, timeout: Duration) -> Self {
        Self { address, timeout }
    }
}

pub(crate) struct SdrdWire {
    stream: TcpStream,
    reader: BufReader<TcpStream>,
    next_request_id: u64,
}

impl SdrdWire {
    pub(crate) fn connect(address: SocketAddr, timeout: Duration) -> Result<Self, SdrError> {
        let stream = TcpStream::connect_timeout(&address, timeout)
            .map_err(|error| SdrError::io("connect", error))?;
        stream
            .set_read_timeout(Some(timeout))
            .map_err(|error| SdrError::io("set_read_timeout", error))?;
        stream
            .set_write_timeout(Some(timeout))
            .map_err(|error| SdrError::io("set_write_timeout", error))?;
        let read_stream = stream
            .try_clone()
            .map_err(|error| SdrError::io("clone_stream", error))?;
        Ok(Self {
            stream,
            reader: BufReader::new(read_stream),
            next_request_id: 1,
        })
    }

    pub(crate) fn request<T: DeserializeOwned>(
        &mut self,
        command: &str,
        arguments: &str,
    ) -> Result<T, SdrError> {
        let request_id = self.next_request_id;
        self.next_request_id = self
            .next_request_id
            .checked_add(1)
            .ok_or_else(|| SdrError::new("request_id_exhausted", "SDRD request id exhausted"))?;
        let request = if arguments.is_empty() {
            format!("SDRD/1 {command} {request_id}\n")
        } else {
            format!("SDRD/1 {command} {request_id} {arguments}\n")
        };
        self.stream
            .write_all(request.as_bytes())
            .map_err(|error| SdrError::io("write_request", error))?;
        self.stream
            .flush()
            .map_err(|error| SdrError::io("flush_request", error))?;

        let mut frame = Vec::new();
        self.reader
            .by_ref()
            .take((SDRD_MAX_RESPONSE_BYTES + 1) as u64)
            .read_until(b'\n', &mut frame)
            .map_err(|error| SdrError::io("read_response", error))?;
        if frame.len() > SDRD_MAX_RESPONSE_BYTES {
            return Err(SdrError::new(
                "response_too_large",
                "SDRD response exceeds 2048 bytes",
            ));
        }
        if frame.last() != Some(&b'\n') {
            return Err(SdrError::new(
                "response_framing",
                "SDRD response is not newline framed",
            ));
        }
        frame.pop();

        let value: serde_json::Value = serde_json::from_slice(&frame)
            .map_err(|error| SdrError::protocol("response_json", error))?;
        let common: CommonResponse = serde_json::from_value(value.clone())
            .map_err(|error| SdrError::protocol("response_common", error))?;
        if common.schema_version != SDRD_SCHEMA_VERSION {
            return Err(SdrError::new(
                "schema_version",
                "unsupported SDRD schema version",
            ));
        }
        if common.request_id != request_id {
            return Err(SdrError::new(
                "request_id",
                "SDRD response request id mismatch",
            ));
        }
        if common.status != "ok" {
            let message = common
                .error
                .unwrap_or_else(|| "SDRD request failed".to_owned());
            return Err(SdrError::with_details("remote_error", message, value));
        }
        serde_json::from_value(value).map_err(|error| SdrError::protocol("response_shape", error))
    }
}

impl SdrEngine for SdrdAdapter {
    fn observe(&mut self) -> Result<SdrSnapshot, SdrError> {
        let mut wire = SdrdWire::connect(self.address, self.timeout)?;
        let hello: HelloResponse = wire.request("HELLO", "")?;
        if hello.server != "p201-sdrd"
            || hello.protocol != "SDRD/1"
            || !matches!(hello.mode.as_str(), "shadow" | "controlled")
            || (hello.mode == "shadow" && hello.mutating_commands)
        {
            return Err(SdrError::new(
                "unexpected_server",
                "SDRD endpoint identity or mode is inconsistent",
            ));
        }

        let capabilities: CapabilitiesResponse = wire.request("CAPABILITIES", "")?;
        if capabilities.mode != hello.mode {
            return Err(SdrError::new(
                "unexpected_mode",
                "SDRD hello and capability modes do not match",
            ));
        }

        let health: HealthResponse = wire.request("HEALTH", "")?;

        let quit: QuitResponse = wire.request("QUIT", "")?;
        if !quit.closing {
            return Err(SdrError::new(
                "quit_rejected",
                "SDRD did not acknowledge connection close",
            ));
        }

        let iio_visible =
            capabilities.iio_visible && health.iio_phy_visible && health.iio_rx_visible;
        let rx_input_valid = capabilities
            .rx_input
            .as_ref()
            .is_some_and(RxInputIdentity::is_fixed_p201_rx1)
            && capabilities.rx_input == health.rx_input;
        let controlled_identity_valid = hello.mode != "controlled" || rx_input_valid;
        Ok(SdrSnapshot {
            online: true,
            healthy: health.healthy
                && health.health_flags == 0
                && iio_visible
                && controlled_identity_valid
                && !health.session_faulted,
            health_flags: health.health_flags,
            iio_visible,
            can_retune: capabilities.radio_control && rx_input_valid,
            can_capture_iq: capabilities.raw_iq_capture
                && capabilities.max_capture_bytes > 0
                && rx_input_valid,
            rx_input: health.rx_input,
        })
    }
}

#[derive(Deserialize)]
struct CommonResponse {
    schema_version: u16,
    request_id: u64,
    status: String,
    #[serde(default)]
    error: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HelloResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    server: String,
    protocol: String,
    mode: String,
    mutating_commands: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CapabilitiesResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    mode: String,
    iio_visible: bool,
    radio_control: bool,
    raw_iq_capture: bool,
    #[serde(default)]
    #[serde(rename = "software_summary")]
    _software_summary: bool,
    #[serde(default)]
    max_capture_bytes: u64,
    #[serde(default)]
    rx_input: Option<RxInputIdentity>,
    #[serde(rename = "fpga_backend")]
    _fpga_backend: String,
    #[serde(rename = "fpga_identity_valid")]
    _fpga_identity_valid: bool,
    #[serde(rename = "fpga_summary_version")]
    _fpga_summary_version: u32,
    #[serde(rename = "fpga_abi_version")]
    _fpga_abi_version: u32,
    #[serde(rename = "fpga_capability")]
    _fpga_capability: u32,
    #[serde(rename = "fpga_aggregate")]
    _fpga_aggregate: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HealthResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    healthy: bool,
    health_flags: u32,
    iio_phy_visible: bool,
    iio_rx_visible: bool,
    #[serde(default)]
    rx_input: Option<RxInputIdentity>,
    #[serde(rename = "fpga_configured")]
    _fpga_configured: bool,
    #[serde(rename = "fpga_mapped")]
    _fpga_mapped: bool,
    #[serde(rename = "fpga_identity_valid")]
    _fpga_identity_valid: bool,
    #[serde(default)]
    session_faulted: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct QuitResponse {
    #[serde(rename = "schema_version")]
    _schema_version: u16,
    #[serde(rename = "request_id")]
    _request_id: u64,
    #[serde(rename = "status")]
    _status: String,
    closing: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SdrError {
    pub code: &'static str,
    pub message: String,
    pub details: Option<serde_json::Value>,
}

impl SdrError {
    pub(crate) fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            details: None,
        }
    }

    pub(crate) fn with_details(
        code: &'static str,
        message: impl Into<String>,
        details: serde_json::Value,
    ) -> Self {
        Self {
            code,
            message: message.into(),
            details: Some(details),
        }
    }

    pub(crate) fn io(operation: &'static str, error: std::io::Error) -> Self {
        Self::new(operation, error.to_string())
    }

    pub(crate) fn protocol(operation: &'static str, error: serde_json::Error) -> Self {
        Self::new(operation, error.to_string())
    }
}

impl fmt::Display for SdrError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)?;
        if let Some(details) = &self.details {
            write!(formatter, " metadata={details}")?;
        }
        Ok(())
    }
}

impl Error for SdrError {}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;

    fn healthy_snapshot() -> SdrSnapshot {
        SdrSnapshot {
            online: true,
            healthy: true,
            health_flags: 0,
            iio_visible: true,
            can_retune: false,
            can_capture_iq: false,
            rx_input: None,
        }
    }

    fn mock_server(responses: Vec<&'static str>) -> (SocketAddr, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            for response in responses {
                let mut request = String::new();
                reader.read_line(&mut request).unwrap();
                assert!(request.starts_with("SDRD/1 "));
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        (address, handle)
    }

    #[test]
    fn replay_adapter_is_a_second_real_adapter() {
        let snapshot = healthy_snapshot();
        let mut replay = ReplaySdrAdapter::new([snapshot.clone()]);
        assert_eq!(replay.observe().unwrap(), snapshot);
        assert_eq!(replay.observe().unwrap_err().code, "replay_exhausted");
    }

    #[test]
    fn reads_and_reduces_shadow_sdrd_snapshot() {
        let responses = vec![
            "{\"schema_version\":1,\"request_id\":1,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"shadow\",\"mutating_commands\":false}\n",
            "{\"schema_version\":1,\"request_id\":2,\"status\":\"ok\",\"mode\":\"shadow\",\"iio_visible\":true,\"radio_control\":false,\"raw_iq_capture\":false,\"software_summary\":true,\"fpga_backend\":\"disabled\",\"fpga_identity_valid\":false,\"fpga_summary_version\":0,\"fpga_abi_version\":0,\"fpga_capability\":0,\"fpga_aggregate\":false}\n",
            "{\"schema_version\":1,\"request_id\":3,\"status\":\"ok\",\"healthy\":true,\"health_flags\":0,\"iio_phy_visible\":true,\"iio_rx_visible\":true,\"fpga_configured\":false,\"fpga_mapped\":false,\"fpga_identity_valid\":false}\n",
            "{\"schema_version\":1,\"request_id\":4,\"status\":\"ok\",\"closing\":true}\n",
        ];
        let (address, handle) = mock_server(responses);
        let mut adapter = SdrdAdapter::new(address, Duration::from_secs(1));
        assert_eq!(adapter.observe().unwrap(), healthy_snapshot());
        handle.join().unwrap();
    }

    #[test]
    fn rejects_mismatched_response_id() {
        let responses = vec![
            "{\"schema_version\":1,\"request_id\":99,\"status\":\"ok\",\"server\":\"p201-sdrd\",\"protocol\":\"SDRD/1\",\"mode\":\"shadow\",\"mutating_commands\":false}\n",
        ];
        let (address, handle) = mock_server(responses);
        let mut adapter = SdrdAdapter::new(address, Duration::from_secs(1));
        assert_eq!(adapter.observe().unwrap_err().code, "request_id");
        handle.join().unwrap();
    }

    #[test]
    fn preserves_remote_execution_metadata_on_failure() {
        let responses = vec![
            "{\"schema_version\":1,\"request_id\":1,\"status\":\"error\",\"error\":\"power_timeout_restored\",\"generation\":7,\"session_generation\":7,\"sequence\":19,\"dropped_samples\":0,\"overflow\":false,\"timeout\":{\"limit_ms\":1,\"elapsed_us\":2048,\"timed_out\":true},\"health\":{\"healthy\":false,\"flags\":4,\"source\":\"iio_adapter\"}}\n",
        ];
        let (address, handle) = mock_server(responses);
        let mut wire = SdrdWire::connect(address, Duration::from_secs(1)).unwrap();
        let error = wire
            .request::<serde_json::Value>("CAPTURE_POWER", "7 4096 8 1")
            .unwrap_err();
        assert_eq!(error.code, "remote_error");
        assert_eq!(error.message, "power_timeout_restored");
        let details = error.details.unwrap();
        assert_eq!(details["session_generation"], 7);
        assert_eq!(details["sequence"], 19);
        assert_eq!(details["timeout"]["timed_out"], true);
        assert_eq!(details["health"]["flags"], 4);
        handle.join().unwrap();
    }

    #[test]
    fn planner_health_never_upgrades_unhealthy_capabilities() {
        let mut snapshot = healthy_snapshot();
        snapshot.healthy = false;
        snapshot.can_retune = true;
        snapshot.can_capture_iq = true;
        let health = snapshot.planner_health(true, 4);
        assert!(!health.sdr_online);
        assert!(!health.can_retune);
        assert!(!health.can_capture_iq);
        assert!(health.recognizer_available);
        assert_eq!(health.dropped_observations, 4);
    }
}
