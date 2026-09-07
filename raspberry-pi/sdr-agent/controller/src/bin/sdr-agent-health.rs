//! Read-only recovery probe using the Controller's strict SDRD contract.
use sdr_agent_controller::sdr::{RxInputIdentity, SdrEngine, SdrdAdapter};
use std::net::SocketAddr;
use std::time::Duration;

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let mut address = None;
    let mut timeout = None;
    while let Some(argument) = args.next() {
        match argument.as_str() {
            "--sdrd" if address.is_none() => {
                address = Some(
                    args.next()
                        .ok_or("missing --sdrd value")?
                        .parse::<SocketAddr>()?,
                );
            }
            "--timeout-ms" if timeout.is_none() => {
                let value = args
                    .next()
                    .ok_or("missing --timeout-ms value")?
                    .parse::<u64>()?;
                if !(1..=1000).contains(&value) {
                    return Err("timeout must be 1..=1000 ms".into());
                }
                timeout = Some(value);
            }
            _ => return Err("only --sdrd HOST:PORT and --timeout-ms are supported".into()),
        }
    }
    let mut adapter = SdrdAdapter::new(
        address.ok_or("--sdrd is required")?,
        Duration::from_millis(timeout.unwrap_or(1000)),
    );
    // No session, retune or capture entry point. Parsing success alone is not health.
    let snapshot = adapter.observe()?;
    println!("{}", serde_json::to_string(&snapshot)?);
    if !snapshot.online
        || !snapshot.healthy
        || snapshot.health_flags != 0
        || !snapshot.iio_visible
        || !snapshot.can_retune
        || !snapshot.can_capture_iq
        || !snapshot
            .rx_input
            .as_ref()
            .is_some_and(RxInputIdentity::is_fixed_p201_rx1)
    {
        return Err("P201 RX1 health or capability check failed".into());
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("p201_health_check_error={error}");
        std::process::exit(1);
    }
}
