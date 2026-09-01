use rustfft::num_complex::Complex32;
use rustfft::{Fft, FftPlanner};
use serde::Serialize;
use std::cmp::Ordering;
use std::f32::consts::PI;
use std::sync::Arc;

const ADC_FULL_SCALE: f32 = 2_048.0;
const MIN_POWER: f32 = 1.0e-20;

#[derive(Clone, Debug)]
pub(crate) struct SpectrumConfig {
    pub center_freq_hz: i64,
    pub sample_rate_hz: i64,
    pub fft_size: usize,
    pub overlap_percent: usize,
    pub frames_per_snapshot: usize,
    pub coarse_bins: usize,
    pub threshold_above_noise_db: f32,
    pub merge_gap_bins: usize,
    pub dc_exclusion_bins: usize,
}

impl SpectrumConfig {
    pub(crate) fn validate(&self) -> Result<(), String> {
        if self.sample_rate_hz <= 0 {
            return Err("sample rate must be positive".to_owned());
        }
        if self.fft_size < 64 || !self.fft_size.is_power_of_two() {
            return Err("FFT size must be a power of two and at least 64".to_owned());
        }
        if self.overlap_percent > 75 {
            return Err("overlap must be between 0 and 75 percent".to_owned());
        }
        if self.frames_per_snapshot == 0 {
            return Err("frames per snapshot must be positive".to_owned());
        }
        if self.coarse_bins == 0 || self.coarse_bins > self.fft_size {
            return Err("coarse bins must be between 1 and FFT size".to_owned());
        }
        if !self.threshold_above_noise_db.is_finite() || self.threshold_above_noise_db <= 0.0 {
            return Err("threshold above noise must be a positive finite value".to_owned());
        }
        if self.dc_exclusion_bins.saturating_mul(2).saturating_add(1) >= self.fft_size {
            return Err("DC exclusion removes every FFT bin".to_owned());
        }
        Ok(())
    }

    pub(crate) fn hop_samples(&self) -> usize {
        (self.fft_size * (100 - self.overlap_percent) / 100).max(1)
    }
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct CandidateBand {
    pub start_hz: i64,
    pub stop_hz: i64,
    pub peak_hz: i64,
    pub peak_dbfs: f32,
    pub power_dbfs: f32,
    pub bins: usize,
    pub contains_dc: bool,
}

#[derive(Clone, Debug, Serialize)]
pub(crate) struct SpectrumSnapshot {
    pub schema_version: u8,
    pub sequence: u64,
    pub backend: &'static str,
    pub center_freq_hz: i64,
    pub sample_rate_hz: i64,
    pub fft_size: usize,
    pub hop_samples: usize,
    pub frames_averaged: usize,
    pub input_samples_seen: u64,
    pub noise_floor_dbfs: f32,
    pub band_power_dbfs: f32,
    pub coarse_psd_dbfs: Vec<f32>,
    pub candidates: Vec<CandidateBand>,
}

pub(crate) struct SpectrumAggregator {
    config: SpectrumConfig,
    fft: Arc<dyn Fft<f32>>,
    scratch: Vec<Complex32>,
    window: Vec<f32>,
    normalization: f32,
    ring: Vec<Complex32>,
    write_index: usize,
    filled: usize,
    samples_since_frame: usize,
    fft_input: Vec<Complex32>,
    accumulated_power: Vec<f32>,
    accumulated_frames: usize,
    sequence: u64,
    input_samples_seen: u64,
}

impl SpectrumAggregator {
    pub(crate) fn new(config: SpectrumConfig) -> Result<Self, String> {
        config.validate()?;
        let mut planner = FftPlanner::<f32>::new();
        let fft = planner.plan_fft_forward(config.fft_size);
        let scratch = vec![Complex32::default(); fft.get_inplace_scratch_len()];
        let window = hann_window(config.fft_size);
        let window_energy: f32 = window.iter().map(|weight| weight * weight).sum();
        let normalization =
            1.0 / (config.fft_size as f32 * window_energy * ADC_FULL_SCALE * ADC_FULL_SCALE);
        let fft_size = config.fft_size;

        Ok(Self {
            config,
            fft,
            scratch,
            window,
            normalization,
            ring: vec![Complex32::default(); fft_size],
            write_index: 0,
            filled: 0,
            samples_since_frame: 0,
            fft_input: vec![Complex32::default(); fft_size],
            accumulated_power: vec![0.0; fft_size],
            accumulated_frames: 0,
            sequence: 0,
            input_samples_seen: 0,
        })
    }

    /// Start a fresh tuning point while retaining the FFT plan, scratch space,
    /// Hann window and all preallocated buffers.
    pub(crate) fn reset_for_center(&mut self, center_freq_hz: i64) {
        self.config.center_freq_hz = center_freq_hz;
        self.ring.fill(Complex32::default());
        self.write_index = 0;
        self.filled = 0;
        self.samples_since_frame = 0;
        self.fft_input.fill(Complex32::default());
        self.accumulated_power.fill(0.0);
        self.accumulated_frames = 0;
        self.sequence = 0;
        self.input_samples_seen = 0;
    }

    /// Consume a continuous IQ stream and return every completed aggregate snapshot.
    /// Partial FFT frames and partial snapshot averages remain buffered for the next call.
    pub(crate) fn push_iq<I>(&mut self, samples: I) -> Vec<SpectrumSnapshot>
    where
        I: IntoIterator<Item = (i16, i16)>,
    {
        let mut snapshots = Vec::new();
        for (i, q) in samples {
            self.input_samples_seen += 1;
            self.ring[self.write_index] = Complex32::new(f32::from(i), f32::from(q));
            self.write_index = (self.write_index + 1) % self.config.fft_size;

            if self.filled < self.config.fft_size {
                self.filled += 1;
                if self.filled == self.config.fft_size {
                    if let Some(snapshot) = self.process_frame() {
                        snapshots.push(snapshot);
                    }
                }
                continue;
            }

            self.samples_since_frame += 1;
            if self.samples_since_frame >= self.config.hop_samples() {
                self.samples_since_frame = 0;
                if let Some(snapshot) = self.process_frame() {
                    snapshots.push(snapshot);
                }
            }
        }
        snapshots
    }

    fn process_frame(&mut self) -> Option<SpectrumSnapshot> {
        for index in 0..self.config.fft_size {
            let sample = self.ring[(self.write_index + index) % self.config.fft_size];
            self.fft_input[index] = sample * self.window[index];
        }
        self.fft
            .process_with_scratch(&mut self.fft_input, &mut self.scratch);

        let half = self.config.fft_size / 2;
        for (unshifted_bin, value) in self.fft_input.iter().enumerate() {
            let shifted_bin = (unshifted_bin + half) % self.config.fft_size;
            self.accumulated_power[shifted_bin] += value.norm_sqr() * self.normalization;
        }
        self.accumulated_frames += 1;

        if self.accumulated_frames < self.config.frames_per_snapshot {
            return None;
        }

        let scale = 1.0 / self.accumulated_frames as f32;
        for power in &mut self.accumulated_power {
            *power *= scale;
        }
        let snapshot = self.build_snapshot();
        self.accumulated_power.fill(0.0);
        self.accumulated_frames = 0;
        self.sequence += 1;
        Some(snapshot)
    }

    fn build_snapshot(&self) -> SpectrumSnapshot {
        let noise_power =
            median_noise_power(&self.accumulated_power, self.config.dc_exclusion_bins);
        let threshold_power =
            noise_power * 10.0_f32.powf(self.config.threshold_above_noise_db / 10.0);
        let candidates = candidate_bands(
            &self.accumulated_power,
            threshold_power,
            self.config.merge_gap_bins,
            &self.config,
        );
        let band_power: f32 = self.accumulated_power.iter().sum();

        SpectrumSnapshot {
            schema_version: 1,
            sequence: self.sequence,
            backend: "cpu_rustfft",
            center_freq_hz: self.config.center_freq_hz,
            sample_rate_hz: self.config.sample_rate_hz,
            fft_size: self.config.fft_size,
            hop_samples: self.config.hop_samples(),
            frames_averaged: self.config.frames_per_snapshot,
            input_samples_seen: self.input_samples_seen,
            noise_floor_dbfs: power_to_dbfs(noise_power),
            band_power_dbfs: power_to_dbfs(band_power),
            coarse_psd_dbfs: coarse_psd(&self.accumulated_power, self.config.coarse_bins),
            candidates,
        }
    }
}

fn hann_window(size: usize) -> Vec<f32> {
    (0..size)
        .map(|index| 0.5 - 0.5 * (2.0 * PI * index as f32 / (size - 1) as f32).cos())
        .collect()
}

fn median_noise_power(power: &[f32], dc_exclusion_bins: usize) -> f32 {
    let center = power.len() / 2;
    let dc_start = center.saturating_sub(dc_exclusion_bins);
    let dc_stop = (center + dc_exclusion_bins).min(power.len() - 1);
    let mut bins: Vec<f32> = power
        .iter()
        .enumerate()
        .filter_map(|(index, &value)| {
            if (dc_start..=dc_stop).contains(&index) || !value.is_finite() {
                None
            } else {
                Some(value.max(MIN_POWER))
            }
        })
        .collect();
    bins.sort_unstable_by(|left, right| left.partial_cmp(right).unwrap_or(Ordering::Equal));
    bins[bins.len() / 2]
}

fn coarse_psd(power: &[f32], coarse_bins: usize) -> Vec<f32> {
    (0..coarse_bins)
        .map(|coarse_bin| {
            let start = coarse_bin * power.len() / coarse_bins;
            let stop = ((coarse_bin + 1) * power.len() / coarse_bins).max(start + 1);
            let mean = power[start..stop].iter().sum::<f32>() / (stop - start) as f32;
            power_to_dbfs(mean)
        })
        .collect()
}

fn candidate_bands(
    power: &[f32],
    threshold_power: f32,
    merge_gap_bins: usize,
    config: &SpectrumConfig,
) -> Vec<CandidateBand> {
    let active: Vec<usize> = power
        .iter()
        .enumerate()
        .filter_map(|(index, &value)| (value >= threshold_power).then_some(index))
        .collect();
    if active.is_empty() {
        return Vec::new();
    }

    let mut ranges = Vec::new();
    let mut start = active[0];
    let mut previous = active[0];
    for &index in active.iter().skip(1) {
        if index - previous - 1 > merge_gap_bins {
            ranges.push((start, previous));
            start = index;
        }
        previous = index;
    }
    ranges.push((start, previous));

    ranges
        .into_iter()
        .map(|(start, stop)| {
            let (peak_bin, &peak_power) = power[start..=stop]
                .iter()
                .enumerate()
                .max_by(|(_, left), (_, right)| left.partial_cmp(right).unwrap_or(Ordering::Equal))
                .map(|(offset, value)| (start + offset, value))
                .expect("candidate range is never empty");
            let band_power = power[start..=stop].iter().sum::<f32>();
            CandidateBand {
                start_hz: bin_edge_hz(start as f64 - 0.5, config),
                stop_hz: bin_edge_hz(stop as f64 + 0.5, config),
                peak_hz: bin_edge_hz(peak_bin as f64, config),
                peak_dbfs: power_to_dbfs(peak_power),
                power_dbfs: power_to_dbfs(band_power),
                bins: stop - start + 1,
                contains_dc: (start..=stop).contains(&(power.len() / 2)),
            }
        })
        .collect()
}

fn bin_edge_hz(shifted_bin: f64, config: &SpectrumConfig) -> i64 {
    let offset_bins = shifted_bin - config.fft_size as f64 / 2.0;
    (config.center_freq_hz as f64
        + offset_bins * config.sample_rate_hz as f64 / config.fft_size as f64)
        .round() as i64
}

fn power_to_dbfs(power: f32) -> f32 {
    10.0 * power.max(MIN_POWER).log10()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> SpectrumConfig {
        SpectrumConfig {
            center_freq_hz: 100_000_000,
            sample_rate_hz: 1_024_000,
            fft_size: 1_024,
            overlap_percent: 50,
            frames_per_snapshot: 4,
            coarse_bins: 64,
            threshold_above_noise_db: 10.0,
            merge_gap_bins: 1,
            dc_exclusion_bins: 1,
        }
    }

    #[test]
    fn rejects_invalid_fft_shape() {
        let mut config = test_config();
        config.fft_size = 1_000;
        assert!(config.validate().unwrap_err().contains("power of two"));
    }

    #[test]
    fn emits_only_after_requested_frame_average() {
        let config = test_config();
        let required_samples =
            config.fft_size + (config.frames_per_snapshot - 1) * config.hop_samples();
        let samples = vec![(0_i16, 0_i16); required_samples];
        let mut aggregator = SpectrumAggregator::new(config).unwrap();
        let snapshots = aggregator.push_iq(samples);
        assert_eq!(snapshots.len(), 1);
        assert_eq!(snapshots[0].frames_averaged, 4);
        assert_eq!(snapshots[0].coarse_psd_dbfs.len(), 64);
    }

    #[test]
    fn finds_and_localizes_a_tone() {
        let config = test_config();
        let count = config.fft_size + (config.frames_per_snapshot - 1) * config.hop_samples();
        let tone_hz = 128_000.0_f32;
        let sample_rate_hz = config.sample_rate_hz as f32;
        let samples = (0..count).map(|index| {
            let phase = 2.0 * PI * tone_hz * index as f32 / sample_rate_hz;
            (
                (phase.cos() * 1_000.0) as i16,
                (phase.sin() * 1_000.0) as i16,
            )
        });
        let mut aggregator = SpectrumAggregator::new(config).unwrap();
        let snapshots = aggregator.push_iq(samples);
        let strongest = snapshots[0]
            .candidates
            .iter()
            .max_by(|left, right| left.peak_dbfs.partial_cmp(&right.peak_dbfs).unwrap())
            .unwrap();
        assert!((strongest.peak_hz - 100_128_000).abs() <= 1_000);
    }

    #[test]
    fn merges_nearby_active_bins() {
        let config = test_config();
        let mut power = vec![MIN_POWER; config.fft_size];
        power[100] = 1.0;
        power[102] = 0.5;
        let candidates = candidate_bands(&power, 0.1, 1, &config);
        assert_eq!(candidates.len(), 1);
        assert_eq!(candidates[0].bins, 3);
    }
}
