`timescale 1ns/1ps
`default_nettype none

// Module: p201_v10s5_fft_family_selftest_core
// Purpose: deterministic isolated FFT-family sidecar self-test core.
// Notes:
// - Intended for a future AXI-Lite wrapper with clk/rst_n/start control.
// - No AD9361 live nets are connected; all stimuli are locally generated.
module p201_v10s5_fft_family_selftest_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    output reg         busy,
    output reg         done,
    output reg         error,
    output reg  [31:0] done_mask,
    output reg  [31:0] error_mask,
    output reg  [31:0] result0,
    output reg  [31:0] result1,
    output reg  [31:0] result2,
    output reg  [31:0] result3
);

    localparam [31:0] BUILD_WORD      = 32'h56313035;  // "V105"
    localparam [31:0] CAP_WORD        = 32'h0000000f;  // packer, FFT, band, corr
    localparam [31:0] ABI_WORD        = 32'h000a5000;

    localparam [31:0] DONE_PACK       = 32'h00000001;
    localparam [31:0] DONE_FFT        = 32'h00000002;
    localparam [31:0] DONE_BAND       = 32'h00000004;
    localparam [31:0] DONE_CORR       = 32'h00000008;
    localparam [31:0] DONE_ALL        = 32'h0000000f;

    localparam [31:0] EXPECT_FFT_TOTAL  = 32'd6385;
    localparam [31:0] EXPECT_BAND_TOTAL = 32'd56622;
    localparam [31:0] EXPECT_BAND0      = 32'd12062;
    localparam [31:0] EXPECT_BAND1      = 32'd12126;
    localparam [31:0] EXPECT_BAND2      = 32'd13186;
    localparam [31:0] EXPECT_BAND3      = 32'd19248;
    localparam signed [63:0] EXPECT_LAG0_RE = 64'sd155328;
    localparam signed [63:0] EXPECT_LAG0_IM = 64'sd552128;
    localparam signed [63:0] EXPECT_LAG1_RE = 64'sd152754;
    localparam signed [63:0] EXPECT_LAG1_IM = 64'sd539322;
    localparam signed [63:0] EXPECT_LAG2_RE = 64'sd150164;
    localparam signed [63:0] EXPECT_LAG2_IM = 64'sd526504;
    localparam signed [63:0] EXPECT_LAG3_RE = 64'sd147559;
    localparam signed [63:0] EXPECT_LAG3_IM = 64'sd513681;

    localparam [31:0] EXPECT_RESULT0 = DONE_ALL;
    localparam [31:0] EXPECT_RESULT1 = 32'h5608ccf1;
    localparam [31:0] EXPECT_RESULT2 = ABI_WORD;
    localparam [31:0] EXPECT_RESULT3 = 32'h00000000;

    localparam [2:0] STATE_IDLE  = 3'd0;
    localparam [2:0] STATE_CLEAR = 3'd1;
    localparam [2:0] STATE_RUN   = 3'd2;
    localparam [2:0] STATE_WAIT  = 3'd3;
    localparam [2:0] STATE_LATCH = 3'd4;
    localparam [2:0] STATE_DONE  = 3'd5;

    reg [2:0] state_reg;
    reg [8:0] gen_index;
    reg [7:0] wait_count;
    reg       start_d;
    reg       clear_modules;

    reg                       pack_iq_valid;
    reg signed [15:0]         pack_iq_i;
    reg signed [15:0]         pack_iq_q;
    wire [31:0]               pack_tdata;
    wire                      pack_tvalid;
    wire                      pack_tlast;
    wire [31:0]               pack_frame_id;
    wire [31:0]               pack_accepted_count;
    wire [31:0]               pack_dropped_count;
    wire [31:0]               pack_overrun_count;
    wire [31:0]               pack_status_flags;
    reg [31:0]                pack_observed_count;
    reg [31:0]                pack_last_count;

    reg                       fft_valid;
    wire                      fft_ready;
    reg                       fft_last;
    reg [7:0]                 fft_index;
    reg signed [15:0]         fft_real;
    reg signed [15:0]         fft_imag;
    wire                      bin_valid;
    wire                      bin_ready;
    wire                      bin_last;
    wire [7:0]                bin_index;
    wire [47:0]               bin_power;
    wire                      bin_power_overflow;
    wire [31:0]               fft_version;
    wire [31:0]               fft_capability;
    wire [31:0]               fft_build_id;
    wire [31:0]               fft_abi_version;
    wire [31:0]               fft_summary_flags;
    wire [31:0]               fft_summary_frame_id;
    wire [31:0]               fft_summary_nfft;
    wire [31:0]               fft_summary_peak_bin;
    wire [47:0]               fft_summary_peak_power;
    wire [63:0]               fft_summary_total_power;
    wire [47:0]               fft_summary_noise_floor;
    wire [47:0]               fft_summary_prominence;
    wire [31:0]               fft_summary_top1_bin;
    wire [47:0]               fft_summary_top1_power;
    wire [31:0]               fft_summary_top2_bin;
    wire [47:0]               fft_summary_top2_power;
    wire [31:0]               fft_summary_top3_bin;
    wire [47:0]               fft_summary_top3_power;

    reg                       band_valid;
    wire                      band_ready;
    reg                       band_last;
    reg [7:0]                 band_index;
    reg [47:0]                band_power;
    wire [31:0]               band_summary_flags;
    wire                      band_summary_valid;
    wire                      band_summary_overrun;
    wire                      band_summary_length_error;
    wire                      band_summary_missing_last;
    wire [31:0]               band_summary_frame_id;
    wire [31:0]               band_summary_nfft;
    wire [63:0]               band_summary_total_power;
    wire [7:0]                band_summary_peak_bin;
    wire [47:0]               band_summary_peak_power;
    wire [7:0]                band_summary_top1_bin;
    wire [47:0]               band_summary_top1_power;
    wire [7:0]                band_summary_top2_bin;
    wire [47:0]               band_summary_top2_power;
    wire [7:0]                band_summary_top3_bin;
    wire [47:0]               band_summary_top3_power;
    wire [47:0]               band_summary_noise_floor;
    wire [47:0]               band_summary_prominence;
    wire [63:0]               band_summary_band0_power;
    wire [63:0]               band_summary_band1_power;
    wire [63:0]               band_summary_band2_power;
    wire [63:0]               band_summary_band3_power;

    reg                       corr_valid;
    reg signed [15:0]         corr_rx0_i;
    reg signed [15:0]         corr_rx0_q;
    reg signed [15:0]         corr_rx1_i;
    reg signed [15:0]         corr_rx1_q;
    wire                      corr_summary_valid;
    wire                      corr_summary_strobe;
    wire [31:0]               corr_summary_frame_id;
    wire [15:0]               corr_summary_samples;
    wire [15:0]               corr_lag0_samples;
    wire [15:0]               corr_lag1_samples;
    wire [15:0]               corr_lag2_samples;
    wire [15:0]               corr_lag3_samples;
    wire signed [63:0]        corr_lag0_re;
    wire signed [63:0]        corr_lag0_im;
    wire signed [63:0]        corr_lag1_re;
    wire signed [63:0]        corr_lag1_im;
    wire signed [63:0]        corr_lag2_re;
    wire signed [63:0]        corr_lag2_im;
    wire signed [63:0]        corr_lag3_re;
    wire signed [63:0]        corr_lag3_im;
    wire [3:0]                corr_lag_valid_mask;

    wire start_pulse;
    wire enable_modules;
    wire run_accept;
    wire pack_done;
    wire fft_done;
    wire band_done;
    wire corr_done;
    wire [31:0] observed_done_mask;
    wire [31:0] check_error_mask;
    wire [31:0] result_hash;

    assign start_pulse = start && !start_d;
    assign enable_modules = (state_reg != STATE_IDLE);
    assign run_accept = (state_reg == STATE_RUN) &&
                        fft_ready &&
                        band_ready &&
                        (gen_index < 9'd256);

    assign pack_done = (pack_frame_id == 32'd1);
    assign fft_done  = (fft_summary_frame_id == 32'd1);
    assign band_done = (band_summary_frame_id == 32'd1);
    assign corr_done = (corr_summary_frame_id == 32'd1);
    assign observed_done_mask =
        (pack_done ? DONE_PACK : 32'd0) |
        (fft_done ? DONE_FFT : 32'd0) |
        (band_done ? DONE_BAND : 32'd0) |
        (corr_done ? DONE_CORR : 32'd0);

    assign check_error_mask = {
        17'd0,
        (observed_done_mask != DONE_ALL),
        (corr_lag3_re != EXPECT_LAG3_RE) ||
            (corr_lag3_im != EXPECT_LAG3_IM),
        (corr_lag2_re != EXPECT_LAG2_RE) ||
            (corr_lag2_im != EXPECT_LAG2_IM),
        (corr_lag1_re != EXPECT_LAG1_RE) ||
            (corr_lag1_im != EXPECT_LAG1_IM),
        (corr_lag0_re != EXPECT_LAG0_RE) ||
            (corr_lag0_im != EXPECT_LAG0_IM),
        !corr_summary_valid ||
            (corr_summary_samples != 16'd64) ||
            (corr_lag0_samples != 16'd64) ||
            (corr_lag1_samples != 16'd63) ||
            (corr_lag2_samples != 16'd62) ||
            (corr_lag3_samples != 16'd61) ||
            (corr_lag_valid_mask != 4'hf),
        (band_summary_band0_power[31:0] != EXPECT_BAND0) ||
            (band_summary_band1_power[31:0] != EXPECT_BAND1) ||
            (band_summary_band2_power[31:0] != EXPECT_BAND2) ||
            (band_summary_band3_power[31:0] != EXPECT_BAND3),
        (band_summary_peak_bin != 8'd100) ||
            (band_summary_peak_power != 48'd12000) ||
            (band_summary_top1_bin != 8'd100) ||
            (band_summary_top2_bin != 8'd200) ||
            (band_summary_top3_bin != 8'd42),
        (band_summary_nfft != 32'd256) ||
            (band_summary_total_power[31:0] != EXPECT_BAND_TOTAL) ||
            (band_summary_total_power[63:32] != 32'd0) ||
            band_summary_overrun ||
            band_summary_length_error ||
            band_summary_missing_last,
        (fft_summary_noise_floor != 48'd1) ||
            (fft_summary_prominence != 48'd4095) ||
            (fft_summary_top1_bin != 32'd5) ||
            (fft_summary_top2_bin != 32'd17) ||
            (fft_summary_top3_bin != 32'd33),
        (fft_summary_total_power[31:0] != EXPECT_FFT_TOTAL) ||
            (fft_summary_total_power[63:32] != 32'd0),
        (fft_summary_nfft != 32'd256) ||
            (fft_summary_peak_bin != 32'd5) ||
            (fft_summary_peak_power != 48'd4096),
        bin_power_overflow,
        (pack_observed_count != 32'd256) ||
            (pack_last_count != 32'd1),
        (pack_frame_id != 32'd1) ||
            (pack_accepted_count != 32'd256) ||
            (pack_dropped_count != 32'd0) ||
            (pack_overrun_count != 32'd0)
    };

    assign result_hash =
        BUILD_WORD ^
        CAP_WORD ^
        pack_accepted_count ^
        pack_dropped_count ^
        pack_observed_count ^
        fft_summary_nfft ^
        fft_summary_peak_bin ^
        fft_summary_peak_power[31:0] ^
        fft_summary_total_power[31:0] ^
        {8'd0, fft_summary_top3_bin[7:0],
         fft_summary_top2_bin[7:0], fft_summary_top1_bin[7:0]} ^
        band_summary_nfft ^
        {8'd0, band_summary_top3_bin,
         band_summary_top2_bin, band_summary_peak_bin} ^
        band_summary_total_power[31:0] ^
        band_summary_band0_power[31:0] ^
        band_summary_band1_power[31:0] ^
        band_summary_band2_power[31:0] ^
        band_summary_band3_power[31:0] ^
        {corr_lag3_samples, corr_summary_samples} ^
        corr_lag0_re[31:0] ^
        corr_lag0_im[31:0] ^
        corr_lag1_re[31:0] ^
        corr_lag1_im[31:0] ^
        corr_lag2_re[31:0] ^
        corr_lag2_im[31:0] ^
        corr_lag3_re[31:0] ^
        corr_lag3_im[31:0];

    p201_fft_frame_packer u_frame_packer (
        .clk            (clk),
        .rst_n          (rst_n),
        .enable         (enable_modules),
        .clear          (clear_modules),
        .iq_valid       (pack_iq_valid),
        .iq_i           (pack_iq_i),
        .iq_q           (pack_iq_q),
        .m_axis_tdata   (pack_tdata),
        .m_axis_tvalid  (pack_tvalid),
        .m_axis_tready  (1'b1),
        .m_axis_tlast   (pack_tlast),
        .frame_id       (pack_frame_id),
        .accepted_count (pack_accepted_count),
        .dropped_count  (pack_dropped_count),
        .overrun_count  (pack_overrun_count),
        .status_flags   (pack_status_flags)
    );

    p201_v10_fft_bin_power #(
        .FFT_WIDTH   (16),
        .NFFT_LOG2   (8),
        .POWER_WIDTH (48)
    ) u_fft_bin_power (
        .clk                (clk),
        .rst_n              (rst_n),
        .enable             (enable_modules),
        .fft_valid          (fft_valid),
        .fft_ready          (fft_ready),
        .fft_last           (fft_last),
        .fft_index          (fft_index),
        .fft_real           (fft_real),
        .fft_imag           (fft_imag),
        .bin_valid          (bin_valid),
        .bin_ready          (bin_ready),
        .bin_last           (bin_last),
        .bin_index          (bin_index),
        .bin_power          (bin_power),
        .bin_power_overflow (bin_power_overflow)
    );

    p201_v10_fft_summary_reducer #(
        .NFFT_LOG2   (8),
        .POWER_WIDTH (48),
        .ACC_WIDTH   (64)
    ) u_fft_summary (
        .clk                 (clk),
        .rst_n               (rst_n),
        .enable              (enable_modules),
        .clear_summary       (clear_modules),
        .bin_valid           (bin_valid),
        .bin_ready           (bin_ready),
        .bin_last            (bin_last),
        .bin_index           (bin_index),
        .bin_power           (bin_power),
        .fft_version         (fft_version),
        .fft_capability      (fft_capability),
        .fft_build_id        (fft_build_id),
        .fft_abi_version     (fft_abi_version),
        .summary_flags       (fft_summary_flags),
        .summary_frame_id    (fft_summary_frame_id),
        .summary_nfft        (fft_summary_nfft),
        .summary_peak_bin    (fft_summary_peak_bin),
        .summary_peak_power  (fft_summary_peak_power),
        .summary_total_power (fft_summary_total_power),
        .summary_noise_floor (fft_summary_noise_floor),
        .summary_prominence  (fft_summary_prominence),
        .summary_top1_bin    (fft_summary_top1_bin),
        .summary_top1_power  (fft_summary_top1_power),
        .summary_top2_bin    (fft_summary_top2_bin),
        .summary_top2_power  (fft_summary_top2_power),
        .summary_top3_bin    (fft_summary_top3_bin),
        .summary_top3_power  (fft_summary_top3_power)
    );

    p201_bandpower_reducer u_bandpower (
        .clk                    (clk),
        .rst_n                  (rst_n),
        .enable                 (enable_modules),
        .clear_summary          (clear_modules),
        .bin_valid              (band_valid),
        .bin_ready              (band_ready),
        .bin_last               (band_last),
        .bin_index              (band_index),
        .bin_power              (band_power),
        .summary_flags          (band_summary_flags),
        .summary_valid          (band_summary_valid),
        .summary_overrun        (band_summary_overrun),
        .summary_length_error   (band_summary_length_error),
        .summary_missing_last   (band_summary_missing_last),
        .summary_frame_id       (band_summary_frame_id),
        .summary_nfft           (band_summary_nfft),
        .summary_total_power    (band_summary_total_power),
        .summary_peak_bin       (band_summary_peak_bin),
        .summary_peak_power     (band_summary_peak_power),
        .summary_top1_bin       (band_summary_top1_bin),
        .summary_top1_power     (band_summary_top1_power),
        .summary_top2_bin       (band_summary_top2_bin),
        .summary_top2_power     (band_summary_top2_power),
        .summary_top3_bin       (band_summary_top3_bin),
        .summary_top3_power     (band_summary_top3_power),
        .summary_noise_floor    (band_summary_noise_floor),
        .summary_prominence     (band_summary_prominence),
        .summary_band0_power    (band_summary_band0_power),
        .summary_band1_power    (band_summary_band1_power),
        .summary_band2_power    (band_summary_band2_power),
        .summary_band3_power    (band_summary_band3_power)
    );

    p201_v10_multilag_corr_module #(
        .DATA_WIDTH (16),
        .ACC_WIDTH  (64),
        .FRAME_LEN  (64)
    ) u_multilag_corr (
        .clk               (clk),
        .rst_n             (rst_n),
        .enable            (enable_modules),
        .clear             (clear_modules),
        .sample_valid      (corr_valid),
        .rx0_i             (corr_rx0_i),
        .rx0_q             (corr_rx0_q),
        .rx1_i             (corr_rx1_i),
        .rx1_q             (corr_rx1_q),
        .summary_valid     (corr_summary_valid),
        .summary_strobe    (corr_summary_strobe),
        .summary_frame_id  (corr_summary_frame_id),
        .summary_samples   (corr_summary_samples),
        .lag0_samples      (corr_lag0_samples),
        .lag1_samples      (corr_lag1_samples),
        .lag2_samples      (corr_lag2_samples),
        .lag3_samples      (corr_lag3_samples),
        .lag0_corr_re      (corr_lag0_re),
        .lag0_corr_im      (corr_lag0_im),
        .lag1_corr_re      (corr_lag1_re),
        .lag1_corr_im      (corr_lag1_im),
        .lag2_corr_re      (corr_lag2_re),
        .lag2_corr_im      (corr_lag2_im),
        .lag3_corr_re      (corr_lag3_re),
        .lag3_corr_im      (corr_lag3_im),
        .lag_valid_mask    (corr_lag_valid_mask)
    );

    function [47:0] band_frame_power;
        input [7:0] idx;
        begin
            case (idx)
                8'd5:   band_frame_power = 48'd3000;
                8'd42:  band_frame_power = 48'd9000;
                8'd100: band_frame_power = 48'd12000;
                8'd170: band_frame_power = 48'd6000;
                8'd191: band_frame_power = 48'd7000;
                8'd200: band_frame_power = 48'd11000;
                8'd255: band_frame_power = 48'd8000;
                default: begin
                    case (idx[7:6])
                        2'b00: band_frame_power = 48'd1;
                        2'b01: band_frame_power = 48'd2;
                        2'b10: band_frame_power = 48'd3;
                        default: band_frame_power = 48'd4;
                    endcase
                end
            endcase
        end
    endfunction

    function signed [15:0] fft_real_word;
        input [7:0] idx;
        begin
            case (idx)
                8'd0:  fft_real_word = 16'sd1;
                8'd5:  fft_real_word = 16'sd64;
                8'd17: fft_real_word = 16'sd32;
                8'd33: fft_real_word = -16'sd16;
                default: fft_real_word = 16'sd2;
            endcase
        end
    endfunction

    function signed [15:0] corr_rx0_i_word;
        input [7:0] idx;
        begin
            corr_rx0_i_word = {8'd0, idx} + 16'sd1;
        end
    endfunction

    function signed [15:0] corr_rx0_q_word;
        input [7:0] idx;
        begin
            corr_rx0_q_word = ($signed({8'd0, idx}) <<< 1) - 16'sd7;
        end
    endfunction

    function signed [15:0] corr_rx1_i_word;
        input [7:0] idx;
        begin
            corr_rx1_i_word = ($signed({8'd0, idx}) * 16'sd3) + 16'sd5;
        end
    endfunction

    function signed [15:0] corr_rx1_q_word;
        input [7:0] idx;
        begin
            corr_rx1_q_word = 16'sd11 - $signed({8'd0, idx});
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            pack_observed_count <= 32'd0;
            pack_last_count <= 32'd0;
        end else if (clear_modules) begin
            pack_observed_count <= 32'd0;
            pack_last_count <= 32'd0;
        end else if (pack_tvalid) begin
            pack_observed_count <= pack_observed_count + 32'd1;
            if (pack_tlast) begin
                pack_last_count <= pack_last_count + 32'd1;
            end
        end
    end

    always @(*) begin
        pack_iq_valid = run_accept;
        pack_iq_i = $signed({7'd0, gen_index[8:0]});
        pack_iq_q = -$signed({7'd0, gen_index[8:0]});

        fft_valid = run_accept;
        fft_last = (gen_index == 9'd255);
        fft_index = gen_index[7:0];
        fft_real = fft_real_word(gen_index[7:0]);
        fft_imag = 16'sd0;

        band_valid = run_accept;
        band_last = (gen_index == 9'd255);
        band_index = gen_index[7:0];
        band_power = band_frame_power(gen_index[7:0]);

        corr_valid = run_accept && (gen_index < 9'd64);
        corr_rx0_i = corr_rx0_i_word(gen_index[7:0]);
        corr_rx0_q = corr_rx0_q_word(gen_index[7:0]);
        corr_rx1_i = corr_rx1_i_word(gen_index[7:0]);
        corr_rx1_q = corr_rx1_q_word(gen_index[7:0]);
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state_reg <= STATE_IDLE;
            gen_index <= 9'd0;
            wait_count <= 8'd0;
            start_d <= 1'b0;
            clear_modules <= 1'b0;
            busy <= 1'b0;
            done <= 1'b0;
            error <= 1'b0;
            done_mask <= 32'd0;
            error_mask <= 32'd0;
            result0 <= 32'd0;
            result1 <= 32'd0;
            result2 <= ABI_WORD;
            result3 <= 32'd0;
        end else begin
            start_d <= start;
            clear_modules <= 1'b0;

            case (state_reg)
                STATE_IDLE: begin
                    busy <= 1'b0;
                    if (start_pulse) begin
                        busy <= 1'b1;
                        done <= 1'b0;
                        error <= 1'b0;
                        done_mask <= 32'd0;
                        error_mask <= 32'd0;
                        result0 <= 32'd0;
                        result1 <= 32'd0;
                        result2 <= ABI_WORD;
                        result3 <= 32'd0;
                        gen_index <= 9'd0;
                        wait_count <= 8'd0;
                        state_reg <= STATE_CLEAR;
                    end
                end
                STATE_CLEAR: begin
                    busy <= 1'b1;
                    clear_modules <= 1'b1;
                    gen_index <= 9'd0;
                    wait_count <= 8'd0;
                    state_reg <= STATE_RUN;
                end
                STATE_RUN: begin
                    busy <= 1'b1;
                    if (run_accept) begin
                        if (gen_index == 9'd255) begin
                            state_reg <= STATE_WAIT;
                        end
                        gen_index <= gen_index + 9'd1;
                    end
                end
                STATE_WAIT: begin
                    busy <= 1'b1;
                    wait_count <= wait_count + 8'd1;
                    done_mask <= observed_done_mask;
                    if ((observed_done_mask == DONE_ALL) ||
                        (wait_count == 8'hff)) begin
                        state_reg <= STATE_LATCH;
                    end
                end
                STATE_LATCH: begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    error <= (check_error_mask != 32'd0) ||
                             (result_hash != EXPECT_RESULT1);
                    done_mask <= observed_done_mask;
                    error_mask <= check_error_mask |
                                  ((result_hash != EXPECT_RESULT1) ?
                                   32'h80000000 : 32'd0);
                    result0 <= EXPECT_RESULT0;
                    result1 <= result_hash;
                    result2 <= EXPECT_RESULT2;
                    result3 <= (check_error_mask == 32'd0) &&
                               (result_hash == EXPECT_RESULT1) ?
                               EXPECT_RESULT3 : check_error_mask;
                    state_reg <= STATE_DONE;
                end
                STATE_DONE: begin
                    busy <= 1'b0;
                    if (start_pulse) begin
                        busy <= 1'b1;
                        done <= 1'b0;
                        error <= 1'b0;
                        done_mask <= 32'd0;
                        error_mask <= 32'd0;
                        result0 <= 32'd0;
                        result1 <= 32'd0;
                        result2 <= ABI_WORD;
                        result3 <= 32'd0;
                        gen_index <= 9'd0;
                        wait_count <= 8'd0;
                        state_reg <= STATE_CLEAR;
                    end
                end
                default: begin
                    state_reg <= STATE_IDLE;
                    busy <= 1'b0;
                end
            endcase
        end
    end

endmodule

`default_nettype wire
