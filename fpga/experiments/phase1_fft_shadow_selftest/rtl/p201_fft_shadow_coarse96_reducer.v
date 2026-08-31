`timescale 1ns/1ps
`default_nettype none

module p201_fft_shadow_coarse96_reducer #(
    parameter integer BIN_INDEX_WIDTH = 12,
    parameter integer POWER_WIDTH = 32
) (
    input  wire                          clk,
    input  wire                          rst_n,
    input  wire                          enable,
    input  wire                          clear,

    input  wire                          bin_valid,
    output wire                          bin_ready,
    input  wire                          bin_last,
    input  wire [BIN_INDEX_WIDTH-1:0]    bin_index,
    input  wire signed [POWER_WIDTH-1:0] bin_power,

    input  wire                          coarse_read_strobe,
    input  wire [6:0]                    coarse_read_index,
    output reg                           coarse_read_valid,
    output reg  [6:0]                    coarse_read_index_out,
    output reg  signed [POWER_WIDTH-1:0] coarse_read_power,

    output reg                           summary_valid,
    output reg  [31:0]                   summary_bin_count,
    output reg  [7:0]                    coarse_bin_count,
    output wire [31:0]                   coarse_bin_step_q16,
    output wire [31:0]                   status_flags
);

    localparam [31:0] BIN_COUNT = 32'd2048;
    localparam [7:0]  COARSE_COUNT = 8'd96;
    localparam [31:0] COARSE_STEP_Q16 = 32'd1398101;

    reg                                      frame_active;
    reg [31:0]                               frame_bin_count;
    reg [95:0]                               coarse_valid_mask;
    reg                                      range_error_seen;
    reg signed [POWER_WIDTH-1:0]             coarse_power [0:95];

    integer                                  i;

    wire                                     accept_bin;
    wire                                     start_frame;
    wire [31:0]                              running_bin_count;
    wire [12:0]                              bin_plus1;
    wire [14:0]                              bin_plus1_times3;
    wire [19:0]                              coarse_index_numer;
    wire [6:0]                               coarse_index_raw;
    wire                                     bin_index_in_range;
    wire [6:0]                               coarse_index;
    wire [95:0]                              coarse_index_mask;
    wire                                     current_coarse_valid;
    wire signed [POWER_WIDTH-1:0]            current_coarse_power;
    wire                                     replace_coarse_power;
    wire                                     read_index_in_range;

    assign bin_ready = enable && !clear;
    assign accept_bin = bin_valid && bin_ready;
    assign start_frame = !frame_active || (bin_index == {BIN_INDEX_WIDTH{1'b0}});
    assign running_bin_count = start_frame ? 32'd1 : (frame_bin_count + 32'd1);

    assign bin_plus1 = {1'b0, bin_index} + 13'd1;
    assign bin_plus1_times3 = {2'b00, bin_plus1} + ({2'b00, bin_plus1} << 1);
    assign coarse_index_numer = ({5'd0, bin_plus1_times3} << 5) - 20'd1;
    assign coarse_index_raw = coarse_index_numer[17:11];
    assign bin_index_in_range = ({20'd0, bin_index} < BIN_COUNT);
    assign coarse_index = (!bin_index_in_range) ? 7'd95 :
                          ((coarse_index_raw >= COARSE_COUNT) ?
                           7'd95 : coarse_index_raw);
    assign coarse_index_mask = 96'd1 << coarse_index;
    assign current_coarse_valid = coarse_valid_mask[coarse_index];
    assign current_coarse_power = coarse_power[coarse_index];
    assign replace_coarse_power = start_frame ||
                                  !current_coarse_valid ||
                                  (bin_power > current_coarse_power);
    assign read_index_in_range = coarse_read_index < COARSE_COUNT[6:0];

    assign coarse_bin_step_q16 = COARSE_STEP_Q16;
    assign status_flags = {
        25'd0,
        range_error_seen,
        coarse_read_valid,
        frame_active,
        bin_ready,
        summary_valid,
        enable,
        clear
    };

    always @(posedge clk) begin
        if (!rst_n) begin
            frame_active <= 1'b0;
            frame_bin_count <= 32'd0;
            coarse_valid_mask <= 96'd0;
            range_error_seen <= 1'b0;
            coarse_read_valid <= 1'b0;
            coarse_read_index_out <= 7'd0;
            coarse_read_power <= {POWER_WIDTH{1'b0}};
            summary_valid <= 1'b0;
            summary_bin_count <= 32'd0;
            coarse_bin_count <= COARSE_COUNT;
            for (i = 0; i < 96; i = i + 1) begin
                coarse_power[i] <= {POWER_WIDTH{1'b0}};
            end
        end else begin
            if (clear || !enable) begin
                frame_active <= 1'b0;
                frame_bin_count <= 32'd0;
                coarse_valid_mask <= 96'd0;
                range_error_seen <= 1'b0;
                coarse_read_valid <= 1'b0;
                coarse_read_index_out <= 7'd0;
                coarse_read_power <= {POWER_WIDTH{1'b0}};
                summary_valid <= 1'b0;
                summary_bin_count <= 32'd0;
                coarse_bin_count <= COARSE_COUNT;
            end else begin
                coarse_read_valid <= 1'b0;

                if (coarse_read_strobe) begin
                    coarse_read_index_out <= coarse_read_index;
                    if (read_index_in_range &&
                        summary_valid &&
                        coarse_valid_mask[coarse_read_index]) begin
                        coarse_read_valid <= 1'b1;
                        coarse_read_power <= coarse_power[coarse_read_index];
                    end else begin
                        coarse_read_valid <= 1'b0;
                        coarse_read_power <= {POWER_WIDTH{1'b0}};
                    end
                end

                if (accept_bin) begin
                    if (start_frame) begin
                        summary_valid <= 1'b0;
                        frame_bin_count <= 32'd0;
                        coarse_valid_mask <= coarse_index_mask;
                        range_error_seen <= !bin_index_in_range;
                    end else begin
                        coarse_valid_mask <= coarse_valid_mask | coarse_index_mask;
                        if (!bin_index_in_range) begin
                            range_error_seen <= 1'b1;
                        end
                    end

                    if (replace_coarse_power) begin
                        coarse_power[coarse_index] <= bin_power;
                    end

                    if (bin_last) begin
                        summary_valid <= 1'b1;
                        summary_bin_count <= running_bin_count;
                        coarse_bin_count <= COARSE_COUNT;
                        frame_active <= 1'b0;
                        frame_bin_count <= 32'd0;
                    end else begin
                        frame_active <= 1'b1;
                        frame_bin_count <= running_bin_count;
                    end
                end
            end
        end
    end

endmodule

`default_nettype wire
