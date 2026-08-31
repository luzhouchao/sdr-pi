`timescale 1ns / 1ps
`default_nettype none

module p201_v10_fft_bin_power #(
    parameter FFT_WIDTH   = 16,
    parameter NFFT_LOG2   = 8,
    parameter POWER_WIDTH = 48
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         enable,

    input  wire                         fft_valid,
    output wire                         fft_ready,
    input  wire                         fft_last,
    input  wire [NFFT_LOG2-1:0]         fft_index,
    input  wire signed [FFT_WIDTH-1:0]  fft_real,
    input  wire signed [FFT_WIDTH-1:0]  fft_imag,

    output wire                         bin_valid,
    input  wire                         bin_ready,
    output wire                         bin_last,
    output wire [NFFT_LOG2-1:0]         bin_index,
    output wire [POWER_WIDTH-1:0]       bin_power,
    output wire                         bin_power_overflow
);

    localparam integer SQUARE_WIDTH = FFT_WIDTH * 2;
    localparam integer POWER_SUM_WIDTH = SQUARE_WIDTH + 1;

    reg                         stage1_valid;
    reg                         stage1_last;
    reg [NFFT_LOG2-1:0]         stage1_index;
    reg [SQUARE_WIDTH-1:0]      stage1_real_sq;
    reg [SQUARE_WIDTH-1:0]      stage1_imag_sq;

    reg                         stage2_valid;
    reg                         stage2_last;
    reg [NFFT_LOG2-1:0]         stage2_index;
    reg [POWER_WIDTH-1:0]       stage2_power;
    reg                         stage2_overflow;

    wire                        advance_pipe;
    wire                        accept_fft;
    wire [SQUARE_WIDTH-1:0]     real_square_next;
    wire [SQUARE_WIDTH-1:0]     imag_square_next;
    wire [POWER_SUM_WIDTH-1:0]  power_sum_next;
    wire [POWER_WIDTH-1:0]      power_saturated_next;
    wire                        power_overflow_next;

    assign advance_pipe = !stage2_valid || bin_ready;
    assign fft_ready = enable && advance_pipe;
    assign accept_fft = fft_valid && fft_ready;

    assign real_square_next = fft_real * fft_real;
    assign imag_square_next = fft_imag * fft_imag;
    assign power_sum_next = {1'b0, stage1_real_sq} + {1'b0, stage1_imag_sq};

    generate
        if (POWER_WIDTH >= POWER_SUM_WIDTH) begin : gen_power_wide
            assign power_saturated_next =
                {{(POWER_WIDTH - POWER_SUM_WIDTH){1'b0}}, power_sum_next};
            assign power_overflow_next = 1'b0;
        end else begin : gen_power_narrow
            assign power_saturated_next = power_overflow_next ?
                                          {POWER_WIDTH{1'b1}} :
                                          power_sum_next[POWER_WIDTH-1:0];
            assign power_overflow_next =
                |power_sum_next[POWER_SUM_WIDTH-1:POWER_WIDTH];
        end
    endgenerate

    assign bin_valid = stage2_valid;
    assign bin_last = stage2_last;
    assign bin_index = stage2_index;
    assign bin_power = stage2_power;
    assign bin_power_overflow = stage2_valid && stage2_overflow;

    always @(posedge clk) begin
        if (!rst_n) begin
            stage1_valid    <= 1'b0;
            stage1_last     <= 1'b0;
            stage1_index    <= {NFFT_LOG2{1'b0}};
            stage1_real_sq  <= {SQUARE_WIDTH{1'b0}};
            stage1_imag_sq  <= {SQUARE_WIDTH{1'b0}};
            stage2_valid    <= 1'b0;
            stage2_last     <= 1'b0;
            stage2_index    <= {NFFT_LOG2{1'b0}};
            stage2_power    <= {POWER_WIDTH{1'b0}};
            stage2_overflow <= 1'b0;
        end else begin
            if (!enable) begin
                stage1_valid    <= 1'b0;
                stage2_valid    <= 1'b0;
                stage2_overflow <= 1'b0;
            end else if (advance_pipe) begin
                stage2_valid    <= stage1_valid;
                stage2_last     <= stage1_last;
                stage2_index    <= stage1_index;
                stage2_power    <= power_saturated_next;
                stage2_overflow <= power_overflow_next;

                stage1_valid   <= accept_fft;
                stage1_last    <= accept_fft ? fft_last : 1'b0;
                stage1_index   <= accept_fft ? fft_index : {NFFT_LOG2{1'b0}};
                stage1_real_sq <= accept_fft ? real_square_next :
                                  {SQUARE_WIDTH{1'b0}};
                stage1_imag_sq <= accept_fft ? imag_square_next :
                                  {SQUARE_WIDTH{1'b0}};
            end
        end
    end

endmodule

`default_nettype wire
