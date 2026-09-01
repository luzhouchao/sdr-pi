use serde::Serialize;
use std::time::{Duration, Instant};

pub const AUTO_RETRY_LIMIT: u8 = 5;
pub const AUTO_RETRY_DELAY_SECS: u64 = 10;
pub const DEFAULT_AUTO_MAX_STEPS: u8 = 8;
pub const HARD_AUTO_MAX_STEPS: u8 = 128;
pub const DEFAULT_AUTO_DURATION_SECS: u64 = 120;
pub const MIN_AUTO_DURATION_SECS: u64 = 10;
pub const HARD_AUTO_DURATION_SECS: u64 = 1_800;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InteractionMode {
    StepApproval,
    AutomaticCruise,
}

impl InteractionMode {
    pub fn label(self) -> &'static str {
        match self {
            Self::StepApproval => "逐步人工批准",
            Self::AutomaticCruise => "受限自动巡航",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CruisePhase {
    Stopped,
    CheckingSdr,
    WaitingForPlanner,
    WaitingForApproval,
    Executing,
    WaitingToRetry,
}

impl CruisePhase {
    pub fn label(self) -> &'static str {
        match self {
            Self::Stopped => "已停止",
            Self::CheckingSdr => "正在检查 SDR",
            Self::WaitingForPlanner => "正在等待上游给出下一步",
            Self::WaitingForApproval => "正在等待人工批准",
            Self::Executing => "正在执行受限动作",
            Self::WaitingToRetry => "等待重试",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CruiseStopReason {
    OperatorStopped,
    SdrRetryExhausted,
    PlannerRetryExhausted,
    StepBudgetExhausted,
    DurationBudgetExhausted,
    ByteBudgetExhausted,
    ApprovalRequired,
    UnsupportedAction,
    PlannerRequestedStop,
    Fault,
}

impl CruiseStopReason {
    pub fn label(self) -> &'static str {
        match self {
            Self::OperatorStopped => "操作员已停止",
            Self::SdrRetryExhausted => "连续 5 次检测不到 SDR",
            Self::PlannerRetryExhausted => "连续 5 次未收到上游下一步",
            Self::StepBudgetExhausted => "已用完巡航步数",
            Self::DurationBudgetExhausted => "已达到巡航时长上限",
            Self::ByteBudgetExhausted => "已达到 IQ 字节预算",
            Self::ApprovalRequired => "下一步需要人工批准",
            Self::UnsupportedAction => "下一步没有生产执行器",
            Self::PlannerRequestedStop => "上游建议停止或保持",
            Self::Fault => "控制器检测到故障",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CruiseSnapshot {
    pub mode: InteractionMode,
    pub active: bool,
    pub phase: CruisePhase,
    pub phase_label: &'static str,
    pub completed_steps: u8,
    pub max_steps: u8,
    pub elapsed_ms: u64,
    pub max_duration_ms: u64,
    pub used_iq_bytes: u64,
    pub max_iq_bytes: u64,
    pub sdr_retry_count: u8,
    pub planner_retry_count: u8,
    pub retry_limit: u8,
    pub stop_reason: Option<CruiseStopReason>,
    pub stop_reason_label: Option<&'static str>,
}

pub struct CruiseControl {
    mode: InteractionMode,
    active: bool,
    phase: CruisePhase,
    started_at: Option<Instant>,
    completed_steps: u8,
    used_iq_bytes: u64,
    max_iq_bytes: u64,
    max_steps: u8,
    max_duration: Duration,
    sdr_retry_count: u8,
    planner_retry_count: u8,
    stop_reason: Option<CruiseStopReason>,
}

impl Default for CruiseControl {
    fn default() -> Self {
        Self {
            mode: InteractionMode::StepApproval,
            active: false,
            phase: CruisePhase::Stopped,
            started_at: None,
            completed_steps: 0,
            used_iq_bytes: 0,
            max_iq_bytes: 0,
            max_steps: DEFAULT_AUTO_MAX_STEPS,
            max_duration: Duration::from_secs(DEFAULT_AUTO_DURATION_SECS),
            sdr_retry_count: 0,
            planner_retry_count: 0,
            stop_reason: None,
        }
    }
}

impl CruiseControl {
    pub fn mode(&self) -> InteractionMode {
        self.mode
    }

    pub fn is_active(&self) -> bool {
        self.active
    }

    pub fn start(
        &mut self,
        max_iq_bytes: u64,
        max_steps: u8,
        max_duration_secs: u64,
        now: Instant,
    ) -> Result<(), &'static str> {
        if max_iq_bytes == 0 {
            return Err("automatic cruise IQ byte budget must be a positive finite value");
        }
        if !(1..=HARD_AUTO_MAX_STEPS).contains(&max_steps) {
            return Err("automatic cruise steps must be between 1 and 128");
        }
        if !(MIN_AUTO_DURATION_SECS..=HARD_AUTO_DURATION_SECS).contains(&max_duration_secs) {
            return Err("automatic cruise duration must be between 10 and 1800 seconds");
        }
        self.mode = InteractionMode::AutomaticCruise;
        self.active = true;
        self.phase = CruisePhase::CheckingSdr;
        self.started_at = Some(now);
        self.completed_steps = 0;
        self.used_iq_bytes = 0;
        self.max_iq_bytes = max_iq_bytes;
        self.max_steps = max_steps;
        self.max_duration = Duration::from_secs(max_duration_secs);
        self.sdr_retry_count = 0;
        self.planner_retry_count = 0;
        self.stop_reason = None;
        Ok(())
    }

    pub fn switch_to_step_approval(&mut self) {
        self.mode = InteractionMode::StepApproval;
        self.stop(CruiseStopReason::OperatorStopped);
    }

    pub fn set_phase(&mut self, phase: CruisePhase) {
        if self.active {
            self.phase = phase;
        }
    }

    pub fn record_sdr_available(&mut self) {
        self.sdr_retry_count = 0;
    }

    pub fn record_sdr_unavailable(&mut self) -> bool {
        self.sdr_retry_count = self.sdr_retry_count.saturating_add(1);
        self.phase = CruisePhase::WaitingToRetry;
        if self.sdr_retry_count >= AUTO_RETRY_LIMIT {
            self.stop(CruiseStopReason::SdrRetryExhausted);
            false
        } else {
            true
        }
    }

    pub fn record_planner_action(&mut self) {
        self.planner_retry_count = 0;
    }

    pub fn record_planner_missing(&mut self) -> bool {
        self.planner_retry_count = self.planner_retry_count.saturating_add(1);
        self.phase = CruisePhase::WaitingToRetry;
        if self.planner_retry_count >= AUTO_RETRY_LIMIT {
            self.stop(CruiseStopReason::PlannerRetryExhausted);
            false
        } else {
            true
        }
    }

    pub fn record_execution(&mut self, iq_bytes: u64) {
        self.completed_steps = self.completed_steps.saturating_add(1);
        self.used_iq_bytes = self.used_iq_bytes.saturating_add(iq_bytes);
        if self.completed_steps >= self.max_steps {
            self.stop(CruiseStopReason::StepBudgetExhausted);
        } else if self.used_iq_bytes >= self.max_iq_bytes {
            self.stop(CruiseStopReason::ByteBudgetExhausted);
        } else {
            self.phase = CruisePhase::CheckingSdr;
        }
    }

    pub fn remaining_iq_bytes(&self) -> u64 {
        self.max_iq_bytes.saturating_sub(self.used_iq_bytes)
    }

    pub fn check_duration(&mut self, now: Instant) -> bool {
        if self.active
            && self
                .started_at
                .is_some_and(|started| now.saturating_duration_since(started) >= self.max_duration)
        {
            self.stop(CruiseStopReason::DurationBudgetExhausted);
        }
        self.active
    }

    pub fn stop(&mut self, reason: CruiseStopReason) {
        self.active = false;
        self.phase = CruisePhase::Stopped;
        self.stop_reason = Some(reason);
    }

    pub fn snapshot(&self, now: Instant) -> CruiseSnapshot {
        let elapsed = self
            .started_at
            .map(|started| now.saturating_duration_since(started))
            .unwrap_or_default();
        CruiseSnapshot {
            mode: self.mode,
            active: self.active,
            phase: self.phase,
            phase_label: self.phase.label(),
            completed_steps: self.completed_steps,
            max_steps: self.max_steps,
            elapsed_ms: elapsed.as_millis().try_into().unwrap_or(u64::MAX),
            max_duration_ms: self.max_duration.as_millis() as u64,
            used_iq_bytes: self.used_iq_bytes,
            max_iq_bytes: self.max_iq_bytes,
            sdr_retry_count: self.sdr_retry_count,
            planner_retry_count: self.planner_retry_count,
            retry_limit: AUTO_RETRY_LIMIT,
            stop_reason: self.stop_reason,
            stop_reason_label: self.stop_reason.map(CruiseStopReason::label),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sdr_and_planner_retries_are_independent_and_stop_on_fifth_failure() {
        let now = Instant::now();
        let mut cruise = CruiseControl::default();
        cruise
            .start(
                1_024,
                DEFAULT_AUTO_MAX_STEPS,
                DEFAULT_AUTO_DURATION_SECS,
                now,
            )
            .unwrap();
        for expected in 1..AUTO_RETRY_LIMIT {
            assert!(cruise.record_sdr_unavailable());
            assert_eq!(cruise.snapshot(now).sdr_retry_count, expected);
            assert_eq!(cruise.snapshot(now).planner_retry_count, 0);
        }
        assert!(!cruise.record_sdr_unavailable());
        assert_eq!(
            cruise.snapshot(now).stop_reason,
            Some(CruiseStopReason::SdrRetryExhausted)
        );

        cruise
            .start(
                1_024,
                DEFAULT_AUTO_MAX_STEPS,
                DEFAULT_AUTO_DURATION_SECS,
                now,
            )
            .unwrap();
        for _ in 1..AUTO_RETRY_LIMIT {
            assert!(cruise.record_planner_missing());
        }
        assert!(!cruise.record_planner_missing());
        assert_eq!(
            cruise.snapshot(now).stop_reason,
            Some(CruiseStopReason::PlannerRetryExhausted)
        );
    }

    #[test]
    fn success_resets_only_the_matching_retry_counter() {
        let now = Instant::now();
        let mut cruise = CruiseControl::default();
        cruise
            .start(
                1_024,
                DEFAULT_AUTO_MAX_STEPS,
                DEFAULT_AUTO_DURATION_SECS,
                now,
            )
            .unwrap();
        cruise.record_sdr_unavailable();
        cruise.record_planner_missing();
        cruise.record_sdr_available();
        let snapshot = cruise.snapshot(now);
        assert_eq!(snapshot.sdr_retry_count, 0);
        assert_eq!(snapshot.planner_retry_count, 1);
        cruise.record_planner_action();
        assert_eq!(cruise.snapshot(now).planner_retry_count, 0);
    }

    #[test]
    fn byte_step_duration_and_operator_limits_stop_the_cruise() {
        let now = Instant::now();
        let mut cruise = CruiseControl::default();
        cruise
            .start(100, DEFAULT_AUTO_MAX_STEPS, DEFAULT_AUTO_DURATION_SECS, now)
            .unwrap();
        cruise.record_execution(100);
        assert_eq!(
            cruise.snapshot(now).stop_reason,
            Some(CruiseStopReason::ByteBudgetExhausted)
        );

        cruise
            .start(100, DEFAULT_AUTO_MAX_STEPS, DEFAULT_AUTO_DURATION_SECS, now)
            .unwrap();
        assert!(!cruise.check_duration(now + Duration::from_secs(DEFAULT_AUTO_DURATION_SECS)));
        assert_eq!(
            cruise
                .snapshot(now + Duration::from_secs(DEFAULT_AUTO_DURATION_SECS))
                .stop_reason,
            Some(CruiseStopReason::DurationBudgetExhausted)
        );

        cruise
            .start(100, DEFAULT_AUTO_MAX_STEPS, DEFAULT_AUTO_DURATION_SECS, now)
            .unwrap();
        cruise.stop(CruiseStopReason::OperatorStopped);
        assert!(!cruise.is_active());
        assert_eq!(cruise.mode(), InteractionMode::AutomaticCruise);
    }

    #[test]
    fn operator_budget_is_finite_and_reflected_in_status() {
        let now = Instant::now();
        let mut cruise = CruiseControl::default();
        assert!(cruise.start(0, 8, 120, now).is_err());
        assert!(cruise.start(100, 0, 120, now).is_err());
        assert!(cruise.start(100, 129, 120, now).is_err());
        assert!(cruise.start(100, 8, 9, now).is_err());
        assert!(cruise.start(100, 8, 1_801, now).is_err());
        cruise.start(100, 128, 1_800, now).unwrap();
        let snapshot = cruise.snapshot(now);
        assert_eq!(snapshot.max_steps, 128);
        assert_eq!(snapshot.max_duration_ms, 1_800_000);

        let large_finite_budget = 2_u64 * 1024 * 1024 * 1024;
        cruise
            .start(
                large_finite_budget,
                DEFAULT_AUTO_MAX_STEPS,
                DEFAULT_AUTO_DURATION_SECS,
                now,
            )
            .unwrap();
        assert_eq!(cruise.snapshot(now).max_iq_bytes, large_finite_budget);
    }
}
