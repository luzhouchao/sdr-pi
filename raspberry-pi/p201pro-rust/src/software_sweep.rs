use crate::aggregation::{CandidateBand, SpectrumAggregator, SpectrumConfig, SpectrumSnapshot};
use industrial_io as iio;
use serde::Serialize;
use std::error::Error;
use std::io;
use std::thread;
use std::time::{Duration, Instant};

const PHY_DEVICE: &str = "ad9361-phy";
const RX_DEVICE: &str = "cf-ad9361-lpc";
const RX_I_CHANNEL: &str = "voltage0";
const RX_Q_CHANNEL: &str = "voltage1";
const RX_LO_CHANNEL: &str = "altvoltage0";
const MAX_SWEEP_BYTES: u64 = 64 * 1024 * 1024;
const MAX_SWEEP_DURATION: Duration = Duration::from_secs(60);
const LO_TOLERANCE_HZ: i64 = 10;

type SweepResult<T> = Result<T, Box<dyn Error>>;

#[derive(Clone, Debug)]
pub(crate) struct SoftwareSweepPlan {
    pub centers_hz: Vec<i64>,
    pub continuous_step_hz: Option<i64>,
    pub sample_rate_hz: i64,
    pub rf_bandwidth_hz: i64,
    pub buffer_samples: usize,
    pub settle_ms: u64,
    pub fft_size: usize,
    pub overlap_percent: usize,
    pub frames_per_point: usize,
    pub coarse_bins: usize,
    pub threshold_db: f32,
    pub merge_gap_bins: usize,
    pub max_points: usize,
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct SoftwareSweepEstimate {
    pub points: usize,
    pub refills_per_point: usize,
    pub maximum_network_bytes: u64,
    pub estimated_duration_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct RadioProfile {
    pub center_freq_hz: i64,
    pub phy_channels: Vec<PhyChannelProfile>,
    pub scan_channels: Vec<ScanChannelProfile>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct PhyChannelProfile {
    pub id: String,
    pub sample_rate_hz: i64,
    pub rf_bandwidth_hz: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ScanChannelProfile {
    pub id: String,
    pub enabled: bool,
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct SoftwareSweepReport {
    pub schema_version: u8,
    pub backend: &'static str,
    pub estimate: SoftwareSweepEstimate,
    pub elapsed_ms: u64,
    pub initial_profile: RadioProfile,
    pub restored_profile: RadioProfile,
    pub restored: bool,
    pub points: Vec<SpectrumSnapshot>,
    pub candidates: Vec<CandidateBand>,
}

impl SoftwareSweepPlan {
    pub(crate) fn validate(&self) -> SweepResult<SoftwareSweepEstimate> {
        if self.centers_hz.is_empty() || self.centers_hz.len() > self.max_points {
            return Err(invalid_input("sweep point count is empty or exceeds max-points").into());
        }
        if self.max_points == 0 || self.max_points > 256 {
            return Err(invalid_input("max-points must be between 1 and 256").into());
        }
        if self
            .centers_hz
            .iter()
            .any(|center| !(70_000_000..=6_000_000_000).contains(center))
        {
            return Err(
                invalid_input("every sweep center must be between 70 MHz and 6 GHz").into(),
            );
        }
        if !(2_083_333..=30_720_000).contains(&self.sample_rate_hz)
            || !(200_000..=56_000_000).contains(&self.rf_bandwidth_hz)
            || self.sample_rate_hz < self.rf_bandwidth_hz
        {
            return Err(invalid_input("invalid sweep sample rate or RF bandwidth").into());
        }
        if !(1_024..=1_048_576).contains(&self.buffer_samples) {
            return Err(invalid_input("buffer-samples must be between 1024 and 1048576").into());
        }
        if self.settle_ms > 5_000 {
            return Err(invalid_input("settle-ms must be at most 5000").into());
        }
        if self.fft_size < 64 || !self.fft_size.is_power_of_two() {
            return Err(invalid_input("fft-size must be a power of two >= 64").into());
        }
        if self.overlap_percent > 75 || self.frames_per_point == 0 || self.frames_per_point > 256 {
            return Err(invalid_input("invalid overlap or frames-per-point").into());
        }
        if self.coarse_bins == 0 || self.coarse_bins > self.fft_size {
            return Err(invalid_input("coarse-bins must be between 1 and FFT size").into());
        }
        if !self.threshold_db.is_finite() || self.threshold_db <= 0.0 {
            return Err(invalid_input("threshold-db must be positive and finite").into());
        }
        if let Some(step_hz) = self.continuous_step_hz {
            if step_hz <= 0 || step_hz.saturating_mul(5) > self.rf_bandwidth_hz.saturating_mul(4) {
                return Err(invalid_input(
                    "continuous step must be positive and no larger than 80% of RF bandwidth",
                )
                .into());
            }
        }

        let hop = (self.fft_size * (100 - self.overlap_percent) / 100).max(1);
        let required_samples = self
            .fft_size
            .saturating_add(self.frames_per_point.saturating_sub(1).saturating_mul(hop));
        let refills_per_point = required_samples.div_ceil(self.buffer_samples).max(1);
        let maximum_network_bytes = (self.centers_hz.len() as u64)
            .checked_mul(refills_per_point as u64)
            .and_then(|value| value.checked_mul(self.buffer_samples as u64))
            .and_then(|value| value.checked_mul(4))
            .ok_or_else(|| invalid_input("sweep byte estimate overflow"))?;
        if maximum_network_bytes > MAX_SWEEP_BYTES {
            return Err(invalid_input("sweep exceeds the 64 MiB network-data cap").into());
        }
        let capture_ms = maximum_network_bytes
            .saturating_div(4)
            .saturating_mul(1_000)
            .div_ceil(self.sample_rate_hz as u64);
        let estimated_duration_ms = capture_ms
            .saturating_add((self.centers_hz.len() as u64).saturating_mul(self.settle_ms));
        if estimated_duration_ms > MAX_SWEEP_DURATION.as_millis() as u64 {
            return Err(invalid_input("estimated sweep duration exceeds 60 seconds").into());
        }
        Ok(SoftwareSweepEstimate {
            points: self.centers_hz.len(),
            refills_per_point,
            maximum_network_bytes,
            estimated_duration_ms,
        })
    }
}

pub(crate) fn run(
    ctx: &iio::Context,
    plan: &SoftwareSweepPlan,
) -> SweepResult<SoftwareSweepReport> {
    let estimate = plan.validate()?;
    let initial_profile = read_profile(ctx)?;
    let started = Instant::now();
    let execution = run_inner(ctx, plan, &estimate);
    let restoration = restore_profile(ctx, &initial_profile);
    let restored_profile = read_profile(ctx);

    match (execution, restoration, restored_profile) {
        (Ok((points, candidates)), Ok(()), Ok(restored_profile)) => {
            verify_restoration(&initial_profile, &restored_profile)?;
            Ok(SoftwareSweepReport {
                schema_version: 1,
                backend: "pi_rustfft_iio",
                estimate,
                elapsed_ms: started.elapsed().as_millis() as u64,
                initial_profile,
                restored_profile,
                restored: true,
                points,
                candidates,
            })
        }
        (Err(execution), Ok(()), Ok(restored_profile)) => {
            verify_restoration(&initial_profile, &restored_profile)?;
            Err(execution)
        }
        (_, Err(restoration), _) => Err(io::Error::other(format!(
            "radio restoration failed after sweep: {restoration}"
        ))
        .into()),
        (_, Ok(()), Err(readback)) => {
            Err(io::Error::other(format!("radio restoration readback failed: {readback}")).into())
        }
    }
}

fn run_inner(
    ctx: &iio::Context,
    plan: &SoftwareSweepPlan,
    estimate: &SoftwareSweepEstimate,
) -> SweepResult<(Vec<SpectrumSnapshot>, Vec<CandidateBand>)> {
    let phy = ctx
        .find_device(PHY_DEVICE)
        .ok_or_else(|| not_found("missing ad9361-phy"))?;
    for channel_name in [RX_I_CHANNEL, RX_Q_CHANNEL] {
        let channel = phy
            .find_input_channel(channel_name)
            .ok_or_else(|| not_found(format!("missing PHY channel {channel_name}")))?;
        channel.attr_write_int("sampling_frequency", plan.sample_rate_hz)?;
        channel.attr_write_int("rf_bandwidth", plan.rf_bandwidth_hz)?;
    }

    let rx = ctx
        .find_device(RX_DEVICE)
        .ok_or_else(|| not_found("missing cf-ad9361-lpc"))?;
    for channel in rx.channels() {
        if channel.is_input() && channel.is_scan_element() {
            channel.disable();
        }
    }
    let i_channel = rx
        .find_input_channel(RX_I_CHANNEL)
        .ok_or_else(|| not_found("missing RX I channel"))?;
    let q_channel = rx
        .find_input_channel(RX_Q_CHANNEL)
        .ok_or_else(|| not_found("missing RX Q channel"))?;
    i_channel.enable();
    q_channel.enable();
    if rx.sample_size()? != 4 {
        return Err(invalid_input("software sweep requires 4-byte complex-int16 samples").into());
    }

    let mut buffer = rx.create_buffer(plan.buffer_samples, false)?;
    let mut aggregator = SpectrumAggregator::new(SpectrumConfig {
        center_freq_hz: plan.centers_hz[0],
        sample_rate_hz: plan.sample_rate_hz,
        fft_size: plan.fft_size,
        overlap_percent: plan.overlap_percent,
        frames_per_snapshot: plan.frames_per_point,
        coarse_bins: plan.coarse_bins,
        threshold_above_noise_db: plan.threshold_db,
        merge_gap_bins: plan.merge_gap_bins,
        dc_exclusion_bins: 1,
    })
    .map_err(invalid_input)?;
    let lo = phy
        .find_output_channel(RX_LO_CHANNEL)
        .ok_or_else(|| not_found("missing RX LO channel"))?;
    let mut points = Vec::with_capacity(plan.centers_hz.len());

    for &center_hz in &plan.centers_hz {
        lo.attr_write_int("frequency", center_hz)?;
        let observed_center = lo.attr_read_int("frequency")?;
        if observed_center.abs_diff(center_hz) > LO_TOLERANCE_HZ as u64 {
            return Err(io::Error::other(format!(
                "LO readback mismatch: requested={center_hz} observed={observed_center}"
            ))
            .into());
        }
        thread::sleep(Duration::from_millis(plan.settle_ms));
        aggregator.reset_for_center(observed_center);
        let mut completed = Vec::new();
        for _ in 0..estimate.refills_per_point {
            let bytes = buffer.refill()?;
            if bytes != plan.buffer_samples.saturating_mul(4) {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    format!(
                        "short IIO refill: expected={} got={bytes}",
                        plan.buffer_samples * 4
                    ),
                )
                .into());
            }
            completed.extend(
                aggregator.push_iq(
                    buffer
                        .channel_iter::<i16>(&i_channel)
                        .zip(buffer.channel_iter::<i16>(&q_channel))
                        .map(|(&i, &q)| (i, q)),
                ),
            );
        }
        let snapshot = completed
            .pop()
            .ok_or_else(|| io::Error::other("FFT aggregation did not complete one sweep point"))?;
        points.push(snapshot);
    }
    drop(buffer);
    let candidates = merge_candidates(&points, plan);
    Ok((points, candidates))
}

fn read_profile(ctx: &iio::Context) -> SweepResult<RadioProfile> {
    let phy = ctx
        .find_device(PHY_DEVICE)
        .ok_or_else(|| not_found("missing ad9361-phy"))?;
    let lo = phy
        .find_output_channel(RX_LO_CHANNEL)
        .ok_or_else(|| not_found("missing RX LO channel"))?;
    let mut phy_channels = Vec::new();
    for id in [RX_I_CHANNEL, RX_Q_CHANNEL] {
        let channel = phy
            .find_input_channel(id)
            .ok_or_else(|| not_found(format!("missing PHY channel {id}")))?;
        phy_channels.push(PhyChannelProfile {
            id: id.to_owned(),
            sample_rate_hz: channel.attr_read_int("sampling_frequency")?,
            rf_bandwidth_hz: channel.attr_read_int("rf_bandwidth")?,
        });
    }
    let rx = ctx
        .find_device(RX_DEVICE)
        .ok_or_else(|| not_found("missing cf-ad9361-lpc"))?;
    let mut scan_channels = Vec::new();
    for channel in rx.channels() {
        if channel.is_input() && channel.is_scan_element() {
            scan_channels.push(ScanChannelProfile {
                id: channel.id().unwrap_or_default(),
                enabled: channel.is_enabled(),
            });
        }
    }
    scan_channels.sort_by(|left, right| left.id.cmp(&right.id));
    Ok(RadioProfile {
        center_freq_hz: lo.attr_read_int("frequency")?,
        phy_channels,
        scan_channels,
    })
}

fn restore_profile(ctx: &iio::Context, profile: &RadioProfile) -> SweepResult<()> {
    let phy = ctx
        .find_device(PHY_DEVICE)
        .ok_or_else(|| not_found("missing ad9361-phy"))?;
    for saved in &profile.phy_channels {
        let channel = phy
            .find_input_channel(&saved.id)
            .ok_or_else(|| not_found(format!("missing PHY channel {}", saved.id)))?;
        channel.attr_write_int("sampling_frequency", saved.sample_rate_hz)?;
        channel.attr_write_int("rf_bandwidth", saved.rf_bandwidth_hz)?;
    }
    let lo = phy
        .find_output_channel(RX_LO_CHANNEL)
        .ok_or_else(|| not_found("missing RX LO channel"))?;
    lo.attr_write_int("frequency", profile.center_freq_hz)?;

    let rx = ctx
        .find_device(RX_DEVICE)
        .ok_or_else(|| not_found("missing cf-ad9361-lpc"))?;
    for saved in &profile.scan_channels {
        let channel = rx
            .find_input_channel(&saved.id)
            .ok_or_else(|| not_found(format!("missing scan channel {}", saved.id)))?;
        if saved.enabled {
            channel.enable();
        } else {
            channel.disable();
        }
    }
    Ok(())
}

fn verify_restoration(expected: &RadioProfile, observed: &RadioProfile) -> SweepResult<()> {
    if expected.phy_channels != observed.phy_channels
        || expected.scan_channels != observed.scan_channels
        || expected.center_freq_hz.abs_diff(observed.center_freq_hz) > LO_TOLERANCE_HZ as u64
    {
        return Err(io::Error::other(format!(
            "radio restoration mismatch: expected={expected:?} observed={observed:?}"
        ))
        .into());
    }
    Ok(())
}

fn merge_candidates(points: &[SpectrumSnapshot], plan: &SoftwareSweepPlan) -> Vec<CandidateBand> {
    let mut candidates: Vec<_> = points
        .iter()
        .flat_map(|point| point.candidates.iter().cloned())
        .collect();
    candidates.sort_by_key(|candidate| candidate.start_hz);
    let bin_hz = (plan.sample_rate_hz / plan.fft_size as i64).max(1);
    let merge_gap_hz = bin_hz.saturating_mul(plan.merge_gap_bins as i64);
    let mut merged: Vec<CandidateBand> = Vec::new();
    for candidate in candidates {
        if let Some(previous) = merged.last_mut() {
            if candidate.start_hz <= previous.stop_hz.saturating_add(merge_gap_hz) {
                previous.start_hz = previous.start_hz.min(candidate.start_hz);
                previous.stop_hz = previous.stop_hz.max(candidate.stop_hz);
                if candidate.peak_dbfs > previous.peak_dbfs {
                    previous.peak_dbfs = candidate.peak_dbfs;
                    previous.peak_hz = candidate.peak_hz;
                }
                previous.power_dbfs = previous.power_dbfs.max(candidate.power_dbfs);
                previous.bins = previous.bins.max(candidate.bins);
                previous.contains_dc |= candidate.contains_dc;
                continue;
            }
        }
        merged.push(candidate);
    }
    merged
}

fn invalid_input(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.into())
}

fn not_found(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::NotFound, message.into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plan() -> SoftwareSweepPlan {
        SoftwareSweepPlan {
            centers_hz: vec![2_440_000_000, 2_441_000_000, 2_442_000_000],
            continuous_step_hz: Some(1_000_000),
            sample_rate_hz: 2_100_000,
            rf_bandwidth_hz: 2_000_000,
            buffer_samples: 8_192,
            settle_ms: 5,
            fft_size: 2_048,
            overlap_percent: 50,
            frames_per_point: 4,
            coarse_bins: 96,
            threshold_db: 12.0,
            merge_gap_bins: 1,
            max_points: 64,
        }
    }

    #[test]
    fn bounded_plan_reports_network_and_duration_estimates() {
        let estimate = plan().validate().unwrap();
        assert_eq!(estimate.points, 3);
        assert_eq!(estimate.refills_per_point, 1);
        assert_eq!(estimate.maximum_network_bytes, 98_304);
        assert!(estimate.estimated_duration_ms < 100);
    }

    #[test]
    fn continuous_plan_rejects_a_coverage_gap() {
        let mut plan = plan();
        plan.continuous_step_hz = Some(1_700_000);
        assert!(plan.validate().unwrap_err().to_string().contains("80%"));
    }

    #[test]
    fn plan_rejects_more_than_64_mib_of_network_iq() {
        let mut plan = plan();
        plan.centers_hz = (0..256).map(|index| 70_000_000 + index * 100_000).collect();
        plan.max_points = 256;
        plan.buffer_samples = 1_048_576;
        assert!(plan.validate().unwrap_err().to_string().contains("64 MiB"));
    }
}
