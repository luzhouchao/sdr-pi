use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use std::process::Command;
use std::thread;
use std::time::Duration;

fn responses() -> Vec<Value> {
    let rx = json!({"identity_version":1,"verified":true,"front_panel_port":"RX1",
        "logical_channel":"RX0","phy_channel":"voltage0","scan_i_channel":"voltage0",
        "scan_q_channel":"voltage1","rf_port_select":"A_BALANCED","source":"iio_channel_attr"});
    vec![
        json!({"schema_version":1,"request_id":1,"status":"ok","server":"p201-sdrd",
            "protocol":"SDRD/1","mode":"controlled","mutating_commands":true}),
        json!({"schema_version":1,"request_id":2,"status":"ok","mode":"controlled",
            "iio_visible":true,"radio_control":true,"raw_iq_capture":true,"software_summary":true,
            "max_capture_bytes":67108864,"rx_input":rx,"fpga_backend":"none","fpga_identity_valid":false,
            "fpga_summary_version":0,"fpga_abi_version":0,"fpga_capability":0,"fpga_aggregate":false}),
        json!({"schema_version":1,"request_id":3,"status":"ok","healthy":true,"health_flags":0,
            "iio_phy_visible":true,"iio_rx_visible":true,"rx_input":rx,"fpga_configured":false,
            "fpga_mapped":false,"fpga_identity_valid":false,"session_faulted":false}),
        json!({"schema_version":1,"request_id":4,"status":"ok","closing":true}),
    ]
}

fn check(values: Vec<Value>, healthy: bool) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let mut reader = BufReader::new(stream.try_clone().unwrap());
        let mut commands = vec![];
        for response in values {
            let mut line = String::new();
            if reader.read_line(&mut line).unwrap() == 0 {
                break;
            }
            commands.push(line);
            writeln!(stream, "{response}").unwrap();
        }
        commands
    });
    let result = Command::new(env!("CARGO_BIN_EXE_sdr-agent-health"))
        .args(["--sdrd", &address.to_string(), "--timeout-ms", "500"])
        .output()
        .unwrap();
    assert_eq!(
        result.status.success(),
        healthy,
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let commands = server.join().unwrap();
    let expected = [
        "SDRD/1 HELLO 1\n",
        "SDRD/1 CAPABILITIES 2\n",
        "SDRD/1 HEALTH 3\n",
        "SDRD/1 QUIT 4\n",
    ];
    assert_eq!(commands, expected[..commands.len()]);
    if healthy {
        assert_eq!(commands.len(), 4);
    }
}

#[test]
fn accepts_strict_healthy_rx1_without_mutation() {
    check(responses(), true);
}

#[test]
fn unhealthy_or_missing_receive_capability_fails_process_status() {
    for (index, key, value) in [
        (2, "healthy", json!(false)),
        (2, "health_flags", json!(4)),
        (2, "session_faulted", json!(true)),
        (2, "iio_rx_visible", json!(false)),
        (1, "radio_control", json!(false)),
        (1, "raw_iq_capture", json!(false)),
        (1, "max_capture_bytes", json!(0)),
    ] {
        let mut values = responses();
        values[index][key] = value;
        check(values, false);
    }
}

#[test]
fn missing_unverified_or_mismatched_input_fails_closed() {
    for variant in 0..4 {
        let mut values = responses();
        match variant {
            0 => {
                values[1].as_object_mut().unwrap().remove("rx_input");
            }
            1 => {
                values[2]["rx_input"]["verified"] = json!(false);
            }
            2 => {
                values[2]["rx_input"]["front_panel_port"] = json!("RX2");
            }
            _ => {
                for value in &mut values[1..3] {
                    value["rx_input"]["logical_channel"] = json!("RX1");
                }
            }
        }
        check(values, false);
    }
}

#[test]
fn protocol_identity_unknown_fields_and_wrong_types_stay_strict() {
    for (index, key, value) in [
        (0, "server", json!("other")),
        (1, "request_id", json!(99)),
        (1, "schema_version", json!(2)),
        (1, "unknown_capability", json!(true)),
        (2, "healthy", json!("true")),
        (3, "closing", json!(false)),
    ] {
        let mut values = responses();
        values[index][key] = value;
        check(values, false);
    }
}

#[test]
fn command_surface_and_timeout_are_bounded() {
    for args in [
        vec!["--mode", "sweep"],
        vec!["--timeout-ms", "0"],
        vec!["--timeout-ms", "1001"],
        vec!["--sdrd"],
        vec!["--sdrd", "bad-address"],
    ] {
        assert!(!Command::new(env!("CARGO_BIN_EXE_sdr-agent-health"))
            .args(args)
            .output()
            .unwrap()
            .status
            .success());
    }
}

#[test]
fn stalled_endpoint_times_out_without_mutation() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = thread::spawn(move || {
        let (stream, _) = listener.accept().unwrap();
        let mut reader = BufReader::new(stream);
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        assert_eq!(line, "SDRD/1 HELLO 1\n");
        thread::sleep(Duration::from_millis(100));
    });
    assert!(!Command::new(env!("CARGO_BIN_EXE_sdr-agent-health"))
        .args(["--sdrd", &address.to_string(), "--timeout-ms", "20"])
        .output()
        .unwrap()
        .status
        .success());
    server.join().unwrap();
}
