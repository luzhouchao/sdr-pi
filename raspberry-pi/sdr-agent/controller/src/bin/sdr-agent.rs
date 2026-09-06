#![cfg(unix)]

use sdr_agent_controller::autonomy::{
    CruiseControl, CruisePhase, CruiseStopReason, InteractionMode, AUTO_RETRY_DELAY_SECS,
    AUTO_RETRY_LIMIT, DEFAULT_AUTO_DURATION_SECS, DEFAULT_AUTO_MAX_STEPS, HARD_AUTO_DURATION_SECS,
    HARD_AUTO_MAX_STEPS, MIN_AUTO_DURATION_SECS,
};
use sdr_agent_controller::execution::{
    ExecutionAuthorization, ExecutionObservation, SdrActionExecutor, SdrdActionAdapter,
};
use sdr_agent_controller::policy::ControllerPolicy;
use sdr_agent_controller::protocol::{
    ControllerState, PlanRequest, PlanResponse, ProposedAction, ValidatedPlan, MAX_FRAME_BYTES,
    MAX_INSTRUCTION_BYTES,
};
use sdr_agent_controller::recognition_execution::{
    EngineeringRecognition, RecognitionCancellation, RecognitionExecutionReport, MAX_RX_BYTES,
};
use sdr_agent_controller::recognizer_admission::{
    refresh_recognizer, RecognizerCapability, UnixRecognizerCapability, DEFAULT_ADMISSION_PATH,
    DEFAULT_RECOGNIZER_SOCKET,
};
use sdr_agent_controller::sdr::{SdrEngine, SdrError, SdrdAdapter};
use sdr_agent_controller::sweep::{
    SdrdSoftwareSweepAdapter, SweepEngine, SweepError, SweepFrequencies, SweepPlan, SweepReport,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
use std::env;
use std::error::Error;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::net::SocketAddr;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError, SyncSender, TrySendError};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

type AppResult<T> = Result<T, Box<dyn Error>>;
const HISTORY_LIMIT: usize = 32;
const CANCEL_START_RETRIES: usize = 50;
const AUTO_RETRY_DELAY: Duration = Duration::from_secs(AUTO_RETRY_DELAY_SECS);
const EVENT_POLL_INTERVAL: Duration = Duration::from_millis(50);
const TERMINAL_INPUT_QUEUE_LIMIT: usize = 4;
const TERMINAL_STATE_SCHEMA_VERSION: u8 = 1;
const TERMINAL_STATE_MAX_BYTES: usize = 64 * 1024;
const TERMINAL_RESUME_MAX_ENTRIES: usize = HISTORY_LIMIT;
const TERMINAL_RESUME_ENTRY_MAX_BYTES: usize = 2_048;
const TERMINAL_RESUME_SUMMARY_MAX_BYTES: usize = 6_144;
const TERMINAL_RESUME_MAX_AGE_MS: u64 = 7 * 24 * 60 * 60 * 1_000;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PersistedTerminalSession {
    schema_version: u8,
    saved_at_ms: u64,
    history: Vec<String>,
}

#[derive(Debug)]
struct LoadedTerminalSession {
    history: VecDeque<String>,
    summary: String,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("sdr_agent_error={error}");
        std::process::exit(1);
    }
}

fn run() -> AppResult<()> {
    let options = Options::parse()?;
    let bytes = read_bounded(fs::File::open(&options.request_path)?)?;
    let template: PlanRequest = serde_json::from_slice(&bytes)?;
    ControllerPolicy.validate_request(&template)?;
    let loaded_session = if options.instruction.is_none() {
        options
            .session_state_path
            .as_deref()
            .map(load_terminal_session)
            .transpose()?
            .flatten()
    } else {
        None
    };
    let executor = options.sdrd_address.map(|address| {
        SdrdActionAdapter::new(address, Duration::from_millis(options.sdrd_timeout_ms))
    });
    let mut app = ConsoleApp::connect(
        template,
        ConsoleConnectionOptions {
            socket_path: options.socket_path,
            recognizer_socket: options.recognizer_socket,
            recognizer_admission: options.recognizer_admission,
            executor,
            engineering_recognition: options.engineering_recognition,
            recognition_audit_path: options.recognition_audit_path,
            sdrd_address: options.sdrd_address,
            sdrd_timeout: Duration::from_millis(options.sdrd_timeout_ms),
            survey_gain_db: options.survey_gain_db,
            sigmf_directory: options.sigmf_directory,
            session_state_path: if options.instruction.is_none() {
                options.session_state_path.clone()
            } else {
                None
            },
        },
        loaded_session,
    )?;

    if let Some(instruction) = options.instruction {
        app.submit(instruction)?;
        while app.agent_cycle_active {
            app.poll()?;
            thread::sleep(EVENT_POLL_INTERVAL);
        }
        return Ok(());
    }

    println!(
        "SDR Agent 已连接。输入 /help 查看命令。硬件执行={}。",
        if app.executor.is_some() {
            "已启用"
        } else {
            "未配置"
        }
    );
    if !app.history.is_empty() {
        println!(
            "已恢复 {} 条有限终端历史；待批准计划、运行中动作和旧 generation 均未恢复。",
            app.history.len()
        );
    }
    if let Some(initial_survey) = options.initial_survey {
        app.start_initial_survey(initial_survey)?;
    }
    let (input_tx, input_rx) = mpsc::sync_channel(TERMINAL_INPUT_QUEUE_LIMIT);
    let priority_stop = Arc::new(AtomicBool::new(false));
    let input_stop = Arc::clone(&priority_stop);
    thread::spawn(move || {
        let stdin = io::stdin();
        loop {
            let mut line = String::new();
            match stdin.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => match enqueue_terminal_input(&input_tx, &input_stop, line) {
                    TerminalEnqueueResult::Queued | TerminalEnqueueResult::StopRequested => {}
                    TerminalEnqueueResult::Full => eprintln!(
                        "终端输入队列已满（最多 {TERMINAL_INPUT_QUEUE_LIMIT} 条）；本行已拒绝，/stop 仍可立即使用。"
                    ),
                    TerminalEnqueueResult::StopInProgress => {
                        eprintln!("停止请求正在处理；本行已拒绝，不会进入旧 generation。")
                    }
                    TerminalEnqueueResult::Disconnected => break,
                },
            }
        }
    });
    print_prompt()?;
    let mut running = true;
    while running {
        if priority_stop.load(Ordering::Acquire) {
            let mut discarded = 0_usize;
            while input_rx.try_recv().is_ok() {
                discarded += 1;
            }
            if discarded > 0 {
                println!("/stop 已丢弃本地队列中的 {discarded} 条旧输入。");
            }
            app.stop("会话已停止")?;
            priority_stop.store(false, Ordering::Release);
            print_prompt()?;
        }
        app.poll()?;
        app.advance_auto()?;
        match input_rx.recv_timeout(EVENT_POLL_INTERVAL) {
            Ok(line) => {
                running = handle_input(&mut app, line.trim())?;
                if running {
                    print_prompt()?;
                }
            }
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => break,
        }
    }
    if app.active_recognition.is_some() {
        app.stop("退出前停止识别")?;
        let deadline = Instant::now() + Duration::from_secs(35);
        while app.active_recognition.is_some() {
            if Instant::now() >= deadline {
                return Err(invalid_input("recognition shutdown remains unconfirmed").into());
            }
            app.poll()?;
            thread::sleep(EVENT_POLL_INTERVAL);
        }
    }
    app.close()?;
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum TerminalEnqueueResult {
    Queued,
    StopRequested,
    Full,
    StopInProgress,
    Disconnected,
}

fn enqueue_terminal_input(
    sender: &SyncSender<String>,
    priority_stop: &AtomicBool,
    line: String,
) -> TerminalEnqueueResult {
    if matches!(line.trim(), "/stop" | "/停止") {
        priority_stop.store(true, Ordering::Release);
        return TerminalEnqueueResult::StopRequested;
    }
    if priority_stop.load(Ordering::Acquire) {
        return TerminalEnqueueResult::StopInProgress;
    }
    match sender.try_send(line) {
        Ok(()) => TerminalEnqueueResult::Queued,
        Err(TrySendError::Full(_)) => TerminalEnqueueResult::Full,
        Err(TrySendError::Disconnected(_)) => TerminalEnqueueResult::Disconnected,
    }
}

fn handle_input(app: &mut ConsoleApp, input: &str) -> AppResult<bool> {
    if input.is_empty() {
        return Ok(true);
    }
    match input {
        "/quit" | "/exit" | "/退出" => return Ok(false),
        "/help" | "/帮助" => print_help(),
        "/status" | "/状态" => app.status()?,
        "/history" | "/历史" => app.print_history(),
        "/approve" | "/批准" => app.approve()?,
        "/reject" | "/拒绝" => app.reject(),
        "/mode manual" | "/模式 人工" => app.enable_step_approval()?,
        "/pause" | "/暂停" => app.stop("会话已暂停")?,
        "/resume" | "/继续" => app.renew(ControllerState::Idle, "会话已恢复")?,
        "/stop" | "/停止" => app.stop("会话已停止")?,
        "/steer" | "/引导" => println!("用法：/steer <补充或修正指令>"),
        "/follow-up" | "/followup" | "/跟进" => {
            println!("用法：/follow-up <本轮完成后处理的指令>")
        }
        _ if input.starts_with("/steer ") => app.queue_model_input(
            input.trim_start_matches("/steer ").trim(),
            SessionQueueKind::Steer,
        )?,
        _ if input.starts_with("/引导 ") => app.queue_model_input(
            input.trim_start_matches("/引导 ").trim(),
            SessionQueueKind::Steer,
        )?,
        _ if input.starts_with("/follow-up ") => app.queue_model_input(
            input.trim_start_matches("/follow-up ").trim(),
            SessionQueueKind::FollowUp,
        )?,
        _ if input.starts_with("/followup ") => app.queue_model_input(
            input.trim_start_matches("/followup ").trim(),
            SessionQueueKind::FollowUp,
        )?,
        _ if input.starts_with("/跟进 ") => app.queue_model_input(
            input.trim_start_matches("/跟进 ").trim(),
            SessionQueueKind::FollowUp,
        )?,
        _ if input == "/auto" || input == "/auto start" => println!(
            "请在命令后写明巡航任务，例如：/auto start --steps 16 --seconds 300 扫描指定的受限频段并根据结果给出下一步。"
        ),
        _ if input.starts_with("/auto start ") => {
            match parse_auto_start(input.trim_start_matches("/auto start ").trim()) {
                Ok(command) => app.start_auto(
                    &command.mission,
                    command.steps,
                    command.seconds,
                    command.iq_bytes,
                )?,
                Err(error) => println!("自动巡航参数无效：{error}"),
            }
        }
        _ if input.starts_with("/recognize ") => app.propose_recognition(input[11..].trim())?,
        _ if input.starts_with('/') => println!("未知命令；输入 /help 查看可用命令。"),
        _ if app.agent_cycle_active => {
            app.queue_model_input(input, SessionQueueKind::Steer)?
        }
        _ => app.submit(input.to_owned())?,
    }
    Ok(true)
}

fn print_prompt() -> io::Result<()> {
    print!("SDR Agent> ");
    io::stdout().flush()
}

#[derive(Debug, Eq, PartialEq)]
struct AutoStartCommand {
    mission: String,
    steps: u8,
    seconds: u64,
    iq_bytes: Option<u64>,
}

fn parse_auto_start(arguments: &str) -> Result<AutoStartCommand, String> {
    let mut steps = None;
    let mut seconds = None;
    let mut mib = None;
    let mut mission = Vec::new();
    let mut tokens = arguments.split_whitespace();
    while let Some(token) = tokens.next() {
        match token {
            "--steps" => {
                if steps.is_some() {
                    return Err("--steps 只能填写一次".to_owned());
                }
                let value = tokens
                    .next()
                    .ok_or_else(|| "--steps 后缺少步数".to_owned())?;
                steps =
                    Some(
                        parse_bounded_auto_value(value, "步数", 1, u64::from(HARD_AUTO_MAX_STEPS))?
                            as u8,
                    );
            }
            "--seconds" => {
                if seconds.is_some() {
                    return Err("--seconds 只能填写一次".to_owned());
                }
                let value = tokens
                    .next()
                    .ok_or_else(|| "--seconds 后缺少秒数".to_owned())?;
                seconds = Some(parse_bounded_auto_value(
                    value,
                    "总时长",
                    MIN_AUTO_DURATION_SECS,
                    HARD_AUTO_DURATION_SECS,
                )?);
            }
            "--mib" => {
                if mib.is_some() {
                    return Err("--mib 只能填写一次".to_owned());
                }
                let value = tokens
                    .next()
                    .ok_or_else(|| "--mib 后缺少累计预算".to_owned())?;
                mib = Some(parse_bounded_auto_value(
                    value,
                    "累计预算",
                    1,
                    u64::MAX / (1024 * 1024),
                )?);
            }
            unknown if unknown.starts_with("--") => {
                return Err(format!("未知参数 {unknown}"));
            }
            word => mission.push(word),
        }
    }
    if mission.is_empty() {
        return Err("必须填写巡航任务".to_owned());
    }
    Ok(AutoStartCommand {
        mission: mission.join(" "),
        steps: steps.unwrap_or(DEFAULT_AUTO_MAX_STEPS),
        seconds: seconds.unwrap_or(DEFAULT_AUTO_DURATION_SECS),
        iq_bytes: mib.map(|value| value * 1024 * 1024),
    })
}

fn parse_bounded_auto_value(
    value: &str,
    label: &str,
    minimum: u64,
    maximum: u64,
) -> Result<u64, String> {
    let parsed = value
        .parse::<u64>()
        .map_err(|_| format!("{label}必须是 {minimum}–{maximum} 的整数"))?;
    if !(minimum..=maximum).contains(&parsed) {
        return Err(format!("{label}必须在 {minimum}–{maximum} 之间"));
    }
    Ok(parsed)
}

struct ConsoleApp {
    recognizer: Box<dyn RecognizerCapability>,
    client: SessionClient,
    template: PlanRequest,
    next_request_id: u64,
    session_generation: u64,
    pending: Option<ValidatedPlan>,
    requests: HashMap<u64, PlanRequest>,
    pending_session_commands: HashMap<u64, PendingSessionCommand>,
    history: VecDeque<String>,
    agent_cycle_active: bool,
    active_request_id: Option<u64>,
    plan_seen_in_cycle: bool,
    executor: Option<SdrdActionAdapter>,
    active_execution: Option<ActiveExecution>,
    active_sweep: Option<ActiveSweep>,
    active_recognition: Option<ActiveRecognition>,
    engineering_recognition: Option<EngineeringRecognition>,
    recognition_audit_path: Option<PathBuf>,
    sdrd_address: Option<SocketAddr>,
    sdrd_timeout: Duration,
    survey_gain_db: i16,
    sigmf_directory: Option<PathBuf>,
    cruise: CruiseControl,
    auto_mission: Option<String>,
    auto_next_instruction: Option<String>,
    next_auto_attempt: Instant,
    deferred_renew: Option<(ControllerState, String)>,
    session_state_path: Option<PathBuf>,
    resume_summary: Option<String>,
}

struct ActiveRecognition {
    request_id: u64,
    session_generation: u64,
    cancellation: RecognitionCancellation,
    worker: JoinHandle<Result<RecognitionExecutionReport, SdrError>>,
}

struct ConsoleConnectionOptions {
    engineering_recognition: Option<EngineeringRecognition>,
    recognition_audit_path: Option<PathBuf>,
    socket_path: PathBuf,
    recognizer_socket: PathBuf,
    recognizer_admission: PathBuf,
    executor: Option<SdrdActionAdapter>,
    sdrd_address: Option<SocketAddr>,
    sdrd_timeout: Duration,
    survey_gain_db: i16,
    sigmf_directory: Option<PathBuf>,
    session_state_path: Option<PathBuf>,
}

struct ActiveExecution {
    request_id: u64,
    session_generation: u64,
    canceller: SdrdActionAdapter,
    worker: JoinHandle<(SdrdActionAdapter, Result<ExecutionObservation, SdrError>)>,
}

struct ActiveSweep {
    kind: ActiveSweepKind,
    session_generation: u64,
    canceller: SdrdActionAdapter,
    worker: JoinHandle<Result<SweepReport, SweepError>>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum ActiveSweepKind {
    Initial,
    Planned {
        request_id: u64,
        maximum_bytes: u64,
    },
    Inspection {
        request_id: u64,
        candidate_id: String,
        maximum_bytes: u64,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SessionQueueKind {
    Steer,
    FollowUp,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PendingSessionCommand {
    Prompt {
        request_id: u64,
    },
    Queue {
        request_id: u64,
        kind: SessionQueueKind,
    },
    Abort,
}

impl SessionQueueKind {
    fn command(self) -> &'static str {
        match self {
            Self::Steer => "steer",
            Self::FollowUp => "follow_up",
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Steer => "引导",
            Self::FollowUp => "跟进",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct InitialSurveyOptions {
    start_hz: u64,
    stop_hz: u64,
    step_hz: u64,
    dwell_ms: u64,
    gain_db: i16,
}

impl ConsoleApp {
    fn connect(
        mut template: PlanRequest,
        options: ConsoleConnectionOptions,
        loaded_session: Option<LoadedTerminalSession>,
    ) -> AppResult<Self> {
        template.observation.health.recognizer_available = false;
        let generation = template.session_generation;
        let next_request_id = template.request_id;
        let (history, resume_summary) = loaded_session.map_or_else(
            || (VecDeque::with_capacity(HISTORY_LIMIT), None),
            |loaded| {
                (
                    loaded.history,
                    (!loaded.summary.is_empty()).then_some(loaded.summary),
                )
            },
        );
        let mut app = Self {
            recognizer: Box::new(UnixRecognizerCapability::new(
                options.recognizer_socket,
                options.recognizer_admission,
            )),
            client: SessionClient::connect(options.socket_path, generation)?,
            template,
            next_request_id,
            session_generation: generation,
            pending: None,
            requests: HashMap::new(),
            pending_session_commands: HashMap::new(),
            history,
            agent_cycle_active: false,
            active_request_id: None,
            plan_seen_in_cycle: false,
            executor: options.executor,
            active_execution: None,
            active_sweep: None,
            active_recognition: None,
            engineering_recognition: options.engineering_recognition,
            recognition_audit_path: options.recognition_audit_path,
            sdrd_address: options.sdrd_address,
            sdrd_timeout: options.sdrd_timeout,
            survey_gain_db: options.survey_gain_db,
            sigmf_directory: options.sigmf_directory,
            cruise: CruiseControl::default(),
            auto_mission: None,
            auto_next_instruction: None,
            next_auto_attempt: Instant::now(),
            deferred_renew: None,
            session_state_path: options.session_state_path,
            resume_summary,
        };
        app.command("open_session", None)?;
        Ok(app)
    }

    fn submit(&mut self, instruction: String) -> AppResult<()> {
        if self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
            || self.agent_cycle_active
        {
            println!("当前步骤尚未结束；可输入 /stop 立即停止，或等待完成后再提交新指令。");
            return Ok(());
        }
        self.refresh_sdr_health(false)?;
        let request_id = self.next_request_id;
        self.next_request_id = self
            .next_request_id
            .checked_add(1)
            .ok_or_else(|| invalid_input("request id exhausted"))?;
        let mut request = self.template.clone();
        request.request_id = request_id;
        request.session_generation = self.session_generation;
        request.instruction = self.resume_summary.as_deref().map_or_else(
            || instruction.clone(),
            |summary| carry_forward_instruction(summary, &instruction),
        );
        ControllerPolicy.validate_request(&request)?;
        self.resume_summary = None;
        println!("模型输入> {}", serde_json::to_string(&request)?);
        self.record(format!("operator: {instruction}"));
        self.requests.insert(request_id, request.clone());
        self.agent_cycle_active = true;
        self.active_request_id = Some(request_id);
        self.plan_seen_in_cycle = false;
        let command_id = self.send_session_command("prompt", Some(request))?;
        self.pending_session_commands
            .insert(command_id, PendingSessionCommand::Prompt { request_id });
        Ok(())
    }

    fn queue_model_input(&mut self, instruction: &str, kind: SessionQueueKind) -> AppResult<()> {
        if instruction.is_empty() {
            println!("{}指令不能为空。", kind.label());
            return Ok(());
        }
        if !self.agent_cycle_active {
            println!(
                "当前没有流式生成；{}只适用于正在运行的模型轮次。",
                kind.label()
            );
            return Ok(());
        }
        if self.deferred_renew.is_some() {
            println!("停止请求正在处理；{}不会进入旧 generation。", kind.label());
            return Ok(());
        }
        if self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
        {
            println!("硬件动作正在执行；只能使用 /stop，不能向已结束的模型轮次排队。");
            return Ok(());
        }
        self.refresh_recognition();
        let request_id = self.next_request_id;
        self.next_request_id = self
            .next_request_id
            .checked_add(1)
            .ok_or_else(|| invalid_input("request id exhausted"))?;
        let mut request = self.template.clone();
        request.request_id = request_id;
        request.session_generation = self.session_generation;
        request.instruction = instruction.to_owned();
        ControllerPolicy.validate_request(&request)?;
        println!(
            "模型{}输入> {}",
            kind.label(),
            serde_json::to_string(&request)?
        );
        self.record(format!("operator {}: {instruction}", kind.command()));
        self.requests.insert(request_id, request.clone());
        let command_id = self.send_session_command(kind.command(), Some(request))?;
        self.pending_session_commands.insert(
            command_id,
            PendingSessionCommand::Queue { request_id, kind },
        );
        println!(
            "模型{}已提交：request={request_id}；等待有界队列确认。",
            kind.label()
        );
        Ok(())
    }

    fn status(&mut self) -> AppResult<()> {
        let response = self.command("get_state", None)?;
        let worker = response.get("data").unwrap_or(&Value::Null);
        let worker_open = worker.get("open").and_then(Value::as_bool).unwrap_or(false);
        let worker_active = worker
            .get("active")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let queued = worker.get("queued").and_then(Value::as_u64).unwrap_or(0);
        println!(
            "控制器状态：{}；运行模式：{}。",
            controller_state_label(self.template.state),
            self.cruise.mode().label()
        );
        println!(
            "Agent 会话：{}；上游模型：{}；等待处理的消息：{} 条。",
            if worker_open {
                "已打开"
            } else {
                "未打开"
            },
            if worker_active {
                "正在生成下一步"
            } else {
                "空闲"
            },
            queued
        );
        println!(
            "人工批准：{}；下一请求编号：{}；安全代次：{}。",
            if self.pending.is_some() {
                "有计划等待决定"
            } else {
                "没有待处理计划"
            },
            self.next_request_id,
            self.session_generation
        );
        self.print_cruise_status();
        Ok(())
    }

    fn renew(&mut self, state: ControllerState, message: &str) -> AppResult<()> {
        if self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
            || self.agent_cycle_active
        {
            return Err(invalid_input(
                "cannot renew the session while a planning or hardware step is active",
            )
            .into());
        }
        self.command("close_session", None)?;
        self.session_generation = self
            .session_generation
            .checked_add(1)
            .ok_or_else(|| invalid_input("session generation exhausted"))?;
        self.template.state = state;
        self.template.observation.health.recognizer_available = false;
        self.template.session_generation = self.session_generation;
        self.template.observation.recognition = None;
        self.pending = None;
        self.requests.clear();
        self.pending_session_commands.clear();
        self.active_request_id = None;
        self.plan_seen_in_cycle = false;
        self.client.session_generation = self.session_generation;
        self.command("open_session", None)?;
        self.record(message.to_owned());
        println!("{message}；旧计划已失效。");
        Ok(())
    }

    fn approve(&mut self) -> AppResult<()> {
        if self.agent_cycle_active {
            println!("等待模型结束确认后再批准；原计划仍保留。");
            return Ok(());
        }
        if self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
        {
            println!("已有硬件动作正在执行。");
            return Ok(());
        }
        if let Some(plan) = self.pending.take() {
            if matches!(plan.action, ProposedAction::RunLocalRecognition { .. }) {
                let mut current = self.template.clone();
                current.request_id = plan.request_id;
                current.session_generation = self.session_generation;
                refresh_recognizer(&mut current, self.recognizer.as_mut());
                if plan.session_generation != self.session_generation
                    || (self.engineering_recognition.is_none()
                        && !current.observation.health.recognizer_available)
                {
                    println!("识别批准已失效：当前 Worker 未通过准入或会话已经改变。");
                    return Ok(());
                }
            }
            self.record(format!("approved request {}", plan.request_id));
            match plan.action {
                ProposedAction::SurveyBand { .. } => self.start_planned_survey(plan)?,
                ProposedAction::InspectCandidate { .. } => self.start_candidate_inspection(plan)?,
                ProposedAction::CaptureBoundedIq { .. } => {
                    let authorization = ExecutionAuthorization::operator_approved(&plan);
                    self.start_execution(plan, authorization)?;
                }
                ProposedAction::RunLocalRecognition { .. } => self.start_recognition(plan)?,
                _ => println!("request={} 没有可批准的生产执行动作。", plan.request_id),
            }
        } else {
            println!("没有等待批准的计划。")
        }
        Ok(())
    }

    fn audit_recognition(
        &self,
        phase: &'static str,
        request_id: u64,
        generation: u64,
        payload: Value,
    ) -> AppResult<()> {
        use sdr_agent_controller::runner::{AuditEvent, AuditSink, JsonlAuditAdapter};
        if let Some(path) = &self.recognition_audit_path {
            let mut sink = JsonlAuditAdapter::open(path)?;
            sink.append(&AuditEvent{schema_version:1,timestamp_unix_ms:u128::from(sdr_agent_controller::recognition_execution::now_ms()),phase,request_id,session_generation:generation,payload})?;
        } else if self.engineering_recognition.is_some() {
            return Err(invalid_input("engineering recognition audit is required").into());
        }
        Ok(())
    }

    fn propose_recognition(&mut self, candidate_id: &str) -> AppResult<()> {
        if self.agent_cycle_active
            || self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
            || self.pending.is_some()
        {
            println!("当前步骤尚未结束，不能加入工程识别。");
            return Ok(());
        }
        let Some(config) = self.engineering_recognition.clone() else {
            println!("工程识别入口未配置；生产能力仍关闭。");
            return Ok(());
        };
        if !self.refresh_sdr_health(true)? {
            return Ok(());
        }
        let mut request = self.template.clone();
        request.request_id = self.next_request_id;
        request.session_generation = self.session_generation;
        request.instruction = format!("人工请求工程识别候选 {candidate_id}");
        let response: PlanResponse = serde_json::from_value(
            json!({"protocol_version":1,"request_id":request.request_id,"session_generation":request.session_generation,"status":"ok","planner":{"provider":"operator-engineering","model":"rf-v1"},"action":{"kind":"run_local_recognition","candidate_id":candidate_id}}),
        )?;
        let plan = config.validate_plan(&request, response)?;
        self.next_request_id = self
            .next_request_id
            .checked_add(1)
            .ok_or_else(|| invalid_input("request exhausted"))?;
        self.audit_recognition(
            "recognition_proposed",
            plan.request_id,
            plan.session_generation,
            json!({"plan":plan,"maximum_rx_bytes":MAX_RX_BYTES,"engineering_only":true}),
        )?;
        self.pending = Some(plan);
        if self.cruise.is_active() {
            self.cruise.stop(CruiseStopReason::ApprovalRequired);
            self.print_cruise_status();
        }
        println!("工程识别等待人工批准：{} 字节上限（新鲜精查 + 四窗采集），生产能力仍为 false；/approve 或 /reject。",MAX_RX_BYTES);
        Ok(())
    }

    fn start_recognition(&mut self, plan: ValidatedPlan) -> AppResult<()> {
        let Some(config) = self.engineering_recognition.clone() else {
            println!("识别执行器未配置。");
            return Ok(());
        };
        let address = self
            .sdrd_address
            .ok_or_else(|| invalid_input("recognition requires SDRD"))?;
        let mut request = self.template.clone();
        request.request_id = plan.request_id;
        request.session_generation = self.session_generation;
        let cancellation = match self
            .cruise
            .recognition_deadline(Instant::now(), MAX_RX_BYTES)
        {
            Ok(Some(deadline)) => RecognitionCancellation::with_deadline(deadline),
            Ok(None) => RecognitionCancellation::default(),
            Err(reason) => {
                self.cruise.stop(reason);
                self.print_cruise_status();
                return Ok(());
            }
        };
        config.preflight(&request, &plan)?;
        let authorization = ExecutionAuthorization::operator_approved(&plan);
        let signal = cancellation.clone();
        let request_id = plan.request_id;
        let session_generation = plan.session_generation;
        self.audit_recognition(
            "recognition_authorized",
            request_id,
            session_generation,
            json!({"plan":plan,"maximum_rx_bytes":MAX_RX_BYTES,"engineering_only":true}),
        )?;
        let worker = thread::spawn(move || {
            config.execute(address, &request, &plan, &authorization, &signal)
        });
        self.active_recognition = Some(ActiveRecognition {
            request_id,
            session_generation,
            cancellation,
            worker,
        });
        self.template.state = ControllerState::Recognizing;
        self.template.observation.recognition = None;

        if self.cruise.mode() == InteractionMode::AutomaticCruise {
            self.cruise.record_execution(MAX_RX_BYTES);
        }
        self.record(format!("recognition authorized request {request_id} maximum_rx_bytes={MAX_RX_BYTES} engineering_only=true"));
        println!("工程识别 request={request_id} 已开始；/stop 将联合停止并等待恢复确认。");
        Ok(())
    }

    fn poll_recognition(&mut self) -> AppResult<()> {
        if !self
            .active_recognition
            .as_ref()
            .is_some_and(|a| a.worker.is_finished())
        {
            return Ok(());
        }
        let active = self
            .active_recognition
            .take()
            .ok_or_else(|| invalid_input("recognition owner missing"))?;
        let result = active
            .worker
            .join()
            .map_err(|_| invalid_input("recognition worker panicked"))?;
        if active.cancellation.deadline_expired() {
            self.cruise.stop(CruiseStopReason::DurationBudgetExhausted);
        }
        if active.cancellation.cancelled() || active.session_generation != self.session_generation {
            let restored = result.is_ok() || matches!(&result,Err(e) if e.code=="cancelled");
            self.audit_recognition(
                "recognition_cancelled",
                active.request_id,
                active.session_generation,
                json!({"restored":restored,"late_result_discarded":true}),
            )?;
            self.record(format!(
                "recognition cancelled request {} restored={restored}",
                active.request_id
            ));
            let state = if restored {
                ControllerState::Holding
            } else {
                ControllerState::Faulted
            };
            let message = self
                .deferred_renew
                .take()
                .map(|(_, m)| m)
                .unwrap_or_else(|| "识别已停止，迟到结果已丢弃".into());
            if self.agent_cycle_active {
                self.deferred_renew = Some((state, message));
            } else {
                self.renew(state, &message)?;
            }
            return Ok(());
        }
        match result {
            Ok(report) => {
                if report.request_id != active.request_id
                    || report.session_generation != active.session_generation
                {
                    return Err(invalid_input("stale recognition report").into());
                }
                self.audit_recognition("recognition_observation",active.request_id,active.session_generation,json!({"observation":report.result.observation,"archive_id":report.archive_id,"archive_error":report.archive_error,"restored":report.post_execution_sdr.healthy}))?;
                self.template.state = ControllerState::Idle;
                self.template.observation = report.next_observation;
                self.emit_observation()?;
                self.record(format!(
                    "recognition completed request {} archive_id={:?} archive_error={:?}",
                    active.request_id, report.archive_id, report.archive_error
                ));
                println!(
                    "RecognitionObservation> {}",
                    serde_json::to_string(&report.result.observation)?
                );
                println!("识别工程结果：生产状态 {:?}，归档 {:?}，归档错误 {:?}；实验 top-1 不作为独立标签。",report.result.observation.status,report.archive_id,report.archive_error);
                self.auto_next_instruction = None;
                self.audit_recognition(
                    "recognition_feedback_requested",
                    active.request_id,
                    active.session_generation,
                    json!({"feedback_request_id":self.next_request_id,"engineering_only":true}),
                )?;
                // Submit one planning turn even when step mode or the cruise
                // approval gate has stopped automatic execution. Its proposal
                // still follows the normal step/cruise authorization policy.
                self.submit("请依据最新紧凑识别摘要给出一个受限 RX 下一步。当前状态若为 unavailable 或 error，只返回 hold 并解释原因；未标注实验预测不能称为已确认分类。".into())?;
            }
            Err(error) => {
                self.template.state = ControllerState::Faulted;
                self.cruise.stop(CruiseStopReason::Fault);
                self.record(format!(
                    "recognition failed request {}: {}",
                    active.request_id, error.code
                ));
                self.audit_recognition(
                    "recognition_failed",
                    active.request_id,
                    active.session_generation,
                    json!({"code":error.code}),
                )?;
                println!("识别失败：{error}");
            }
        }
        Ok(())
    }

    fn start_execution(
        &mut self,
        plan: ValidatedPlan,
        authorization: ExecutionAuthorization,
    ) -> AppResult<()> {
        let request_id = plan.request_id;
        let Some(mut executor) = self.executor.take() else {
            println!("request={request_id} 未执行：没有配置 SDRD 执行器。");
            if self.cruise.is_active() {
                self.cruise.stop(CruiseStopReason::Fault);
                self.print_cruise_status();
            }
            return Ok(());
        };
        let session_generation = plan.session_generation;
        let canceller = executor.clone();
        let worker = thread::spawn(move || {
            let result = executor.execute(&plan, &authorization);
            (executor, result)
        });
        self.active_execution = Some(ActiveExecution {
            request_id,
            session_generation,
            canceller,
            worker,
        });
        self.cruise.set_phase(CruisePhase::Executing);
        println!("受限硬件动作 request={request_id} 已开始；执行期间可随时输入 /stop。");
        Ok(())
    }

    fn start_initial_survey(&mut self, options: InitialSurveyOptions) -> AppResult<()> {
        if self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
            || self.agent_cycle_active
        {
            return Err(
                invalid_input("cannot start initial survey while another step is active").into(),
            );
        }
        let Some(address) = self.sdrd_address else {
            println!("首次扫频失败：没有配置 SDRD 地址。");
            return Ok(());
        };
        if !self.refresh_sdr_health(true)? {
            println!("首次扫频失败：SDR 健康检查未通过，不会尝试调谐。");
            return Ok(());
        }
        let plan = SweepPlan {
            sweep_id: format!("initial-{}", self.session_generation),
            session_generation: self.session_generation,
            frequencies: SweepFrequencies::Range {
                start_hz: options.start_hz,
                stop_hz: options.stop_hz,
                step_hz: options.step_hz,
            },
            sample_rate_hz: 10_000_000,
            rf_bandwidth_hz: 10_000_000,
            settle_ms: options.dwell_ms,
            frame_samples: 4_096,
            aggregate_frames: 1,
            point_timeout_ms: 250,
            detection_threshold_db: 12.0,
            gain_db: Some(options.gain_db),
        };
        let validated = sdr_agent_controller::sweep::validate_plan(&plan)?;
        let points = validated.centers_hz.len();
        let maximum_bytes = points as u64 * 4_096 * 4;
        let timeout = self.sdrd_timeout.max(Duration::from_millis(500));
        let adapter = self.software_sweep_adapter(address, timeout);
        let mut engine = SweepEngine::new(adapter);
        let worker = thread::spawn(move || engine.run(&plan));
        self.active_sweep = Some(ActiveSweep {
            kind: ActiveSweepKind::Initial,
            session_generation: self.session_generation,
            canceller: SdrdActionAdapter::new(address, timeout),
            worker,
        });
        self.template.state = ControllerState::Surveying;
        println!(
            "首次扫频已开始：{}–{} Hz，{} 个点，步进 {} Hz，每点停留 {} ms，固定接收增益 {} dB；最多处理 {} 字节接收样本，可随时输入 /stop。",
            options.start_hz,
            options.stop_hz,
            points,
            options.step_hz,
            options.dwell_ms,
            options.gain_db,
            maximum_bytes
        );
        Ok(())
    }

    fn start_planned_survey(&mut self, plan: ValidatedPlan) -> AppResult<()> {
        if self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
        {
            return Err(
                invalid_input("cannot start planned survey while another step is active").into(),
            );
        }
        let ProposedAction::SurveyBand {
            start_hz,
            stop_hz,
            step_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
        } = plan.action
        else {
            return Err(invalid_input("planned sweep requires survey_band action").into());
        };
        let Some(address) = self.sdrd_address else {
            println!("自动扫频失败：没有配置 SDRD 地址。");
            if self.cruise.is_active() {
                self.cruise.stop(CruiseStopReason::Fault);
                self.print_cruise_status();
            }
            return Ok(());
        };
        if !self.refresh_sdr_health(true)? {
            println!("自动扫频失败：SDR 健康检查未通过，不会尝试调谐。");
            if self.cruise.is_active() {
                let retrying = self.cruise.record_sdr_unavailable();
                self.next_auto_attempt = Instant::now() + AUTO_RETRY_DELAY;
                if !retrying {
                    self.print_cruise_status();
                }
            }
            return Ok(());
        }
        let sweep = SweepPlan {
            sweep_id: format!("request-{}", plan.request_id),
            session_generation: plan.session_generation,
            frequencies: SweepFrequencies::Range {
                start_hz,
                stop_hz,
                step_hz,
            },
            sample_rate_hz,
            rf_bandwidth_hz,
            settle_ms: dwell_ms,
            frame_samples: 4_096,
            aggregate_frames: 1,
            point_timeout_ms: 250,
            detection_threshold_db: 12.0,
            gain_db: Some(self.survey_gain_db),
        };
        let validated = sdr_agent_controller::sweep::validate_plan(&sweep)?;
        let points = validated.centers_hz.len();
        let maximum_bytes = points as u64 * 4_096 * 4;
        if self.cruise.is_active() && maximum_bytes > self.cruise.remaining_iq_bytes() {
            self.cruise.stop(CruiseStopReason::ByteBudgetExhausted);
            println!(
                "自动扫频未开始：需要处理 {maximum_bytes} 字节，超过巡航剩余接收预算 {} 字节。",
                self.cruise.remaining_iq_bytes()
            );
            self.print_cruise_status();
            return Ok(());
        }
        let timeout = self.sdrd_timeout.max(Duration::from_millis(500));
        let adapter = self.software_sweep_adapter(address, timeout);
        let mut engine = SweepEngine::new(adapter);
        let worker = thread::spawn(move || engine.run(&sweep));
        self.active_sweep = Some(ActiveSweep {
            kind: ActiveSweepKind::Planned {
                request_id: plan.request_id,
                maximum_bytes,
            },
            session_generation: plan.session_generation,
            canceller: SdrdActionAdapter::new(address, timeout),
            worker,
        });
        self.template.state = ControllerState::Surveying;
        self.cruise.set_phase(CruisePhase::Executing);
        println!(
            "自动扫频 request={} 已开始：{}–{} Hz，{} 个点，步进 {} Hz，采样率 {} Hz，射频带宽 {} Hz，每点停留 {} ms，固定接收增益 {} dB；最多处理 {} 字节，可随时输入 /stop。",
            plan.request_id,
            start_hz,
            stop_hz,
            points,
            step_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
            self.survey_gain_db,
            maximum_bytes
        );
        Ok(())
    }

    fn start_candidate_inspection(&mut self, plan: ValidatedPlan) -> AppResult<()> {
        if self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
        {
            return Err(
                invalid_input("cannot inspect a candidate while another step is active").into(),
            );
        }
        let ProposedAction::InspectCandidate {
            candidate_id,
            center_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
        } = plan.action
        else {
            return Err(invalid_input("candidate inspection requires inspect_candidate").into());
        };
        let Some(address) = self.sdrd_address else {
            println!("候选复查失败：没有配置 SDRD 地址。");
            if self.cruise.is_active() {
                self.cruise.stop(CruiseStopReason::Fault);
                self.print_cruise_status();
            }
            return Ok(());
        };
        if !self.refresh_sdr_health(true)? {
            println!("候选复查失败：SDR 健康检查未通过，不会尝试调谐。");
            if self.cruise.is_active() {
                let retrying = self.cruise.record_sdr_unavailable();
                self.next_auto_attempt = Instant::now() + AUTO_RETRY_DELAY;
                if !retrying {
                    self.print_cruise_status();
                }
            }
            return Ok(());
        }
        let sweep = SweepPlan {
            sweep_id: format!("inspect-{}", plan.request_id),
            session_generation: plan.session_generation,
            frequencies: SweepFrequencies::Centers {
                centers_hz: vec![center_hz],
            },
            sample_rate_hz,
            rf_bandwidth_hz,
            settle_ms: dwell_ms,
            frame_samples: 4_096,
            aggregate_frames: 1,
            point_timeout_ms: 250,
            detection_threshold_db: 12.0,
            gain_db: Some(self.survey_gain_db),
        };
        sdr_agent_controller::sweep::validate_plan(&sweep)?;
        let maximum_bytes = 4_096_u64 * 4;
        if self.cruise.is_active() && maximum_bytes > self.cruise.remaining_iq_bytes() {
            self.cruise.stop(CruiseStopReason::ByteBudgetExhausted);
            println!(
                "候选复查未开始：需要处理 {maximum_bytes} 字节，超过巡航剩余接收预算 {} 字节。",
                self.cruise.remaining_iq_bytes()
            );
            self.print_cruise_status();
            return Ok(());
        }
        let timeout = self.sdrd_timeout.max(Duration::from_millis(500));
        let adapter = self.software_sweep_adapter(address, timeout);
        let mut engine = SweepEngine::new(adapter);
        let worker = thread::spawn(move || engine.run(&sweep));
        self.active_sweep = Some(ActiveSweep {
            kind: ActiveSweepKind::Inspection {
                request_id: plan.request_id,
                candidate_id: candidate_id.clone(),
                maximum_bytes,
            },
            session_generation: plan.session_generation,
            canceller: SdrdActionAdapter::new(address, timeout),
            worker,
        });
        self.template.state = ControllerState::Inspecting;
        self.cruise.set_phase(CruisePhase::Executing);
        println!(
            "候选复查 request={} 已开始：候选 {}，中心 {} Hz，带宽 {} Hz，驻留 {} ms，固定接收增益 {} dB；最多处理 {} 字节，可随时输入 /stop。",
            plan.request_id,
            candidate_id,
            center_hz,
            rf_bandwidth_hz,
            dwell_ms,
            self.survey_gain_db,
            maximum_bytes
        );
        Ok(())
    }

    fn software_sweep_adapter(
        &self,
        address: SocketAddr,
        timeout: Duration,
    ) -> SdrdSoftwareSweepAdapter {
        let adapter = SdrdSoftwareSweepAdapter::new(address, timeout);
        self.sigmf_directory
            .as_ref()
            .map_or(adapter.clone(), |directory| {
                adapter.with_sigmf_directory(directory)
            })
    }

    fn poll_sweep(&mut self) -> AppResult<()> {
        let finished = self
            .active_sweep
            .as_ref()
            .is_some_and(|active| active.worker.is_finished());
        if !finished {
            return Ok(());
        }
        let active = self
            .active_sweep
            .take()
            .ok_or_else(|| invalid_input("missing active sweep"))?;
        let kind = active.kind;
        let result = active
            .worker
            .join()
            .map_err(|_| invalid_input("survey worker panicked"))?;
        match result {
            Ok(report) => {
                if !self.refresh_sdr_health(true)? {
                    self.template.state = ControllerState::Faulted;
                    println!("扫频失败：结束后 SDR 健康或状态恢复检查未通过。");
                    if self.cruise.is_active() {
                        self.cruise.stop(CruiseStopReason::Fault);
                        self.print_cruise_status();
                    }
                    return Ok(());
                }
                let health = self.template.observation.health.clone();
                self.template.state = ControllerState::Idle;
                if !matches!(&kind, ActiveSweepKind::Inspection { .. }) {
                    self.emit_sweep_plot(&report, &kind)?;
                }
                match kind {
                    ActiveSweepKind::Initial => {
                        self.template.observation =
                            report.planner_observation(0, health, self.survey_gain_db);
                        self.record(format!(
                            "initial survey completed with {} candidates",
                            report.candidates.len()
                        ));
                        println!(
                            "首次扫频完成：{} 个频点，耗时 {} ms，噪声基线 {:.1} dBFS，发现 {} 个候选；射频状态已恢复。",
                            report.points.len(),
                            report.elapsed_ms,
                            report.noise_floor_dbfs,
                            report.candidates.len()
                        );
                    }
                    ActiveSweepKind::Planned {
                        request_id,
                        maximum_bytes,
                    } => {
                        self.template.observation =
                            report.planner_observation(0, health, self.survey_gain_db);
                        self.record(format!(
                            "executed survey request {request_id} with {} candidates",
                            report.candidates.len()
                        ));
                        println!(
                            "扫频执行结果：request={request_id} 已完成 {} 个频点，耗时 {} ms，固定增益 {} dB，噪声基线 {:.1} dBFS，发现 {} 个候选；零削顶，射频状态已恢复。",
                            report.points.len(),
                            report.elapsed_ms,
                            self.survey_gain_db,
                            report.noise_floor_dbfs,
                            report.candidates.len()
                        );
                        if self.cruise.is_active() {
                            self.cruise.record_execution(maximum_bytes);
                            if self.cruise.is_active() {
                                let mission =
                                    self.auto_mission.as_deref().unwrap_or("继续受限巡航");
                                self.auto_next_instruction = Some(format!(
                                    "自动巡航任务：{mission}\n上一步 survey_band request={request_id} 已执行：{} 个频点、固定增益 {} dB、噪声基线 {:.1} dBFS、{} 个候选、处理 {} 字节，零削顶且射频状态已恢复。最新候选已写入 PlanningContext，请根据真实结果只给出下一步。",
                                    report.points.len(),
                                    self.survey_gain_db,
                                    report.noise_floor_dbfs,
                                    report.candidates.len(),
                                    maximum_bytes
                                ));
                                self.next_auto_attempt = Instant::now();
                            }
                            self.print_cruise_status();
                        }
                    }
                    ActiveSweepKind::Inspection {
                        request_id,
                        candidate_id,
                        maximum_bytes,
                    } => {
                        self.template.observation = report.planner_inspection_observation(
                            &self.template.observation,
                            &candidate_id,
                            health,
                        )?;
                        let candidate = self
                            .template
                            .observation
                            .candidates
                            .iter()
                            .find(|candidate| candidate.id == candidate_id)
                            .cloned()
                            .ok_or_else(|| invalid_input("missing inspected candidate"))?;
                        self.record(format!(
                            "inspected candidate {candidate_id} for request {request_id}"
                        ));
                        println!(
                            "候选复查结果：request={request_id}，候选 {candidate_id}，中心 {} Hz，带宽 {} Hz，实测功率 {:.1} dBFS，参考信噪比 {:.1} dB；零削顶，射频状态已恢复。",
                            candidate.center_hz,
                            candidate.bandwidth_hz,
                            candidate.peak_dbfs,
                            candidate.snr_db
                        );
                        if self.cruise.is_active() {
                            self.cruise.record_execution(maximum_bytes);
                            if self.cruise.is_active() {
                                let mission =
                                    self.auto_mission.as_deref().unwrap_or("继续受限巡航");
                                self.auto_next_instruction = Some(format!(
                                    "自动巡航任务：{mission}\n上一步 inspect_candidate request={request_id} 已真实复查候选 {candidate_id}：中心 {} Hz、带宽 {} Hz、固定增益 {} dB、实测功率 {:.1} dBFS、参考信噪比 {:.1} dB、处理 {} 字节，零削顶且射频状态已恢复。请根据最新候选只给出下一步。",
                                    candidate.center_hz,
                                    candidate.bandwidth_hz,
                                    self.survey_gain_db,
                                    candidate.peak_dbfs,
                                    candidate.snr_db,
                                    maximum_bytes
                                ));
                                self.next_auto_attempt = Instant::now();
                            }
                            self.print_cruise_status();
                        }
                    }
                }
                self.emit_observation()?;
                for candidate in report.candidates.iter().take(8) {
                    println!(
                        "候选 {}：中心 {} Hz，带宽 {} Hz，峰值 {:.1} dBFS，信噪比 {:.1} dB。",
                        candidate.id,
                        candidate.center_hz,
                        candidate.bandwidth_hz,
                        candidate.peak_dbfs,
                        candidate.snr_db
                    );
                }
            }
            Err(error) => {
                self.template.state = ControllerState::Holding;
                match kind {
                    ActiveSweepKind::Initial => {
                        self.record(format!("initial survey failed: {error}"));
                        println!("首次扫频失败：{error}。SDRD 已执行停止与状态恢复路径。");
                    }
                    ActiveSweepKind::Planned { request_id, .. } => {
                        self.record(format!("survey request {request_id} failed: {error}"));
                        println!(
                            "自动扫频失败：request={request_id}，{error}。SDRD 已执行停止与状态恢复路径。"
                        );
                        if self.cruise.is_active() {
                            self.cruise.stop(CruiseStopReason::Fault);
                            self.print_cruise_status();
                        }
                    }
                    ActiveSweepKind::Inspection {
                        request_id,
                        candidate_id,
                        ..
                    } => {
                        self.record(format!(
                            "candidate inspection request {request_id} failed: {error}"
                        ));
                        println!(
                            "候选复查失败：request={request_id}，候选 {candidate_id}，{error}。SDRD 已执行停止与状态恢复路径。"
                        );
                        if self.cruise.is_active() {
                            self.cruise.stop(CruiseStopReason::Fault);
                            self.print_cruise_status();
                        }
                    }
                }
            }
        }
        Ok(())
    }

    fn reject(&mut self) {
        if let Some(plan) = self.pending.take() {
            self.record(format!("rejected request {}", plan.request_id));
            println!("已拒绝 request={}。", plan.request_id);
        } else {
            println!("没有等待拒绝的计划。")
        }
    }

    fn poll_execution(&mut self) -> AppResult<()> {
        let finished = self
            .active_execution
            .as_ref()
            .is_some_and(|active| active.worker.is_finished());
        if !finished {
            return Ok(());
        }
        let active = self
            .active_execution
            .take()
            .ok_or_else(|| invalid_input("missing active execution"))?;
        let request_id = active.request_id;
        let (executor, result) = active
            .worker
            .join()
            .map_err(|_| invalid_input("hardware execution worker panicked"))?;
        self.executor = Some(executor);
        match result {
            Ok(observation) => {
                self.record(format!("executed request {request_id}"));
                self.template.observation.age_ms = 0;
                self.template.observation.health = observation
                    .post_execution_sdr
                    .planner_health(false, self.template.observation.health.dropped_observations);
                self.emit_observation()?;
                println!(
                    "执行结果：request={request_id} 已安全采集 {} 个复数样本（{} 字节）；丢样 {}，溢出 {}，射频状态已恢复。",
                    observation.capture.samples_captured,
                    observation.capture.bytes_written,
                    observation.capture.dropped_samples,
                    if observation.capture.overflow { "是" } else { "否" }
                );
                if self.cruise.is_active() {
                    self.cruise
                        .record_execution(observation.capture.bytes_written);
                    if self.cruise.is_active() {
                        let mission = self.auto_mission.as_deref().unwrap_or("继续受限巡航");
                        self.auto_next_instruction = Some(format!(
                            "自动巡航任务：{mission}\n上一步 request={request_id} 已完成，采集 {} 个样本、{} 字节、丢样 {}、溢出 {}，并已恢复射频状态。请根据这个结果和最新健康状态只给出下一步。",
                            observation.capture.samples_captured,
                            observation.capture.bytes_written,
                            observation.capture.dropped_samples,
                            observation.capture.overflow
                        ));
                        self.next_auto_attempt = Instant::now();
                    }
                    self.print_cruise_status();
                }
            }
            Err(error) => {
                self.record(format!("execution failed request {request_id}: {error}"));
                println!("执行失败：{error}");
                if self.cruise.is_active() && !self.refresh_sdr_health(true)? {
                    let retrying = self.cruise.record_sdr_unavailable();
                    self.next_auto_attempt = Instant::now() + AUTO_RETRY_DELAY;
                    println!(
                        "SDR 连通性重试：第 {}/{} 次{}。",
                        self.cruise.snapshot(Instant::now()).sdr_retry_count,
                        AUTO_RETRY_LIMIT,
                        if retrying {
                            "，10 秒后重试"
                        } else {
                            "，巡航退出"
                        }
                    );
                    self.print_cruise_status();
                } else {
                    self.cruise.stop(CruiseStopReason::Fault);
                    self.template.state = ControllerState::Faulted;
                    self.print_cruise_status();
                }
            }
        }
        Ok(())
    }

    fn stop(&mut self, message: &str) -> AppResult<()> {
        if self.cruise.is_active() {
            self.cruise.stop(CruiseStopReason::OperatorStopped);
            self.auto_mission = None;
            self.auto_next_instruction = None;
            self.print_cruise_status();
        }
        if self.agent_cycle_active {
            self.request_agent_abort()?;
            if self.agent_cycle_active {
                self.deferred_renew = Some((ControllerState::Holding, message.to_owned()));
            }
            println!("已要求上游停止当前生成；收到结束确认后会使旧计划失效。");
        }
        if let Some(active) = &self.active_recognition {
            active.cancellation.cancel();
            self.deferred_renew = Some((ControllerState::Holding, message.to_owned()));
            println!("已请求联合停止 SDR/Worker；回收和恢复确认前不接受新动作。");
            return Ok(());
        }
        if self.active_sweep.is_some() {
            return self.stop_sweep(message);
        }
        if self.active_execution.is_none() {
            if self.agent_cycle_active {
                return Ok(());
            }
            self.deferred_renew = None;
            return self.renew(ControllerState::Holding, message);
        }

        let mut attempts = 0_usize;
        let cancel_result = loop {
            let result = {
                let active = self
                    .active_execution
                    .as_mut()
                    .ok_or_else(|| invalid_input("missing active execution"))?;
                active.canceller.cancel(active.session_generation)
            };
            let retry = matches!(
                &result,
                Err(error)
                    if error.code == "remote_error"
                        && error.message == "stale_or_missing_session"
            ) && self
                .active_execution
                .as_ref()
                .is_some_and(|active| !active.worker.is_finished());
            if !retry {
                break result;
            }
            if attempts >= CANCEL_START_RETRIES {
                break result;
            }
            attempts += 1;
            thread::sleep(Duration::from_millis(10));
        };
        if let Err(error) = cancel_result {
            let already_finished = self
                .active_execution
                .as_ref()
                .is_some_and(|active| active.worker.is_finished());
            if already_finished {
                self.poll_execution()?;
                return self.renew(ControllerState::Holding, message);
            }
            println!("取消请求失败，硬件动作仍由当前会话持有：{error}");
            return Ok(());
        }

        let active = self
            .active_execution
            .take()
            .ok_or_else(|| invalid_input("missing active execution"))?;
        let request_id = active.request_id;
        let (executor, execution_result) = active
            .worker
            .join()
            .map_err(|_| invalid_input("hardware execution worker panicked after cancellation"))?;
        self.executor = Some(executor);
        self.record(format!("cancelled request {request_id}"));
        match execution_result {
            Ok(observation) => println!(
                "取消请求到达时动作已完成：{}",
                serde_json::to_string(&observation)?
            ),
            Err(error) => println!("硬件动作已取消并完成恢复：{error}"),
        }
        if self.agent_cycle_active {
            self.deferred_renew = Some((ControllerState::Holding, message.to_owned()));
            Ok(())
        } else {
            self.renew(ControllerState::Holding, message)
        }
    }

    fn stop_sweep(&mut self, message: &str) -> AppResult<()> {
        let mut attempts = 0_usize;
        let cancel_result = loop {
            let result = {
                let active = self
                    .active_sweep
                    .as_mut()
                    .ok_or_else(|| invalid_input("missing active sweep"))?;
                active.canceller.cancel(active.session_generation)
            };
            let retry = matches!(
                &result,
                Err(error)
                    if error.code == "remote_error" && error.message == "stale_or_missing_session"
            ) && self
                .active_sweep
                .as_ref()
                .is_some_and(|active| !active.worker.is_finished());
            if !retry || attempts >= CANCEL_START_RETRIES {
                break result;
            }
            attempts += 1;
            thread::sleep(Duration::from_millis(10));
        };
        if let Err(error) = cancel_result {
            if self
                .active_sweep
                .as_ref()
                .is_some_and(|active| active.worker.is_finished())
            {
                self.poll_sweep()?;
                return self.renew(ControllerState::Holding, message);
            }
            println!("扫频取消请求失败，SDR 仍由当前会话持有：{error}");
            return Ok(());
        }
        let active = self
            .active_sweep
            .take()
            .ok_or_else(|| invalid_input("missing active sweep"))?;
        let kind = active.kind;
        let result = active
            .worker
            .join()
            .map_err(|_| invalid_input("survey worker panicked after cancellation"))?;
        match (kind, result) {
            (ActiveSweepKind::Initial, Ok(report)) => {
                println!("取消到达前扫频已完成：{} 个频点。", report.points.len())
            }
            (ActiveSweepKind::Initial, Err(error)) => {
                println!("首次扫频已取消并完成恢复：{error}")
            }
            (ActiveSweepKind::Planned { request_id, .. }, Ok(report)) => println!(
                "取消到达前自动扫频 request={request_id} 已完成：{} 个频点。",
                report.points.len()
            ),
            (ActiveSweepKind::Planned { request_id, .. }, Err(error)) => {
                println!("自动扫频 request={request_id} 已取消并完成恢复：{error}")
            }
            (
                ActiveSweepKind::Inspection {
                    request_id,
                    candidate_id,
                    ..
                },
                Ok(_),
            ) => println!("取消到达前候选复查 request={request_id}、候选 {candidate_id} 已完成。"),
            (
                ActiveSweepKind::Inspection {
                    request_id,
                    candidate_id,
                    ..
                },
                Err(error),
            ) => println!(
                "候选复查 request={request_id}、候选 {candidate_id} 已取消并完成恢复：{error}"
            ),
        }
        self.renew(ControllerState::Holding, message)
    }

    fn request_agent_abort(&mut self) -> AppResult<()> {
        if self
            .pending_session_commands
            .values()
            .any(|pending| matches!(pending, PendingSessionCommand::Abort))
        {
            return Ok(());
        }
        let command_id = self.send_session_command("abort", None)?;
        self.pending_session_commands
            .insert(command_id, PendingSessionCommand::Abort);
        Ok(())
    }

    fn enable_step_approval(&mut self) -> AppResult<()> {
        if self.cruise.mode() == InteractionMode::StepApproval && !self.cruise.is_active() {
            println!("当前已经是逐步人工批准模式。每个可执行动作都会等待 /approve 或 /reject。");
            return Ok(());
        }
        let had_active_step = self.agent_cycle_active
            || self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some();
        if had_active_step {
            self.stop("已切换到逐步人工批准模式")?;
        }
        self.cruise.switch_to_step_approval();
        self.auto_mission = None;
        self.auto_next_instruction = None;
        if !had_active_step {
            self.renew(ControllerState::Idle, "已切换到逐步人工批准模式")?;
        }
        println!("已切换到逐步人工批准模式；自动巡航已关闭，旧自动计划不会继续执行。");
        Ok(())
    }

    fn start_auto(
        &mut self,
        mission: &str,
        max_steps: u8,
        max_duration_secs: u64,
        max_iq_bytes: Option<u64>,
    ) -> AppResult<()> {
        if mission.is_empty() || mission.len() > 700 || mission.chars().any(char::is_control) {
            return Err(invalid_input("自动巡航任务必须为 1–700 字节的单行文本").into());
        }
        if self.agent_cycle_active
            || self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
        {
            println!("当前步骤尚未结束；请先 /stop，再启动新的自动巡航。");
            return Ok(());
        }
        if self.pending.is_some() {
            println!("仍有计划等待人工决定；请先 /approve、/reject 或 /stop。");
            return Ok(());
        }
        let max_iq_bytes = max_iq_bytes.unwrap_or_else(|| {
            self.template
                .limits
                .max_iq_bytes
                .saturating_mul(u64::from(max_steps))
        });
        if max_iq_bytes == 0 {
            return Err(invalid_input("无法从步骤数推导有限 IQ 预算").into());
        }
        self.renew(ControllerState::Idle, "自动巡航已建立新的安全代次")?;
        self.cruise
            .start(max_iq_bytes, max_steps, max_duration_secs, Instant::now())
            .map_err(invalid_input)?;
        self.auto_mission = Some(mission.to_owned());
        self.auto_next_instruction = Some(format!(
            "自动巡航任务：{mission}\n本巡航最多 {max_steps} 个已执行步骤、{max_duration_secs} 秒、累计 {} 字节 IQ；SDR 不可用或上游未给出下一步各自连续重试 5 次，每次间隔 10 秒。只能提出 Rust Controller 能验证的接收动作，安全边界不变。请给出第一步。",
            max_iq_bytes
        ));
        self.next_auto_attempt = Instant::now();
        println!(
            "已启动受限自动巡航：最多 {max_steps} 步、{max_duration_secs} 秒、{} 字节；两类失败分别最多重试 5 次、间隔 10 秒。输入 /stop 可立即停止。",
            max_iq_bytes
        );
        self.print_cruise_status();
        Ok(())
    }

    fn poll(&mut self) -> AppResult<()> {
        self.poll_recognition()?;
        while let Some(frame) = self.client.try_read()? {
            self.handle_frame(frame)?;
        }
        self.poll_execution()?;
        self.poll_sweep()?;
        if !self.agent_cycle_active
            && self.active_execution.is_none()
            && self.active_sweep.is_none()
            && self.active_recognition.is_none()
        {
            if let Some((state, message)) = self.deferred_renew.take() {
                self.renew(state, &message)?;
            }
        }
        Ok(())
    }

    fn advance_auto(&mut self) -> AppResult<()> {
        if !self.cruise.is_active() {
            return Ok(());
        }
        if !self.cruise.check_duration(Instant::now()) {
            self.print_cruise_status();
            if self.agent_cycle_active
                || self.active_execution.is_some()
                || self.active_sweep.is_some()
                || self.active_recognition.is_some()
            {
                self.stop("自动巡航达到时长上限")?;
            }
            return Ok(());
        }
        if self.agent_cycle_active
            || self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
            || self.pending.is_some()
            || Instant::now() < self.next_auto_attempt
        {
            return Ok(());
        }
        self.cruise.set_phase(CruisePhase::CheckingSdr);
        if !self.refresh_sdr_health(true)? {
            let retrying = self.cruise.record_sdr_unavailable();
            self.next_auto_attempt = Instant::now() + AUTO_RETRY_DELAY;
            println!(
                "SDR 连通性重试：第 {}/{} 次{}。",
                self.cruise.snapshot(Instant::now()).sdr_retry_count,
                AUTO_RETRY_LIMIT,
                if retrying {
                    "，10 秒后重试"
                } else {
                    "，巡航退出"
                }
            );
            self.print_cruise_status();
            return Ok(());
        }
        self.cruise.record_sdr_available();
        let instruction = self.auto_next_instruction.take().unwrap_or_else(|| {
            format!(
                "自动巡航任务：{}\n请根据最新状态给出下一步。",
                self.auto_mission.as_deref().unwrap_or("继续受限巡航")
            )
        });
        self.cruise.set_phase(CruisePhase::WaitingForPlanner);
        self.print_cruise_status();
        self.submit(instruction)
    }

    fn refresh_recognition(&mut self) {
        let mut request = self.template.clone();
        request.request_id = self.next_request_id;
        request.session_generation = self.session_generation;
        refresh_recognizer(&mut request, self.recognizer.as_mut());
        self.template.observation.health.recognizer_available =
            request.observation.health.recognizer_available;
        self.template.observation.recognition = request.observation.recognition;
    }

    fn refresh_sdr_health(&mut self, announce_failure: bool) -> AppResult<bool> {
        self.template.observation.health.recognizer_available = false;
        let Some(address) = self.sdrd_address else {
            if announce_failure {
                println!("SDR 检查失败：没有配置 SDRD 地址。");
            }
            self.refresh_recognition();
            return Ok(false);
        };
        let mut observer = SdrdAdapter::new(address, self.sdrd_timeout);
        let result = match observer.observe() {
            Ok(snapshot) if snapshot.online && snapshot.healthy => {
                self.template.observation.age_ms = 0;
                self.template.observation.health = snapshot
                    .planner_health(false, self.template.observation.health.dropped_observations);
                Ok(true)
            }
            Ok(snapshot) => {
                self.template.observation.age_ms = 0;
                self.template.observation.health = snapshot
                    .planner_health(false, self.template.observation.health.dropped_observations);
                if announce_failure {
                    println!("SDR 检查未通过：设备有响应，但健康状态异常。");
                }
                Ok(false)
            }
            Err(error) => {
                self.template.observation.health.sdr_online = false;
                self.template.observation.health.can_retune = false;
                self.template.observation.health.can_capture_iq = false;
                if announce_failure {
                    println!("SDR 检查失败：{error}");
                }
                Ok(false)
            }
        };
        self.refresh_recognition();
        result
    }

    fn print_cruise_status(&self) {
        let snapshot = self.cruise.snapshot(Instant::now());
        if snapshot.mode == InteractionMode::StepApproval {
            println!("巡航状态：未启用；当前每个可执行动作都需要人工批准。");
            return;
        }
        if snapshot.active {
            println!(
                "巡航状态：{}；已完成 {}/{} 步，累计 {:.1}/{:.1} MiB，SDR 重试 {}/{}，上游重试 {}/{}。",
                snapshot.phase_label,
                snapshot.completed_steps,
                snapshot.max_steps,
                snapshot.used_iq_bytes as f64 / (1024.0 * 1024.0),
                snapshot.max_iq_bytes as f64 / (1024.0 * 1024.0),
                snapshot.sdr_retry_count,
                snapshot.retry_limit,
                snapshot.planner_retry_count,
                snapshot.retry_limit
            );
        } else {
            println!(
                "巡航状态：已退出；原因：{}。",
                snapshot.stop_reason_label.unwrap_or("尚未启动")
            );
        }
    }

    fn close(&mut self) -> AppResult<()> {
        if self.active_execution.is_some()
            || self.active_sweep.is_some()
            || self.active_recognition.is_some()
            || self.agent_cycle_active
        {
            self.stop("终端关闭，硬件动作已停止")?;
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        while self.agent_cycle_active && Instant::now() < deadline {
            self.poll()?;
            thread::sleep(Duration::from_millis(10));
        }
        if !self.agent_cycle_active {
            let _ = self.command("close_session", None);
        }
        Ok(())
    }

    fn command(&mut self, kind: &str, context: Option<PlanRequest>) -> AppResult<Value> {
        let command_id = self.send_session_command(kind, context)?;
        loop {
            let frame = self.client.read()?;
            if frame.get("type").and_then(Value::as_str) == Some("response")
                && frame.get("command_id").and_then(Value::as_u64) == Some(command_id)
            {
                if frame.get("session_generation").and_then(Value::as_u64)
                    != Some(self.session_generation)
                {
                    return Err(invalid_input("stale session response").into());
                }
                if frame.get("success").and_then(Value::as_bool) != Some(true) {
                    return Err(invalid_input(
                        frame
                            .get("error")
                            .and_then(Value::as_str)
                            .unwrap_or("session command failed"),
                    )
                    .into());
                }
                return Ok(frame);
            }
            self.handle_frame(frame)?;
        }
    }

    fn send_session_command(&mut self, kind: &str, context: Option<PlanRequest>) -> AppResult<u64> {
        let command_id = self.client.next_command_id();
        let mut command = json!({
            "protocol_version": 1,
            "command_id": command_id,
            "session_generation": self.session_generation,
            "type": kind,
        });
        if let Some(context) = context {
            command["context"] = serde_json::to_value(context)?;
        }
        self.client.write(&command)?;
        Ok(command_id)
    }

    fn handle_frame(&mut self, frame: Value) -> AppResult<()> {
        match frame.get("type").and_then(Value::as_str) {
            Some("event") => self.handle_event(frame),
            Some("response") => self.handle_session_response(frame),
            _ => Err(invalid_input("unknown session frame type").into()),
        }
    }

    fn handle_session_response(&mut self, frame: Value) -> AppResult<()> {
        let command_id = frame
            .get("command_id")
            .and_then(Value::as_u64)
            .ok_or_else(|| invalid_input("session response is missing command_id"))?;
        let response_generation = frame
            .get("session_generation")
            .and_then(Value::as_u64)
            .ok_or_else(|| invalid_input("session response is missing session_generation"))?;
        let Some(pending) = self.pending_session_commands.remove(&command_id) else {
            if response_generation != self.session_generation {
                println!("已忽略过期 session response；当前安全代次未改变。");
                return Ok(());
            }
            return Err(invalid_input("session response has no pending command").into());
        };
        if response_generation != self.session_generation {
            if let PendingSessionCommand::Prompt { request_id }
            | PendingSessionCommand::Queue { request_id, .. } = pending
            {
                self.requests.remove(&request_id);
            }
            println!("已拒绝过期 session response；当前安全代次未改变。");
            return Ok(());
        }
        let success = frame.get("success").and_then(Value::as_bool) == Some(true);
        let error = frame
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("session command failed")
            .to_owned();
        match pending {
            PendingSessionCommand::Prompt { request_id } if !success => {
                self.requests.remove(&request_id);
                if self.active_request_id == Some(request_id) {
                    self.active_request_id = None;
                }
                self.agent_cycle_active = false;
                self.plan_seen_in_cycle = false;
                if self.cruise.is_active() {
                    let retrying = self.cruise.record_planner_missing();
                    self.next_auto_attempt = Instant::now() + AUTO_RETRY_DELAY;
                    println!(
                        "上游下一步重试：第 {}/{} 次；本次未开始：{}{}。",
                        self.cruise.snapshot(Instant::now()).planner_retry_count,
                        AUTO_RETRY_LIMIT,
                        error,
                        if retrying {
                            "，10 秒后重试"
                        } else {
                            "，巡航退出"
                        }
                    );
                    self.print_cruise_status();
                } else {
                    println!("上游模型未接受本轮输入：{error}");
                }
            }
            PendingSessionCommand::Prompt { .. } => {}
            PendingSessionCommand::Queue { request_id, kind } if success => {
                let queued = frame
                    .pointer("/data/queued")
                    .and_then(Value::as_u64)
                    .unwrap_or(0);
                println!(
                    "已加入模型{}队列：request={request_id}，当前排队 {queued}/{TERMINAL_INPUT_QUEUE_LIMIT}。",
                    kind.label()
                );
            }
            PendingSessionCommand::Queue { request_id, kind } => {
                self.requests.remove(&request_id);
                println!("模型{}输入被拒绝：{error}", kind.label());
            }
            PendingSessionCommand::Abort if !success => {
                println!("上游停止请求被拒绝：{error}");
            }
            PendingSessionCommand::Abort => {}
        }
        Ok(())
    }

    fn handle_event(&mut self, frame: Value) -> AppResult<()> {
        if frame.get("type").and_then(Value::as_str) != Some("event") {
            return Ok(());
        }
        if frame.get("session_generation").and_then(Value::as_u64) != Some(self.session_generation)
        {
            println!("已忽略过期 session event；当前安全代次未改变。");
            return Ok(());
        }
        match frame.get("event").and_then(Value::as_str).unwrap_or("") {
            "thinking_start" | "thinking_delta" | "thinking_end" => {
                let data = frame
                    .get("data")
                    .cloned()
                    .ok_or_else(|| invalid_input("thinking event is missing data"))?;
                let request_id = data
                    .get("request_id")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| invalid_input("thinking event is missing request_id"))?;
                if !self.requests.contains_key(&request_id) {
                    return Err(invalid_input("thinking event refers to an unknown request").into());
                }
                if data.get("delta").is_some_and(|delta| !delta.is_string()) {
                    return Err(invalid_input("thinking delta must be text").into());
                }
                let label = match frame.get("event").and_then(Value::as_str) {
                    Some("thinking_start") => "ThinkingStart",
                    Some("thinking_delta") => "ThinkingDelta",
                    _ => "ThinkingEnd",
                };
                println!("{label}> {}", serde_json::to_string(&data)?);
            }
            "web_search_start" | "web_search_end" | "web_search_error" => {
                for line in describe_web_search_event(&frame, &self.requests)? {
                    println!("{line}");
                }
            }
            "assistant_message" => {
                if let Some(text) = frame.pointer("/data/text").and_then(Value::as_str) {
                    if !text.trim().is_empty() {
                        println!("Agent> {text}");
                        self.record(format!("agent: {text}"));
                    }
                }
            }
            "plan_proposed" => {
                let response: PlanResponse = serde_json::from_value(
                    frame
                        .get("data")
                        .cloned()
                        .ok_or_else(|| invalid_input("missing plan"))?,
                )?;
                let mut request = self
                    .requests
                    .get(&response.request_id)
                    .cloned()
                    .ok_or_else(|| invalid_input("plan refers to an unknown request"))?;
                refresh_recognizer(&mut request, self.recognizer.as_mut());
                let plan = if let Some(config) = &self.engineering_recognition {
                    config.validate_plan(&request, response)?
                } else {
                    ControllerPolicy.validate_response(&request, response)?
                };
                let decision_basis = describe_decision_basis(&plan, &request);
                let requires_early_abort = matches!(
                    &plan.action,
                    ProposedAction::CaptureBoundedIq { .. }
                        | ProposedAction::SurveyBand { .. }
                        | ProposedAction::InspectCandidate { .. }
                        | ProposedAction::RunLocalRecognition { .. }
                );
                self.plan_seen_in_cycle = true;
                self.cruise.record_planner_action();
                println!("已验证计划：{}", describe_plan(&plan));
                println!("决策依据> {decision_basis}");
                let agent_reply = describe_agent_reply(&plan, self.cruise.mode());
                println!("Agent> {agent_reply}");
                self.record(format!("agent: {agent_reply}"));
                self.record(format!("validated request {}", plan.request_id));
                match self.cruise.mode() {
                    InteractionMode::StepApproval => {
                        if matches!(
                            plan.action,
                            ProposedAction::CaptureBoundedIq { .. }
                                | ProposedAction::SurveyBand { .. }
                                | ProposedAction::InspectCandidate { .. }
                                | ProposedAction::RunLocalRecognition { .. }
                        ) {
                            if self.pending.is_some() {
                                return Err(
                                    invalid_input("a validated plan is already pending").into()
                                );
                            }
                            self.pending = Some(plan);
                            println!("逐步批准模式：输入 /approve 执行，或输入 /reject 拒绝。")
                        } else {
                            println!("该计划当前没有生产执行器，仅记录建议，不会操作硬件。");
                        }
                    }
                    InteractionMode::AutomaticCruise if !self.cruise.is_active() => {
                        println!("该计划到达时巡航已经停止，已作为过期计划忽略，不会执行。")
                    }
                    InteractionMode::AutomaticCruise => match &plan.action {
                        _ if plan.approval_required => {
                            self.pending = Some(plan);
                            self.cruise.stop(CruiseStopReason::ApprovalRequired);
                            println!("自动巡航不会代替人工批准；计划已停在批准门前。");
                            self.print_cruise_status();
                        }
                        ProposedAction::CaptureBoundedIq { .. } => {
                            let authorization = ExecutionAuthorization::automatic(&plan)?;
                            self.start_execution(plan, authorization)?;
                        }
                        ProposedAction::SurveyBand { .. } => {
                            self.start_planned_survey(plan)?;
                        }
                        ProposedAction::InspectCandidate { .. } => {
                            self.start_candidate_inspection(plan)?;
                        }
                        ProposedAction::Hold { .. } | ProposedAction::StopSession { .. } => {
                            self.cruise.stop(CruiseStopReason::PlannerRequestedStop);
                            self.print_cruise_status();
                        }
                        _ => {
                            self.cruise.stop(CruiseStopReason::UnsupportedAction);
                            println!("自动巡航已停止：该建议尚无生产执行器，不能伪装成已执行。");
                            self.print_cruise_status();
                        }
                    },
                }
                if self.agent_cycle_active && requires_early_abort {
                    self.request_agent_abort()?;
                    println!(
                        "可执行计划已经 Rust 验证；已结束本轮剩余模型生成，避免队列中的旧输入越过批准或执行门禁。"
                    );
                }
            }
            "agent_error" => {
                let error = frame
                    .pointer("/data/error")
                    .and_then(Value::as_str)
                    .unwrap_or("上游暂不可用");
                println!("上游模型本次请求失败：{error}");
                self.record(format!("planner error: {error}"));
            }
            "agent_end" => {
                self.agent_cycle_active = false;
                self.active_request_id = None;
                self.requests.clear();
                if self.cruise.is_active() && !self.plan_seen_in_cycle {
                    let retrying = self.cruise.record_planner_missing();
                    self.next_auto_attempt = Instant::now() + AUTO_RETRY_DELAY;
                    println!(
                        "上游下一步重试：第 {}/{} 次{}。",
                        self.cruise.snapshot(Instant::now()).planner_retry_count,
                        AUTO_RETRY_LIMIT,
                        if retrying {
                            "，10 秒后重试"
                        } else {
                            "，巡航退出"
                        }
                    );
                    self.print_cruise_status();
                }
                self.plan_seen_in_cycle = false;
            }
            _ => {}
        }
        Ok(())
    }

    fn record(&mut self, entry: String) {
        if self.history.len() == HISTORY_LIMIT {
            self.history.pop_front();
        }
        self.history.push_back(entry);
        if let Some(path) = &self.session_state_path {
            if let Err(error) = persist_terminal_session(path, &self.history) {
                eprintln!("终端会话状态未保存：{error}");
            }
        }
    }

    fn emit_observation(&mut self) -> AppResult<()> {
        self.refresh_recognition();
        println!(
            "Observation> {}",
            serde_json::to_string(&self.template.observation)?
        );
        Ok(())
    }

    fn emit_sweep_plot(&self, report: &SweepReport, kind: &ActiveSweepKind) -> AppResult<()> {
        let kind = match kind {
            ActiveSweepKind::Initial => "initial",
            ActiveSweepKind::Planned { .. } => "planned",
            ActiveSweepKind::Inspection { .. } => return Ok(()),
        };
        let points: Vec<Value> = report
            .points
            .iter()
            .map(|point| json!([point.actual_center_hz, point.band_power_dbfs]))
            .collect();
        println!(
            "SweepPlot> {}",
            serde_json::to_string(&json!({
                "schema_version": 1,
                "sweep_id": report.sweep_id,
                "kind": kind,
                "elapsed_ms": report.elapsed_ms,
                "gain_db": self.survey_gain_db,
                "noise_floor_dbfs": report.noise_floor_dbfs,
                "points": points,
                "candidates": report.candidates,
                "dataset": report.dataset,
            }))?
        );
        Ok(())
    }

    fn print_history(&self) {
        if self.history.is_empty() {
            println!("本次终端没有历史记录。")
        } else {
            for entry in &self.history {
                println!("{entry}");
            }
        }
    }
}

fn describe_web_search_event(
    frame: &Value,
    requests: &HashMap<u64, PlanRequest>,
) -> AppResult<Vec<String>> {
    let event = frame
        .get("event")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid_input("web search event name is missing"))?;
    let data = frame
        .get("data")
        .and_then(Value::as_object)
        .ok_or_else(|| invalid_input("web search event data is missing"))?;
    let request_id = data
        .get("request_id")
        .and_then(Value::as_u64)
        .ok_or_else(|| invalid_input("web search event is missing request_id"))?;
    if !requests.contains_key(&request_id) {
        return Err(invalid_input("web search event refers to an unknown request").into());
    }
    let phase = event
        .strip_prefix("web_search_")
        .ok_or_else(|| invalid_input("invalid web search event"))?;
    if data.get("phase").and_then(Value::as_str) != Some(phase) {
        return Err(invalid_input("web search event phase does not match its name").into());
    }
    let query = require_web_event_text(data, "query", 512)?;
    match phase {
        "start" => {
            require_web_event_keys(data, &["request_id", "phase", "query"])?;
            Ok(vec![format!(
                "搜索> 正在查询 {}",
                serde_json::to_string(query)?
            )])
        }
        "error" => {
            require_web_event_keys(data, &["request_id", "phase", "query", "error"])?;
            let error = require_web_event_text(data, "error", 512)?;
            Ok(vec![format!(
                "搜索> 查询 {} 失败：{}",
                serde_json::to_string(query)?,
                error
            )])
        }
        "end" => {
            require_web_event_keys(
                data,
                &[
                    "request_id",
                    "phase",
                    "query",
                    "count",
                    "sources",
                    "truncated",
                ],
            )?;
            let count = data
                .get("count")
                .and_then(Value::as_u64)
                .ok_or_else(|| invalid_input("web search result count is missing"))?;
            let sources = data
                .get("sources")
                .and_then(Value::as_array)
                .ok_or_else(|| invalid_input("web search sources are missing"))?;
            if count > 8 || sources.len() != count as usize {
                return Err(invalid_input("web search source count is invalid").into());
            }
            if !data.get("truncated").is_some_and(Value::is_boolean) {
                return Err(invalid_input("web search truncated flag is invalid").into());
            }
            let mut lines = vec![format!(
                "搜索> 查询 {} 返回 {count} 个来源{}。",
                serde_json::to_string(query)?,
                if data.get("truncated").and_then(Value::as_bool) == Some(true) {
                    "（结果已截断）"
                } else {
                    ""
                }
            )];
            for source in sources {
                let source = source
                    .as_object()
                    .ok_or_else(|| invalid_input("web search source must be an object"))?;
                require_web_event_keys(source, &["title", "url"])?;
                let title = require_web_event_text(source, "title", 256)?;
                let url = require_web_event_text(source, "url", 2_048)?;
                if !(url.starts_with("http://") || url.starts_with("https://")) {
                    return Err(invalid_input("web search source URL must use HTTP(S)").into());
                }
                lines.push(format!(
                    "搜索来源> {} — {}",
                    serde_json::to_string(title)?,
                    serde_json::to_string(url)?
                ));
            }
            Ok(lines)
        }
        _ => Err(invalid_input("invalid web search event phase").into()),
    }
}

fn require_web_event_text<'a>(
    data: &'a serde_json::Map<String, Value>,
    key: &str,
    maximum_bytes: usize,
) -> AppResult<&'a str> {
    let value = data
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| invalid_input(format!("web search {key} must be text")))?;
    if value.is_empty() || value.len() > maximum_bytes || value.chars().any(char::is_control) {
        return Err(invalid_input(format!("web search {key} is invalid")).into());
    }
    Ok(value)
}

fn require_web_event_keys(
    data: &serde_json::Map<String, Value>,
    expected: &[&str],
) -> AppResult<()> {
    if data.len() != expected.len() || expected.iter().any(|key| !data.contains_key(*key)) {
        return Err(invalid_input("web search event contains unexpected fields").into());
    }
    Ok(())
}

struct SessionClient {
    writer: UnixStream,
    reader: UnixStream,
    pending: Vec<u8>,
    command_id: u64,
    session_generation: u64,
}

impl SessionClient {
    fn connect(path: PathBuf, session_generation: u64) -> AppResult<Self> {
        let writer = UnixStream::connect(path)?;
        let reader = writer.try_clone()?;
        reader.set_nonblocking(true)?;
        Ok(Self {
            writer,
            reader,
            pending: Vec::new(),
            command_id: 1,
            session_generation,
        })
    }

    fn next_command_id(&mut self) -> u64 {
        let id = self.command_id;
        self.command_id = self.command_id.checked_add(1).unwrap_or(1);
        id
    }

    fn write(&mut self, value: &Value) -> AppResult<()> {
        let mut frame = serde_json::to_vec(value)?;
        if frame.len() > MAX_FRAME_BYTES {
            return Err(invalid_input("session command exceeds 32 KiB").into());
        }
        frame.push(b'\n');
        self.writer.write_all(&frame)?;
        self.writer.flush()?;
        Ok(())
    }

    fn read(&mut self) -> AppResult<Value> {
        loop {
            if let Some(frame) = self.try_read()? {
                return Ok(frame);
            }
            thread::sleep(Duration::from_millis(2));
        }
    }

    fn try_read(&mut self) -> AppResult<Option<Value>> {
        if let Some(frame) = self.take_frame()? {
            return Ok(Some(frame));
        }
        let mut chunk = [0_u8; 4_096];
        match self.reader.read(&mut chunk) {
            Ok(0) => Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "planner session socket closed",
            )
            .into()),
            Ok(count) => {
                self.pending.extend_from_slice(&chunk[..count]);
                if self.pending.len() > MAX_FRAME_BYTES && !self.pending.contains(&b'\n') {
                    return Err(invalid_input("session response exceeds 32 KiB").into());
                }
                self.take_frame()
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    fn take_frame(&mut self) -> AppResult<Option<Value>> {
        let Some(newline) = self.pending.iter().position(|byte| *byte == b'\n') else {
            return Ok(None);
        };
        if newline > MAX_FRAME_BYTES {
            return Err(invalid_input("session response exceeds 32 KiB").into());
        }
        let frame = self.pending[..newline].to_vec();
        self.pending.drain(..=newline);
        Ok(Some(serde_json::from_slice(&frame)?))
    }
}

struct Options {
    engineering_recognition: Option<EngineeringRecognition>,
    recognition_audit_path: Option<PathBuf>,
    socket_path: PathBuf,
    recognizer_socket: PathBuf,
    recognizer_admission: PathBuf,
    request_path: PathBuf,
    instruction: Option<String>,
    sdrd_address: Option<SocketAddr>,
    sdrd_timeout_ms: u64,
    survey_gain_db: i16,
    initial_survey: Option<InitialSurveyOptions>,
    sigmf_directory: Option<PathBuf>,
    session_state_path: Option<PathBuf>,
}

impl Options {
    fn parse() -> AppResult<Self> {
        let mut engineering_root = None;
        let mut recognition_audit_path = None;
        let mut recognition_archive = None;
        let mut socket_path = PathBuf::from("/run/sdr-agent/session.sock");
        let mut recognizer_socket = PathBuf::from(DEFAULT_RECOGNIZER_SOCKET);
        let mut recognizer_admission = PathBuf::from(DEFAULT_ADMISSION_PATH);
        let mut request_path = PathBuf::from("/etc/sdr-agent/request.json");
        let mut instruction = Vec::new();
        let mut sdrd_address = None;
        let mut sdrd_timeout_ms = 5_000_u64;
        let mut survey_gain_db = 20_u64;
        let mut initial_survey_start_hz = None;
        let mut initial_survey_stop_hz = None;
        let mut initial_survey_step_hz = None;
        let mut initial_survey_dwell_ms = None;
        let mut initial_survey_gain_db = None;
        let mut sigmf_directory = None;
        let mut session_state_path = None;
        let mut session_state_disabled = false;
        let mut args = env::args().skip(1);
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--recognition-audit" => {
                    recognition_audit_path =
                        Some(PathBuf::from(args.next().ok_or_else(|| {
                            invalid_input("missing recognition audit path")
                        })?))
                }
                "--engineering-recognition-root" => {
                    engineering_root = Some(PathBuf::from(
                        args.next()
                            .ok_or_else(|| invalid_input("missing engineering root"))?,
                    ))
                }
                "--recognition-archive" => {
                    recognition_archive = Some(
                        args.next()
                            .ok_or_else(|| invalid_input("missing archive address"))?
                            .parse::<SocketAddr>()?,
                    )
                }
                "--recognizer-socket" => {
                    recognizer_socket = PathBuf::from(
                        args.next()
                            .ok_or_else(|| invalid_input("missing --recognizer-socket value"))?,
                    )
                }
                "--recognizer-admission" => {
                    recognizer_admission = PathBuf::from(
                        args.next()
                            .ok_or_else(|| invalid_input("missing --recognizer-admission value"))?,
                    )
                }
                "--socket" => {
                    socket_path = PathBuf::from(
                        args.next()
                            .ok_or_else(|| invalid_input("missing --socket value"))?,
                    )
                }
                "--request" => {
                    request_path = PathBuf::from(
                        args.next()
                            .ok_or_else(|| invalid_input("missing --request value"))?,
                    )
                }
                "--sdrd" => {
                    sdrd_address = Some(
                        args.next()
                            .ok_or_else(|| invalid_input("missing --sdrd value"))?
                            .parse()?,
                    )
                }
                "--sdrd-timeout-ms" => {
                    sdrd_timeout_ms = args
                        .next()
                        .ok_or_else(|| invalid_input("missing --sdrd-timeout-ms value"))?
                        .parse()?;
                }
                "--survey-gain-db" => {
                    survey_gain_db = parse_option_u64(&mut args, &arg)?;
                }
                "--sigmf-directory" => {
                    sigmf_directory =
                        Some(PathBuf::from(args.next().ok_or_else(|| {
                            invalid_input("missing --sigmf-directory value")
                        })?));
                }
                "--session-state" => {
                    let value = args
                        .next()
                        .ok_or_else(|| invalid_input("missing --session-state value"))?;
                    if value == "off" {
                        session_state_disabled = true;
                        session_state_path = None;
                    } else {
                        session_state_disabled = false;
                        session_state_path = Some(PathBuf::from(value));
                    }
                }
                "--initial-survey-start-hz" => {
                    initial_survey_start_hz = Some(parse_option_u64(&mut args, &arg)?);
                }
                "--initial-survey-stop-hz" => {
                    initial_survey_stop_hz = Some(parse_option_u64(&mut args, &arg)?);
                }
                "--initial-survey-step-hz" => {
                    initial_survey_step_hz = Some(parse_option_u64(&mut args, &arg)?);
                }
                "--initial-survey-dwell-ms" => {
                    initial_survey_dwell_ms = Some(parse_option_u64(&mut args, &arg)?);
                }
                "--initial-survey-gain-db" => {
                    initial_survey_gain_db = Some(parse_option_u64(&mut args, &arg)?);
                }
                _ if arg.starts_with('-') => {
                    return Err(invalid_input(format!("unknown option {arg}")).into())
                }
                _ => instruction.push(arg),
            }
        }
        if !(100..=60_000).contains(&sdrd_timeout_ms) {
            return Err(invalid_input("--sdrd-timeout-ms must be between 100 and 60000").into());
        }
        let survey_gain_db: i16 = survey_gain_db
            .try_into()
            .map_err(|_| invalid_input("survey gain must be between 0 and 60 dB"))?;
        if !(0..=60).contains(&survey_gain_db) {
            return Err(invalid_input("survey gain must be between 0 and 60 dB").into());
        }
        let survey_fields = [
            initial_survey_start_hz,
            initial_survey_stop_hz,
            initial_survey_step_hz,
            initial_survey_dwell_ms,
        ];
        let initial_survey =
            if survey_fields.iter().all(Option::is_none) && initial_survey_gain_db.is_none() {
                None
            } else if survey_fields.iter().any(Option::is_none) {
                return Err(
                    invalid_input("initial survey requires start, stop, step, and dwell").into(),
                );
            } else {
                let options = InitialSurveyOptions {
                    start_hz: initial_survey_start_hz.unwrap(),
                    stop_hz: initial_survey_stop_hz.unwrap(),
                    step_hz: initial_survey_step_hz.unwrap(),
                    dwell_ms: initial_survey_dwell_ms.unwrap(),
                    gain_db: initial_survey_gain_db
                        .unwrap_or(survey_gain_db as u64)
                        .try_into()
                        .map_err(|_| {
                            invalid_input("initial survey gain must be between 0 and 60 dB")
                        })?,
                };
                if !(0..=60).contains(&options.gain_db) {
                    return Err(
                        invalid_input("initial survey gain must be between 0 and 60 dB").into(),
                    );
                }
                let plan = SweepPlan {
                    sweep_id: "initial-options".into(),
                    session_generation: 1,
                    frequencies: SweepFrequencies::Range {
                        start_hz: options.start_hz,
                        stop_hz: options.stop_hz,
                        step_hz: options.step_hz,
                    },
                    sample_rate_hz: 10_000_000,
                    rf_bandwidth_hz: 10_000_000,
                    settle_ms: options.dwell_ms,
                    frame_samples: 4_096,
                    aggregate_frames: 1,
                    point_timeout_ms: 250,
                    detection_threshold_db: 12.0,
                    gain_db: Some(options.gain_db),
                };
                sdr_agent_controller::sweep::validate_plan(&plan)?;
                Some(options)
            };
        let instruction = (!instruction.is_empty()).then(|| instruction.join(" "));
        if instruction.is_none() && !session_state_disabled && session_state_path.is_none() {
            session_state_path = Some(default_terminal_state_path()?);
        }
        if session_state_path
            .as_ref()
            .is_some_and(|path| !path.is_absolute())
        {
            return Err(invalid_input("--session-state must be an absolute path or off").into());
        }
        let engineering_recognition = match (engineering_root, recognition_archive) {
            (Some(root), Some(archive))
                if sdrd_address.is_some()
                    && recognition_audit_path
                        .as_ref()
                        .is_some_and(|p| p.is_absolute()) =>
            {
                Some(EngineeringRecognition::new(root, archive)?)
            }
            (None, None) => None,
            _ => {
                return Err(invalid_input(
                    "engineering recognition requires root, archive, absolute recognition audit path and SDRD address together",
                )
                .into())
            }
        };
        Ok(Self {
            engineering_recognition,
            recognition_audit_path,
            socket_path,
            recognizer_socket,
            recognizer_admission,
            request_path,
            instruction,
            sdrd_address,
            sdrd_timeout_ms,
            survey_gain_db,
            initial_survey,
            sigmf_directory,
            session_state_path,
        })
    }
}

fn parse_option_u64(args: &mut impl Iterator<Item = String>, option: &str) -> AppResult<u64> {
    Ok(args
        .next()
        .ok_or_else(|| invalid_input(format!("missing {option} value")))?
        .parse()?)
}

fn read_bounded(mut reader: impl Read) -> AppResult<Vec<u8>> {
    let mut bytes = Vec::new();
    reader
        .by_ref()
        .take((MAX_FRAME_BYTES + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_FRAME_BYTES {
        return Err(invalid_input("request template exceeds 32 KiB").into());
    }
    Ok(bytes)
}

fn print_help() {
    println!(
        "查看：/status 当前状态，/history 本次历史\n\
         人工模式：/mode manual，/approve 批准当前步骤，/reject 拒绝当前步骤\n\
         自动巡航：/auto start [--steps 1–128] [--seconds 10–1800] [--mib 正整数] <任务>\n\
         不填 --mib 时，按步数 × 单动作 IQ 上限自动推导有限预算。\n\
         默认 8 步、120 秒；累计字节预算按当前限制推导。两类失败各重试 5 次，每次间隔 10 秒\n\
         流式输入：普通文本或 /steer 会立即引导当前轮，/follow-up 在本轮后处理；队列最多 4 条\n\
         工程识别：配置后 /recognize <候选ID>，仍须 /approve；不会开启生产能力。\n\
         会话：/pause 暂停，/resume 继续，/stop 始终优先立即停止，/quit 退出"
    );
}

fn controller_state_label(state: ControllerState) -> &'static str {
    match state {
        ControllerState::Idle => "空闲，可以接收新任务",
        ControllerState::Surveying => "正在扫频",
        ControllerState::Inspecting => "正在检查候选信号",
        ControllerState::Recognizing => "正在识别信号",
        ControllerState::Holding => "已保持，不会继续操作硬件",
        ControllerState::Faulted => "故障锁定，需要检查后恢复",
    }
}

fn describe_plan(plan: &ValidatedPlan) -> String {
    let approval = if plan.approval_required {
        "；必须人工批准"
    } else {
        "；位于自动安全阈值内"
    };
    match &plan.action {
        ProposedAction::Hold { reason } => format!("保持当前状态：{reason}"),
        ProposedAction::SurveyBand {
            start_hz,
            stop_hz,
            step_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
        } => format!(
            "受限扫频 {}–{} Hz，步进 {} Hz、采样率 {} Hz、射频带宽 {} Hz，每点停留 {} ms，执行时采用设置中的固定接收增益{}",
            start_hz, stop_hz, step_hz, sample_rate_hz, rf_bandwidth_hz, dwell_ms, approval
        ),
        ProposedAction::InspectCandidate {
            candidate_id,
            center_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
        } => format!(
            "受限复查候选 {candidate_id}：中心 {} Hz、采样率 {} Hz、射频带宽 {} Hz、驻留 {} ms，执行时采用设置中的固定接收增益{}",
            center_hz, sample_rate_hz, rf_bandwidth_hz, dwell_ms, approval
        ),
        ProposedAction::CaptureBoundedIq {
            candidate_id,
            center_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            samples,
        } => format!(
            "受限采集候选 {candidate_id}：中心 {} Hz、采样率 {}、射频带宽 {}、{} 个复数样本（最多 {} 字节）{}",
            center_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            samples,
            samples.saturating_mul(4),
            approval
        ),
        ProposedAction::RunLocalRecognition { candidate_id } => {
            format!("建议本地识别候选 {candidate_id}；识别后端尚未启用，不会执行")
        }
        ProposedAction::StopSession { reason } => format!("停止本次会话：{reason}"),
    }
}

fn describe_decision_basis(plan: &ValidatedPlan, request: &PlanRequest) -> String {
    let limits = &request.limits;
    let correlation = format!(
        "request={}、generation={} 与当前上下文一致；状态={:?}",
        plan.request_id, plan.session_generation, request.state
    );
    let action = match &plan.action {
        ProposedAction::Hold { .. } => "保持不触发硬件，原因文本已通过长度和可打印字符校验".to_owned(),
        ProposedAction::StopSession { .. } => {
            "停止会话不触发新的硬件动作，原因文本已通过校验".to_owned()
        }
        ProposedAction::SurveyBand {
            start_hz,
            stop_hz,
            step_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
        } => {
            let points = (stop_hz - start_hz).div_ceil(*step_hz).saturating_add(1);
            let bytes = points.saturating_mul(4_096 * 4);
            format!(
                "扫频范围位于 {}–{} Hz，跨度 {}≤{} Hz，点数 {}≤768，步进 {}≤射频带宽 {} 的 80%，采样率 {} Hz，停留 {}≤{} ms，预计处理 {}≤{} 字节；SDR 在线且允许调谐",
                limits.min_freq_hz,
                limits.max_freq_hz,
                stop_hz - start_hz,
                limits.max_span_hz,
                points,
                step_hz,
                rf_bandwidth_hz,
                sample_rate_hz,
                dwell_ms,
                limits.max_dwell_ms,
                bytes,
                limits.max_iq_bytes
            )
        }
        ProposedAction::InspectCandidate {
            candidate_id,
            center_hz,
            sample_rate_hz,
            rf_bandwidth_hz,
            dwell_ms,
        } => format!(
            "候选 {candidate_id} 存在；中心 {} Hz 位于安全频段，采样率 {} Hz，射频带宽 {}≤{} Hz，停留 {}≤1000 ms；SDR 在线且允许调谐",
            center_hz, sample_rate_hz, rf_bandwidth_hz, limits.max_bandwidth_hz, dwell_ms
        ),
        ProposedAction::CaptureBoundedIq {
            candidate_id,
            center_hz,
            rf_bandwidth_hz,
            samples,
            ..
        } => {
            let bytes = samples.saturating_mul(4);
            format!(
                "候选 {candidate_id} 存在；中心 {} Hz 与候选匹配，带宽 {}≤{} Hz，样本 {}≤{}，字节 {}≤{}；{}",
                center_hz,
                rf_bandwidth_hz,
                limits.max_bandwidth_hz,
                samples,
                limits.max_iq_samples,
                bytes,
                limits.max_iq_bytes,
                if plan.approval_required {
                    "超过自动批准阈值，必须人工批准"
                } else {
                    "未超过自动批准阈值"
                }
            )
        }
        ProposedAction::RunLocalRecognition { candidate_id } => format!(
            "候选 {candidate_id} 存在，且本地识别能力由运行时探测为可用"
        ),
    };
    format!("{correlation}；{action}")
}

fn describe_agent_reply(plan: &ValidatedPlan, mode: InteractionMode) -> String {
    if let ProposedAction::Hold { reason } = &plan.action {
        return reason.clone();
    }

    let summary = describe_plan(plan);
    if mode == InteractionMode::StepApproval
        && matches!(
            &plan.action,
            ProposedAction::CaptureBoundedIq { .. }
                | ProposedAction::SurveyBand { .. }
                | ProposedAction::InspectCandidate { .. }
        )
    {
        format!("计划已生成：{summary}。请点击批准或输入 /approve 执行，也可以拒绝。")
    } else {
        format!("下一步计划：{summary}")
    }
}

fn invalid_input(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.into())
}

fn default_terminal_state_path() -> AppResult<PathBuf> {
    if let Some(root) = env::var_os("XDG_STATE_HOME").map(PathBuf::from) {
        if root.is_absolute() {
            return Ok(root.join("sdrharness/terminal-session.json"));
        }
    }
    let home = env::var_os("HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .ok_or_else(|| {
            invalid_input("HOME or absolute XDG_STATE_HOME is required for session state")
        })?;
    Ok(home.join(".local/state/sdrharness/terminal-session.json"))
}

fn load_terminal_session(path: &Path) -> AppResult<Option<LoadedTerminalSession>> {
    if !path.is_absolute() {
        return Err(invalid_input("terminal session state path must be absolute").into());
    }
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    ensure_private_state_parent(
        path.parent()
            .ok_or_else(|| invalid_input("terminal session state path has no parent"))?,
    )?;
    validate_private_state_file(path, &metadata)?;
    if metadata.len() > TERMINAL_STATE_MAX_BYTES as u64 {
        return Err(invalid_input("terminal session state exceeds 64 KiB").into());
    }
    let bytes = read_bounded_limit(File::open(path)?, TERMINAL_STATE_MAX_BYTES)?;
    let persisted: PersistedTerminalSession = serde_json::from_slice(&bytes)?;
    if persisted.schema_version != TERMINAL_STATE_SCHEMA_VERSION {
        return Err(invalid_input("unsupported terminal session state schema").into());
    }
    let now = unix_time_ms()?;
    if persisted.saved_at_ms > now.saturating_add(5 * 60 * 1_000) {
        return Err(invalid_input("terminal session state timestamp is in the future").into());
    }
    if now.saturating_sub(persisted.saved_at_ms) > TERMINAL_RESUME_MAX_AGE_MS {
        return Ok(None);
    }
    if persisted.history.len() > TERMINAL_RESUME_MAX_ENTRIES {
        return Err(invalid_input("terminal session state has too many history entries").into());
    }
    for entry in &persisted.history {
        validate_resumable_history_entry(entry)?;
    }
    let summary = bounded_resume_summary(&persisted.history);
    Ok(Some(LoadedTerminalSession {
        history: persisted.history.into(),
        summary,
    }))
}

fn persist_terminal_session(path: &Path, history: &VecDeque<String>) -> AppResult<()> {
    if !path.is_absolute() {
        return Err(invalid_input("terminal session state path must be absolute").into());
    }
    let parent = path
        .parent()
        .ok_or_else(|| invalid_input("terminal session state path has no parent"))?;
    ensure_private_state_parent(parent)?;
    if let Ok(metadata) = fs::symlink_metadata(path) {
        validate_private_state_file(path, &metadata)?;
    }
    let mut resumable = history
        .iter()
        .filter_map(|entry| sanitize_resumable_history_entry(entry))
        .collect::<Vec<_>>();
    if resumable.len() > TERMINAL_RESUME_MAX_ENTRIES {
        resumable.drain(..resumable.len() - TERMINAL_RESUME_MAX_ENTRIES);
    }
    for entry in &resumable {
        validate_resumable_history_entry(entry)?;
    }
    let state = PersistedTerminalSession {
        schema_version: TERMINAL_STATE_SCHEMA_VERSION,
        saved_at_ms: unix_time_ms()?,
        history: resumable,
    };
    let bytes = serde_json::to_vec_pretty(&state)?;
    if bytes.len() > TERMINAL_STATE_MAX_BYTES {
        return Err(invalid_input("terminal session state exceeds 64 KiB").into());
    }
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| invalid_input("terminal session state filename is invalid"))?;
    let temporary = parent.join(format!(
        ".{file_name}.tmp-{}-{}",
        std::process::id(),
        unix_time_ms()?
    ));
    let result = (|| -> AppResult<()> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, path)?;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
        File::open(parent)?.sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn ensure_private_state_parent(parent: &Path) -> AppResult<()> {
    if !parent.exists() {
        fs::create_dir_all(parent)?;
        fs::set_permissions(parent, fs::Permissions::from_mode(0o700))?;
    }
    let metadata = fs::symlink_metadata(parent)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(invalid_input("terminal session state parent must be a real directory").into());
    }
    if metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o077 != 0 {
        return Err(invalid_input("terminal session state parent must be owner-only").into());
    }
    Ok(())
}

fn validate_private_state_file(path: &Path, metadata: &fs::Metadata) -> AppResult<()> {
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(invalid_input(format!(
            "terminal session state is not a regular file: {}",
            path.display()
        ))
        .into());
    }
    if metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o777 != 0o600 {
        return Err(invalid_input("terminal session state must be owner mode 0600").into());
    }
    Ok(())
}

fn read_bounded_limit(mut reader: impl Read, maximum: usize) -> AppResult<Vec<u8>> {
    let mut bytes = Vec::new();
    reader
        .by_ref()
        .take((maximum + 1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err(invalid_input(format!("input exceeds {maximum} bytes")).into());
    }
    Ok(bytes)
}

fn validate_resumable_history_entry(entry: &str) -> AppResult<()> {
    if !is_resumable_history_entry(entry)
        || entry.len() > TERMINAL_RESUME_ENTRY_MAX_BYTES
        || entry.chars().any(char::is_control)
    {
        return Err(invalid_input("terminal session history entry is invalid").into());
    }
    Ok(())
}

fn is_resumable_history_entry(entry: &str) -> bool {
    entry.starts_with("operator: ")
        || entry.starts_with("operator steer: ")
        || entry.starts_with("operator follow_up: ")
        || entry.starts_with("agent: ")
}

fn sanitize_resumable_history_entry(entry: &str) -> Option<String> {
    if !is_resumable_history_entry(entry) {
        return None;
    }
    let printable = entry
        .chars()
        .map(|character| {
            if character.is_control() {
                ' '
            } else {
                character
            }
        })
        .collect::<String>();
    let normalized = single_line(&printable);
    Some(head_utf8(&normalized, TERMINAL_RESUME_ENTRY_MAX_BYTES))
}

fn bounded_resume_summary(history: &[String]) -> String {
    let joined = history.join("\n");
    if joined.len() <= TERMINAL_RESUME_SUMMARY_MAX_BYTES {
        joined
    } else {
        tail_utf8(&joined, TERMINAL_RESUME_SUMMARY_MAX_BYTES)
    }
}

fn carry_forward_instruction(summary: &str, instruction: &str) -> String {
    const PREFIX: &str = "前序有限终端摘要（不含任何批准或执行授权）：";
    const CURRENT: &str = "；当前指令：";
    let summary = single_line(summary);
    let instruction = single_line(instruction);
    let fixed = PREFIX.len() + CURRENT.len() + instruction.len();
    if summary.is_empty() || fixed >= MAX_INSTRUCTION_BYTES {
        return instruction;
    }
    let budget = MAX_INSTRUCTION_BYTES - fixed;
    let summary = if summary.len() > budget {
        tail_utf8(&summary, budget)
    } else {
        summary
    };
    format!("{PREFIX}{summary}{CURRENT}{instruction}")
}

fn single_line(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn tail_utf8(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let mut start = value.len() - maximum_bytes;
    while start < value.len() && !value.is_char_boundary(start) {
        start += 1;
    }
    value[start..].to_owned()
}

fn head_utf8(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let mut end = maximum_bytes;
    while end > 0 && !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_owned()
}

fn unix_time_ms() -> AppResult<u64> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| invalid_input("system clock predates Unix epoch"))?
        .as_millis()
        .try_into()
        .map_err(|_| invalid_input("system time exceeds u64 milliseconds"))?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_request(request_id: u64, session_generation: u64) -> PlanRequest {
        serde_json::from_value(json!({
            "protocol_version": 1,
            "request_id": request_id,
            "session_generation": session_generation,
            "instruction": "测试流式终端输入",
            "state": "idle",
            "observation": {
                "age_ms": 0,
                "health": {
                    "sdr_online": true,
                    "can_retune": true,
                    "can_capture_iq": true,
                    "recognizer_available": false,
                    "dropped_observations": 0
                },
                "candidates": []
            },
            "limits": {
                "min_freq_hz": 70_000_000,
                "max_freq_hz": 6_000_000_000_u64,
                "max_span_hz": 6_000_000_000_u64,
                "max_bandwidth_hz": 30_000_000,
                "max_dwell_ms": 5_000,
                "max_iq_samples": 1_048_576,
                "max_iq_bytes": 4_194_304,
                "auto_approve_iq_bytes": 262_144,
                "max_observation_age_ms": 10_000
            }
        }))
        .unwrap()
    }

    fn test_console() -> (ConsoleApp, UnixStream) {
        let (writer, peer) = UnixStream::pair().unwrap();
        let reader = writer.try_clone().unwrap();
        reader.set_nonblocking(true).unwrap();
        let template = test_request(1, 1);
        (
            ConsoleApp {
                recognizer: Box::new(
                    sdr_agent_controller::recognizer_admission::UnavailableRecognizer,
                ),
                client: SessionClient {
                    writer,
                    reader,
                    pending: Vec::new(),
                    command_id: 1,
                    session_generation: 1,
                },
                template,
                next_request_id: 2,
                session_generation: 1,
                pending: None,
                requests: HashMap::new(),
                pending_session_commands: HashMap::new(),
                history: VecDeque::new(),
                agent_cycle_active: false,
                active_request_id: None,
                plan_seen_in_cycle: false,
                executor: None,
                active_execution: None,
                active_sweep: None,
                active_recognition: None,
                engineering_recognition: None,
                recognition_audit_path: None,
                sdrd_address: None,
                sdrd_timeout: Duration::from_secs(1),
                survey_gain_db: 20,
                sigmf_directory: None,
                cruise: CruiseControl::default(),
                auto_mission: None,
                auto_next_instruction: None,
                next_auto_attempt: Instant::now(),
                deferred_renew: None,
                session_state_path: None,
                resume_summary: None,
            },
            peer,
        )
    }

    fn synthetic_recognition_report(app: &ConsoleApp) -> RecognitionExecutionReport {
        use sdr_agent_controller::recognition_result::{
            CalibrationStatus, RecognitionObservation, RecognitionResult, RecognitionStatus,
        };
        let mut next = app.template.observation.clone();
        let observation = RecognitionObservation {
            schema_version: 1,
            candidate_id: "synthetic-candidate".into(),
            request_id: 1,
            session_generation: 1,
            observed_at_unix_ms: sdr_agent_controller::recognition_execution::now_ms(),
            status: RecognitionStatus::Error,
            reason: Some("synthetic_late".into()),
            class: None,
            calibrated_confidence: None,
            calibration_status: CalibrationStatus::Unavailable,
            decision_references: None,
            identity: None,
            source: None,
            quality: None,
            timing: None,
        };
        next.recognition = Some(observation.clone());
        RecognitionExecutionReport {
            engineering_only: true,
            maximum_rx_bytes: MAX_RX_BYTES,
            request_id: 1,
            session_generation: 1,
            result: RecognitionResult {
                schema_version: 1,
                observation,
                experimental_prediction: None,
                uncalibrated_probability: None,
                experimental_batch: None,
            },
            archive_id: Some(1),
            archive_error: None,
            post_execution_sdr: sdr_agent_controller::sdr::SdrSnapshot {
                online: true,
                healthy: true,
                health_flags: 0,
                iio_visible: true,
                can_retune: true,
                can_capture_iq: true,
                rx_input: None,
            },
            next_observation: next,
        }
    }

    #[test]
    fn completed_recognition_starts_one_compact_feedback_turn_in_step_mode() {
        use std::io::{BufRead, BufReader};
        let (mut app, peer) = test_console();
        app.template.limits.max_span_hz = 5_930_000_000;
        app.template.observation.candidates.push(
            sdr_agent_controller::protocol::CandidateSummary {
                id: "synthetic-candidate".into(),
                center_hz: 433_920_000,
                bandwidth_hz: 200_000,
                peak_dbfs: -30.0,
                snr_db: 10.0,
                age_ms: 0,
            },
        );
        let report = synthetic_recognition_report(&app);
        app.active_recognition = Some(ActiveRecognition {
            request_id: 1,
            session_generation: 1,
            cancellation: RecognitionCancellation::default(),
            worker: thread::spawn(move || Ok(report)),
        });
        let deadline = Instant::now() + Duration::from_secs(2);
        while !app
            .active_recognition
            .as_ref()
            .unwrap()
            .worker
            .is_finished()
        {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(1));
        }
        app.poll_recognition().unwrap();
        assert!(app.agent_cycle_active);
        assert_eq!(app.active_request_id, Some(2));
        assert!(app.active_recognition.is_none());
        assert!(app.active_execution.is_none());
        assert!(app.active_sweep.is_none());
        assert_eq!(app.cruise.mode(), InteractionMode::StepApproval);
        assert!(!app.template.observation.health.recognizer_available);
        let request = &app.requests[&2];
        assert_eq!(
            request.observation.recognition.as_ref().unwrap().request_id,
            1
        );
        let wire = serde_json::to_string(request).unwrap();
        assert!(!wire.contains("experimental_batch"));
        assert!(!wire.contains("logits"));
        assert!(!wire.contains("iq_path"));
        peer.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        let mut reader = BufReader::new(peer);
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        assert!(line.contains("prompt"));
        app.poll_recognition().unwrap();
        assert_eq!(app.next_request_id, 3);
    }

    #[test]
    fn recognition_stop_retains_owner_and_discards_late_result_before_renew() {
        let (mut app, mut peer) = test_console();
        app.cruise.start(65536, 2, 60, Instant::now()).unwrap();
        let signal = RecognitionCancellation::default();
        let (release, wait) = mpsc::channel();
        let report = synthetic_recognition_report(&app);
        app.active_recognition = Some(ActiveRecognition {
            request_id: 1,
            session_generation: 1,
            cancellation: signal.clone(),
            worker: thread::spawn(move || {
                wait.recv_timeout(Duration::from_secs(2)).unwrap();
                Ok(report)
            }),
        });
        app.stop("test stop").unwrap();
        assert!(signal.cancelled());
        assert_eq!(app.session_generation, 1);
        assert!(app.active_recognition.is_some());
        assert!(!app.cruise.is_active());
        assert!(app.renew(ControllerState::Holding, "too early").is_err());
        app.submit("must not execute".into()).unwrap();
        app.start_auto("must not restart", 2, 60, Some(65536))
            .unwrap();
        assert_eq!(app.session_generation, 1);
        assert_eq!(app.next_request_id, 2);
        peer.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        let acknowledger = thread::spawn(move || {
            use std::io::{BufRead, BufReader};
            let mut reader = BufReader::new(peer.try_clone().unwrap());
            for _ in 0..2 {
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                let q: Value = serde_json::from_str(&line).unwrap();
                let reply = json!({"type":"response","command_id":q["command_id"],"session_generation":q["session_generation"],"success":true,"data":{}});
                writeln!(peer, "{}", reply).unwrap();
            }
        });
        release.send(()).unwrap();
        while !app
            .active_recognition
            .as_ref()
            .unwrap()
            .worker
            .is_finished()
        {
            thread::sleep(Duration::from_millis(1));
        }
        app.poll_recognition().unwrap();
        acknowledger.join().unwrap();
        assert_eq!(app.session_generation, 2);
        assert!(app.template.observation.recognition.is_none());
        assert!(app.active_recognition.is_none());
    }

    fn reply_plan(action: ProposedAction) -> ValidatedPlan {
        ValidatedPlan {
            request_id: 1,
            session_generation: 1,
            approval_required: false,
            action,
            planner: sdr_agent_controller::protocol::PlannerMeta {
                provider: "test".to_owned(),
                model: "test".to_owned(),
            },
        }
    }

    #[test]
    fn bounds_terminal_input_and_prioritizes_stop_when_full() {
        let (sender, receiver) = mpsc::sync_channel(TERMINAL_INPUT_QUEUE_LIMIT);
        let stop = AtomicBool::new(false);
        for index in 0..TERMINAL_INPUT_QUEUE_LIMIT {
            assert_eq!(
                enqueue_terminal_input(&sender, &stop, format!("queued {index}")),
                TerminalEnqueueResult::Queued
            );
        }
        assert_eq!(
            enqueue_terminal_input(&sender, &stop, "overflow".to_owned()),
            TerminalEnqueueResult::Full
        );
        assert_eq!(
            enqueue_terminal_input(&sender, &stop, "/stop\n".to_owned()),
            TerminalEnqueueResult::StopRequested
        );
        assert!(stop.load(Ordering::Acquire));
        assert_eq!(receiver.try_iter().count(), TERMINAL_INPUT_QUEUE_LIMIT);
        assert_eq!(
            enqueue_terminal_input(&sender, &stop, "after stop".to_owned()),
            TerminalEnqueueResult::StopInProgress
        );
        stop.store(false, Ordering::Release);
        drop(receiver);
        assert_eq!(
            enqueue_terminal_input(&sender, &stop, "after close".to_owned()),
            TerminalEnqueueResult::Disconnected
        );
    }

    #[test]
    fn handles_async_prompt_and_queue_acknowledgements() {
        let (mut app, _peer) = test_console();
        app.agent_cycle_active = true;
        app.active_request_id = Some(10);
        app.requests.insert(10, test_request(10, 1));
        app.pending_session_commands
            .insert(41, PendingSessionCommand::Prompt { request_id: 10 });
        app.handle_session_response(json!({
            "type": "response",
            "command_id": 41,
            "session_generation": 1,
            "success": true,
            "data": {"accepted": true}
        }))
        .unwrap();
        assert!(app.agent_cycle_active);
        assert_eq!(app.active_request_id, Some(10));
        assert!(app.requests.contains_key(&10));

        app.requests.insert(11, test_request(11, 1));
        app.pending_session_commands.insert(
            42,
            PendingSessionCommand::Queue {
                request_id: 11,
                kind: SessionQueueKind::Steer,
            },
        );
        app.handle_session_response(json!({
            "type": "response",
            "command_id": 42,
            "session_generation": 1,
            "success": true,
            "data": {"queued": 1}
        }))
        .unwrap();
        assert!(app.requests.contains_key(&11));
        assert!(app.pending_session_commands.is_empty());
    }

    #[test]
    fn fails_closed_without_terminating_on_async_failure_or_stale_frames() {
        let (mut app, _peer) = test_console();
        app.agent_cycle_active = true;
        app.active_request_id = Some(10);
        app.requests.insert(10, test_request(10, 1));
        app.pending_session_commands
            .insert(41, PendingSessionCommand::Prompt { request_id: 10 });
        app.handle_session_response(json!({
            "type": "response",
            "command_id": 41,
            "session_generation": 1,
            "success": false,
            "error": "Planner Worker is busy"
        }))
        .unwrap();
        assert!(!app.agent_cycle_active);
        assert_eq!(app.active_request_id, None);
        assert!(!app.requests.contains_key(&10));

        app.session_generation = 2;
        app.template.session_generation = 2;
        app.requests.insert(12, test_request(12, 1));
        app.pending_session_commands.insert(
            43,
            PendingSessionCommand::Queue {
                request_id: 12,
                kind: SessionQueueKind::FollowUp,
            },
        );
        app.handle_session_response(json!({
            "type": "response",
            "command_id": 43,
            "session_generation": 1,
            "success": true,
            "data": {"queued": 1}
        }))
        .unwrap();
        assert!(!app.requests.contains_key(&12));
        assert_eq!(app.session_generation, 2);

        app.handle_session_response(json!({
            "type": "response",
            "command_id": 999,
            "session_generation": 1,
            "success": true
        }))
        .unwrap();
        app.handle_event(json!({
            "type": "event",
            "event": "agent_end",
            "session_generation": 1
        }))
        .unwrap();
        assert_eq!(app.session_generation, 2);
        assert!(app
            .handle_session_response(json!({
                "type": "response",
                "command_id": 999,
                "session_generation": 2,
                "success": true
            }))
            .is_err());
    }

    fn terminal_state_test_path(label: &str) -> PathBuf {
        let directory = env::temp_dir().join(format!(
            "sdrharness-terminal-state-{label}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&directory);
        fs::create_dir_all(&directory).unwrap();
        fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).unwrap();
        directory.join("session.json")
    }

    #[test]
    fn atomically_persists_only_bounded_private_conversation_history() {
        let path = terminal_state_test_path("bounded");
        let mut history = VecDeque::new();
        history.push_back("approved request 4".to_owned());
        history.push_back("execution failed request 4".to_owned());
        for index in 0..40 {
            history.push_back(format!("operator: message {index}"));
        }
        history.push_back(format!("agent: final\n{}", "x".repeat(3_000)));
        persist_terminal_session(&path, &history).unwrap();

        let metadata = fs::symlink_metadata(&path).unwrap();
        assert_eq!(metadata.mode() & 0o777, 0o600);
        assert_eq!(metadata.uid(), unsafe { libc::geteuid() });
        assert!(metadata.len() <= TERMINAL_STATE_MAX_BYTES as u64);
        let loaded = load_terminal_session(&path).unwrap().unwrap();
        assert_eq!(loaded.history.len(), TERMINAL_RESUME_MAX_ENTRIES);
        assert!(loaded
            .history
            .iter()
            .all(|entry| { entry.starts_with("operator: ") || entry.starts_with("agent: ") }));
        assert!(loaded
            .history
            .iter()
            .all(|entry| entry.len() <= TERMINAL_RESUME_ENTRY_MAX_BYTES
                && !entry.chars().any(char::is_control)));
        assert!(loaded.summary.len() <= TERMINAL_RESUME_SUMMARY_MAX_BYTES);
        assert!(!loaded.summary.contains("approved request"));
        assert!(!loaded.summary.contains("execution failed"));
        assert!(path.parent().unwrap().read_dir().unwrap().all(|entry| {
            !entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .contains(".tmp-")
        }));
        fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }

    #[test]
    fn rejects_expired_loose_or_action_bearing_session_state() {
        let path = terminal_state_test_path("reject");
        let expired = PersistedTerminalSession {
            schema_version: TERMINAL_STATE_SCHEMA_VERSION,
            saved_at_ms: unix_time_ms().unwrap() - TERMINAL_RESUME_MAX_AGE_MS - 1,
            history: vec!["operator: old".to_owned()],
        };
        fs::write(&path, serde_json::to_vec(&expired).unwrap()).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        assert!(load_terminal_session(&path).unwrap().is_none());

        fs::write(
            &path,
            serde_json::to_vec(&json!({
                "schema_version": 1,
                "saved_at_ms": unix_time_ms().unwrap(),
                "history": ["operator: safe"],
                "pending_plan": {"request_id": 7}
            }))
            .unwrap(),
        )
        .unwrap();
        assert!(load_terminal_session(&path).is_err());
        fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).unwrap();
        assert!(load_terminal_session(&path).is_err());
        fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }

    #[test]
    fn bounds_resumed_context_to_one_unprivileged_instruction() {
        let summary = format!("operator: {}\nagent: previous hold", "历史".repeat(3_000));
        let instruction = carry_forward_instruction(&summary, "当前只查询状态");
        assert!(instruction.len() <= MAX_INSTRUCTION_BYTES);
        assert!(instruction.contains("不含任何批准或执行授权"));
        assert!(instruction.ends_with("当前指令：当前只查询状态"));
    }

    #[test]
    fn parses_default_and_operator_cruise_budgets() {
        assert_eq!(
            parse_auto_start("在允许频段内检查活动").unwrap(),
            AutoStartCommand {
                mission: "在允许频段内检查活动".to_owned(),
                steps: DEFAULT_AUTO_MAX_STEPS,
                seconds: DEFAULT_AUTO_DURATION_SECS,
                iq_bytes: None,
            }
        );
        assert_eq!(
            parse_auto_start("--steps 128 --seconds 1800 --mib 32 完整巡航").unwrap(),
            AutoStartCommand {
                mission: "完整巡航".to_owned(),
                steps: 128,
                seconds: 1_800,
                iq_bytes: Some(32 * 1024 * 1024),
            }
        );
    }

    #[test]
    fn rejects_invalid_or_ambiguous_cruise_parameters() {
        for invalid in [
            "--steps 0 任务",
            "--steps 129 任务",
            "--seconds 9 任务",
            "--seconds 1801 任务",
            "--steps 8 --steps 9 任务",
            "--seconds 120 --seconds 121 任务",
            "--mib 0 任务",
            "--mib 17592186044416 任务",
            "--mib 16 --mib 32 任务",
            "--unknown 1 任务",
            "--steps",
            "--seconds",
            "--mib",
        ] {
            assert!(parse_auto_start(invalid).is_err(), "accepted {invalid}");
        }
    }

    #[test]
    fn hold_reason_becomes_the_visible_agent_reply() {
        let plan = reply_plan(ProposedAction::Hold {
            reason: "你好，我已连接，可以帮你安全地检查频段。".to_owned(),
        });
        assert_eq!(
            describe_agent_reply(&plan, InteractionMode::StepApproval),
            "你好，我已连接，可以帮你安全地检查频段。"
        );
    }

    #[test]
    fn validates_and_renders_correlated_web_search_sources() {
        let mut requests = HashMap::new();
        requests.insert(
            7,
            serde_json::from_value(json!({
                "protocol_version": 1,
                "request_id": 7,
                "session_generation": 2,
                "instruction": "搜索公开资料",
                "state": "idle",
                "observation": {
                    "age_ms": 0,
                    "health": {
                        "sdr_online": true,
                        "can_retune": true,
                        "can_capture_iq": true,
                        "recognizer_available": false,
                        "dropped_observations": 0
                    },
                    "candidates": []
                },
                "limits": {
                    "min_freq_hz": 70000000,
                    "max_freq_hz": 6000000000_u64,
                    "max_span_hz": 6000000000_u64,
                    "max_bandwidth_hz": 30000000,
                    "max_dwell_ms": 5000,
                    "max_iq_samples": 1048576,
                    "max_iq_bytes": 4194304,
                    "auto_approve_iq_bytes": 262144,
                    "max_observation_age_ms": 10000
                }
            }))
            .unwrap(),
        );
        let frame = json!({
            "event": "web_search_end",
            "data": {
                "request_id": 7,
                "phase": "end",
                "query": "Spark X2.5",
                "count": 1,
                "sources": [{"title": "Official source", "url": "https://example.com/spark"}],
                "truncated": false
            }
        });
        let lines = describe_web_search_event(&frame, &requests).unwrap();
        assert_eq!(lines.len(), 2);
        assert!(lines[0].contains("返回 1 个来源"));
        assert!(lines[1].contains("https://example.com/spark"));

        let mut invalid = frame;
        invalid["data"]["sources"][0]["url"] = json!("file:///etc/passwd");
        assert!(describe_web_search_event(&invalid, &requests).is_err());
    }

    #[test]
    fn manual_survey_reply_explains_the_approval_gate() {
        let plan = reply_plan(ProposedAction::SurveyBand {
            start_hz: 70_000_000,
            stop_hz: 90_000_000,
            step_hz: 100_000,
            sample_rate_hz: 2_100_000,
            rf_bandwidth_hz: 2_000_000,
            dwell_ms: 10,
        });
        let reply = describe_agent_reply(&plan, InteractionMode::StepApproval);
        assert!(reply.contains("70000000–90000000 Hz"));
        assert!(reply.contains("请点击批准或输入 /approve"));
    }
    struct SyntheticAdmitted;
    impl RecognizerCapability for SyntheticAdmitted {
        fn observe(
            &mut self,
            request_id: u64,
            session_generation: u64,
        ) -> sdr_agent_controller::recognizer_admission::RecognizerCapabilityObservation {
            sdr_agent_controller::recognizer_admission::RecognizerCapabilityObservation {
                recognizer_available: true,
                reason: "synthetic_fixture".to_owned(),
                request_id,
                session_generation,
                observed_at_unix_ms: unix_time_ms().unwrap(),
                worker_instance_id: Some("a".repeat(64)),
                admission_sha256: Some("b".repeat(64)),
            }
        }
    }

    #[test]
    fn terminal_clears_forged_availability_for_prompt_and_queued_context() {
        let (mut app, _peer) = test_console();
        app.template.limits.max_span_hz = 5_930_000_000;
        app.template.observation.health.recognizer_available = true;
        app.submit("检查状态".to_owned()).unwrap();
        assert!(!app.requests[&2].observation.health.recognizer_available);
        app.template.observation.health.recognizer_available = true;
        app.queue_model_input("补充", SessionQueueKind::FollowUp)
            .unwrap();
        assert!(!app.requests[&3].observation.health.recognizer_available);
    }

    #[test]
    fn engineering_step_and_cruise_proposals_cannot_skip_operator_approval() {
        for automatic in [false, true] {
            let (mut app, _peer) = test_console();
            let mut request = test_request(7, 1);
            request.limits.max_span_hz = 5_930_000_000;
            request
                .observation
                .candidates
                .push(sdr_agent_controller::protocol::CandidateSummary {
                    id: "candidate-1".into(),
                    center_hz: 433_920_000,
                    bandwidth_hz: 200_000,
                    peak_dbfs: -20.0,
                    snr_db: 10.0,
                    age_ms: 0,
                });
            app.template = request.clone();
            app.requests.insert(7, request);
            app.engineering_recognition = Some(
                EngineeringRecognition::new(
                    PathBuf::from("/missing-s5"),
                    "127.0.0.1:9".parse().unwrap(),
                )
                .unwrap(),
            );
            if automatic {
                app.cruise.start(65536, 2, 60, Instant::now()).unwrap();
            }
            app.handle_event(json!({"type":"event","session_generation":1,"event":"plan_proposed","data":{"protocol_version":1,"request_id":7,"session_generation":1,"status":"ok","planner":{"provider":"synthetic-regression","model":"fixture"},"action":{"kind":"run_local_recognition","candidate_id":"candidate-1"}}})).unwrap();
            assert!(app.pending.as_ref().unwrap().approval_required);
            assert!(app.active_recognition.is_none());
            assert!(!app.template.observation.health.recognizer_available);
            if automatic {
                assert!(!app.cruise.is_active());
                assert_eq!(
                    app.cruise.snapshot(Instant::now()).stop_reason,
                    Some(CruiseStopReason::ApprovalRequired)
                );
            }
        }
    }

    #[test]
    fn recognition_enters_manual_gate_in_step_and_cruise_and_rechecks_on_approval() {
        for automatic in [false, true] {
            let (mut app, _peer) = test_console();
            app.recognizer = Box::new(SyntheticAdmitted);
            let mut request = test_request(7, 1);
            request
                .observation
                .candidates
                .push(sdr_agent_controller::protocol::CandidateSummary {
                    id: "candidate-1".to_owned(),
                    center_hz: 433_920_000,
                    bandwidth_hz: 200_000,
                    peak_dbfs: -18.0,
                    snr_db: 16.0,
                    age_ms: 0,
                });
            app.requests.insert(7, request);
            if automatic {
                app.cruise
                    .start(1024 * 1024, 8, 120, Instant::now())
                    .unwrap();
            }
            app.handle_event(
                json!({"type":"event", "session_generation":1, "event":"plan_proposed", "data":{
                    "protocol_version":1,"request_id":7,"session_generation":1,"status":"ok",
                    "action":{"kind":"run_local_recognition","candidate_id":"candidate-1"},
                    "planner":{"provider":"test","model":"test"}
                }}),
            )
            .unwrap();
            assert!(app.pending.as_ref().unwrap().approval_required);
            assert!(app.active_execution.is_none());
            if automatic {
                assert_eq!(
                    app.cruise.snapshot(Instant::now()).stop_reason,
                    Some(CruiseStopReason::ApprovalRequired)
                );
            }
            app.recognizer =
                Box::new(sdr_agent_controller::recognizer_admission::UnavailableRecognizer);
            app.approve().unwrap();
            assert!(app.pending.is_none());
            assert!(app.active_execution.is_none());
        }
    }
}
