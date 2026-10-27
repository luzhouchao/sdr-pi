use serde::{Deserialize, Serialize};
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
            Self::StepApproval => "等待批准",
            Self::AutomaticCruise => "自动任务",
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
    TaskCompleted,
    OperatorStopped,
    SdrRetryExhausted,
    PlannerRetryExhausted,
    StepBudgetExhausted,
    DurationBudgetExhausted,
    ByteBudgetExhausted,
    ApprovalRequired,
    UnsupportedAction,
    PlannerRequestedStop,
    AdjacentSweepRequired,
    LocalSweepLimit,
    EmptySweepLimit,
    Fault,
}

impl CruiseStopReason {
    pub fn label(self) -> &'static str {
        match self {
            Self::TaskCompleted => "任务目标已完成",
            Self::OperatorStopped => "操作员已停止",
            Self::SdrRetryExhausted => "连续 5 次检测不到 SDR",
            Self::PlannerRetryExhausted => "连续 5 次未收到上游下一步",
            Self::StepBudgetExhausted => "已用完任务步数",
            Self::DurationBudgetExhausted => "已达到任务时长上限",
            Self::ByteBudgetExhausted => "已达到 IQ 字节预算",
            Self::ApprovalRequired => "下一步需要人工批准",
            Self::UnsupportedAction => "下一步没有生产执行器",
            Self::PlannerRequestedStop => "上游建议停止或保持",
            Self::AdjacentSweepRequired => "上一轮无候选，不能继续同一区域细扫",
            Self::LocalSweepLimit => "已达到局部扫频复查上限",
            Self::EmptySweepLimit => "连续三轮无候选，结束本次任务",
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

    /// Approval waits remain part of the original cruise duration budget.
    pub fn recognition_deadline(
        &self,
        now: Instant,
        bytes: u64,
    ) -> Result<Option<Instant>, CruiseStopReason> {
        if self.mode != InteractionMode::AutomaticCruise {
            return Ok(None);
        }
        if self.completed_steps >= self.max_steps {
            return Err(CruiseStopReason::StepBudgetExhausted);
        }
        let deadline = self
            .started_at
            .and_then(|started| started.checked_add(self.max_duration))
            .ok_or(CruiseStopReason::DurationBudgetExhausted)?;
        if now >= deadline {
            return Err(CruiseStopReason::DurationBudgetExhausted);
        }
        if bytes > self.remaining_iq_bytes() {
            return Err(CruiseStopReason::ByteBudgetExhausted);
        }
        Ok(Some(deadline))
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

// These limits bound work, not RF truth: empty relative-contrast candidates do
// not prove an empty spectrum. History covers only this explicitly started run.
pub const LOCAL_SWEEP_LIMIT: u8 = 3;
pub const EMPTY_SWEEP_LIMIT: u8 = 3;
pub const RECENT_SWEEP_LIMIT: usize = 8;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SweepVisit {
    pub start_hz: u64,
    pub stop_hz: u64,
    pub candidate_count: u8,
}

impl SweepVisit {
    fn overlaps(&self, start_hz: u64, stop_hz: u64) -> bool {
        // Neighboring multi-point scans may share one boundary. A single-point
        // recheck inside a previous range still counts as local work.
        if self.start_hz == self.stop_hz || start_hz == stop_hz {
            self.start_hz <= stop_hz && start_hz <= self.stop_hz
        } else {
            self.start_hz < stop_hz && start_hz < self.stop_hz
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CruisePlanningSummary {
    pub remaining_steps: u8,
    pub remaining_ms: u64,
    pub remaining_iq_bytes: u64,
    pub local_sweep_limit: u8,
    pub empty_sweep_limit: u8,
    pub consecutive_empty_sweeps: u8,
    pub recent_sweeps: Vec<SweepVisit>,
    pub history_truncated: bool,
}

impl CruisePlanningSummary {
    pub fn valid(&self, min_hz: u64, max_hz: u64) -> bool {
        self.remaining_steps <= HARD_AUTO_MAX_STEPS
            && self.remaining_ms <= HARD_AUTO_DURATION_SECS * 1_000
            && self.remaining_iq_bytes <= 9_007_199_254_740_991
            && self.local_sweep_limit == LOCAL_SWEEP_LIMIT
            && self.empty_sweep_limit == EMPTY_SWEEP_LIMIT
            && self.consecutive_empty_sweeps <= EMPTY_SWEEP_LIMIT
            && self.recent_sweeps.len() <= RECENT_SWEEP_LIMIT
            && self.recent_sweeps.iter().all(|v| {
                min_hz <= v.start_hz
                    && v.start_hz <= v.stop_hz
                    && v.stop_hz <= max_hz
                    && v.candidate_count <= 32
            })
    }
}

#[derive(Default)]
pub struct SweepProgress {
    visits: Vec<SweepVisit>,
    consecutive_empty: u8,
}

impl SweepProgress {
    pub fn check(&self, action: &crate::protocol::ProposedAction) -> Result<(), CruiseStopReason> {
        use crate::protocol::ProposedAction;
        let (start_hz, stop_hz) = match action {
            ProposedAction::SurveyBand {
                start_hz, stop_hz, ..
            } => (*start_hz, *stop_hz),
            ProposedAction::InspectCandidate { center_hz, .. } => (*center_hz, *center_hz),
            _ => return Ok(()),
        };
        if self.consecutive_empty >= EMPTY_SWEEP_LIMIT {
            return Err(CruiseStopReason::EmptySweepLimit);
        }
        if self.visits.len() >= usize::from(HARD_AUTO_MAX_STEPS) {
            return Err(CruiseStopReason::StepBudgetExhausted);
        }
        if self
            .visits
            .last()
            .is_some_and(|last| last.candidate_count == 0 && last.overlaps(start_hz, stop_hz))
        {
            return Err(CruiseStopReason::AdjacentSweepRequired);
        }
        if self
            .visits
            .iter()
            .filter(|v| v.overlaps(start_hz, stop_hz))
            .count()
            >= usize::from(LOCAL_SWEEP_LIMIT)
        {
            return Err(CruiseStopReason::LocalSweepLimit);
        }
        Ok(())
    }

    pub fn record(&mut self, visit: SweepVisit) -> Option<CruiseStopReason> {
        if self.visits.len() >= usize::from(HARD_AUTO_MAX_STEPS) {
            return Some(CruiseStopReason::StepBudgetExhausted);
        }
        self.consecutive_empty = if visit.candidate_count == 0 {
            self.consecutive_empty
                .saturating_add(1)
                .min(EMPTY_SWEEP_LIMIT)
        } else {
            0
        };
        self.visits.push(visit);
        (self.consecutive_empty >= EMPTY_SWEEP_LIMIT).then_some(CruiseStopReason::EmptySweepLimit)
    }

    pub fn planning_summary(&self, cruise: &CruiseControl, now: Instant) -> CruisePlanningSummary {
        let status = cruise.snapshot(now);
        CruisePlanningSummary {
            remaining_steps: status.max_steps.saturating_sub(status.completed_steps),
            remaining_ms: status.max_duration_ms.saturating_sub(status.elapsed_ms),
            remaining_iq_bytes: cruise.remaining_iq_bytes(),
            local_sweep_limit: LOCAL_SWEEP_LIMIT,
            empty_sweep_limit: EMPTY_SWEEP_LIMIT,
            consecutive_empty_sweeps: self.consecutive_empty,
            recent_sweeps: self
                .visits
                .iter()
                .rev()
                .take(RECENT_SWEEP_LIMIT)
                .cloned()
                .collect::<Vec<_>>()
                .into_iter()
                .rev()
                .collect(),
            history_truncated: self.visits.len() > RECENT_SWEEP_LIMIT,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognition_approval_preserves_all_cruise_budgets() {
        let now = Instant::now();
        let mut cruise = CruiseControl::default();
        assert_eq!(cruise.recognition_deadline(now, 32768), Ok(None));
        cruise.start(65536, 2, 10, now).unwrap();
        cruise.stop(CruiseStopReason::ApprovalRequired);
        assert_eq!(
            cruise.recognition_deadline(now, 32768),
            Ok(Some(now + Duration::from_secs(10)))
        );
        assert_eq!(
            cruise.recognition_deadline(now + Duration::from_secs(10), 32768),
            Err(CruiseStopReason::DurationBudgetExhausted)
        );
        assert_eq!(
            cruise.recognition_deadline(now, 65537),
            Err(CruiseStopReason::ByteBudgetExhausted)
        );
        cruise.record_execution(32768);
        cruise.record_execution(32768);
        assert_eq!(
            cruise.recognition_deadline(now, 32768),
            Err(CruiseStopReason::StepBudgetExhausted)
        );
    }

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
