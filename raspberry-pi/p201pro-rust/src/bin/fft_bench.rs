use rustfft::num_complex::Complex32;
use rustfft::FftPlanner;
use std::f32::consts::PI;
use std::hint::black_box;
use std::time::Instant;

const FFT_SIZES: [usize; 6] = [1_024, 2_048, 4_096, 8_192, 16_384, 32_768];
const POINTS_PER_CASE: usize = 16_777_216;

fn main() {
    println!(
        "n,iterations,prep_p50_us,fft_p50_us,reduce_p50_us,total_p50_us,total_p95_us,total_p99_us,one_core_msps_no_overlap,one_core_msps_50pct_overlap,one_core_msps_75pct_overlap,checksum"
    );

    for n in FFT_SIZES {
        run_case(n);
    }
}

fn run_case(n: usize) {
    let iterations = (POINTS_PER_CASE / n).max(256);
    let warmup = (iterations / 16).clamp(16, 256);
    let mut planner = FftPlanner::<f32>::new();
    let fft = planner.plan_fft_forward(n);
    let mut scratch = vec![Complex32::default(); fft.get_inplace_scratch_len()];
    let mut samples = synthetic_iq(n);
    let window = hann_window(n);
    let mut spectrum = vec![Complex32::default(); n];

    for _ in 0..warmup {
        prepare(&samples, &window, &mut spectrum);
        fft.process_with_scratch(&mut spectrum, &mut scratch);
        black_box(reduce_power(&spectrum));
        samples.rotate_left(2);
    }

    let mut prep_ns = Vec::with_capacity(iterations);
    let mut fft_ns = Vec::with_capacity(iterations);
    let mut reduce_ns = Vec::with_capacity(iterations);
    let mut total_ns = Vec::with_capacity(iterations);
    let mut checksum = 0.0_f64;

    for iteration in 0..iterations {
        let total_started = Instant::now();

        let stage_started = Instant::now();
        prepare(&samples, &window, &mut spectrum);
        prep_ns.push(stage_started.elapsed().as_nanos() as u64);

        let stage_started = Instant::now();
        fft.process_with_scratch(&mut spectrum, &mut scratch);
        fft_ns.push(stage_started.elapsed().as_nanos() as u64);

        let stage_started = Instant::now();
        let (sum, peak) = reduce_power(&spectrum);
        reduce_ns.push(stage_started.elapsed().as_nanos() as u64);

        total_ns.push(total_started.elapsed().as_nanos() as u64);
        checksum += f64::from(sum + peak) * ((iteration & 1) as f64 + 1.0);
        samples.rotate_left(2);
    }

    let total_p50_ns = percentile(&total_ns, 50);
    let no_overlap_msps = sustainable_msps(n, total_p50_ns);
    let overlap_50_msps = sustainable_msps(n / 2, total_p50_ns);
    let overlap_75_msps = sustainable_msps(n / 4, total_p50_ns);

    println!(
        "{n},{iterations},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{no_overlap_msps:.3},{overlap_50_msps:.3},{overlap_75_msps:.3},{:.6e}",
        ns_to_us(percentile(&prep_ns, 50)),
        ns_to_us(percentile(&fft_ns, 50)),
        ns_to_us(percentile(&reduce_ns, 50)),
        ns_to_us(total_p50_ns),
        ns_to_us(percentile(&total_ns, 95)),
        ns_to_us(percentile(&total_ns, 99)),
        black_box(checksum),
    );
}

fn synthetic_iq(n: usize) -> Vec<i16> {
    (0..n * 2)
        .map(|index| (((index * 17 + index / 7) & 0x0fff) as i32 - 2_048) as i16)
        .collect()
}

fn hann_window(n: usize) -> Vec<f32> {
    (0..n)
        .map(|index| 0.5 - 0.5 * (2.0 * PI * index as f32 / (n - 1) as f32).cos())
        .collect()
}

fn prepare(samples: &[i16], window: &[f32], output: &mut [Complex32]) {
    for ((iq, &weight), value) in samples
        .chunks_exact(2)
        .zip(window.iter())
        .zip(output.iter_mut())
    {
        value.re = f32::from(iq[0]) * weight;
        value.im = f32::from(iq[1]) * weight;
    }
}

fn reduce_power(spectrum: &[Complex32]) -> (f32, f32) {
    spectrum.iter().fold((0.0, 0.0), |(sum, peak), value| {
        let power = value.norm_sqr();
        (sum + power, peak.max(power))
    })
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let index = (sorted.len() * percentile).div_ceil(100).saturating_sub(1);
    sorted[index.min(sorted.len() - 1)]
}

fn ns_to_us(ns: u64) -> f64 {
    ns as f64 / 1_000.0
}

fn sustainable_msps(hop: usize, frame_time_ns: u64) -> f64 {
    hop as f64 * 1_000.0 / frame_time_ns as f64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percentile_uses_nearest_rank() {
        assert_eq!(percentile(&[4, 1, 3, 2], 50), 2);
        assert_eq!(percentile(&[4, 1, 3, 2], 95), 4);
    }

    #[test]
    fn computes_realtime_capacity() {
        assert!((sustainable_msps(1_024, 100_000) - 10.24).abs() < 1e-9);
    }
}
