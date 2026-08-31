`timescale 1ns/1ps
`default_nettype none

module p201_v10s123_nonfft_ooc_top (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         enable,
    input  wire         clear,
    input  wire         sample_valid,
    input  wire signed [15:0] sample_i,
    input  wire signed [15:0] sample_q,
    input  wire [31:0]  energy_value,
    input  wire [15:0]  energy_index,
    output wire [31:0]  status_word,
    output wire [31:0]  quality_count,
    output wire [31:0]  window_count,
    output wire [31:0]  energy_peak
);

    wire quality_done;
    wire quality_valid;
    wire quality_overflow;
    wire quality_protocol_error;
    wire signed [47:0] quality_sum_i;
    wire signed [47:0] quality_sum_q;
    wire [63:0] quality_sum_i2;
    wire [63:0] quality_sum_q2;
    wire signed [63:0] quality_sum_iq;
    wire [15:0] quality_abs_peak;
    wire [31:0] quality_clip_i_count;
    wire [31:0] quality_clip_q_count;
    wire [31:0] quality_sat_i_count;
    wire [31:0] quality_sat_q_count;
    wire [31:0] quality_valid_count;
    wire [31:0] quality_drop_count;

    wire window_sample_ready;
    wire window_out_valid;
    wire window_last_out;
    wire signed [15:0] window_out_i;
    wire signed [15:0] window_out_q;
    wire [2:0] window_frame_index;
    wire [31:0] window_frame_id;
    wire [31:0] window_raw_count;
    wire [31:0] window_drop_count;
    wire [31:0] window_overflow_count;
    wire [31:0] window_status_flags;

    wire energy_sample_ready;
    wire [31:0] energy_summary_flags;
    wire [31:0] energy_summary_frame_id;
    wire [15:0] energy_summary_sample_count;
    wire [63:0] energy_summary_total;
    wire [31:0] energy_summary_noise;
    wire [15:0] energy_summary_peak_index;
    wire [31:0] energy_summary_second_peak;
    wire [15:0] energy_summary_second_index;
    wire [31:0] energy_summary_prominence;
    wire [15:0] energy_threshold_count;

    reg [2:0] sample_phase;
    reg [7:0] energy_count;

    always @(posedge clk) begin
        if (!rst_n) begin
            sample_phase <= 3'd0;
            energy_count <= 8'd0;
        end else if (clear || !enable) begin
            sample_phase <= 3'd0;
            energy_count <= 8'd0;
        end else if (sample_valid) begin
            sample_phase <= sample_phase + 3'd1;
            if (energy_count == 8'd7) begin
                energy_count <= 8'd0;
            end else begin
                energy_count <= energy_count + 8'd1;
            end
        end
    end

    p201_sdr_quality_stats u_quality_stats (
        .clk            (clk),
        .rst_n          (rst_n),
        .enable         (enable),
        .clear          (clear),
        .frame_start    (sample_valid && (sample_phase == 3'd0)),
        .frame_end      (sample_valid && (sample_phase == 3'd7)),
        .sample_valid   (sample_valid),
        .sample_drop    (!window_sample_ready && sample_valid),
        .sample_i       (sample_i),
        .sample_q       (sample_q),
        .frame_active   (),
        .frame_done     (quality_done),
        .stats_valid    (quality_valid),
        .overflow       (quality_overflow),
        .protocol_error (quality_protocol_error),
        .sample_count   (quality_count),
        .sum_i          (quality_sum_i),
        .sum_q          (quality_sum_q),
        .sum_i2         (quality_sum_i2),
        .sum_q2         (quality_sum_q2),
        .sum_iq         (quality_sum_iq),
        .abs_peak       (quality_abs_peak),
        .clip_i_count   (quality_clip_i_count),
        .clip_q_count   (quality_clip_q_count),
        .sat_i_count    (quality_sat_i_count),
        .sat_q_count    (quality_sat_q_count),
        .valid_count    (quality_valid_count),
        .drop_count     (quality_drop_count)
    );

    p201_v10s2_frame_window u_frame_window (
        .clk              (clk),
        .rst_n            (rst_n),
        .enable           (enable),
        .clear            (clear),
        .decim_factor     (8'd2),
        .window_mode      (1'b1),
        .sample_valid     (sample_valid),
        .sample_ready     (window_sample_ready),
        .sample_i         (sample_i),
        .sample_q         (sample_q),
        .out_valid        (window_out_valid),
        .out_ready        (1'b1),
        .last_out         (window_last_out),
        .out_i            (window_out_i),
        .out_q            (window_out_q),
        .frame_index      (window_frame_index),
        .frame_id         (window_frame_id),
        .raw_sample_count (window_raw_count),
        .accepted_count   (window_count),
        .dropped_count    (window_drop_count),
        .overflow_count   (window_overflow_count),
        .status_flags     (window_status_flags)
    );

    p201_v10s3_energy_peak_reducer u_energy_peak (
        .clk                       (clk),
        .rst_n                     (rst_n),
        .enable                    (enable),
        .clear_summary             (clear),
        .sample_valid              (sample_valid),
        .sample_ready              (energy_sample_ready),
        .sample_last               (energy_count == 8'd7),
        .sample_value              (energy_value),
        .sample_index              (energy_index),
        .threshold_value           (32'd1024),
        .summary_flags             (energy_summary_flags),
        .summary_frame_id          (energy_summary_frame_id),
        .summary_sample_count      (energy_summary_sample_count),
        .summary_total_energy      (energy_summary_total),
        .summary_noise_floor       (energy_summary_noise),
        .summary_peak_value        (energy_peak),
        .summary_peak_index        (energy_summary_peak_index),
        .summary_second_peak_value (energy_summary_second_peak),
        .summary_second_peak_index (energy_summary_second_index),
        .summary_prominence        (energy_summary_prominence),
        .summary_threshold_count   (energy_threshold_count)
    );

    assign status_word = {
        16'd0,
        quality_protocol_error,
        quality_overflow,
        quality_valid,
        quality_done,
        energy_summary_flags[4],
        energy_summary_flags[3],
        energy_summary_flags[2],
        energy_summary_flags[0],
        window_status_flags[7],
        window_last_out,
        window_out_valid,
        energy_sample_ready
    };

endmodule

`default_nettype wire
