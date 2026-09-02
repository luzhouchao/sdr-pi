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
};
use sdr_agent_controller::sdr::{SdrEngine, SdrError, SdrdAdapter};
use sdr_agent_controller::sweep::{
    SdrdSoftwareSweepAdapter, SweepEngine, SweepError, SweepFrequencies, SweepPlan, SweepReport,
};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
use std::env;
use std::error::Error;
use std::fs;
use std::io::{self, Read, Write};
use std::net::SocketAddr;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::mpsc::{self, RecvTimeoutError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

type AppResult<T> = Result<T, Box<dyn Error>>;
const HISTORY_LIMIT: usize = 32;
const CANCEL_START_RETRIES: usize = 50;
const AUTO_RETRY_DELAY: Duration = Duration::from_secs(AUTO_RETRY_DELAY_SECS);
const EVENT_POLL_INTERVAL: Duration = Duration::from_millis(50);

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
    let executor = options.sdrd_address.map(|address| {
        SdrdActionAdapter::new(address, Duration::from_millis(options.sdrd_timeout_ms))
    });
    let mut app = ConsoleApp::connect(
        options.socket_path,
        template,
        executor,
        options.sdrd_address,
        Duration::from_millis(options.sdrd_timeout_ms),
        options.survey_gain_db,
        options.sigmf_directory,
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
    if let Some(initial_survey) = options.initial_survey {
        app.start_initial_survey(initial_survey)?;
    }
    let (input_tx, input_rx) = mpsc::channel();
    thread::spawn(move || {
        let stdin = io::stdin();
        loop {
            let mut line = String::new();
            match stdin.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) if input_tx.send(line).is_err() => break,
                Ok(_) => {}
            }
        }
    });
    print_prompt()?;
    let mut running = true;
    while running {
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
    app.close()?;
    Ok(())
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
        _ if input.starts_with('/') => println!("未知命令；输入 /help 查看可用命令。"),
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
    client: SessionClient,
    template: PlanRequest,
    next_request_id: u64,
    session_generation: u64,
    pending: Option<ValidatedPlan>,
    requests: HashMap<u64, PlanRequest>,
    history: VecDeque<String>,
    agent_cycle_active: bool,
    active_request_id: Option<u64>,
    plan_seen_in_cycle: bool,
    executor: Option<SdrdActionAdapter>,
    active_execution: Option<ActiveExecution>,
    active_sweep: Option<ActiveSweep>,
    sdrd_address: Option<SocketAddr>,
    sdrd_timeout: Duration,
    survey_gain_db: i16,
    sigmf_directory: Option<PathBuf>,
    cruise: CruiseControl,
    auto_mission: Option<String>,
    auto_next_instruction: Option<String>,
    next_auto_attempt: Instant,
    deferred_renew: Option<(ControllerState, String)>,
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
struct InitialSurveyOptions {
    start_hz: u64,
    stop_hz: u64,
    step_hz: u64,
    dwell_ms: u64,
    gain_db: i16,
}

impl ConsoleApp {
    fn connect(
        socket_path: PathBuf,
        template: PlanRequest,
        executor: Option<SdrdActionAdapter>,
        sdrd_address: Option<SocketAddr>,
        sdrd_timeout: Duration,
        survey_gain_db: i16,
        sigmf_directory: Option<PathBuf>,
    ) -> AppResult<Self> {
        let generation = template.session_generation;
        let next_request_id = template.request_id;
        let mut app = Self {
            client: SessionClient::connect(socket_path, generation)?,
            template,
            next_request_id,
            session_generation: generation,
            pending: None,
            requests: HashMap::new(),
            history: VecDeque::with_capacity(HISTORY_LIMIT),
            agent_cycle_active: false,
            active_request_id: None,
            plan_seen_in_cycle: false,
            executor,
            active_execution: None,
            active_sweep: None,
            sdrd_address,
            sdrd_timeout,
            survey_gain_db,
            sigmf_directory,
            cruise: CruiseControl::default(),
            auto_mission: None,
            auto_next_instruction: None,
            next_auto_attempt: Instant::now(),
            deferred_renew: None,
        };
        app.command("open_session", None)?;
        Ok(app)
    }

    fn submit(&mut self, instruction: String) -> AppResult<()> {
        if self.active_execution.is_some() || self.active_sweep.is_some() || self.agent_cycle_active
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
        request.instruction = instruction.clone();
        ControllerPolicy.validate_request(&request)?;
        println!("模型输入> {}", serde_json::to_string(&request)?);
        self.record(format!("operator: {instruction}"));
        self.requests.insert(request_id, request.clone());
        self.agent_cycle_active = true;
        self.active_request_id = Some(request_id);
        self.plan_seen_in_cycle = false;
        if let Err(error) = self.command("prompt", Some(request)) {
            self.requests.remove(&request_id);
            self.active_request_id = None;
            self.agent_cycle_active = false;
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
                return Ok(());
            }
            return Err(error);
        }
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
        if self.active_execution.is_some() || self.active_sweep.is_some() || self.agent_cycle_active
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
        self.template.session_generation = self.session_generation;
        self.pending = None;
        self.requests.clear();
        self.active_request_id = None;
        self.plan_seen_in_cycle = false;
        self.client.session_generation = self.session_generation;
        self.command("open_session", None)?;
        self.record(message.to_owned());
        println!("{message}；旧计划已失效。");
        Ok(())
    }

    fn approve(&mut self) -> AppResult<()> {
        if self.active_execution.is_some() || self.active_sweep.is_some() {
            println!("已有硬件动作正在执行。");
            return Ok(());
        }
        if let Some(plan) = self.pending.take() {
            self.record(format!("approved request {}", plan.request_id));
            match plan.action {
                ProposedAction::SurveyBand { .. } => self.start_planned_survey(plan)?,
                ProposedAction::InspectCandidate { .. } => self.start_candidate_inspection(plan)?,
                ProposedAction::CaptureBoundedIq { .. } => {
                    let authorization = ExecutionAuthorization::operator_approved(&plan);
                    self.start_execution(plan, authorization)?;
                }
                _ => println!("request={} 没有可批准的生产执行动作。", plan.request_id),
            }
        } else {
            println!("没有等待批准的计划。")
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
        if self.active_execution.is_some() || self.active_sweep.is_some() || self.agent_cycle_active
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
        if self.active_execution.is_some() || self.active_sweep.is_some() {
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
        if self.active_execution.is_some() || self.active_sweep.is_some() {
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
                self.template.observation.health = observation.post_execution_sdr.planner_health(
                    self.template.observation.health.recognizer_available,
                    self.template.observation.health.dropped_observations,
                );
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
            self.command("abort", None)?;
            if self.agent_cycle_active {
                self.deferred_renew = Some((ControllerState::Holding, message.to_owned()));
            }
            println!("已要求上游停止当前生成；收到结束确认后会使旧计划失效。");
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

    fn enable_step_approval(&mut self) -> AppResult<()> {
        if self.cruise.mode() == InteractionMode::StepApproval && !self.cruise.is_active() {
            println!("当前已经是逐步人工批准模式。每个可执行动作都会等待 /approve 或 /reject。");
            return Ok(());
        }
        let had_active_step = self.agent_cycle_active
            || self.active_execution.is_some()
            || self.active_sweep.is_some();
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
        if self.agent_cycle_active || self.active_execution.is_some() || self.active_sweep.is_some()
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
        while let Some(frame) = self.client.try_read()? {
            self.handle_event(frame)?;
        }
        self.poll_execution()?;
        self.poll_sweep()?;
        if !self.agent_cycle_active
            && self.active_execution.is_none()
            && self.active_sweep.is_none()
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
            {
                self.stop("自动巡航达到时长上限")?;
            }
            return Ok(());
        }
        if self.agent_cycle_active
            || self.active_execution.is_some()
            || self.active_sweep.is_some()
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

    fn refresh_sdr_health(&mut self, announce_failure: bool) -> AppResult<bool> {
        let Some(address) = self.sdrd_address else {
            if announce_failure {
                println!("SDR 检查失败：没有配置 SDRD 地址。");
            }
            return Ok(false);
        };
        let mut observer = SdrdAdapter::new(address, self.sdrd_timeout);
        match observer.observe() {
            Ok(snapshot) if snapshot.online && snapshot.healthy => {
                self.template.observation.age_ms = 0;
                self.template.observation.health = snapshot.planner_health(
                    self.template.observation.health.recognizer_available,
                    self.template.observation.health.dropped_observations,
                );
                Ok(true)
            }
            Ok(snapshot) => {
                self.template.observation.age_ms = 0;
                self.template.observation.health = snapshot.planner_health(
                    self.template.observation.health.recognizer_available,
                    self.template.observation.health.dropped_observations,
                );
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
        }
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
        if self.active_execution.is_some() || self.active_sweep.is_some() || self.agent_cycle_active
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
        let mut command = json!({
            "protocol_version": 1,
            "command_id": self.client.next_command_id(),
            "session_generation": self.session_generation,
            "type": kind,
        });
        if let Some(context) = context {
            command["context"] = serde_json::to_value(context)?;
        }
        self.client.write(&command)?;
        loop {
            let frame = self.client.read()?;
            if frame.get("type").and_then(Value::as_str) == Some("response")
                && frame.get("command_id").and_then(Value::as_u64)
                    == command.get("command_id").and_then(Value::as_u64)
            {
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
            self.handle_event(frame)?;
        }
    }

    fn handle_event(&mut self, frame: Value) -> AppResult<()> {
        if frame.get("type").and_then(Value::as_str) != Some("event") {
            return Ok(());
        }
        if frame.get("session_generation").and_then(Value::as_u64) != Some(self.session_generation)
        {
            return Err(invalid_input("stale session event").into());
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
                let request = self
                    .requests
                    .get(&response.request_id)
                    .ok_or_else(|| invalid_input("plan refers to an unknown request"))?;
                let plan = ControllerPolicy.validate_response(request, response)?;
                let decision_basis = describe_decision_basis(&plan, request);
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
                        ProposedAction::CaptureBoundedIq { .. } if plan.approval_required => {
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
                if self.agent_cycle_active {
                    self.command("abort", None)?;
                    println!(
                        "计划已经 Rust 验证；已结束本轮剩余模型生成，避免阻塞执行后的下一步。"
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
                if let Some(request_id) = self.active_request_id.take() {
                    self.requests.remove(&request_id);
                }
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
    }

    fn emit_observation(&self) -> AppResult<()> {
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
    socket_path: PathBuf,
    request_path: PathBuf,
    instruction: Option<String>,
    sdrd_address: Option<SocketAddr>,
    sdrd_timeout_ms: u64,
    survey_gain_db: i16,
    initial_survey: Option<InitialSurveyOptions>,
    sigmf_directory: Option<PathBuf>,
}

impl Options {
    fn parse() -> AppResult<Self> {
        let mut socket_path = PathBuf::from("/run/sdr-agent/session.sock");
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
        let mut args = env::args().skip(1);
        while let Some(arg) = args.next() {
            match arg.as_str() {
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
        Ok(Self {
            socket_path,
            request_path,
            instruction: (!instruction.is_empty()).then(|| instruction.join(" ")),
            sdrd_address,
            sdrd_timeout_ms,
            survey_gain_db,
            initial_survey,
            sigmf_directory,
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
         默认 8 步、120 秒、累计 64 MiB；两类失败各重试 5 次，每次间隔 10 秒\n\
         会话：/pause 暂停，/resume 继续，/stop 立即停止，/quit 退出"
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

#[cfg(test)]
mod tests {
    use super::*;

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
}
