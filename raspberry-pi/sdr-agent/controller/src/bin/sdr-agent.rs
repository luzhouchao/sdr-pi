#![cfg(unix)]

use sdr_agent_controller::policy::ControllerPolicy;
use sdr_agent_controller::protocol::{
    ControllerState, PlanRequest, PlanResponse, ValidatedPlan, MAX_FRAME_BYTES,
};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
use std::env;
use std::error::Error;
use std::fs;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;

type AppResult<T> = Result<T, Box<dyn Error>>;
const HISTORY_LIMIT: usize = 32;

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
    let mut app = ConsoleApp::connect(options.socket_path, template)?;

    if let Some(instruction) = options.instruction {
        app.submit(instruction)?;
        return Ok(());
    }

    println!("SDR Agent 已连接。输入 /help 查看命令。当前版本不会直接执行硬件动作。");
    let stdin = io::stdin();
    loop {
        print!("SDR Agent> ");
        io::stdout().flush()?;
        let mut line = String::new();
        if stdin.read_line(&mut line)? == 0 {
            println!();
            break;
        }
        let input = line.trim();
        if input.is_empty() {
            continue;
        }
        match input {
            "/quit" | "/exit" | "/退出" => break,
            "/help" | "/帮助" => print_help(),
            "/status" | "/状态" => app.status()?,
            "/history" | "/历史" => app.print_history(),
            "/approve" | "/批准" => app.approve(),
            "/reject" | "/拒绝" => app.reject(),
            "/pause" | "/暂停" => app.renew(ControllerState::Holding, "会话已暂停")?,
            "/resume" | "/继续" => app.renew(ControllerState::Idle, "会话已恢复")?,
            "/stop" | "/停止" => app.renew(ControllerState::Holding, "会话已停止")?,
            _ if input.starts_with('/') => {
                println!("未知命令；输入 /help 查看可用命令。")
            }
            _ => app.submit(input.to_owned())?,
        }
    }
    app.close()?;
    Ok(())
}

struct ConsoleApp {
    client: SessionClient,
    template: PlanRequest,
    next_request_id: u64,
    session_generation: u64,
    pending: Option<ValidatedPlan>,
    requests: HashMap<u64, PlanRequest>,
    history: VecDeque<String>,
    agent_cycle_ended: bool,
}

impl ConsoleApp {
    fn connect(socket_path: PathBuf, template: PlanRequest) -> AppResult<Self> {
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
            agent_cycle_ended: false,
        };
        app.command("open_session", None)?;
        Ok(app)
    }

    fn submit(&mut self, instruction: String) -> AppResult<()> {
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
        self.record(format!("operator: {instruction}"));
        self.requests.insert(request_id, request.clone());
        self.agent_cycle_ended = false;
        self.command("prompt", Some(request))?;
        if !self.agent_cycle_ended {
            self.read_until_agent_end()?;
        }
        self.requests.remove(&request_id);
        Ok(())
    }

    fn status(&mut self) -> AppResult<()> {
        let response = self.command("get_state", None)?;
        println!(
            "state={:?} generation={} next_request={} pending_approval={} worker={}",
            self.template.state,
            self.session_generation,
            self.next_request_id,
            self.pending.is_some(),
            response.get("data").unwrap_or(&Value::Null)
        );
        Ok(())
    }

    fn renew(&mut self, state: ControllerState, message: &str) -> AppResult<()> {
        self.command("close_session", None)?;
        self.session_generation = self
            .session_generation
            .checked_add(1)
            .ok_or_else(|| invalid_input("session generation exhausted"))?;
        self.template.state = state;
        self.template.session_generation = self.session_generation;
        self.pending = None;
        self.requests.clear();
        self.client.session_generation = self.session_generation;
        self.command("open_session", None)?;
        self.record(message.to_owned());
        println!("{message}；旧计划已失效。");
        Ok(())
    }

    fn approve(&mut self) {
        if let Some(plan) = self.pending.take() {
            self.record(format!("approved request {}", plan.request_id));
            println!(
                "已记录批准 request={}；SdrActionExecutor 尚未启用，因此没有操作硬件。",
                plan.request_id
            );
        } else {
            println!("没有等待批准的计划。")
        }
    }

    fn reject(&mut self) {
        if let Some(plan) = self.pending.take() {
            self.record(format!("rejected request {}", plan.request_id));
            println!("已拒绝 request={}。", plan.request_id);
        } else {
            println!("没有等待拒绝的计划。")
        }
    }

    fn close(&mut self) -> AppResult<()> {
        let _ = self.command("close_session", None);
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

    fn read_until_agent_end(&mut self) -> AppResult<()> {
        loop {
            let frame = self.client.read()?;
            let ended = frame.get("type").and_then(Value::as_str) == Some("event")
                && frame.get("event").and_then(Value::as_str) == Some("agent_end");
            self.handle_event(frame)?;
            if ended {
                return Ok(());
            }
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
            "assistant_message" => {
                if let Some(text) = frame.pointer("/data/text").and_then(Value::as_str) {
                    println!("Agent> {text}");
                    self.record(format!("agent: {text}"));
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
                println!("Validated plan> {}", serde_json::to_string(&plan)?);
                self.record(format!("validated request {}", plan.request_id));
                if plan.approval_required {
                    self.pending = Some(plan);
                    println!("该计划需要人工批准：输入 /approve 或 /reject。")
                }
            }
            "agent_error" => {
                let error = frame
                    .pointer("/data/error")
                    .and_then(Value::as_str)
                    .unwrap_or("Agent unavailable");
                return Err(invalid_input(error).into());
            }
            "agent_end" => self.agent_cycle_ended = true,
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
    reader: BufReader<UnixStream>,
    command_id: u64,
    session_generation: u64,
}

impl SessionClient {
    fn connect(path: PathBuf, session_generation: u64) -> AppResult<Self> {
        let writer = UnixStream::connect(path)?;
        let reader = BufReader::new(writer.try_clone()?);
        Ok(Self {
            writer,
            reader,
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
        let mut frame = Vec::new();
        self.reader
            .by_ref()
            .take((MAX_FRAME_BYTES + 1) as u64)
            .read_until(b'\n', &mut frame)?;
        if frame.len() > MAX_FRAME_BYTES + 1 || frame.last() != Some(&b'\n') {
            return Err(invalid_input("invalid session response framing").into());
        }
        frame.pop();
        Ok(serde_json::from_slice(&frame)?)
    }
}

struct Options {
    socket_path: PathBuf,
    request_path: PathBuf,
    instruction: Option<String>,
}

impl Options {
    fn parse() -> AppResult<Self> {
        let mut socket_path = PathBuf::from("/run/sdr-agent/session.sock");
        let mut request_path = PathBuf::from("/etc/sdr-agent/request.json");
        let mut instruction = Vec::new();
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
                _ if arg.starts_with('-') => {
                    return Err(invalid_input(format!("unknown option {arg}")).into())
                }
                _ => instruction.push(arg),
            }
        }
        Ok(Self {
            socket_path,
            request_path,
            instruction: (!instruction.is_empty()).then(|| instruction.join(" ")),
        })
    }
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
        "/status 状态  /history 历史  /approve 批准  /reject 拒绝\n\
         /pause 暂停  /resume 继续  /stop 停止  /quit 退出"
    );
}

fn invalid_input(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.into())
}
