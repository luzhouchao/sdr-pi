`timescale 1ns/1ps
`default_nettype none

module p201_sdr_quality_stats #(
    parameter integer SAMPLE_WIDTH = 16,
    parameter integer COUNT_WIDTH  = 32,
    parameter integer SUM_WIDTH    = 48,
    parameter integer POWER_WIDTH  = 64,
    parameter integer MAX_SAMPLES  = 65535
) (
    input  wire                              clk,
    input  wire                              rst_n,
    input  wire                              enable,
    input  wire                              clear,

    input  wire                              frame_start,
    input  wire                              frame_end,
    input  wire                              sample_valid,
    input  wire                              sample_drop,
    input  wire signed [SAMPLE_WIDTH-1:0]   sample_i,
    input  wire signed [SAMPLE_WIDTH-1:0]   sample_q,

    output reg                               frame_active,
    output reg                               frame_done,
    output reg                               stats_valid,
    output reg                               overflow,
    output reg                               protocol_error,

    output reg  [COUNT_WIDTH-1:0]           sample_count,
    output reg  signed [SUM_WIDTH-1:0]      sum_i,
    output reg  signed [SUM_WIDTH-1:0]      sum_q,
    output reg  [POWER_WIDTH-1:0]           sum_i2,
    output reg  [POWER_WIDTH-1:0]           sum_q2,
    output reg  signed [POWER_WIDTH-1:0]    sum_iq,
    output reg  [SAMPLE_WIDTH-1:0]          abs_peak,
    output reg  [COUNT_WIDTH-1:0]           clip_i_count,
    output reg  [COUNT_WIDTH-1:0]           clip_q_count,
    output reg  [COUNT_WIDTH-1:0]           sat_i_count,
    output reg  [COUNT_WIDTH-1:0]           sat_q_count,
    output reg  [COUNT_WIDTH-1:0]           valid_count,
    output reg  [COUNT_WIDTH-1:0]           drop_count
);

    localparam integer PRODUCT_WIDTH = SAMPLE_WIDTH * 2;
    localparam signed [SAMPLE_WIDTH-1:0] POS_FULL_SCALE =
        {1'b0, {(SAMPLE_WIDTH-1){1'b1}}};
    localparam signed [SAMPLE_WIDTH-1:0] NEG_FULL_SCALE =
        {1'b1, {(SAMPLE_WIDTH-1){1'b0}}};
    localparam signed [SAMPLE_WIDTH-1:0] POS_SAT_LEVEL =
        {1'b0, {(SAMPLE_WIDTH-2){1'b1}}, 1'b0};
    localparam signed [SAMPLE_WIDTH-1:0] NEG_SAT_LEVEL =
        {1'b1, 1'b0, {(SAMPLE_WIDTH-2){1'b0}}};

    wire signed [PRODUCT_WIDTH-1:0] i_square;
    wire signed [PRODUCT_WIDTH-1:0] q_square;
    wire signed [PRODUCT_WIDTH-1:0] iq_product;
    wire [SAMPLE_WIDTH-1:0]         abs_i;
    wire [SAMPLE_WIDTH-1:0]         abs_q;
    wire [SAMPLE_WIDTH-1:0]         sample_peak;
    wire                            frame_is_open;
    wire                            accept_sample;
    wire                            count_room;
    wire                            clip_i;
    wire                            clip_q;
    wire                            sat_i;
    wire                            sat_q;

    assign i_square = sample_i * sample_i;
    assign q_square = sample_q * sample_q;
    assign iq_product = sample_i * sample_q;
    assign abs_i = abs_signed_sample(sample_i);
    assign abs_q = abs_signed_sample(sample_q);
    assign sample_peak = (abs_i >= abs_q) ? abs_i : abs_q;
    assign frame_is_open = frame_active || frame_start;
    assign accept_sample = enable && frame_is_open && sample_valid && count_room;
    assign count_room = sample_count < MAX_SAMPLES[COUNT_WIDTH-1:0];
    assign clip_i = (sample_i == POS_FULL_SCALE) || (sample_i == NEG_FULL_SCALE);
    assign clip_q = (sample_q == POS_FULL_SCALE) || (sample_q == NEG_FULL_SCALE);
    assign sat_i = (sample_i >= POS_SAT_LEVEL) || (sample_i <= NEG_SAT_LEVEL);
    assign sat_q = (sample_q >= POS_SAT_LEVEL) || (sample_q <= NEG_SAT_LEVEL);

    function [SAMPLE_WIDTH-1:0] abs_signed_sample;
        input signed [SAMPLE_WIDTH-1:0] value;
        begin
            if (value[SAMPLE_WIDTH-1]) begin
                abs_signed_sample = (~value) + {{(SAMPLE_WIDTH-1){1'b0}}, 1'b1};
            end else begin
                abs_signed_sample = value[SAMPLE_WIDTH-1:0];
            end
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            frame_active   <= 1'b0;
            frame_done     <= 1'b0;
            stats_valid    <= 1'b0;
            overflow       <= 1'b0;
            protocol_error <= 1'b0;
            sample_count   <= {COUNT_WIDTH{1'b0}};
            sum_i          <= {SUM_WIDTH{1'b0}};
            sum_q          <= {SUM_WIDTH{1'b0}};
            sum_i2         <= {POWER_WIDTH{1'b0}};
            sum_q2         <= {POWER_WIDTH{1'b0}};
            sum_iq         <= {POWER_WIDTH{1'b0}};
            abs_peak       <= {SAMPLE_WIDTH{1'b0}};
            clip_i_count   <= {COUNT_WIDTH{1'b0}};
            clip_q_count   <= {COUNT_WIDTH{1'b0}};
            sat_i_count    <= {COUNT_WIDTH{1'b0}};
            sat_q_count    <= {COUNT_WIDTH{1'b0}};
            valid_count    <= {COUNT_WIDTH{1'b0}};
            drop_count     <= {COUNT_WIDTH{1'b0}};
        end else begin
            frame_done <= 1'b0;

            if (clear || !enable) begin
                frame_active   <= 1'b0;
                frame_done     <= 1'b0;
                stats_valid    <= 1'b0;
                overflow       <= 1'b0;
                protocol_error <= 1'b0;
                sample_count   <= {COUNT_WIDTH{1'b0}};
                sum_i          <= {SUM_WIDTH{1'b0}};
                sum_q          <= {SUM_WIDTH{1'b0}};
                sum_i2         <= {POWER_WIDTH{1'b0}};
                sum_q2         <= {POWER_WIDTH{1'b0}};
                sum_iq         <= {POWER_WIDTH{1'b0}};
                abs_peak       <= {SAMPLE_WIDTH{1'b0}};
                clip_i_count   <= {COUNT_WIDTH{1'b0}};
                clip_q_count   <= {COUNT_WIDTH{1'b0}};
                sat_i_count    <= {COUNT_WIDTH{1'b0}};
                sat_q_count    <= {COUNT_WIDTH{1'b0}};
                valid_count    <= {COUNT_WIDTH{1'b0}};
                drop_count     <= {COUNT_WIDTH{1'b0}};
            end else begin
                if (frame_start) begin
                    if (frame_active) begin
                        protocol_error <= 1'b1;
                    end
                    frame_active <= 1'b1;
                    stats_valid  <= 1'b0;
                    overflow     <= 1'b0;
                    sample_count <= {COUNT_WIDTH{1'b0}};
                    sum_i        <= {SUM_WIDTH{1'b0}};
                    sum_q        <= {SUM_WIDTH{1'b0}};
                    sum_i2       <= {POWER_WIDTH{1'b0}};
                    sum_q2       <= {POWER_WIDTH{1'b0}};
                    sum_iq       <= {POWER_WIDTH{1'b0}};
                    abs_peak     <= {SAMPLE_WIDTH{1'b0}};
                    clip_i_count <= {COUNT_WIDTH{1'b0}};
                    clip_q_count <= {COUNT_WIDTH{1'b0}};
                    sat_i_count  <= {COUNT_WIDTH{1'b0}};
                    sat_q_count  <= {COUNT_WIDTH{1'b0}};
                    valid_count  <= {COUNT_WIDTH{1'b0}};
                    drop_count   <= {COUNT_WIDTH{1'b0}};
                end

                if (sample_valid && frame_is_open) begin
                    valid_count <= valid_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                end

                if (sample_drop && frame_is_open) begin
                    drop_count <= drop_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                end

                if (sample_valid && frame_is_open && !count_room) begin
                    overflow <= 1'b1;
                end

                if (sample_valid && !frame_is_open) begin
                    protocol_error <= 1'b1;
                end

                if (accept_sample) begin
                    sample_count <= sample_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                    sum_i <= sum_i + {{(SUM_WIDTH-SAMPLE_WIDTH){sample_i[SAMPLE_WIDTH-1]}}, sample_i};
                    sum_q <= sum_q + {{(SUM_WIDTH-SAMPLE_WIDTH){sample_q[SAMPLE_WIDTH-1]}}, sample_q};
                    sum_i2 <= sum_i2 + {{(POWER_WIDTH-PRODUCT_WIDTH){1'b0}}, i_square};
                    sum_q2 <= sum_q2 + {{(POWER_WIDTH-PRODUCT_WIDTH){1'b0}}, q_square};
                    sum_iq <= sum_iq + {{(POWER_WIDTH-PRODUCT_WIDTH){iq_product[PRODUCT_WIDTH-1]}}, iq_product};
                    if (sample_peak > abs_peak) begin
                        abs_peak <= sample_peak;
                    end
                    if (clip_i) begin
                        clip_i_count <= clip_i_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                    end
                    if (clip_q) begin
                        clip_q_count <= clip_q_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                    end
                    if (sat_i) begin
                        sat_i_count <= sat_i_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                    end
                    if (sat_q) begin
                        sat_q_count <= sat_q_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                    end
                end

                if (frame_end) begin
                    if (!frame_active) begin
                        protocol_error <= 1'b1;
                    end
                    frame_active <= 1'b0;
                    frame_done   <= frame_active;
                    stats_valid  <= frame_active;
                end
            end
        end
    end

endmodule

`default_nettype wire
