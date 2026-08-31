`timescale 1ns/1ps
`default_nettype none

// Module: p201_v10_multilag_corr_module
// Purpose: isolated OOC candidate for fixed lag0..lag3 dual-RX complex correlation.
// Notes:
// - Inputs are signed 16-bit raw I/Q samples.
// - Correlation definition: sum rx0[n] * conj(rx1[n-lag]).
// - NX or a future register wrapper owns normalization, atan2, policy, and fallback.
module p201_v10_multilag_corr_module #(
    parameter DATA_WIDTH = 16,
    parameter ACC_WIDTH = 64,
    parameter FRAME_LEN = 64
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         enable,
    input  wire                         clear,
    input  wire                         sample_valid,
    input  wire signed [DATA_WIDTH-1:0] rx0_i,
    input  wire signed [DATA_WIDTH-1:0] rx0_q,
    input  wire signed [DATA_WIDTH-1:0] rx1_i,
    input  wire signed [DATA_WIDTH-1:0] rx1_q,
    output reg                          summary_valid,
    output reg                          summary_strobe,
    output reg [31:0]                   summary_frame_id,
    output reg [15:0]                   summary_samples,
    output reg [15:0]                   lag0_samples,
    output reg [15:0]                   lag1_samples,
    output reg [15:0]                   lag2_samples,
    output reg [15:0]                   lag3_samples,
    output reg signed [ACC_WIDTH-1:0]   lag0_corr_re,
    output reg signed [ACC_WIDTH-1:0]   lag0_corr_im,
    output reg signed [ACC_WIDTH-1:0]   lag1_corr_re,
    output reg signed [ACC_WIDTH-1:0]   lag1_corr_im,
    output reg signed [ACC_WIDTH-1:0]   lag2_corr_re,
    output reg signed [ACC_WIDTH-1:0]   lag2_corr_im,
    output reg signed [ACC_WIDTH-1:0]   lag3_corr_re,
    output reg signed [ACC_WIDTH-1:0]   lag3_corr_im,
    output reg [3:0]                    lag_valid_mask
);

    localparam MULT_WIDTH = DATA_WIDTH * 2;
    localparam PROD_SUM_WIDTH = MULT_WIDTH + 1;
    localparam FRAME_CNT_WIDTH = 16;
    localparam [FRAME_CNT_WIDTH-1:0] FRAME_LEN_VALUE = FRAME_LEN;

    reg [FRAME_CNT_WIDTH-1:0] sample_index;
    reg [31:0] frame_id_acc;

    reg signed [DATA_WIDTH-1:0] rx1_i_d0;
    reg signed [DATA_WIDTH-1:0] rx1_q_d0;
    reg signed [DATA_WIDTH-1:0] rx1_i_d1;
    reg signed [DATA_WIDTH-1:0] rx1_q_d1;
    reg signed [DATA_WIDTH-1:0] rx1_i_d2;
    reg signed [DATA_WIDTH-1:0] rx1_q_d2;

    reg signed [ACC_WIDTH-1:0] lag0_re_acc;
    reg signed [ACC_WIDTH-1:0] lag0_im_acc;
    reg signed [ACC_WIDTH-1:0] lag1_re_acc;
    reg signed [ACC_WIDTH-1:0] lag1_im_acc;
    reg signed [ACC_WIDTH-1:0] lag2_re_acc;
    reg signed [ACC_WIDTH-1:0] lag2_im_acc;
    reg signed [ACC_WIDTH-1:0] lag3_re_acc;
    reg signed [ACC_WIDTH-1:0] lag3_im_acc;

    reg product_valid_pipe;
    reg finish_frame_pipe;
    reg lag1_enable_pipe;
    reg lag2_enable_pipe;
    reg lag3_enable_pipe;

    reg signed [MULT_WIDTH-1:0] lag0_ii_pipe;
    reg signed [MULT_WIDTH-1:0] lag0_qq_pipe;
    reg signed [MULT_WIDTH-1:0] lag0_qi_pipe;
    reg signed [MULT_WIDTH-1:0] lag0_iq_pipe;
    reg signed [MULT_WIDTH-1:0] lag1_ii_pipe;
    reg signed [MULT_WIDTH-1:0] lag1_qq_pipe;
    reg signed [MULT_WIDTH-1:0] lag1_qi_pipe;
    reg signed [MULT_WIDTH-1:0] lag1_iq_pipe;
    reg signed [MULT_WIDTH-1:0] lag2_ii_pipe;
    reg signed [MULT_WIDTH-1:0] lag2_qq_pipe;
    reg signed [MULT_WIDTH-1:0] lag2_qi_pipe;
    reg signed [MULT_WIDTH-1:0] lag2_iq_pipe;
    reg signed [MULT_WIDTH-1:0] lag3_ii_pipe;
    reg signed [MULT_WIDTH-1:0] lag3_qq_pipe;
    reg signed [MULT_WIDTH-1:0] lag3_qi_pipe;
    reg signed [MULT_WIDTH-1:0] lag3_iq_pipe;

    wire frame_len_supported = (FRAME_LEN == 64) || (FRAME_LEN == 256);
    wire accept_sample = enable && sample_valid && frame_len_supported;
    wire finish_frame = accept_sample && (sample_index == (FRAME_LEN_VALUE - 16'd1));
    wire lag1_enable = accept_sample && (sample_index >= 16'd1);
    wire lag2_enable = accept_sample && (sample_index >= 16'd2);
    wire lag3_enable = accept_sample && (sample_index >= 16'd3);

    wire signed [PROD_SUM_WIDTH-1:0] lag0_re_sample =
        {lag0_ii_pipe[MULT_WIDTH-1], lag0_ii_pipe} + {lag0_qq_pipe[MULT_WIDTH-1], lag0_qq_pipe};
    wire signed [PROD_SUM_WIDTH-1:0] lag0_im_sample =
        {lag0_qi_pipe[MULT_WIDTH-1], lag0_qi_pipe} - {lag0_iq_pipe[MULT_WIDTH-1], lag0_iq_pipe};
    wire signed [PROD_SUM_WIDTH-1:0] lag1_re_sample =
        {lag1_ii_pipe[MULT_WIDTH-1], lag1_ii_pipe} + {lag1_qq_pipe[MULT_WIDTH-1], lag1_qq_pipe};
    wire signed [PROD_SUM_WIDTH-1:0] lag1_im_sample =
        {lag1_qi_pipe[MULT_WIDTH-1], lag1_qi_pipe} - {lag1_iq_pipe[MULT_WIDTH-1], lag1_iq_pipe};
    wire signed [PROD_SUM_WIDTH-1:0] lag2_re_sample =
        {lag2_ii_pipe[MULT_WIDTH-1], lag2_ii_pipe} + {lag2_qq_pipe[MULT_WIDTH-1], lag2_qq_pipe};
    wire signed [PROD_SUM_WIDTH-1:0] lag2_im_sample =
        {lag2_qi_pipe[MULT_WIDTH-1], lag2_qi_pipe} - {lag2_iq_pipe[MULT_WIDTH-1], lag2_iq_pipe};
    wire signed [PROD_SUM_WIDTH-1:0] lag3_re_sample =
        {lag3_ii_pipe[MULT_WIDTH-1], lag3_ii_pipe} + {lag3_qq_pipe[MULT_WIDTH-1], lag3_qq_pipe};
    wire signed [PROD_SUM_WIDTH-1:0] lag3_im_sample =
        {lag3_qi_pipe[MULT_WIDTH-1], lag3_qi_pipe} - {lag3_iq_pipe[MULT_WIDTH-1], lag3_iq_pipe};

    wire signed [ACC_WIDTH-1:0] lag0_re_next = lag0_re_acc + sign_extend_product(lag0_re_sample);
    wire signed [ACC_WIDTH-1:0] lag0_im_next = lag0_im_acc + sign_extend_product(lag0_im_sample);
    wire signed [ACC_WIDTH-1:0] lag1_re_next =
        lag1_enable_pipe ? (lag1_re_acc + sign_extend_product(lag1_re_sample)) : lag1_re_acc;
    wire signed [ACC_WIDTH-1:0] lag1_im_next =
        lag1_enable_pipe ? (lag1_im_acc + sign_extend_product(lag1_im_sample)) : lag1_im_acc;
    wire signed [ACC_WIDTH-1:0] lag2_re_next =
        lag2_enable_pipe ? (lag2_re_acc + sign_extend_product(lag2_re_sample)) : lag2_re_acc;
    wire signed [ACC_WIDTH-1:0] lag2_im_next =
        lag2_enable_pipe ? (lag2_im_acc + sign_extend_product(lag2_im_sample)) : lag2_im_acc;
    wire signed [ACC_WIDTH-1:0] lag3_re_next =
        lag3_enable_pipe ? (lag3_re_acc + sign_extend_product(lag3_re_sample)) : lag3_re_acc;
    wire signed [ACC_WIDTH-1:0] lag3_im_next =
        lag3_enable_pipe ? (lag3_im_acc + sign_extend_product(lag3_im_sample)) : lag3_im_acc;

    function signed [ACC_WIDTH-1:0] sign_extend_product;
        input signed [PROD_SUM_WIDTH-1:0] value;
        begin
            sign_extend_product = {{(ACC_WIDTH-PROD_SUM_WIDTH){value[PROD_SUM_WIDTH-1]}}, value};
        end
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            sample_index <= 16'd0;
            frame_id_acc <= 32'd0;
            rx1_i_d0 <= {DATA_WIDTH{1'b0}};
            rx1_q_d0 <= {DATA_WIDTH{1'b0}};
            rx1_i_d1 <= {DATA_WIDTH{1'b0}};
            rx1_q_d1 <= {DATA_WIDTH{1'b0}};
            rx1_i_d2 <= {DATA_WIDTH{1'b0}};
            rx1_q_d2 <= {DATA_WIDTH{1'b0}};
            lag0_re_acc <= {ACC_WIDTH{1'b0}};
            lag0_im_acc <= {ACC_WIDTH{1'b0}};
            lag1_re_acc <= {ACC_WIDTH{1'b0}};
            lag1_im_acc <= {ACC_WIDTH{1'b0}};
            lag2_re_acc <= {ACC_WIDTH{1'b0}};
            lag2_im_acc <= {ACC_WIDTH{1'b0}};
            lag3_re_acc <= {ACC_WIDTH{1'b0}};
            lag3_im_acc <= {ACC_WIDTH{1'b0}};
            product_valid_pipe <= 1'b0;
            finish_frame_pipe <= 1'b0;
            lag1_enable_pipe <= 1'b0;
            lag2_enable_pipe <= 1'b0;
            lag3_enable_pipe <= 1'b0;
            lag0_ii_pipe <= {MULT_WIDTH{1'b0}};
            lag0_qq_pipe <= {MULT_WIDTH{1'b0}};
            lag0_qi_pipe <= {MULT_WIDTH{1'b0}};
            lag0_iq_pipe <= {MULT_WIDTH{1'b0}};
            lag1_ii_pipe <= {MULT_WIDTH{1'b0}};
            lag1_qq_pipe <= {MULT_WIDTH{1'b0}};
            lag1_qi_pipe <= {MULT_WIDTH{1'b0}};
            lag1_iq_pipe <= {MULT_WIDTH{1'b0}};
            lag2_ii_pipe <= {MULT_WIDTH{1'b0}};
            lag2_qq_pipe <= {MULT_WIDTH{1'b0}};
            lag2_qi_pipe <= {MULT_WIDTH{1'b0}};
            lag2_iq_pipe <= {MULT_WIDTH{1'b0}};
            lag3_ii_pipe <= {MULT_WIDTH{1'b0}};
            lag3_qq_pipe <= {MULT_WIDTH{1'b0}};
            lag3_qi_pipe <= {MULT_WIDTH{1'b0}};
            lag3_iq_pipe <= {MULT_WIDTH{1'b0}};
            summary_valid <= 1'b0;
            summary_strobe <= 1'b0;
            summary_frame_id <= 32'd0;
            summary_samples <= 16'd0;
            lag0_samples <= 16'd0;
            lag1_samples <= 16'd0;
            lag2_samples <= 16'd0;
            lag3_samples <= 16'd0;
            lag0_corr_re <= {ACC_WIDTH{1'b0}};
            lag0_corr_im <= {ACC_WIDTH{1'b0}};
            lag1_corr_re <= {ACC_WIDTH{1'b0}};
            lag1_corr_im <= {ACC_WIDTH{1'b0}};
            lag2_corr_re <= {ACC_WIDTH{1'b0}};
            lag2_corr_im <= {ACC_WIDTH{1'b0}};
            lag3_corr_re <= {ACC_WIDTH{1'b0}};
            lag3_corr_im <= {ACC_WIDTH{1'b0}};
            lag_valid_mask <= 4'b0000;
        end else begin
            summary_strobe <= 1'b0;

            if (clear || !enable) begin
                sample_index <= 16'd0;
                rx1_i_d0 <= {DATA_WIDTH{1'b0}};
                rx1_q_d0 <= {DATA_WIDTH{1'b0}};
                rx1_i_d1 <= {DATA_WIDTH{1'b0}};
                rx1_q_d1 <= {DATA_WIDTH{1'b0}};
                rx1_i_d2 <= {DATA_WIDTH{1'b0}};
                rx1_q_d2 <= {DATA_WIDTH{1'b0}};
                lag0_re_acc <= {ACC_WIDTH{1'b0}};
                lag0_im_acc <= {ACC_WIDTH{1'b0}};
                lag1_re_acc <= {ACC_WIDTH{1'b0}};
                lag1_im_acc <= {ACC_WIDTH{1'b0}};
                lag2_re_acc <= {ACC_WIDTH{1'b0}};
                lag2_im_acc <= {ACC_WIDTH{1'b0}};
                lag3_re_acc <= {ACC_WIDTH{1'b0}};
                lag3_im_acc <= {ACC_WIDTH{1'b0}};
                product_valid_pipe <= 1'b0;
                finish_frame_pipe <= 1'b0;
                lag1_enable_pipe <= 1'b0;
                lag2_enable_pipe <= 1'b0;
                lag3_enable_pipe <= 1'b0;
                summary_valid <= 1'b0;
                summary_frame_id <= 32'd0;
                summary_samples <= 16'd0;
                lag0_samples <= 16'd0;
                lag1_samples <= 16'd0;
                lag2_samples <= 16'd0;
                lag3_samples <= 16'd0;
                lag0_corr_re <= {ACC_WIDTH{1'b0}};
                lag0_corr_im <= {ACC_WIDTH{1'b0}};
                lag1_corr_re <= {ACC_WIDTH{1'b0}};
                lag1_corr_im <= {ACC_WIDTH{1'b0}};
                lag2_corr_re <= {ACC_WIDTH{1'b0}};
                lag2_corr_im <= {ACC_WIDTH{1'b0}};
                lag3_corr_re <= {ACC_WIDTH{1'b0}};
                lag3_corr_im <= {ACC_WIDTH{1'b0}};
                lag_valid_mask <= 4'b0000;
            end else begin
                if (accept_sample) begin
                    product_valid_pipe <= 1'b1;
                    finish_frame_pipe <= finish_frame;
                    lag1_enable_pipe <= lag1_enable;
                    lag2_enable_pipe <= lag2_enable;
                    lag3_enable_pipe <= lag3_enable;
                    lag0_ii_pipe <= rx0_i * rx1_i;
                    lag0_qq_pipe <= rx0_q * rx1_q;
                    lag0_qi_pipe <= rx0_q * rx1_i;
                    lag0_iq_pipe <= rx0_i * rx1_q;
                    lag1_ii_pipe <= rx0_i * rx1_i_d0;
                    lag1_qq_pipe <= rx0_q * rx1_q_d0;
                    lag1_qi_pipe <= rx0_q * rx1_i_d0;
                    lag1_iq_pipe <= rx0_i * rx1_q_d0;
                    lag2_ii_pipe <= rx0_i * rx1_i_d1;
                    lag2_qq_pipe <= rx0_q * rx1_q_d1;
                    lag2_qi_pipe <= rx0_q * rx1_i_d1;
                    lag2_iq_pipe <= rx0_i * rx1_q_d1;
                    lag3_ii_pipe <= rx0_i * rx1_i_d2;
                    lag3_qq_pipe <= rx0_q * rx1_q_d2;
                    lag3_qi_pipe <= rx0_q * rx1_i_d2;
                    lag3_iq_pipe <= rx0_i * rx1_q_d2;
                    rx1_i_d0 <= rx1_i;
                    rx1_q_d0 <= rx1_q;
                    rx1_i_d1 <= rx1_i_d0;
                    rx1_q_d1 <= rx1_q_d0;
                    rx1_i_d2 <= rx1_i_d1;
                    rx1_q_d2 <= rx1_q_d1;

                    if (finish_frame) begin
                        sample_index <= 16'd0;
                    end else begin
                        sample_index <= sample_index + 16'd1;
                    end
                end else begin
                    product_valid_pipe <= 1'b0;
                    finish_frame_pipe <= 1'b0;
                    lag1_enable_pipe <= 1'b0;
                    lag2_enable_pipe <= 1'b0;
                    lag3_enable_pipe <= 1'b0;
                end

                if (product_valid_pipe) begin
                    if (finish_frame_pipe) begin
                        summary_valid <= 1'b1;
                        summary_strobe <= 1'b1;
                        summary_frame_id <= frame_id_acc + 32'd1;
                        summary_samples <= FRAME_LEN_VALUE;
                        lag0_samples <= FRAME_LEN_VALUE;
                        lag1_samples <= FRAME_LEN_VALUE - 16'd1;
                        lag2_samples <= FRAME_LEN_VALUE - 16'd2;
                        lag3_samples <= FRAME_LEN_VALUE - 16'd3;
                        lag0_corr_re <= lag0_re_next;
                        lag0_corr_im <= lag0_im_next;
                        lag1_corr_re <= lag1_re_next;
                        lag1_corr_im <= lag1_im_next;
                        lag2_corr_re <= lag2_re_next;
                        lag2_corr_im <= lag2_im_next;
                        lag3_corr_re <= lag3_re_next;
                        lag3_corr_im <= lag3_im_next;
                        lag_valid_mask <= 4'b1111;
                        lag0_re_acc <= {ACC_WIDTH{1'b0}};
                        lag0_im_acc <= {ACC_WIDTH{1'b0}};
                        lag1_re_acc <= {ACC_WIDTH{1'b0}};
                        lag1_im_acc <= {ACC_WIDTH{1'b0}};
                        lag2_re_acc <= {ACC_WIDTH{1'b0}};
                        lag2_im_acc <= {ACC_WIDTH{1'b0}};
                        lag3_re_acc <= {ACC_WIDTH{1'b0}};
                        lag3_im_acc <= {ACC_WIDTH{1'b0}};
                        frame_id_acc <= frame_id_acc + 32'd1;
                    end else begin
                        lag0_re_acc <= lag0_re_next;
                        lag0_im_acc <= lag0_im_next;
                        lag1_re_acc <= lag1_re_next;
                        lag1_im_acc <= lag1_im_next;
                        lag2_re_acc <= lag2_re_next;
                        lag2_im_acc <= lag2_im_next;
                        lag3_re_acc <= lag3_re_next;
                        lag3_im_acc <= lag3_im_next;
                    end
                end
            end
        end
    end

endmodule

`default_nettype wire
