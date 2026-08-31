`timescale 1ns/1ps
`default_nettype none

module p201_v10s2_frame_window #(
    parameter SAMPLE_WIDTH     = 16,
    parameter COEFF_WIDTH      = 16,
    parameter FRAME_LEN        = 8,
    parameter FRAME_INDEX_BITS = 3,
    parameter DECIM_WIDTH      = 8,
    parameter COUNT_WIDTH      = 32
) (
    input  wire                          clk,
    input  wire                          rst_n,
    input  wire                          enable,
    input  wire                          clear,

    input  wire [DECIM_WIDTH-1:0]        decim_factor,
    input  wire                          window_mode,

    input  wire                          sample_valid,
    output wire                          sample_ready,
    input  wire signed [SAMPLE_WIDTH-1:0] sample_i,
    input  wire signed [SAMPLE_WIDTH-1:0] sample_q,

    output reg                           out_valid,
    input  wire                          out_ready,
    output reg                           last_out,
    output reg  signed [SAMPLE_WIDTH-1:0] out_i,
    output reg  signed [SAMPLE_WIDTH-1:0] out_q,
    output reg  [FRAME_INDEX_BITS-1:0]   frame_index,
    output reg  [COUNT_WIDTH-1:0]        frame_id,

    output reg  [COUNT_WIDTH-1:0]        raw_sample_count,
    output reg  [COUNT_WIDTH-1:0]        accepted_count,
    output reg  [COUNT_WIDTH-1:0]        dropped_count,
    output reg  [COUNT_WIDTH-1:0]        overflow_count,
    output wire [31:0]                   status_flags
);

    localparam [FRAME_INDEX_BITS-1:0] FRAME_LAST_INDEX =
        FRAME_LEN[FRAME_INDEX_BITS-1:0] - {{(FRAME_INDEX_BITS-1){1'b0}}, 1'b1};

    reg [DECIM_WIDTH-1:0] decim_count;
    reg                   overflow_seen;

    wire output_blocked;
    wire input_drop;
    wire input_fire;
    wire decim_hit;
    wire [DECIM_WIDTH-1:0] decim_limit;
    wire [COEFF_WIDTH-1:0] window_coeff;

    assign output_blocked = out_valid && !out_ready;
    assign sample_ready   = enable && !clear && !output_blocked;
    assign input_drop     = sample_valid && (!sample_ready);
    assign input_fire     = sample_valid && sample_ready;
    assign decim_limit    = (decim_factor == {DECIM_WIDTH{1'b0}}) ?
                            {{(DECIM_WIDTH-1){1'b0}}, 1'b1} :
                            decim_factor;
    assign decim_hit      = (decim_count == {DECIM_WIDTH{1'b0}});

    assign status_flags = {
        24'd0,
        overflow_seen,
        output_blocked,
        window_mode,
        last_out,
        out_valid,
        enable,
        1'b1,
        1'b1
    };

    p201_v10s2_hann8_coeff #(
        .COEFF_WIDTH(COEFF_WIDTH),
        .INDEX_WIDTH(FRAME_INDEX_BITS)
    ) u_hann8_coeff (
        .index(frame_index),
        .coeff(window_coeff)
    );

    function signed [SAMPLE_WIDTH-1:0] apply_window;
        input signed [SAMPLE_WIDTH-1:0] sample_value;
        input [COEFF_WIDTH-1:0]         coeff_value;
        reg signed [SAMPLE_WIDTH+COEFF_WIDTH:0] product;
        begin
            product = sample_value * $signed({1'b0, coeff_value});
            apply_window = product[SAMPLE_WIDTH+COEFF_WIDTH-2:COEFF_WIDTH-1];
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid        <= 1'b0;
            last_out         <= 1'b0;
            out_i            <= {SAMPLE_WIDTH{1'b0}};
            out_q            <= {SAMPLE_WIDTH{1'b0}};
            frame_index      <= {FRAME_INDEX_BITS{1'b0}};
            frame_id         <= {COUNT_WIDTH{1'b0}};
            raw_sample_count <= {COUNT_WIDTH{1'b0}};
            accepted_count   <= {COUNT_WIDTH{1'b0}};
            dropped_count    <= {COUNT_WIDTH{1'b0}};
            overflow_count   <= {COUNT_WIDTH{1'b0}};
            decim_count      <= {DECIM_WIDTH{1'b0}};
            overflow_seen    <= 1'b0;
        end else begin
            if (clear) begin
                out_valid        <= 1'b0;
                last_out         <= 1'b0;
                out_i            <= {SAMPLE_WIDTH{1'b0}};
                out_q            <= {SAMPLE_WIDTH{1'b0}};
                frame_index      <= {FRAME_INDEX_BITS{1'b0}};
                frame_id         <= {COUNT_WIDTH{1'b0}};
                raw_sample_count <= {COUNT_WIDTH{1'b0}};
                accepted_count   <= {COUNT_WIDTH{1'b0}};
                dropped_count    <= {COUNT_WIDTH{1'b0}};
                overflow_count   <= {COUNT_WIDTH{1'b0}};
                decim_count      <= {DECIM_WIDTH{1'b0}};
                overflow_seen    <= 1'b0;
            end else if (!enable) begin
                out_valid   <= 1'b0;
                last_out    <= 1'b0;
                frame_index <= {FRAME_INDEX_BITS{1'b0}};
                decim_count <= {DECIM_WIDTH{1'b0}};
            end else begin
                if (out_valid && out_ready) begin
                    out_valid <= 1'b0;
                    last_out  <= 1'b0;
                end

                if (input_drop) begin
                    dropped_count  <= dropped_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                    overflow_count <= overflow_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                    overflow_seen  <= 1'b1;
                end

                if (input_fire) begin
                    raw_sample_count <= raw_sample_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};

                    if (decim_hit) begin
                        out_valid      <= 1'b1;
                        last_out       <= (frame_index == FRAME_LAST_INDEX);
                        accepted_count <= accepted_count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};

                        if (window_mode) begin
                            out_i <= apply_window(sample_i, window_coeff);
                            out_q <= apply_window(sample_q, window_coeff);
                        end else begin
                            out_i <= sample_i;
                            out_q <= sample_q;
                        end

                        if (frame_index == FRAME_LAST_INDEX) begin
                            frame_index <= {FRAME_INDEX_BITS{1'b0}};
                            frame_id    <= frame_id + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                        end else begin
                            frame_index <= frame_index + {{(FRAME_INDEX_BITS-1){1'b0}}, 1'b1};
                        end

                        if (decim_limit <= {{(DECIM_WIDTH-1){1'b0}}, 1'b1}) begin
                            decim_count <= {DECIM_WIDTH{1'b0}};
                        end else begin
                            decim_count <= decim_limit - {{(DECIM_WIDTH-1){1'b0}}, 1'b1};
                        end
                    end else begin
                        decim_count <= decim_count - {{(DECIM_WIDTH-1){1'b0}}, 1'b1};
                    end
                end
            end
        end
    end

endmodule

`default_nettype wire
