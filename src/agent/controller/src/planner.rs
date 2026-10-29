use crate::protocol::{PlanRequest, PlanResponse, MAX_FRAME_BYTES};
use std::error::Error;
use std::fmt;
use std::io;
use std::time::Duration;

pub trait Planner {
    fn plan(&mut self, request: &PlanRequest) -> Result<PlanResponse, PlannerError>;
}

#[cfg(unix)]
pub struct UnixPlannerAdapter {
    socket_path: std::path::PathBuf,
    timeout: Duration,
}

#[cfg(unix)]
impl UnixPlannerAdapter {
    pub fn new(socket_path: impl Into<std::path::PathBuf>, timeout: Duration) -> Self {
        Self {
            socket_path: socket_path.into(),
            timeout,
        }
    }
}

#[cfg(unix)]
impl Planner for UnixPlannerAdapter {
    fn plan(&mut self, request: &PlanRequest) -> Result<PlanResponse, PlannerError> {
        use std::io::{BufRead, BufReader, Read, Write};
        use std::os::unix::net::UnixStream;

        let mut frame = serde_json::to_vec(request)
            .map_err(|error| PlannerError::protocol(format!("encode request: {error}")))?;
        if frame.len() > MAX_FRAME_BYTES {
            return Err(PlannerError::protocol("request frame exceeds 32 KiB"));
        }
        frame.push(b'\n');

        let mut stream = UnixStream::connect(&self.socket_path)
            .map_err(|error| PlannerError::transport("connect planner socket", error))?;
        stream
            .set_read_timeout(Some(self.timeout))
            .map_err(|error| PlannerError::transport("set planner read timeout", error))?;
        stream
            .set_write_timeout(Some(self.timeout))
            .map_err(|error| PlannerError::transport("set planner write timeout", error))?;
        stream
            .write_all(&frame)
            .map_err(|error| PlannerError::transport("write planner request", error))?;

        let mut response_frame = Vec::new();
        let reader = BufReader::new(stream);
        reader
            .take((MAX_FRAME_BYTES + 1) as u64)
            .read_until(b'\n', &mut response_frame)
            .map_err(|error| PlannerError::transport("read planner response", error))?;
        if response_frame.len() > MAX_FRAME_BYTES + 1 {
            return Err(PlannerError::protocol("response frame exceeds 32 KiB"));
        }
        if response_frame.last() != Some(&b'\n') {
            return Err(PlannerError::protocol(
                "planner response is not newline framed",
            ));
        }
        response_frame.pop();
        serde_json::from_slice(&response_frame)
            .map_err(|error| PlannerError::protocol(format!("decode response: {error}")))
    }
}

#[derive(Debug)]
pub struct PlannerError {
    kind: &'static str,
    message: String,
}

impl PlannerError {
    fn transport(operation: &'static str, error: io::Error) -> Self {
        Self {
            kind: "transport",
            message: format!("{operation}: {error}"),
        }
    }

    fn protocol(message: impl Into<String>) -> Self {
        Self {
            kind: "protocol",
            message: message.into(),
        }
    }
}

impl fmt::Display for PlannerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.kind, self.message)
    }
}

impl Error for PlannerError {}
