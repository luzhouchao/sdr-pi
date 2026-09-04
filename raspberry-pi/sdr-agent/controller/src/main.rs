#[cfg(not(unix))]
compile_error!("sdr-agent-controller currently targets Linux/Unix only");

use sdr_agent_controller::execution::{
    ExecutionAuthorization, SdrActionExecutor, SdrdActionAdapter,
};
use sdr_agent_controller::live_recognition::{
    validate_live_plan, LiveRecognitionEngine, LiveRecognitionPlan, SdrdLiveRecognitionCapture,
    LIVE_RECOGNITION_RAW_BYTES, LIVE_RECOGNITION_SPOOL_BYTES,
};
use sdr_agent_controller::planner::UnixPlannerAdapter;
use sdr_agent_controller::policy::ControllerPolicy;
use sdr_agent_controller::protocol::{PlanRequest, PlanResponse, ValidatedPlan, MAX_FRAME_BYTES};
use sdr_agent_controller::recognizer::{
    LocalRecognizer, RecognitionRequest, UnixRecognizerAdapter, RECOGNIZER_MAX_FRAME_BYTES,
};
use sdr_agent_controller::runner::{ApprovalMode, JsonlAuditAdapter, Runner};
use sdr_agent_controller::sdr::{SdrEngine, SdrdAdapter};
use sdr_agent_controller::sweep::{SdrdSoftwareSweepAdapter, SweepEngine, SweepPlan};
use sdr_agent_controller::Controller;
use serde::Deserialize;
use std::env;
use std::error::Error;
use std::fs;
use std::io::{self, Read};
use std::net::SocketAddr;
use std::time::Duration;

type AppResult<T> = Result<T, Box<dyn Error>>;

fn main() {
    if let Err(error) = run() {
        eprintln!("controller_error={error}");
        std::process::exit(1);
    }
}

fn run() -> AppResult<()> {
    let mut socket = "/run/sdr-agent/planner.sock".to_owned();
    let mut request_path = "-".to_owned();
    let mut instruction = None;
    let mut mode = "plan".to_owned();
    let mut sdrd_address = None;
    let mut recognizer_socket = "/run/sdr-agent/recognizer.sock".to_owned();
    let mut recognizer_spool_root = "/run/sdr-agent/iq".to_owned();
    let mut timeout_ms = 30_000_u64;
    let mut sdrd_timeout_ms = 5_000_u64;
    let mut recognizer_timeout_ms = 5_000_u64;
    let mut execution_approval = None;
    let mut audit_log = "/var/lib/sdr-agent/audit.jsonl".to_owned();
    let mut session_generation = None;
    let mut survey_gain_db = 20_i16;
    let mut sweep_point_timeout_ms = 250_u32;
    let mut args = env::args().skip(1);
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .ok_or_else(|| invalid_input(format!("missing value for {flag}")))?;
        match flag.as_str() {
            "--socket" => socket = value,
            "--request" => request_path = value,
            "--instruction" => instruction = Some(value),
            "--mode" => mode = value,
            "--sdrd" => sdrd_address = Some(value.parse::<SocketAddr>()?),
            "--recognizer-socket" => recognizer_socket = value,
            "--recognizer-spool-root" => recognizer_spool_root = value,
            "--timeout-ms" => timeout_ms = value.parse()?,
            "--sdrd-timeout-ms" => sdrd_timeout_ms = value.parse()?,
            "--recognizer-timeout-ms" => recognizer_timeout_ms = value.parse()?,
            "--approval" => execution_approval = Some(value),
            "--audit-log" => audit_log = value,
            "--session-generation" => session_generation = Some(value.parse::<u64>()?),
            "--survey-gain-db" => survey_gain_db = value.parse::<i16>()?,
            "--sweep-point-timeout-ms" => sweep_point_timeout_ms = value.parse::<u32>()?,
            _ => return Err(invalid_input(format!("unknown option {flag}")).into()),
        }
    }
    if !(100..=120_000).contains(&timeout_ms) {
        return Err(invalid_input("--timeout-ms must be between 100 and 120000").into());
    }
    if !(100..=60_000).contains(&sdrd_timeout_ms) {
        return Err(invalid_input("--sdrd-timeout-ms must be between 100 and 60000").into());
    }
    if !(1..=5_000).contains(&recognizer_timeout_ms) {
        return Err(invalid_input("--recognizer-timeout-ms must be between 1 and 5000").into());
    }
    if !(0..=60).contains(&survey_gain_db) {
        return Err(invalid_input("--survey-gain-db must be between 0 and 60").into());
    }
    if !(1..=5_000).contains(&sweep_point_timeout_ms) {
        return Err(invalid_input("--sweep-point-timeout-ms must be between 1 and 5000").into());
    }
    if !matches!(
        mode.as_str(),
        "plan"
            | "observe"
            | "recognize"
            | "recognize-live"
            | "execute"
            | "cancel"
            | "sweep"
            | "run-once"
    ) {
        return Err(invalid_input(
            "--mode must be plan, observe, recognize, recognize-live, execute, cancel, sweep, or run-once",
        )
        .into());
    }

    if mode == "run-once" {
        let address = sdrd_address
            .ok_or_else(|| invalid_input("--mode run-once requires --sdrd HOST:PORT"))?;
        let bytes = read_request(&request_path, MAX_FRAME_BYTES)?;
        let mut request: PlanRequest = serde_json::from_slice(&bytes)?;
        if let Some(instruction) = instruction {
            request.instruction = instruction;
        }
        let approval = match execution_approval.as_deref().unwrap_or("pending") {
            "pending" => ApprovalMode::Pending,
            "automatic" => ApprovalMode::Automatic,
            "operator" => ApprovalMode::Operator,
            value => {
                return Err(invalid_input(format!(
                    "--approval must be pending, automatic, or operator; got {value}"
                ))
                .into())
            }
        };
        let observer = SdrdAdapter::new(address, Duration::from_millis(sdrd_timeout_ms));
        let planner = UnixPlannerAdapter::new(socket, Duration::from_millis(timeout_ms));
        let executor = SdrdActionAdapter::new(address, Duration::from_millis(sdrd_timeout_ms));
        let sweep_backend =
            SdrdSoftwareSweepAdapter::new(address, Duration::from_millis(sdrd_timeout_ms));
        let audit = JsonlAuditAdapter::open(audit_log)?;
        let mut runner = Runner::new(
            observer,
            planner,
            executor,
            sweep_backend,
            survey_gain_db,
            sweep_point_timeout_ms,
            audit,
        );
        println!(
            "{}",
            serde_json::to_string(&runner.run_once(request, approval)?)?
        );
        return Ok(());
    }

    if mode == "sweep" {
        if instruction.is_some() {
            return Err(invalid_input("--instruction is valid only in plan mode").into());
        }
        let address =
            sdrd_address.ok_or_else(|| invalid_input("--mode sweep requires --sdrd HOST:PORT"))?;
        let bytes = read_request(&request_path, MAX_FRAME_BYTES)?;
        let plan: SweepPlan = serde_json::from_slice(&bytes)?;
        let adapter =
            SdrdSoftwareSweepAdapter::new(address, Duration::from_millis(sdrd_timeout_ms));
        println!(
            "{}",
            serde_json::to_string(&SweepEngine::new(adapter).run(&plan)?)?
        );
        return Ok(());
    }

    if mode == "cancel" {
        let address =
            sdrd_address.ok_or_else(|| invalid_input("--mode cancel requires --sdrd HOST:PORT"))?;
        let generation = session_generation
            .ok_or_else(|| invalid_input("--mode cancel requires --session-generation N"))?;
        let mut executor = SdrdActionAdapter::new(address, Duration::from_millis(sdrd_timeout_ms));
        println!("{}", serde_json::to_string(&executor.cancel(generation)?)?);
        return Ok(());
    }

    if mode == "observe" {
        let address = sdrd_address
            .ok_or_else(|| invalid_input("--mode observe requires --sdrd HOST:PORT"))?;
        let mut sdr = SdrdAdapter::new(address, Duration::from_millis(sdrd_timeout_ms));
        println!("{}", serde_json::to_string(&sdr.observe()?)?);
        return Ok(());
    }

    if mode == "recognize" {
        if instruction.is_some() {
            return Err(invalid_input("--instruction is valid only in plan mode").into());
        }
        let bytes = read_request(&request_path, RECOGNIZER_MAX_FRAME_BYTES)?;
        let request: RecognitionRequest = serde_json::from_slice(&bytes)?;
        let mut recognizer = UnixRecognizerAdapter::new(
            recognizer_socket,
            recognizer_spool_root,
            Duration::from_millis(recognizer_timeout_ms),
        );
        println!(
            "{}",
            serde_json::to_string(&recognizer.classify(&request)?)?
        );
        return Ok(());
    }

    if mode == "recognize-live" {
        if instruction.is_some() {
            return Err(invalid_input("--instruction is valid only in plan mode").into());
        }
        let address = sdrd_address
            .ok_or_else(|| invalid_input("--mode recognize-live requires --sdrd HOST:PORT"))?;
        let bytes = read_request(&request_path, RECOGNIZER_MAX_FRAME_BYTES)?;
        let plan: LiveRecognitionPlan = serde_json::from_slice(&bytes)?;
        validate_live_plan(&plan)?;
        eprintln!(
            "validated_live_recognition_plan={} p201_max_bytes={} agx_spool_max_bytes={}",
            serde_json::to_string(&plan)?,
            LIVE_RECOGNITION_RAW_BYTES,
            LIVE_RECOGNITION_SPOOL_BYTES
        );
        let capture =
            SdrdLiveRecognitionCapture::new(address, Duration::from_millis(sdrd_timeout_ms));
        let recognizer = UnixRecognizerAdapter::new(
            recognizer_socket,
            recognizer_spool_root.clone(),
            Duration::from_millis(recognizer_timeout_ms),
        );
        let mut engine = LiveRecognitionEngine::new(capture, recognizer, recognizer_spool_root);
        println!("{}", serde_json::to_string(&engine.run(&plan)?)?);
        return Ok(());
    }

    if mode == "execute" {
        if instruction.is_some() {
            return Err(invalid_input("--instruction is valid only in plan mode").into());
        }
        let address = sdrd_address
            .ok_or_else(|| invalid_input("--mode execute requires --sdrd HOST:PORT"))?;
        let bytes = read_request(&request_path, MAX_FRAME_BYTES)?;
        let input: ExecutionInput = serde_json::from_slice(&bytes)?;
        ControllerPolicy.validate_request(&input.request)?;
        let plan: ValidatedPlan =
            ControllerPolicy.validate_response(&input.request, input.response)?;
        let authorization = if execution_approval.as_deref() == Some("operator") {
            ExecutionAuthorization::operator_approved(&plan)
        } else {
            ExecutionAuthorization::automatic(&plan)?
        };
        let mut executor = SdrdActionAdapter::new(address, Duration::from_millis(sdrd_timeout_ms));
        println!(
            "{}",
            serde_json::to_string(&executor.execute(&plan, &authorization)?)?
        );
        return Ok(());
    }

    let bytes = read_request(&request_path, MAX_FRAME_BYTES)?;
    let mut request: PlanRequest = serde_json::from_slice(&bytes)?;
    if let Some(instruction) = instruction {
        request.instruction = instruction;
    }
    if let Some(address) = sdrd_address {
        let mut sdr = SdrdAdapter::new(address, Duration::from_millis(sdrd_timeout_ms));
        let snapshot = sdr.observe()?;
        let recognizer_available = request.observation.health.recognizer_available;
        let dropped_observations = request.observation.health.dropped_observations;
        request.observation.health =
            snapshot.planner_health(recognizer_available, dropped_observations);
    }
    let planner = UnixPlannerAdapter::new(socket, Duration::from_millis(timeout_ms));
    let mut controller = Controller::new(planner);
    let plan = controller.decide(&request)?;
    println!("{}", serde_json::to_string(&plan)?);
    Ok(())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ExecutionInput {
    request: PlanRequest,
    response: PlanResponse,
}

fn read_request(path: &str, max_bytes: usize) -> AppResult<Vec<u8>> {
    if path == "-" {
        read_bounded(io::stdin(), max_bytes)
    } else {
        read_bounded(fs::File::open(path)?, max_bytes)
    }
}

fn read_bounded(mut reader: impl Read, max_bytes: usize) -> AppResult<Vec<u8>> {
    let mut bytes = Vec::new();
    reader
        .by_ref()
        .take((max_bytes + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > max_bytes {
        return Err(invalid_input(format!("request exceeds {max_bytes} bytes")).into());
    }
    Ok(bytes)
}

fn invalid_input(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.into())
}
