`timescale 1ns/1ps
`default_nettype none

module p201_fft_shadow_top4_reducer #(
    parameter integer BIN_INDEX_WIDTH = 12,
    parameter integer POWER_WIDTH = 32,
    parameter integer GUARD_BINS = 3
) (
    input  wire                              clk,
    input  wire                              rst_n,
    input  wire                              enable,
    input  wire                              clear,

    input  wire                              bin_valid,
    output wire                              bin_ready,
    input  wire                              bin_last,
    input  wire [BIN_INDEX_WIDTH-1:0]        bin_index,
    input  wire signed [POWER_WIDTH-1:0]     bin_power,

    output reg                               summary_valid,
    output reg  [31:0]                       summary_bin_count,
    output reg  [2:0]                        top_count,
    output reg  [BIN_INDEX_WIDTH-1:0]        top0_bin,
    output reg  signed [POWER_WIDTH-1:0]     top0_power,
    output reg  [BIN_INDEX_WIDTH-1:0]        top1_bin,
    output reg  signed [POWER_WIDTH-1:0]     top1_power,
    output reg  [BIN_INDEX_WIDTH-1:0]        top2_bin,
    output reg  signed [POWER_WIDTH-1:0]     top2_power,
    output reg  [BIN_INDEX_WIDTH-1:0]        top3_bin,
    output reg  signed [POWER_WIDTH-1:0]     top3_power,
    output wire [31:0]                       status_flags
);

    localparam [2:0] STATE_IDLE   = 3'd0;
    localparam [2:0] STATE_GUARD  = 3'd1;
    localparam [2:0] STATE_INSERT = 3'd2;
    localparam [2:0] STATE_FINISH = 3'd3;

    reg [2:0]                                state;
    reg [2:0]                                scan_index;
    reg                                      frame_active;
    reg [31:0]                               frame_bin_count;
    reg [3:0]                                work_valid;
    reg [BIN_INDEX_WIDTH-1:0]                work_bin [0:3];
    reg signed [POWER_WIDTH-1:0]             work_power [0:3];
    reg                                      pending_last;
    reg                                      pending_allowed;
    reg [BIN_INDEX_WIDTH-1:0]                pending_bin;
    reg signed [POWER_WIDTH-1:0]             pending_power;
    reg [31:0]                               pending_bin_count;

    integer                                  i;

    wire                                     accept_bin;
    wire                                     start_frame;
    wire [31:0]                              running_bin_count;
    wire [2:0]                               work_count;

    assign bin_ready = enable && !clear && (state == STATE_IDLE);
    assign accept_bin = bin_valid && bin_ready;
    assign start_frame = !frame_active || (bin_index == {BIN_INDEX_WIDTH{1'b0}});
    assign running_bin_count = start_frame ? 32'd1 : (frame_bin_count + 32'd1);
    assign work_count = {2'd0, work_valid[0]} +
                        {2'd0, work_valid[1]} +
                        {2'd0, work_valid[2]} +
                        {2'd0, work_valid[3]};
    assign status_flags = {
        23'd0,
        pending_allowed,
        pending_last,
        frame_active,
        state,
        bin_ready,
        summary_valid,
        enable
    };

    function is_better;
        input signed [POWER_WIDTH-1:0] candidate_power;
        input [BIN_INDEX_WIDTH-1:0] candidate_bin;
        input stored_valid;
        input signed [POWER_WIDTH-1:0] stored_power;
        input [BIN_INDEX_WIDTH-1:0] stored_bin;
        begin
            is_better = !stored_valid ||
                        (candidate_power > stored_power) ||
                        ((candidate_power == stored_power) &&
                         (candidate_bin < stored_bin));
        end
    endfunction

    function within_guard;
        input [BIN_INDEX_WIDTH-1:0] lhs;
        input [BIN_INDEX_WIDTH-1:0] rhs;
        reg [BIN_INDEX_WIDTH-1:0] diff;
        begin
            diff = (lhs >= rhs) ? (lhs - rhs) : (rhs - lhs);
            within_guard = (diff <= GUARD_BINS);
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= STATE_IDLE;
            scan_index <= 3'd0;
            frame_active <= 1'b0;
            frame_bin_count <= 32'd0;
            pending_last <= 1'b0;
            pending_allowed <= 1'b0;
            pending_bin <= {BIN_INDEX_WIDTH{1'b0}};
            pending_power <= {POWER_WIDTH{1'b0}};
            pending_bin_count <= 32'd0;
            summary_valid <= 1'b0;
            summary_bin_count <= 32'd0;
            top_count <= 3'd0;
            top0_bin <= {BIN_INDEX_WIDTH{1'b0}};
            top0_power <= {POWER_WIDTH{1'b0}};
            top1_bin <= {BIN_INDEX_WIDTH{1'b0}};
            top1_power <= {POWER_WIDTH{1'b0}};
            top2_bin <= {BIN_INDEX_WIDTH{1'b0}};
            top2_power <= {POWER_WIDTH{1'b0}};
            top3_bin <= {BIN_INDEX_WIDTH{1'b0}};
            top3_power <= {POWER_WIDTH{1'b0}};
            for (i = 0; i < 4; i = i + 1) begin
                work_valid[i] <= 1'b0;
                work_bin[i] <= {BIN_INDEX_WIDTH{1'b0}};
                work_power[i] <= {POWER_WIDTH{1'b0}};
            end
        end else begin
            if (clear || !enable) begin
                state <= STATE_IDLE;
                scan_index <= 3'd0;
                frame_active <= 1'b0;
                frame_bin_count <= 32'd0;
                pending_last <= 1'b0;
                pending_allowed <= 1'b0;
                pending_bin <= {BIN_INDEX_WIDTH{1'b0}};
                pending_power <= {POWER_WIDTH{1'b0}};
                pending_bin_count <= 32'd0;
                summary_valid <= 1'b0;
                summary_bin_count <= 32'd0;
                top_count <= 3'd0;
                top0_bin <= {BIN_INDEX_WIDTH{1'b0}};
                top0_power <= {POWER_WIDTH{1'b0}};
                top1_bin <= {BIN_INDEX_WIDTH{1'b0}};
                top1_power <= {POWER_WIDTH{1'b0}};
                top2_bin <= {BIN_INDEX_WIDTH{1'b0}};
                top2_power <= {POWER_WIDTH{1'b0}};
                top3_bin <= {BIN_INDEX_WIDTH{1'b0}};
                top3_power <= {POWER_WIDTH{1'b0}};
                for (i = 0; i < 4; i = i + 1) begin
                    work_valid[i] <= 1'b0;
                    work_bin[i] <= {BIN_INDEX_WIDTH{1'b0}};
                    work_power[i] <= {POWER_WIDTH{1'b0}};
                end
            end else begin
                case (state)
                    STATE_IDLE: begin
                        scan_index <= 3'd0;
                        if (accept_bin) begin
                            pending_last <= bin_last;
                            pending_allowed <= 1'b1;
                            pending_bin <= bin_index;
                            pending_power <= bin_power;
                            pending_bin_count <= running_bin_count;
                            if (start_frame) begin
                                summary_valid <= 1'b0;
                                frame_bin_count <= 32'd0;
                                for (i = 0; i < 4; i = i + 1) begin
                                    work_valid[i] <= 1'b0;
                                    work_bin[i] <= {BIN_INDEX_WIDTH{1'b0}};
                                    work_power[i] <= {POWER_WIDTH{1'b0}};
                                end
                            end
                            state <= STATE_GUARD;
                        end
                    end

                    STATE_GUARD: begin
                        if (work_valid[scan_index] &&
                            within_guard(pending_bin, work_bin[scan_index])) begin
                            if (is_better(pending_power,
                                          pending_bin,
                                          1'b1,
                                          work_power[scan_index],
                                          work_bin[scan_index])) begin
                                pending_allowed <= 1'b1;
                                case (scan_index)
                                    3'd0: begin
                                        work_valid[0] <= work_valid[1];
                                        work_bin[0] <= work_bin[1];
                                        work_power[0] <= work_power[1];
                                        work_valid[1] <= work_valid[2];
                                        work_bin[1] <= work_bin[2];
                                        work_power[1] <= work_power[2];
                                        work_valid[2] <= work_valid[3];
                                        work_bin[2] <= work_bin[3];
                                        work_power[2] <= work_power[3];
                                        work_valid[3] <= 1'b0;
                                        work_bin[3] <= {BIN_INDEX_WIDTH{1'b0}};
                                        work_power[3] <= {POWER_WIDTH{1'b0}};
                                    end
                                    3'd1: begin
                                        work_valid[1] <= work_valid[2];
                                        work_bin[1] <= work_bin[2];
                                        work_power[1] <= work_power[2];
                                        work_valid[2] <= work_valid[3];
                                        work_bin[2] <= work_bin[3];
                                        work_power[2] <= work_power[3];
                                        work_valid[3] <= 1'b0;
                                        work_bin[3] <= {BIN_INDEX_WIDTH{1'b0}};
                                        work_power[3] <= {POWER_WIDTH{1'b0}};
                                    end
                                    3'd2: begin
                                        work_valid[2] <= work_valid[3];
                                        work_bin[2] <= work_bin[3];
                                        work_power[2] <= work_power[3];
                                        work_valid[3] <= 1'b0;
                                        work_bin[3] <= {BIN_INDEX_WIDTH{1'b0}};
                                        work_power[3] <= {POWER_WIDTH{1'b0}};
                                    end
                                    default: begin
                                        work_valid[3] <= 1'b0;
                                        work_bin[3] <= {BIN_INDEX_WIDTH{1'b0}};
                                        work_power[3] <= {POWER_WIDTH{1'b0}};
                                    end
                                endcase
                                scan_index <= 3'd0;
                                state <= STATE_INSERT;
                            end else begin
                                pending_allowed <= 1'b0;
                                state <= STATE_FINISH;
                            end
                        end else if (scan_index == 3'd3) begin
                            scan_index <= 3'd0;
                            state <= STATE_INSERT;
                        end else begin
                            scan_index <= scan_index + 3'd1;
                        end
                    end

                    STATE_INSERT: begin
                        if (!pending_allowed) begin
                            state <= STATE_FINISH;
                        end else if (is_better(pending_power,
                                               pending_bin,
                                               work_valid[scan_index],
                                               work_power[scan_index],
                                               work_bin[scan_index])) begin
                            case (scan_index)
                                3'd0: begin
                                    work_valid[3] <= work_valid[2];
                                    work_bin[3] <= work_bin[2];
                                    work_power[3] <= work_power[2];
                                    work_valid[2] <= work_valid[1];
                                    work_bin[2] <= work_bin[1];
                                    work_power[2] <= work_power[1];
                                    work_valid[1] <= work_valid[0];
                                    work_bin[1] <= work_bin[0];
                                    work_power[1] <= work_power[0];
                                    work_valid[0] <= 1'b1;
                                    work_bin[0] <= pending_bin;
                                    work_power[0] <= pending_power;
                                end
                                3'd1: begin
                                    work_valid[3] <= work_valid[2];
                                    work_bin[3] <= work_bin[2];
                                    work_power[3] <= work_power[2];
                                    work_valid[2] <= work_valid[1];
                                    work_bin[2] <= work_bin[1];
                                    work_power[2] <= work_power[1];
                                    work_valid[1] <= 1'b1;
                                    work_bin[1] <= pending_bin;
                                    work_power[1] <= pending_power;
                                end
                                3'd2: begin
                                    work_valid[3] <= work_valid[2];
                                    work_bin[3] <= work_bin[2];
                                    work_power[3] <= work_power[2];
                                    work_valid[2] <= 1'b1;
                                    work_bin[2] <= pending_bin;
                                    work_power[2] <= pending_power;
                                end
                                default: begin
                                    work_valid[3] <= 1'b1;
                                    work_bin[3] <= pending_bin;
                                    work_power[3] <= pending_power;
                                end
                            endcase
                            state <= STATE_FINISH;
                        end else if (scan_index == 3'd3) begin
                            state <= STATE_FINISH;
                        end else begin
                            scan_index <= scan_index + 3'd1;
                        end
                    end

                    STATE_FINISH: begin
                        if (pending_last) begin
                            summary_valid <= 1'b1;
                            summary_bin_count <= pending_bin_count;
                            top_count <= work_count;
                            top0_bin <= work_bin[0];
                            top0_power <= work_power[0];
                            top1_bin <= work_bin[1];
                            top1_power <= work_power[1];
                            top2_bin <= work_bin[2];
                            top2_power <= work_power[2];
                            top3_bin <= work_bin[3];
                            top3_power <= work_power[3];
                            frame_active <= 1'b0;
                            frame_bin_count <= 32'd0;
                            for (i = 0; i < 4; i = i + 1) begin
                                work_valid[i] <= 1'b0;
                                work_bin[i] <= {BIN_INDEX_WIDTH{1'b0}};
                                work_power[i] <= {POWER_WIDTH{1'b0}};
                            end
                        end else begin
                            frame_active <= 1'b1;
                            frame_bin_count <= pending_bin_count;
                        end
                        pending_last <= 1'b0;
                        pending_allowed <= 1'b0;
                        scan_index <= 3'd0;
                        state <= STATE_IDLE;
                    end

                    default: begin
                        state <= STATE_IDLE;
                    end
                endcase
            end
        end
    end

endmodule

`default_nettype wire
