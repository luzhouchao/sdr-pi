`timescale 1ns/1ps
`default_nettype none

module p201_fft_shadow_fft4_smoke_core #(
    parameter integer SAMPLE_WIDTH = 16,
    parameter integer FFT_WIDTH = 20,
    parameter integer POWER_WIDTH = 48
) (
    input  wire                              clk,
    input  wire                              rst_n,
    input  wire                              enable,
    input  wire                              clear,

    input  wire                              sample_valid,
    output wire                              sample_ready,
    input  wire                              sample_last,
    input  wire signed [SAMPLE_WIDTH-1:0]    sample_i,
    input  wire signed [SAMPLE_WIDTH-1:0]    sample_q,

    output reg                               summary_valid,
    output reg  [31:0]                       sample_count,
    output reg  [31:0]                       nfft,
    output reg  [31:0]                       peak_bin,
    output reg  [POWER_WIDTH-1:0]            peak_power,
    output reg  [POWER_WIDTH-1:0]            total_power,
    output reg  [POWER_WIDTH-1:0]            bin0_power,
    output reg  [POWER_WIDTH-1:0]            bin1_power,
    output reg  [POWER_WIDTH-1:0]            bin2_power,
    output reg  [POWER_WIDTH-1:0]            bin3_power,
    output wire [31:0]                       status_flags
);

    localparam [2:0] STATE_IDLE       = 3'd0;
    localparam [2:0] STATE_LOAD       = 3'd1;
    localparam [2:0] STATE_FFT        = 3'd2;
    localparam [2:0] STATE_POWER_MUL  = 3'd3;
    localparam [2:0] STATE_POWER_SUM  = 3'd4;
    localparam [2:0] STATE_POWER_PEAK = 3'd5;
    localparam [2:0] STATE_DONE       = 3'd6;

    reg [2:0]                           state;
    reg [2:0]                           load_index;
    reg                                 early_last_seen;
    reg                                 missing_last_seen;
    reg signed [SAMPLE_WIDTH-1:0]       x_i [0:3];
    reg signed [SAMPLE_WIDTH-1:0]       x_q [0:3];
    reg signed [FFT_WIDTH-1:0]          fft_i [0:3];
    reg signed [FFT_WIDTH-1:0]          fft_q [0:3];
    reg [(FFT_WIDTH*2)-1:0]             fft_i_sq [0:3];
    reg [(FFT_WIDTH*2)-1:0]             fft_q_sq [0:3];

    integer                             i;

    wire                                accept_sample;
    wire signed [FFT_WIDTH-1:0]         x0_i;
    wire signed [FFT_WIDTH-1:0]         x0_q;
    wire signed [FFT_WIDTH-1:0]         x1_i;
    wire signed [FFT_WIDTH-1:0]         x1_q;
    wire signed [FFT_WIDTH-1:0]         x2_i;
    wire signed [FFT_WIDTH-1:0]         x2_q;
    wire signed [FFT_WIDTH-1:0]         x3_i;
    wire signed [FFT_WIDTH-1:0]         x3_q;

    wire signed [FFT_WIDTH-1:0]         y0_i;
    wire signed [FFT_WIDTH-1:0]         y0_q;
    wire signed [FFT_WIDTH-1:0]         y1_i;
    wire signed [FFT_WIDTH-1:0]         y1_q;
    wire signed [FFT_WIDTH-1:0]         y2_i;
    wire signed [FFT_WIDTH-1:0]         y2_q;
    wire signed [FFT_WIDTH-1:0]         y3_i;
    wire signed [FFT_WIDTH-1:0]         y3_q;

    wire [POWER_WIDTH-1:0]              p0;
    wire [POWER_WIDTH-1:0]              p1;
    wire [POWER_WIDTH-1:0]              p2;
    wire [POWER_WIDTH-1:0]              p3;
    wire [(FFT_WIDTH*2):0]              p0_raw;
    wire [(FFT_WIDTH*2):0]              p1_raw;
    wire [(FFT_WIDTH*2):0]              p2_raw;
    wire [(FFT_WIDTH*2):0]              p3_raw;
    wire [POWER_WIDTH-1:0]              sum01;
    wire [POWER_WIDTH-1:0]              sum23;
    wire [31:0]                         computed_peak_bin;
    wire [POWER_WIDTH-1:0]              computed_peak_power;

    assign sample_ready = enable && !clear && (state == STATE_IDLE || state == STATE_LOAD);
    assign accept_sample = sample_valid && sample_ready;

    assign x0_i = {{(FFT_WIDTH-SAMPLE_WIDTH){x_i[0][SAMPLE_WIDTH-1]}}, x_i[0]};
    assign x0_q = {{(FFT_WIDTH-SAMPLE_WIDTH){x_q[0][SAMPLE_WIDTH-1]}}, x_q[0]};
    assign x1_i = {{(FFT_WIDTH-SAMPLE_WIDTH){x_i[1][SAMPLE_WIDTH-1]}}, x_i[1]};
    assign x1_q = {{(FFT_WIDTH-SAMPLE_WIDTH){x_q[1][SAMPLE_WIDTH-1]}}, x_q[1]};
    assign x2_i = {{(FFT_WIDTH-SAMPLE_WIDTH){x_i[2][SAMPLE_WIDTH-1]}}, x_i[2]};
    assign x2_q = {{(FFT_WIDTH-SAMPLE_WIDTH){x_q[2][SAMPLE_WIDTH-1]}}, x_q[2]};
    assign x3_i = {{(FFT_WIDTH-SAMPLE_WIDTH){x_i[3][SAMPLE_WIDTH-1]}}, x_i[3]};
    assign x3_q = {{(FFT_WIDTH-SAMPLE_WIDTH){x_q[3][SAMPLE_WIDTH-1]}}, x_q[3]};

    assign y0_i = x0_i + x1_i + x2_i + x3_i;
    assign y0_q = x0_q + x1_q + x2_q + x3_q;
    assign y1_i = x0_i + x1_q - x2_i - x3_q;
    assign y1_q = x0_q - x1_i - x2_q + x3_i;
    assign y2_i = x0_i - x1_i + x2_i - x3_i;
    assign y2_q = x0_q - x1_q + x2_q - x3_q;
    assign y3_i = x0_i - x1_q - x2_i + x3_q;
    assign y3_q = x0_q + x1_i - x2_q - x3_i;

    assign p0_raw = {1'b0, fft_i_sq[0]} + {1'b0, fft_q_sq[0]};
    assign p1_raw = {1'b0, fft_i_sq[1]} + {1'b0, fft_q_sq[1]};
    assign p2_raw = {1'b0, fft_i_sq[2]} + {1'b0, fft_q_sq[2]};
    assign p3_raw = {1'b0, fft_i_sq[3]} + {1'b0, fft_q_sq[3]};
    assign p0 = {{(POWER_WIDTH-(FFT_WIDTH*2+1)){1'b0}}, p0_raw};
    assign p1 = {{(POWER_WIDTH-(FFT_WIDTH*2+1)){1'b0}}, p1_raw};
    assign p2 = {{(POWER_WIDTH-(FFT_WIDTH*2+1)){1'b0}}, p2_raw};
    assign p3 = {{(POWER_WIDTH-(FFT_WIDTH*2+1)){1'b0}}, p3_raw};
    assign sum01 = bin0_power + bin1_power;
    assign sum23 = bin2_power + bin3_power;

    assign computed_peak_power =
        (bin1_power > bin0_power && bin1_power >= bin2_power && bin1_power >= bin3_power) ? bin1_power :
        (bin2_power > bin0_power && bin2_power > bin1_power && bin2_power >= bin3_power) ? bin2_power :
        (bin3_power > bin0_power && bin3_power > bin1_power && bin3_power > bin2_power) ? bin3_power :
        bin0_power;

    assign computed_peak_bin =
        (computed_peak_power == bin1_power && bin1_power > bin0_power) ? 32'd1 :
        (computed_peak_power == bin2_power && bin2_power > bin0_power && bin2_power > bin1_power) ? 32'd2 :
        (computed_peak_power == bin3_power && bin3_power > bin0_power && bin3_power > bin1_power && bin3_power > bin2_power) ? 32'd3 :
        32'd0;

    assign status_flags = {
        24'd0,
        missing_last_seen,
        early_last_seen,
        sample_ready,
        summary_valid,
        state,
        enable
    };

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= STATE_IDLE;
            load_index <= 3'd0;
            early_last_seen <= 1'b0;
            missing_last_seen <= 1'b0;
            summary_valid <= 1'b0;
            sample_count <= 32'd0;
            nfft <= 32'd4;
            peak_bin <= 32'd0;
            peak_power <= {POWER_WIDTH{1'b0}};
            total_power <= {POWER_WIDTH{1'b0}};
            bin0_power <= {POWER_WIDTH{1'b0}};
            bin1_power <= {POWER_WIDTH{1'b0}};
            bin2_power <= {POWER_WIDTH{1'b0}};
            bin3_power <= {POWER_WIDTH{1'b0}};
            for (i = 0; i < 4; i = i + 1) begin
                x_i[i] <= {SAMPLE_WIDTH{1'b0}};
                x_q[i] <= {SAMPLE_WIDTH{1'b0}};
                fft_i[i] <= {FFT_WIDTH{1'b0}};
                fft_q[i] <= {FFT_WIDTH{1'b0}};
                fft_i_sq[i] <= {(FFT_WIDTH*2){1'b0}};
                fft_q_sq[i] <= {(FFT_WIDTH*2){1'b0}};
            end
        end else begin
            if (clear || !enable) begin
                state <= STATE_IDLE;
                load_index <= 3'd0;
                early_last_seen <= 1'b0;
                missing_last_seen <= 1'b0;
                summary_valid <= 1'b0;
                sample_count <= 32'd0;
                peak_bin <= 32'd0;
                peak_power <= {POWER_WIDTH{1'b0}};
                total_power <= {POWER_WIDTH{1'b0}};
                bin0_power <= {POWER_WIDTH{1'b0}};
                bin1_power <= {POWER_WIDTH{1'b0}};
                bin2_power <= {POWER_WIDTH{1'b0}};
                bin3_power <= {POWER_WIDTH{1'b0}};
            end else begin
                case (state)
                    STATE_IDLE: begin
                        load_index <= 3'd0;
                        if (accept_sample) begin
                            summary_valid <= 1'b0;
                            early_last_seen <= sample_last;
                            missing_last_seen <= 1'b0;
                            x_i[0] <= sample_i;
                            x_q[0] <= sample_q;
                            sample_count <= 32'd1;
                            load_index <= 3'd1;
                            state <= STATE_LOAD;
                        end
                    end

                    STATE_LOAD: begin
                        if (accept_sample) begin
                            x_i[load_index] <= sample_i;
                            x_q[load_index] <= sample_q;
                            sample_count <= {29'd0, load_index} + 32'd1;
                            if (sample_last && load_index != 3'd3) begin
                                early_last_seen <= 1'b1;
                            end
                            if (load_index == 3'd3) begin
                                if (!sample_last) begin
                                    missing_last_seen <= 1'b1;
                                end
                                load_index <= 3'd0;
                                state <= STATE_FFT;
                            end else begin
                                load_index <= load_index + 3'd1;
                            end
                        end
                    end

                    STATE_FFT: begin
                        fft_i[0] <= y0_i;
                        fft_q[0] <= y0_q;
                        fft_i[1] <= y1_i;
                        fft_q[1] <= y1_q;
                        fft_i[2] <= y2_i;
                        fft_q[2] <= y2_q;
                        fft_i[3] <= y3_i;
                        fft_q[3] <= y3_q;
                        state <= STATE_POWER_MUL;
                    end

                    STATE_POWER_MUL: begin
                        fft_i_sq[0] <= fft_i[0] * fft_i[0];
                        fft_q_sq[0] <= fft_q[0] * fft_q[0];
                        fft_i_sq[1] <= fft_i[1] * fft_i[1];
                        fft_q_sq[1] <= fft_q[1] * fft_q[1];
                        fft_i_sq[2] <= fft_i[2] * fft_i[2];
                        fft_q_sq[2] <= fft_q[2] * fft_q[2];
                        fft_i_sq[3] <= fft_i[3] * fft_i[3];
                        fft_q_sq[3] <= fft_q[3] * fft_q[3];
                        state <= STATE_POWER_SUM;
                    end

                    STATE_POWER_SUM: begin
                        bin0_power <= p0;
                        bin1_power <= p1;
                        bin2_power <= p2;
                        bin3_power <= p3;
                        state <= STATE_POWER_PEAK;
                    end

                    STATE_POWER_PEAK: begin
                        total_power <= sum01 + sum23;
                        peak_power <= computed_peak_power;
                        peak_bin <= computed_peak_bin;
                        state <= STATE_DONE;
                    end

                    STATE_DONE: begin
                        summary_valid <= 1'b1;
                        sample_count <= 32'd4;
                        nfft <= 32'd4;
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
