`timescale 1ns/1ps
`default_nettype none

module p201_v10s5_nonfft_selftest_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        start,
    output reg         busy,
    output reg  [31:0] done,
    output reg  [31:0] error,
    output reg  [31:0] result
);

    localparam [31:0] DONE_QUALITY       = 32'h00000001;
    localparam [31:0] DONE_WINDOW        = 32'h00000002;
    localparam [31:0] DONE_ENERGY        = 32'h00000004;

    localparam [2:0] STATE_IDLE          = 3'd0;
    localparam [2:0] STATE_CLEAR         = 3'd1;
    localparam [2:0] STATE_PRIME         = 3'd2;
    localparam [2:0] STATE_RUN           = 3'd3;
    localparam [2:0] STATE_WAIT          = 3'd4;
    localparam [2:0] STATE_DONE          = 3'd5;

    localparam [31:0] EXPECT_SUM_I       = 32'h00008374;
    localparam [31:0] EXPECT_SUM_Q       = 32'hffff7b9c;
    localparam [31:0] EXPECT_SUM_I2      = 32'h400e6d8c;
    localparam [31:0] EXPECT_SUM_Q2      = 32'h400fe730;
    localparam [31:0] EXPECT_SUM_IQ      = 32'hbff187e8;
    localparam [31:0] EXPECT_RESULT      = 32'h400f75cf;

    localparam [31:0] EXPECT_EN_TOTAL    = 32'd309;
    localparam [31:0] EXPECT_EN_NOISE    = 32'd2;
    localparam [31:0] EXPECT_EN_PEAK     = 32'd100;
    localparam [31:0] EXPECT_EN_SECOND   = 32'd90;
    localparam [31:0] EXPECT_EN_PROM     = 32'd98;

    reg                       start_d;
    reg                       enable_reg;
    reg                       clear_modules;
    reg                       feed_valid;
    reg                       feed_last;
    reg signed [15:0]         feed_i;
    reg signed [15:0]         feed_q;
    reg [31:0]                feed_energy;
    reg [15:0]                feed_energy_index;
    reg [2:0]                 state_reg;
    reg [3:0]                 gen_index;
    reg [3:0]                 wait_count;

    wire                      start_pulse;
    wire                      quality_frame_done;
    wire                      quality_stats_valid;
    wire                      quality_overflow;
    wire                      quality_protocol_error;
    wire [31:0]               quality_count;
    wire signed [47:0]        quality_sum_i;
    wire signed [47:0]        quality_sum_q;
    wire [63:0]               quality_sum_i2;
    wire [63:0]               quality_sum_q2;
    wire signed [63:0]        quality_sum_iq;
    wire [15:0]               quality_abs_peak;
    wire [31:0]               quality_clip_i;
    wire [31:0]               quality_clip_q;
    wire [31:0]               quality_sat_i;
    wire [31:0]               quality_sat_q;
    wire [31:0]               quality_valid_count;
    wire [31:0]               quality_drop_count;

    wire                      window_sample_ready;
    wire                      window_out_valid;
    wire                      window_last_out;
    wire signed [15:0]        window_out_i;
    wire signed [15:0]        window_out_q;
    wire [2:0]                window_frame_index;
    wire [31:0]               window_frame_id;
    wire [31:0]               window_raw_count;
    wire [31:0]               window_accepted_count;
    wire [31:0]               window_dropped_count;
    wire [31:0]               window_overflow_count;
    wire [31:0]               window_status_flags;

    wire                      energy_sample_ready;
    wire [31:0]               energy_flags;
    wire [31:0]               energy_frame_id;
    wire [15:0]               energy_sample_count;
    wire [63:0]               energy_total;
    wire [31:0]               energy_noise;
    wire [31:0]               energy_peak;
    wire [15:0]               energy_peak_index;
    wire [31:0]               energy_second_peak;
    wire [15:0]               energy_second_index;
    wire [31:0]               energy_prominence;
    wire [15:0]               energy_threshold_count;

    wire [31:0]               quality_clip_word;
    wire [31:0]               quality_sat_word;
    wire [31:0]               result_word;
    wire                      quality_pass;
    wire                      window_pass;
    wire                      energy_pass;

    assign start_pulse = start && !start_d;
    assign quality_clip_word = {quality_clip_q[15:0], quality_clip_i[15:0]};
    assign quality_sat_word = {quality_sat_q[15:0], quality_sat_i[15:0]};

    assign quality_pass =
        quality_stats_valid &&
        (quality_count == 32'd8) &&
        (quality_sum_i[31:0] == EXPECT_SUM_I) &&
        (quality_sum_q[31:0] == EXPECT_SUM_Q) &&
        (quality_sum_i2[31:0] == EXPECT_SUM_I2) &&
        (quality_sum_q2[31:0] == EXPECT_SUM_Q2) &&
        (quality_sum_iq[31:0] == EXPECT_SUM_IQ) &&
        (quality_abs_peak == 16'd32768) &&
        (quality_clip_i == 32'd1) &&
        (quality_clip_q == 32'd1) &&
        (quality_sat_i == 32'd1) &&
        (quality_sat_q == 32'd1) &&
        (quality_valid_count == 32'd8) &&
        (quality_drop_count == 32'd0) &&
        !quality_overflow &&
        !quality_protocol_error;

    assign window_pass =
        (window_raw_count == 32'd8) &&
        (window_accepted_count == 32'd8) &&
        (window_dropped_count == 32'd0) &&
        (window_overflow_count == 32'd0) &&
        (window_frame_id == 32'd1);

    assign energy_pass =
        ((energy_flags & 32'h00000111) == 32'h00000111) &&
        (energy_frame_id == 32'd1) &&
        (energy_sample_count == 16'd8) &&
        (energy_total[31:0] == EXPECT_EN_TOTAL) &&
        (energy_noise == EXPECT_EN_NOISE) &&
        (energy_peak == EXPECT_EN_PEAK) &&
        (energy_peak_index == 16'd4) &&
        (energy_second_peak == EXPECT_EN_SECOND) &&
        (energy_second_index == 16'd6) &&
        (energy_prominence == EXPECT_EN_PROM) &&
        (energy_threshold_count == 16'd3);

    assign result_word =
        quality_count ^
        quality_sum_i[31:0] ^
        quality_sum_q[31:0] ^
        quality_sum_i2[31:0] ^
        quality_sum_q2[31:0] ^
        quality_sum_iq[31:0] ^
        {16'd0, quality_abs_peak} ^
        quality_clip_word ^
        quality_sat_word ^
        quality_valid_count ^
        quality_drop_count ^
        window_raw_count ^
        window_accepted_count ^
        window_dropped_count ^
        window_overflow_count ^
        window_frame_id ^
        (energy_flags & 32'h00000111) ^
        energy_frame_id ^
        {16'd0, energy_sample_count} ^
        energy_total[31:0] ^
        energy_noise ^
        energy_peak ^
        {16'd0, energy_peak_index} ^
        energy_second_peak ^
        {16'd0, energy_second_index} ^
        energy_prominence ^
        {16'd0, energy_threshold_count};

    p201_sdr_quality_stats u_quality_stats (
        .clk            (clk),
        .rst_n          (rst_n),
        .enable         (enable_reg),
        .clear          (clear_modules),
        .frame_start    (feed_valid && (gen_index == 4'd0)),
        .frame_end      (feed_valid && (gen_index == 4'd7)),
        .sample_valid   (feed_valid),
        .sample_drop    (1'b0),
        .sample_i       (feed_i),
        .sample_q       (feed_q),
        .frame_active   (),
        .frame_done     (quality_frame_done),
        .stats_valid    (quality_stats_valid),
        .overflow       (quality_overflow),
        .protocol_error (quality_protocol_error),
        .sample_count   (quality_count),
        .sum_i          (quality_sum_i),
        .sum_q          (quality_sum_q),
        .sum_i2         (quality_sum_i2),
        .sum_q2         (quality_sum_q2),
        .sum_iq         (quality_sum_iq),
        .abs_peak       (quality_abs_peak),
        .clip_i_count   (quality_clip_i),
        .clip_q_count   (quality_clip_q),
        .sat_i_count    (quality_sat_i),
        .sat_q_count    (quality_sat_q),
        .valid_count    (quality_valid_count),
        .drop_count     (quality_drop_count)
    );

    p201_v10s2_frame_window u_frame_window (
        .clk              (clk),
        .rst_n            (rst_n),
        .enable           (enable_reg),
        .clear            (clear_modules),
        .decim_factor     (8'd1),
        .window_mode      (1'b1),
        .sample_valid     (feed_valid),
        .sample_ready     (window_sample_ready),
        .sample_i         (feed_i),
        .sample_q         (feed_q),
        .out_valid        (window_out_valid),
        .out_ready        (1'b1),
        .last_out         (window_last_out),
        .out_i            (window_out_i),
        .out_q            (window_out_q),
        .frame_index      (window_frame_index),
        .frame_id         (window_frame_id),
        .raw_sample_count (window_raw_count),
        .accepted_count   (window_accepted_count),
        .dropped_count    (window_dropped_count),
        .overflow_count   (window_overflow_count),
        .status_flags     (window_status_flags)
    );

    p201_v10s3_energy_peak_reducer u_energy_peak (
        .clk                       (clk),
        .rst_n                     (rst_n),
        .enable                    (enable_reg),
        .clear_summary             (clear_modules),
        .sample_valid              (feed_valid),
        .sample_ready              (energy_sample_ready),
        .sample_last               (feed_last),
        .sample_value              (feed_energy),
        .sample_index              (feed_energy_index),
        .threshold_value           (32'd50),
        .summary_flags             (energy_flags),
        .summary_frame_id          (energy_frame_id),
        .summary_sample_count      (energy_sample_count),
        .summary_total_energy      (energy_total),
        .summary_noise_floor       (energy_noise),
        .summary_peak_value        (energy_peak),
        .summary_peak_index        (energy_peak_index),
        .summary_second_peak_value (energy_second_peak),
        .summary_second_peak_index (energy_second_index),
        .summary_prominence        (energy_prominence),
        .summary_threshold_count   (energy_threshold_count)
    );

    function signed [15:0] sample_i_for_index;
        input [3:0] index;
        begin
            case (index)
                4'd0: sample_i_for_index = 16'sd3;
                4'd1: sample_i_for_index = -16'sd5;
                4'd2: sample_i_for_index = 16'sd32767;
                4'd3: sample_i_for_index = -16'sd100;
                4'd4: sample_i_for_index = 16'sd10;
                4'd5: sample_i_for_index = -16'sd30;
                4'd6: sample_i_for_index = 16'sd1000;
                default: sample_i_for_index = 16'sd7;
            endcase
        end
    endfunction

    function signed [15:0] sample_q_for_index;
        input [3:0] index;
        begin
            case (index)
                4'd0: sample_q_for_index = -16'sd4;
                4'd1: sample_q_for_index = 16'sd12;
                4'd2: sample_q_for_index = -16'sd32768;
                4'd3: sample_q_for_index = -16'sd200;
                4'd4: sample_q_for_index = 16'sd20;
                4'd5: sample_q_for_index = 16'sd40;
                4'd6: sample_q_for_index = -16'sd1000;
                default: sample_q_for_index = 16'sd8;
            endcase
        end
    endfunction

    function [31:0] energy_for_index;
        input [3:0] index;
        begin
            case (index)
                4'd0: energy_for_index = 32'd5;
                4'd1: energy_for_index = 32'd7;
                4'd2: energy_for_index = 32'd50;
                4'd3: energy_for_index = 32'd2;
                4'd4: energy_for_index = 32'd100;
                4'd5: energy_for_index = 32'd25;
                4'd6: energy_for_index = 32'd90;
                default: energy_for_index = 32'd30;
            endcase
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            start_d           <= 1'b0;
            enable_reg        <= 1'b0;
            clear_modules     <= 1'b0;
            feed_valid        <= 1'b0;
            feed_last         <= 1'b0;
            feed_i            <= 16'sd0;
            feed_q            <= 16'sd0;
            feed_energy       <= 32'd0;
            feed_energy_index <= 16'd0;
            state_reg         <= STATE_IDLE;
            gen_index         <= 4'd0;
            wait_count        <= 4'd0;
            busy              <= 1'b0;
            done              <= 32'd0;
            error             <= 32'd0;
            result            <= 32'd0;
        end else begin
            start_d           <= start;
            clear_modules     <= 1'b0;
            feed_valid        <= 1'b0;
            feed_last         <= 1'b0;
            feed_i            <= 16'sd0;
            feed_q            <= 16'sd0;
            feed_energy       <= 32'd0;
            feed_energy_index <= 16'd0;

            case (state_reg)
                STATE_IDLE: begin
                    busy <= 1'b0;
                    enable_reg <= 1'b0;
                    if (start_pulse) begin
                        busy <= 1'b1;
                        enable_reg <= 1'b1;
                        clear_modules <= 1'b1;
                        gen_index <= 4'd0;
                        wait_count <= 4'd0;
                        done <= 32'd0;
                        error <= 32'd0;
                        result <= 32'd0;
                        state_reg <= STATE_CLEAR;
                    end
                end
                STATE_CLEAR: begin
                    busy <= 1'b1;
                    enable_reg <= 1'b1;
                    clear_modules <= 1'b1;
                    gen_index <= 4'd0;
                    wait_count <= 4'd0;
                    state_reg <= STATE_PRIME;
                end
                STATE_PRIME: begin
                    busy <= 1'b1;
                    enable_reg <= 1'b1;
                    feed_valid <= 1'b1;
                    feed_i <= sample_i_for_index(4'd0);
                    feed_q <= sample_q_for_index(4'd0);
                    feed_energy <= energy_for_index(4'd0);
                    feed_energy_index <= 16'd0;
                    state_reg <= STATE_RUN;
                end
                STATE_RUN: begin
                    busy <= 1'b1;
                    enable_reg <= 1'b1;
                    if (gen_index == 4'd7) begin
                        gen_index <= 4'd0;
                        wait_count <= 4'd0;
                        state_reg <= STATE_WAIT;
                    end else begin
                        feed_valid <= 1'b1;
                        feed_last <= (gen_index == 4'd6);
                        feed_i <= sample_i_for_index(gen_index + 4'd1);
                        feed_q <= sample_q_for_index(gen_index + 4'd1);
                        feed_energy <= energy_for_index(gen_index + 4'd1);
                        feed_energy_index <= {12'd0, gen_index + 4'd1};
                        gen_index <= gen_index + 4'd1;
                    end
                end
                STATE_WAIT: begin
                    busy <= 1'b1;
                    enable_reg <= 1'b1;
                    wait_count <= wait_count + 4'd1;
                    if (wait_count == 4'd4) begin
                        done <=
                            (quality_pass ? DONE_QUALITY : 32'd0) |
                            (window_pass ? DONE_WINDOW : 32'd0) |
                            (energy_pass ? DONE_ENERGY : 32'd0);
                        error <=
                            (quality_pass ? 32'd0 : DONE_QUALITY) |
                            (window_pass ? 32'd0 : DONE_WINDOW) |
                            (energy_pass ? 32'd0 : DONE_ENERGY);
                        result <= result_word;
                        busy <= 1'b0;
                        state_reg <= STATE_DONE;
                    end
                end
                STATE_DONE: begin
                    busy <= 1'b0;
                    enable_reg <= 1'b1;
                    if (start_pulse) begin
                        busy <= 1'b1;
                        clear_modules <= 1'b1;
                        gen_index <= 4'd0;
                        wait_count <= 4'd0;
                        done <= 32'd0;
                        error <= 32'd0;
                        result <= 32'd0;
                        state_reg <= STATE_CLEAR;
                    end
                end
                default: begin
                    busy <= 1'b0;
                    enable_reg <= 1'b0;
                    state_reg <= STATE_IDLE;
                end
            endcase

            if ((state_reg == STATE_WAIT) &&
                (wait_count == 4'd4) &&
                quality_pass &&
                window_pass &&
                energy_pass &&
                (result_word != EXPECT_RESULT)) begin
                error <= DONE_QUALITY | DONE_WINDOW | DONE_ENERGY;
            end
        end
    end

endmodule

`default_nettype wire
