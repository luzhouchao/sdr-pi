//! One executable for interactive sessions, scripted Controller operations and
//! the strictly read-only recovery probe. Each mode reuses its existing path.
#[cfg(not(unix))]
compile_error!("sdr-agent currently targets Linux/Unix only");

#[path = "cli/batch.rs"]
mod batch;
#[path = "cli/console.rs"]
mod console;
#[path = "cli/health.rs"]
mod health;

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if args == ["--help"] {
        println!(
            "sdr-agent [interactive options]\n\
             sdr-agent --mode MODE [script options]\n\
             sdr-agent --mode health --sdrd HOST:PORT [--timeout-ms 1..1000]\n\n\
             Without --mode: interactive Agent used by terminal and Web; /help lists commands.\n\
             Script modes include plan, observe, sweep, execute, cancel and run-once.\n\
             plan reads one JSON request and returns a plan; it does not execute it.\n\
             health checks verified RX1 and fails on unhealthy state; it never starts a session.\n\
             All options take one value. Recognition remains subject to its admission gates."
        );
        return Ok(());
    }
    match mode_index(&args)? {
        Some(index) if args[index + 1] == "health" => {
            args.drain(index..index + 2);
            health::run(args.into_iter())
        }
        Some(_) => batch::run(args.into_iter()),
        None => console::run(),
    }
}

fn mode_index(args: &[String]) -> Result<Option<usize>, &'static str> {
    let mut found = None;
    // Inspect option positions only: an instruction value equal to "--mode"
    // must never redirect an interactive invocation to another execution path.
    for index in (0..args.len()).step_by(2) {
        if args[index] == "--mode" {
            if index + 1 == args.len() {
                return Err("missing --mode value");
            }
            if found.replace(index).is_some() {
                return Err("duplicate --mode");
            }
        }
    }
    Ok(found)
}

fn main() {
    if let Err(error) = run() {
        eprintln!("sdr_agent_error={error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::mode_index;

    #[test]
    fn dispatch_uses_option_positions_and_rejects_ambiguous_modes() {
        let strings = |args: &[&str]| args.iter().map(|s| (*s).to_owned()).collect::<Vec<_>>();
        assert_eq!(mode_index(&strings(&["--instruction", "--mode"])), Ok(None));
        assert_eq!(
            mode_index(&strings(&["--sdrd", "127.0.0.1:1", "--mode", "health"])),
            Ok(Some(2))
        );
        assert!(mode_index(&strings(&["--mode"])).is_err());
        assert!(mode_index(&strings(&["--mode", "health", "--mode", "sweep"])).is_err());
    }
}
