use industrial_io as iio;
use std::env;
use std::error::Error;
use std::fmt;
use std::io;
use std::time::{Duration, Instant};

type AppResult<T> = Result<T, Box<dyn Error>>;

const PHY_DEVICE: &str = "ad9361-phy";
const RX_DEVICE: &str = "cf-ad9361-lpc";
const RX_I_CHANNEL: &str = "voltage0";
const RX_Q_CHANNEL: &str = "voltage1";
const RX_LO_CHANNEL: &str = "altvoltage0";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Command {
    Probe,
    Capture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Analysis {
    Full,
    None,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Config {
    command: Command,
    uri: String,
    center_freq_hz: i64,
    sample_rate_hz: i64,
    rf_bandwidth_hz: i64,
    buffer_samples: usize,
    seconds: u64,
    analysis: Analysis,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            command: Command::Probe,
            uri: "ip:192.168.1.10".to_owned(),
            center_freq_hz: 2_452_000_000,
            sample_rate_hz: 2_100_000,
            rf_bandwidth_hz: 2_000_000,
            buffer_samples: 65_536,
            seconds: 3,
            analysis: Analysis::Full,
        }
    }
}

impl Config {
    fn parse<I, S>(args: I) -> AppResult<Self>
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let mut args = args.into_iter().map(Into::into);
        let mut cfg = Self::default();
        let command = args.next().ok_or_else(|| invalid_input(usage()))?;
        cfg.command = match command.as_str() {
            "probe" => Command::Probe,
            "capture" => Command::Capture,
            "-h" | "--help" | "help" => return Err(invalid_input(usage()).into()),
            other => {
                return Err(
                    invalid_input(format!("unknown command {other:?}\n\n{}", usage())).into(),
                )
            }
        };

        while let Some(flag) = args.next() {
            let value = args
                .next()
                .ok_or_else(|| invalid_input(format!("missing value for {flag}")))?;
            match flag.as_str() {
                "--uri" => cfg.uri = value,
                "--center-freq" => cfg.center_freq_hz = parse_value(&flag, &value)?,
                "--sample-rate" => cfg.sample_rate_hz = parse_value(&flag, &value)?,
                "--rf-bandwidth" => cfg.rf_bandwidth_hz = parse_value(&flag, &value)?,
                "--buffer-samples" => cfg.buffer_samples = parse_value(&flag, &value)?,
                "--seconds" => cfg.seconds = parse_value(&flag, &value)?,
                "--analysis" => {
                    cfg.analysis = match value.as_str() {
                        "full" => Analysis::Full,
                        "none" => Analysis::None,
                        _ => return Err(invalid_input("--analysis must be full or none").into()),
                    }
                }
                other => return Err(invalid_input(format!("unknown option {other:?}")).into()),
            }
        }

        cfg.validate()?;
        Ok(cfg)
    }

    fn validate(&self) -> AppResult<()> {
        if !self.uri.starts_with("ip:") {
            return Err(invalid_input("--uri must use the ip: libiio backend").into());
        }
        if !(70_000_000..=6_000_000_000).contains(&self.center_freq_hz) {
            return Err(invalid_input("--center-freq must be between 70 MHz and 6 GHz").into());
        }
        if !(2_083_333..=30_720_000).contains(&self.sample_rate_hz) {
            return Err(
                invalid_input("--sample-rate must be between 2.083333 and 30.72 MS/s").into(),
            );
        }
        if !(200_000..=56_000_000).contains(&self.rf_bandwidth_hz) {
            return Err(invalid_input("--rf-bandwidth must be between 0.2 and 56 MHz").into());
        }
        if self.sample_rate_hz < self.rf_bandwidth_hz {
            return Err(invalid_input("--sample-rate must be >= --rf-bandwidth").into());
        }
        if !(1_024..=1_048_576).contains(&self.buffer_samples) {
            return Err(invalid_input("--buffer-samples must be between 1024 and 1048576").into());
        }
        if !(1..=60).contains(&self.seconds) {
            return Err(invalid_input("--seconds must be between 1 and 60").into());
        }
        Ok(())
    }
}

fn parse_value<T>(flag: &str, value: &str) -> AppResult<T>
where
    T: std::str::FromStr,
    T::Err: fmt::Display,
{
    value
        .parse::<T>()
        .map_err(|err| invalid_input(format!("invalid value for {flag}: {value:?}: {err}")).into())
}

fn invalid_input(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.into())
}

fn not_found(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::NotFound, message.into())
}

fn usage() -> String {
    format!(
        "Usage:\n  p201pro-test probe [options]\n  p201pro-test capture [options]\n\nOptions:\n  --uri URI                 default ip:192.168.1.10\n  --center-freq HZ          default 2452000000\n  --sample-rate HZ          default 2100000\n  --rf-bandwidth HZ         default 2000000\n  --buffer-samples COUNT    default 65536\n  --seconds N               default 3 (capture only)\n  --analysis full|none      default full; none benchmarks refill only"
    )
}

fn main() {
    if let Err(err) = run() {
        eprintln!("error: {err}");
        std::process::exit(1);
    }
}

fn run() -> AppResult<()> {
    let cfg = Config::parse(env::args().skip(1))?;
    println!("client_libiio={:?}", iio::library_version());
    println!("uri={}", cfg.uri);

    let ctx = iio::Context::from_uri(&cfg.uri)?;
    ctx.set_timeout(Duration::from_secs(5))?;
    print_context(&ctx);
    validate_device_layout(&ctx)?;

    match cfg.command {
        Command::Probe => probe(&ctx),
        Command::Capture => capture(&ctx, &cfg),
    }
}

fn print_context(ctx: &iio::Context) {
    println!("context_name={}", ctx.name());
    println!("context_description={}", ctx.description());
    println!("context_version={:?}", ctx.version());
    for (name, value) in ctx.attributes() {
        println!("context_attr.{name}={value}");
    }
}

fn validate_device_layout(ctx: &iio::Context) -> AppResult<()> {
    ctx.find_device(PHY_DEVICE)
        .ok_or_else(|| not_found(format!("missing IIO device {PHY_DEVICE}")))?;
    let rx = ctx
        .find_device(RX_DEVICE)
        .ok_or_else(|| not_found(format!("missing IIO device {RX_DEVICE}")))?;
    for channel in [RX_I_CHANNEL, RX_Q_CHANNEL] {
        let channel = rx
            .find_input_channel(channel)
            .ok_or_else(|| not_found(format!("missing RX channel {channel}")))?;
        if !channel.is_scan_element() {
            return Err(not_found(format!(
                "RX channel {:?} is not a scan element",
                channel.id()
            ))
            .into());
        }
        let format = channel.data_format();
        if !format.is_signed()
            || format.length() != 16
            || format.bits() != 12
            || format.shift() != 0
        {
            return Err(invalid_input(format!(
                "unsupported RX format for {:?}: length={} bits={} shift={} signed={} big_endian={}",
                channel.id(),
                format.length(),
                format.bits(),
                format.shift(),
                format.is_signed(),
                format.is_big_endian()
            ))
            .into());
        }
    }
    Ok(())
}

fn probe(ctx: &iio::Context) -> AppResult<()> {
    println!("mode=probe");
    for device in ctx.devices() {
        println!(
            "device id={} name={} channels={} buffer_capable={}",
            device.id().unwrap_or_default(),
            device.name().unwrap_or_default(),
            device.num_channels(),
            device.is_buffer_capable()
        );
        if device.name().as_deref() == Some(RX_DEVICE) {
            for channel in device.channels() {
                let format = channel.data_format();
                println!(
                    "  channel id={} direction={:?} scan={} index={:?} format={}bit_container/{}bit_data shift={} signed={} big_endian={}",
                    channel.id().unwrap_or_default(),
                    channel.direction(),
                    channel.is_scan_element(),
                    channel.index().ok(),
                    format.length(),
                    format.bits(),
                    format.shift(),
                    format.is_signed(),
                    format.is_big_endian()
                );
            }
        }
    }
    println!("probe_result=ok");
    Ok(())
}

fn capture(ctx: &iio::Context, cfg: &Config) -> AppResult<()> {
    println!("mode=capture");
    let actual_sample_rate_hz = configure_phy(ctx, cfg)?;

    let rx = ctx
        .find_device(RX_DEVICE)
        .ok_or_else(|| not_found(format!("missing IIO device {RX_DEVICE}")))?;
    for channel in rx.channels() {
        if channel.is_input() && channel.is_scan_element() {
            channel.disable();
        }
    }
    let i_channel = rx
        .find_input_channel(RX_I_CHANNEL)
        .ok_or_else(|| not_found(format!("missing RX channel {RX_I_CHANNEL}")))?;
    let q_channel = rx
        .find_input_channel(RX_Q_CHANNEL)
        .ok_or_else(|| not_found(format!("missing RX channel {RX_Q_CHANNEL}")))?;
    i_channel.enable();
    q_channel.enable();

    let sample_size = rx.sample_size()?;
    if sample_size != 4 {
        return Err(invalid_input(format!("expected 4-byte IQ samples, got {sample_size}")).into());
    }
    println!("rx_sample_size_bytes={sample_size}");
    println!("buffer_samples={}", cfg.buffer_samples);
    println!("requested_seconds={}", cfg.seconds);
    println!("analysis={:?}", cfg.analysis);

    let mut buffer = rx.create_buffer(cfg.buffer_samples, false)?;
    let started = Instant::now();
    let deadline = Duration::from_secs(cfg.seconds);
    let mut stats = CaptureStats::default();

    while started.elapsed() < deadline {
        let refill_started = Instant::now();
        let bytes = buffer.refill()?;
        let refill_elapsed = refill_started.elapsed();
        stats.observe_refill(bytes, refill_elapsed);
        match cfg.analysis {
            Analysis::Full => stats.observe_iq(
                buffer.channel_iter::<i16>(&i_channel),
                buffer.channel_iter::<i16>(&q_channel),
            ),
            Analysis::None => stats.observe_sample_count(bytes / sample_size),
        }
    }

    let elapsed = started.elapsed();
    stats.print(
        elapsed,
        cfg.sample_rate_hz,
        actual_sample_rate_hz,
        cfg.analysis,
    );
    if stats.samples == 0 {
        return Err(io::Error::new(
            io::ErrorKind::UnexpectedEof,
            "capture returned zero samples",
        )
        .into());
    }
    println!("capture_result=ok");
    Ok(())
}

fn configure_phy(ctx: &iio::Context, cfg: &Config) -> AppResult<i64> {
    let phy = ctx
        .find_device(PHY_DEVICE)
        .ok_or_else(|| not_found(format!("missing IIO device {PHY_DEVICE}")))?;
    let lo = phy
        .find_output_channel(RX_LO_CHANNEL)
        .ok_or_else(|| not_found(format!("missing RX LO channel {RX_LO_CHANNEL}")))?;
    lo.attr_write_int("frequency", cfg.center_freq_hz)?;

    let mut actual_sample_rate_hz = 0;
    for channel_name in [RX_I_CHANNEL, RX_Q_CHANNEL] {
        let channel = phy
            .find_input_channel(channel_name)
            .ok_or_else(|| not_found(format!("missing PHY input channel {channel_name}")))?;
        channel.attr_write_int("sampling_frequency", cfg.sample_rate_hz)?;
        channel.attr_write_int("rf_bandwidth", cfg.rf_bandwidth_hz)?;
        let channel_sample_rate_hz = channel.attr_read_int("sampling_frequency")?;
        let channel_rf_bandwidth_hz = channel.attr_read_int("rf_bandwidth")?;
        println!("readback.{channel_name}.sample_rate_hz={channel_sample_rate_hz}");
        println!("readback.{channel_name}.rf_bandwidth_hz={channel_rf_bandwidth_hz}");
        if actual_sample_rate_hz == 0 {
            actual_sample_rate_hz = channel_sample_rate_hz;
        } else if actual_sample_rate_hz != channel_sample_rate_hz {
            return Err(invalid_input("PHY I/Q channels reported different sample rates").into());
        }
    }

    println!("center_freq_hz={}", cfg.center_freq_hz);
    println!("sample_rate_hz={}", cfg.sample_rate_hz);
    println!("rf_bandwidth_hz={}", cfg.rf_bandwidth_hz);
    Ok(actual_sample_rate_hz)
}

#[derive(Debug)]
struct CaptureStats {
    buffers: u64,
    bytes: u64,
    samples: u64,
    sum_i: i128,
    sum_q: i128,
    sum_power: f64,
    min_i: i16,
    max_i: i16,
    min_q: i16,
    max_q: i16,
    clipped: u64,
    max_refill: Duration,
}

impl Default for CaptureStats {
    fn default() -> Self {
        Self {
            buffers: 0,
            bytes: 0,
            samples: 0,
            sum_i: 0,
            sum_q: 0,
            sum_power: 0.0,
            min_i: i16::MAX,
            max_i: i16::MIN,
            min_q: i16::MAX,
            max_q: i16::MIN,
            clipped: 0,
            max_refill: Duration::ZERO,
        }
    }
}

impl CaptureStats {
    fn observe_refill(&mut self, bytes: usize, elapsed: Duration) {
        self.buffers += 1;
        self.bytes += bytes as u64;
        self.max_refill = self.max_refill.max(elapsed);
    }

    fn observe_iq<'a, I, Q>(&mut self, i_values: I, q_values: Q)
    where
        I: Iterator<Item = &'a i16>,
        Q: Iterator<Item = &'a i16>,
    {
        for (&i, &q) in i_values.zip(q_values) {
            self.samples += 1;
            self.sum_i += i as i128;
            self.sum_q += q as i128;
            self.sum_power += f64::from(i) * f64::from(i) + f64::from(q) * f64::from(q);
            self.min_i = self.min_i.min(i);
            self.max_i = self.max_i.max(i);
            self.min_q = self.min_q.min(q);
            self.max_q = self.max_q.max(q);
            if i == -2_048 || i == 2_047 || q == -2_048 || q == 2_047 {
                self.clipped += 1;
            }
        }
    }

    fn observe_sample_count(&mut self, samples: usize) {
        self.samples += samples as u64;
    }

    fn print(
        &self,
        elapsed: Duration,
        requested_sample_rate_hz: i64,
        actual_sample_rate_hz: i64,
        analysis: Analysis,
    ) {
        let seconds = elapsed.as_secs_f64();
        let samples = self.samples.max(1) as f64;
        let sample_rate = self.samples as f64 / seconds;
        let mib_per_second = self.bytes as f64 / seconds / (1024.0 * 1024.0);
        let rms = (self.sum_power / samples).sqrt();
        println!("elapsed_seconds={seconds:.6}");
        println!("buffers={}", self.buffers);
        println!("bytes={}", self.bytes);
        println!("complex_samples={}", self.samples);
        println!("measured_sample_rate_sps={sample_rate:.3}");
        println!("requested_sample_rate_sps={requested_sample_rate_hz}");
        println!("actual_sample_rate_sps={actual_sample_rate_hz}");
        println!("throughput_mib_s={mib_per_second:.3}");
        println!(
            "max_refill_ms={:.3}",
            self.max_refill.as_secs_f64() * 1_000.0
        );
        if analysis == Analysis::Full {
            println!("mean_i={:.3}", self.sum_i as f64 / samples);
            println!("mean_q={:.3}", self.sum_q as f64 / samples);
            println!("rms_iq_codes={rms:.3}");
            println!("rms_iq_normalized={:.6}", rms / 2_048.0);
            println!("min_i={} max_i={}", self.min_i, self.max_i);
            println!("min_q={} max_q={}", self.min_q, self.max_q);
            println!("clipped_samples={}", self.clipped);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_capture_overrides() {
        let cfg = Config::parse([
            "capture",
            "--seconds",
            "5",
            "--sample-rate",
            "5000000",
            "--rf-bandwidth",
            "4000000",
            "--buffer-samples",
            "16384",
            "--analysis",
            "none",
        ])
        .unwrap();
        assert_eq!(cfg.command, Command::Capture);
        assert_eq!(cfg.seconds, 5);
        assert_eq!(cfg.sample_rate_hz, 5_000_000);
        assert_eq!(cfg.rf_bandwidth_hz, 4_000_000);
        assert_eq!(cfg.buffer_samples, 16_384);
        assert_eq!(cfg.analysis, Analysis::None);
    }

    #[test]
    fn rejects_bandwidth_above_sample_rate() {
        let err = Config::parse([
            "capture",
            "--sample-rate",
            "2100000",
            "--rf-bandwidth",
            "3000000",
        ])
        .unwrap_err();
        assert!(err.to_string().contains("sample-rate must be >="));
    }

    #[test]
    fn computes_iq_statistics() {
        let i = [1_i16, -2, 3, -2_048];
        let q = [4_i16, 5, -6, 0];
        let mut stats = CaptureStats::default();
        stats.observe_iq(i.iter(), q.iter());
        assert_eq!(stats.samples, 4);
        assert_eq!(stats.sum_i, -2_046);
        assert_eq!(stats.sum_q, 3);
        assert_eq!(stats.min_i, -2_048);
        assert_eq!(stats.max_i, 3);
        assert_eq!(stats.clipped, 1);
    }
}
