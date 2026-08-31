`timescale 1ns / 1ps
`default_nettype none

module p201_v10_fft_stream_summary_top #(
    parameter FFT_WIDTH   = 16,
    parameter NFFT_LOG2   = 8,
    parameter POWER_WIDTH = 48,
    parameter ACC_WIDTH   = 64
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         enable,
    input  wire                         clear_summary,

    input  wire                         fft_valid,
    output wire                         fft_ready,
    input  wire                         fft_last,
    input  wire [NFFT_LOG2-1:0]         fft_index,
    input  wire signed [FFT_WIDTH-1:0]  fft_real,
    input  wire signed [FFT_WIDTH-1:0]  fft_imag,

    output wire [31:0]                  fft_version,
    output wire [31:0]                  fft_capability,
    output wire [31:0]                  fft_build_id,
    output wire [31:0]                  fft_abi_version,

    output wire [31:0]                  summary_flags,
    output wire [31:0]                  summary_frame_id,
    output wire [31:0]                  summary_nfft,
    output wire [31:0]                  summary_peak_bin,
    output wire [POWER_WIDTH-1:0]       summary_peak_power,
    output wire [ACC_WIDTH-1:0]         summary_total_power,
    output wire [POWER_WIDTH-1:0]       summary_noise_floor,
    output wire [POWER_WIDTH-1:0]       summary_prominence,
    output wire [31:0]                  summary_top1_bin,
    output wire [POWER_WIDTH-1:0]       summary_top1_power,
    output wire [31:0]                  summary_top2_bin,
    output wire [POWER_WIDTH-1:0]       summary_top2_power,
    output wire [31:0]                  summary_top3_bin,
    output wire [POWER_WIDTH-1:0]       summary_top3_power
);

    wire                         bin_valid;
    wire                         bin_ready;
    wire                         bin_last;
    wire [NFFT_LOG2-1:0]         bin_index;
    wire [POWER_WIDTH-1:0]       bin_power;
    wire                         bin_power_overflow;
    wire [31:0]                  reducer_flags;

    reg                          bin_power_overflow_seen;

    assign summary_flags = reducer_flags |
                           (bin_power_overflow_seen ? 32'h00000004 : 32'd0);

    p201_v10_fft_bin_power #(
        .FFT_WIDTH(FFT_WIDTH),
        .NFFT_LOG2(NFFT_LOG2),
        .POWER_WIDTH(POWER_WIDTH)
    ) u_bin_power (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .fft_valid(fft_valid),
        .fft_ready(fft_ready),
        .fft_last(fft_last),
        .fft_index(fft_index),
        .fft_real(fft_real),
        .fft_imag(fft_imag),
        .bin_valid(bin_valid),
        .bin_ready(bin_ready),
        .bin_last(bin_last),
        .bin_index(bin_index),
        .bin_power(bin_power),
        .bin_power_overflow(bin_power_overflow)
    );

    p201_v10_fft_summary_reducer #(
        .NFFT_LOG2(NFFT_LOG2),
        .POWER_WIDTH(POWER_WIDTH),
        .ACC_WIDTH(ACC_WIDTH)
    ) u_summary (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear_summary(clear_summary),
        .bin_valid(bin_valid),
        .bin_ready(bin_ready),
        .bin_last(bin_last),
        .bin_index(bin_index),
        .bin_power(bin_power),
        .fft_version(fft_version),
        .fft_capability(fft_capability),
        .fft_build_id(fft_build_id),
        .fft_abi_version(fft_abi_version),
        .summary_flags(reducer_flags),
        .summary_frame_id(summary_frame_id),
        .summary_nfft(summary_nfft),
        .summary_peak_bin(summary_peak_bin),
        .summary_peak_power(summary_peak_power),
        .summary_total_power(summary_total_power),
        .summary_noise_floor(summary_noise_floor),
        .summary_prominence(summary_prominence),
        .summary_top1_bin(summary_top1_bin),
        .summary_top1_power(summary_top1_power),
        .summary_top2_bin(summary_top2_bin),
        .summary_top2_power(summary_top2_power),
        .summary_top3_bin(summary_top3_bin),
        .summary_top3_power(summary_top3_power)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            bin_power_overflow_seen <= 1'b0;
        end else begin
            if (!enable || clear_summary) begin
                bin_power_overflow_seen <= 1'b0;
            end else if (bin_power_overflow) begin
                bin_power_overflow_seen <= 1'b1;
            end
        end
    end

endmodule

`default_nettype wire
