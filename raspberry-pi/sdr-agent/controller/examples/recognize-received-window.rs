//! Explicit file-replay engineering tool; no SDR client, corpus writes or production decision.
use sdr_agent_controller::{
    received_window::{prepare, ReceivedWindow},
    recognition_input::frozen_rf_v1_profile,
    recognition_result::RecognitionResult,
    supervised_recognition::run_supervised_batch,
};
use std::{
    io::Read,
    path::PathBuf,
    sync::atomic::{AtomicBool, Ordering},
};
static CANCELLED: AtomicBool = AtomicBool::new(false);
extern "C" fn cancel(_: libc::c_int) {
    CANCELLED.store(true, Ordering::Relaxed);
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        return Err(
            "usage: recognize-received-window INPUT_JSON IQ_ROOT SUPERVISOR_ROOT|--validate-only"
                .into(),
        );
    }
    let root = PathBuf::from(&args[2]);
    let mut bytes = Vec::new();
    std::fs::File::open(&args[1])?
        .take(65537)
        .read_to_end(&mut bytes)?;
    if bytes.len() > 65536 {
        return Err("received input exceeds 64 KiB".into());
    }
    let input: ReceivedWindow = serde_json::from_slice(&bytes)?;
    let loaded = frozen_rf_v1_profile()?;
    let batch = prepare(&loaded, &root, &input)?;
    if args[3] == "--validate-only" {
        println!(
            "{}",
            serde_json::json!({"validated":true,"raw_iq_sha256":input.raw_iq_sha256,"batch":batch.summary,"recognizer_available":false})
        );
        return Ok(());
    }
    unsafe {
        libc::signal(libc::SIGINT, cancel as *const () as libc::sighandler_t);
        libc::signal(libc::SIGTERM, cancel as *const () as libc::sighandler_t);
    }
    let report = run_supervised_batch(&loaded, batch, &PathBuf::from(&args[3]), || {
        CANCELLED.load(Ordering::Relaxed)
    })?;
    let result = RecognitionResult::from_experimental_batch(
        &loaded,
        report,
        input.capture_received_at_unix_ms,
    )?;
    println!(
        "{}",
        serde_json::json!({"mode":"received_window_replay","synthetic_input":false,"raw_iq_sha256":input.raw_iq_sha256,"result":result})
    );
    Ok(())
}
