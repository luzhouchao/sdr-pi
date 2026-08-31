`timescale 1ns / 1ps

module p201pro_ad9361_power_tap_axi_regs #
(
    parameter integer AXIL_ADDR_WIDTH = 8,
    parameter integer DEFAULT_FRAME_LEN = 64
)
(
    input  wire                         adc_clk,
    input  wire                         adc_rst,
    input  wire signed [15:0]           adc_i,
    input  wire signed [15:0]           adc_q,
    input  wire signed [15:0]           adc_i1,
    input  wire signed [15:0]           adc_q1,
    input  wire                         adc_valid,
    input  wire                         adc_valid1,

    input  wire                         s_axi_aclk,
    input  wire                         s_axi_aresetn,
    input  wire [AXIL_ADDR_WIDTH-1:0]   s_axi_awaddr,
    input  wire                         s_axi_awvalid,
    output reg                          s_axi_awready,
    input  wire [31:0]                  s_axi_wdata,
    input  wire [3:0]                   s_axi_wstrb,
    input  wire                         s_axi_wvalid,
    output reg                          s_axi_wready,
    output reg  [1:0]                   s_axi_bresp,
    output reg                          s_axi_bvalid,
    input  wire                         s_axi_bready,
    input  wire [AXIL_ADDR_WIDTH-1:0]   s_axi_araddr,
    input  wire                         s_axi_arvalid,
    output reg                          s_axi_arready,
    output reg  [31:0]                  s_axi_rdata,
    output reg  [1:0]                   s_axi_rresp,
    output reg                          s_axi_rvalid,
    input  wire                         s_axi_rready,

    output wire                         summary_valid,
    output wire                         irq
);

    localparam [7:0] REG_CONTROL          = 8'h00;
    localparam [7:0] REG_FRAME_LEN        = 8'h04;
    localparam [7:0] REG_STATUS           = 8'h08;
    localparam [7:0] REG_SAMPLE_COUNT     = 8'h0c;
    localparam [7:0] REG_PEAK_POWER_LO    = 8'h10;
    localparam [7:0] REG_PEAK_POWER_HI    = 8'h14;
    localparam [7:0] REG_PEAK_INDEX       = 8'h18;
    localparam [7:0] REG_SUM_POWER_LO     = 8'h1c;
    localparam [7:0] REG_SUM_POWER_HI     = 8'h20;
    localparam [7:0] REG_FRAME_COUNT      = 8'h24;
    localparam [7:0] REG_LAST_POWER_LO    = 8'h28;
    localparam [7:0] REG_LAST_POWER_HI    = 8'h2c;
    localparam [7:0] REG_DEBUG_FLAGS      = 8'h30;
    localparam [7:0] REG_DEBUG_CLK        = 8'h34;
    localparam [7:0] REG_DEBUG_VALID      = 8'h38;
    localparam [7:0] REG_DEBUG_ACCEPT     = 8'h3c;
    localparam [7:0] REG_SUMMARY_VERSION  = 8'h40;
    localparam [7:0] REG_SUMMARY_FLAGS    = 8'h44;
    localparam [7:0] REG_SUMMARY_FRAME    = 8'h48;
    localparam [7:0] REG_SUMMARY_SAMPLES  = 8'h4c;
    localparam [7:0] REG_SUMMARY_SUM_LO   = 8'h50;
    localparam [7:0] REG_SUMMARY_SUM_HI   = 8'h54;
    localparam [7:0] REG_SUMMARY_PEAK     = 8'h58;
    localparam [7:0] REG_SUMMARY_PEAK_IDX = 8'h5c;
    localparam [7:0] REG_SNAPSHOT_COUNT   = 8'h60;
    localparam [7:0] REG_SNAPSHOT_INDEX   = 8'h64;
    localparam [7:0] REG_SNAPSHOT_DATA    = 8'h68;
    localparam [7:0] REG_SNAPSHOT1_DATA   = 8'h6c;
    localparam [7:0] REG_DUAL_SAMPLES     = 8'h70;
    localparam [7:0] REG_RX0_POWER_LO     = 8'h74;
    localparam [7:0] REG_RX0_POWER_HI     = 8'h78;
    localparam [7:0] REG_RX1_POWER_LO     = 8'h7c;
    localparam [7:0] REG_RX1_POWER_HI     = 8'h80;
    localparam [7:0] REG_CROSS_RE_LO      = 8'h84;
    localparam [7:0] REG_CROSS_RE_HI      = 8'h88;
    localparam [7:0] REG_CROSS_IM_LO      = 8'h8c;
    localparam [7:0] REG_CROSS_IM_HI      = 8'h90;
    localparam [7:0] REG_RX1_PEAK_POWER   = 8'h94;
    localparam [7:0] REG_RX1_PEAK_IDX     = 8'h98;
    localparam [7:0] REG_I0_SUM_LO        = 8'h9c;
    localparam [7:0] REG_I0_SUM_HI        = 8'ha0;
    localparam [7:0] REG_Q0_SUM_LO        = 8'ha4;
    localparam [7:0] REG_Q0_SUM_HI        = 8'ha8;
    localparam [7:0] REG_I1_SUM_LO        = 8'hac;
    localparam [7:0] REG_I1_SUM_HI        = 8'hb0;
    localparam [7:0] REG_Q1_SUM_LO        = 8'hb4;
    localparam [7:0] REG_Q1_SUM_HI        = 8'hb8;
    localparam [7:0] REG_RX0_CORR_PWR_LO  = 8'hbc;
    localparam [7:0] REG_RX0_CORR_PWR_MID = 8'hc0;
    localparam [7:0] REG_RX0_CORR_PWR_HI  = 8'hc4;
    localparam [7:0] REG_RX1_CORR_PWR_LO  = 8'hc8;
    localparam [7:0] REG_RX1_CORR_PWR_MID = 8'hcc;
    localparam [7:0] REG_RX1_CORR_PWR_HI  = 8'hd0;
    localparam [7:0] REG_CORR_CROSS_RE_LO = 8'hd4;
    localparam [7:0] REG_CORR_CROSS_RE_MID= 8'hd8;
    localparam [7:0] REG_CORR_CROSS_RE_HI = 8'hdc;
    localparam [7:0] REG_CORR_CROSS_IM_LO = 8'he0;
    localparam [7:0] REG_CORR_CROSS_IM_MID= 8'he4;
    localparam [7:0] REG_CORR_CROSS_IM_HI = 8'he8;

    reg        enable_axi;
    reg [15:0] frame_len_axi;
    reg [31:0] control_shadow_axi;
    reg [31:0] frame_len_shadow_axi;
    reg        clear_toggle_axi;
    (* ASYNC_REG = "TRUE" *) reg        pending_meta_axi;
    (* ASYNC_REG = "TRUE" *) reg        pending_sync_axi;
    reg        pending_sync_axi_d;
    (* ASYNC_REG = "TRUE" *) reg        adc_rst_meta_axi;
    (* ASYNC_REG = "TRUE" *) reg        adc_rst_sync_axi;
    (* ASYNC_REG = "TRUE" *) reg        enable_adc_meta_axi;
    (* ASYNC_REG = "TRUE" *) reg        enable_adc_sync_axi;
    (* ASYNC_REG = "TRUE" *) reg        heartbeat_meta_axi;
    (* ASYNC_REG = "TRUE" *) reg        heartbeat_sync_axi;
    reg        heartbeat_sync_axi_d;
    (* ASYNC_REG = "TRUE" *) reg        valid_meta_axi;
    (* ASYNC_REG = "TRUE" *) reg        valid_sync_axi;
    reg        valid_sync_axi_d;
    (* ASYNC_REG = "TRUE" *) reg        accept_meta_axi;
    (* ASYNC_REG = "TRUE" *) reg        accept_sync_axi;
    reg        accept_sync_axi_d;
    reg [31:0] debug_clk_count_axi;
    reg [31:0] debug_valid_count_axi;
    reg [31:0] debug_accept_count_axi;

    (* ASYNC_REG = "TRUE" *) reg        enable_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg        enable_sync_adc;
    (* ASYNC_REG = "TRUE" *) reg [15:0] frame_len_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg [15:0] frame_len_sync_adc;
    (* ASYNC_REG = "TRUE" *) reg        clear_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg        clear_sync_adc;
    reg        clear_seen_adc;

    reg        pending_adc;
    reg [15:0] sample_index_adc;
    reg [39:0] peak_power_adc;
    reg [15:0] peak_index_adc;
    reg [47:0] sum_power_adc;
    reg [31:0] frame_count_adc;
    reg [39:0] last_power_adc;
    reg        frame_closing_adc;
    reg        square_valid_adc;
    reg        power_valid_adc;
    reg        square_frame_done_adc;
    reg        power_frame_done_adc;
    reg [15:0] square_sample_index_adc;
    reg [15:0] power_sample_index_adc;
    reg [31:0] i_square_adc;
    reg [31:0] q_square_adc;
    reg [31:0] i1_square_adc;
    reg [31:0] q1_square_adc;
    reg signed [32:0] cross_re_pipe_adc;
    reg signed [32:0] cross_im_pipe_adc;
    reg [32:0] power_pipe_adc;
    reg [32:0] power1_pipe_adc;
    reg [19:0] debug_heartbeat_div_adc;
    reg        debug_heartbeat_toggle_adc;
    reg        debug_valid_toggle_adc;
    reg        debug_accept_toggle_adc;

    reg [15:0] summary_sample_count_adc;
    reg [39:0] summary_peak_power_adc;
    reg [15:0] summary_peak_index_adc;
    reg [47:0] summary_sum_power_adc;
    reg [47:0] rx1_sum_power_adc;
    reg [39:0] rx1_peak_power_adc;
    reg [15:0] rx1_peak_index_adc;
    reg signed [47:0] cross_re_sum_adc;
    reg signed [47:0] cross_im_sum_adc;
    reg signed [47:0] i0_sum_adc;
    reg signed [47:0] q0_sum_adc;
    reg signed [47:0] i1_sum_adc;
    reg signed [47:0] q1_sum_adc;
    reg [47:0] summary_rx1_sum_power_adc;
    reg [39:0] summary_rx1_peak_power_adc;
    reg [15:0] summary_rx1_peak_index_adc;
    reg signed [47:0] summary_cross_re_sum_adc;
    reg signed [47:0] summary_cross_im_sum_adc;
    reg signed [47:0] summary_i0_sum_adc;
    reg signed [47:0] summary_q0_sum_adc;
    reg signed [47:0] summary_i1_sum_adc;
    reg signed [47:0] summary_q1_sum_adc;
    reg signed [63:0] summary_rx0_corr_power_num_adc;
    reg signed [63:0] summary_rx1_corr_power_num_adc;
    reg signed [63:0] summary_corr_cross_re_num_adc;
    reg signed [63:0] summary_corr_cross_im_num_adc;
    reg [31:0] summary_frame_count_adc;
    reg [39:0] summary_last_power_adc;
    reg [2:0]  post_state_adc;
    reg [15:0] post_sample_count_adc;
    reg [47:0] post_rx0_power_adc;
    reg [47:0] post_rx1_power_adc;
    reg signed [47:0] post_cross_re_adc;
    reg signed [47:0] post_cross_im_adc;
    reg signed [23:0] post_i0_sum_adc;
    reg signed [23:0] post_q0_sum_adc;
    reg signed [23:0] post_i1_sum_adc;
    reg signed [23:0] post_q1_sum_adc;
    reg signed [63:0] post_rx0_power_n_adc;
    reg signed [63:0] post_rx1_power_n_adc;
    reg signed [63:0] post_cross_re_n_adc;
    reg signed [63:0] post_cross_im_n_adc;
    reg signed [47:0] post_i0_square_adc;
    reg signed [47:0] post_q0_square_adc;
    reg signed [47:0] post_i1_square_adc;
    reg signed [47:0] post_q1_square_adc;
    reg signed [47:0] post_i0_i1_product_adc;
    reg signed [47:0] post_q0_q1_product_adc;
    reg signed [47:0] post_q0_i1_product_adc;
    reg signed [47:0] post_i0_q1_product_adc;

    reg [15:0] summary_sample_count_axi;
    reg [39:0] summary_peak_power_axi;
    reg [15:0] summary_peak_index_axi;
    reg [47:0] summary_sum_power_axi;
    reg [47:0] summary_rx1_sum_power_axi;
    reg [39:0] summary_rx1_peak_power_axi;
    reg [15:0] summary_rx1_peak_index_axi;
    reg signed [47:0] summary_cross_re_sum_axi;
    reg signed [47:0] summary_cross_im_sum_axi;
    reg signed [47:0] summary_i0_sum_axi;
    reg signed [47:0] summary_q0_sum_axi;
    reg signed [47:0] summary_i1_sum_axi;
    reg signed [47:0] summary_q1_sum_axi;
    reg signed [63:0] summary_rx0_corr_power_num_axi;
    reg signed [63:0] summary_rx1_corr_power_num_axi;
    reg signed [63:0] summary_corr_cross_re_num_axi;
    reg signed [63:0] summary_corr_cross_im_num_axi;
    reg [31:0] summary_frame_count_axi;
    reg [39:0] summary_last_power_axi;
    reg [6:0]  summary_snapshot_count_axi;
    reg [5:0]  snapshot_index_axi;

    wire [32:0] square_sum_adc = $unsigned(i_square_adc) + $unsigned(q_square_adc);
    wire [32:0] square1_sum_adc = $unsigned(i1_square_adc) + $unsigned(q1_square_adc);
    wire [39:0] power_40_next = {7'd0, power_pipe_adc};
    wire [39:0] power1_40_next = {7'd0, power1_pipe_adc};
    wire [47:0] sum_power_next = sum_power_adc + {15'd0, power_pipe_adc};
    wire [47:0] rx1_sum_power_next = rx1_sum_power_adc + {15'd0, power1_pipe_adc};
    wire signed [47:0] cross_re_sum_next = cross_re_sum_adc + {{15{cross_re_pipe_adc[32]}}, cross_re_pipe_adc};
    wire signed [47:0] cross_im_sum_next = cross_im_sum_adc + {{15{cross_im_pipe_adc[32]}}, cross_im_pipe_adc};
    wire signed [47:0] i0_sum_next = i0_sum_adc + {{32{adc_i[15]}}, adc_i};
    wire signed [47:0] q0_sum_next = q0_sum_adc + {{32{adc_q[15]}}, adc_q};
    wire signed [47:0] i1_sum_next = i1_sum_adc + {{32{adc_i1[15]}}, adc_i1};
    wire signed [47:0] q1_sum_next = q1_sum_adc + {{32{adc_q1[15]}}, adc_q1};
    wire [15:0] sample_count_next = sample_index_adc + 16'd1;
    wire [15:0] final_sample_count_adc = power_sample_index_adc + 16'd1;
    wire [15:0] frame_len_adc = (frame_len_sync_adc == 16'd0) ? 16'd1 : frame_len_sync_adc;
    wire accept_sample_adc = adc_valid && adc_valid1 && enable_sync_adc && !pending_adc && !frame_closing_adc;
    wire frame_done = accept_sample_adc && (sample_count_next >= frame_len_adc);
    wire peak_update = (power_sample_index_adc == 16'd0) || (power_40_next > peak_power_adc);
    wire [39:0] peak_power_next = peak_update ? power_40_next : peak_power_adc;
    wire [15:0] peak_index_next = peak_update ? power_sample_index_adc : peak_index_adc;
    wire rx1_peak_update = (power_sample_index_adc == 16'd0) || (power1_40_next > rx1_peak_power_adc);
    wire [39:0] rx1_peak_power_next = rx1_peak_update ? power1_40_next : rx1_peak_power_adc;
    wire [15:0] rx1_peak_index_next = rx1_peak_update ? power_sample_index_adc : rx1_peak_index_adc;
    wire signed [31:0] cross_re_i_adc = adc_i * adc_i1;
    wire signed [31:0] cross_re_q_adc = adc_q * adc_q1;
    wire signed [31:0] cross_im_qi_adc = adc_q * adc_i1;
    wire signed [31:0] cross_im_iq_adc = adc_i * adc_q1;
    wire signed [63:0] post_sample_count_signed_adc = $signed({48'd0, post_sample_count_adc});
    wire signed [63:0] post_rx0_power_n_next = $signed({16'd0, post_rx0_power_adc}) * post_sample_count_signed_adc;
    wire signed [63:0] post_rx1_power_n_next = $signed({16'd0, post_rx1_power_adc}) * post_sample_count_signed_adc;
    wire signed [63:0] post_cross_re_n_next = post_cross_re_adc * post_sample_count_signed_adc;
    wire signed [63:0] post_cross_im_n_next = post_cross_im_adc * post_sample_count_signed_adc;
    wire signed [47:0] post_i0_square_next = post_i0_sum_adc * post_i0_sum_adc;
    wire signed [47:0] post_q0_square_next = post_q0_sum_adc * post_q0_sum_adc;
    wire signed [47:0] post_i1_square_next = post_i1_sum_adc * post_i1_sum_adc;
    wire signed [47:0] post_q1_square_next = post_q1_sum_adc * post_q1_sum_adc;
    wire signed [47:0] post_i0_i1_product_next = post_i0_sum_adc * post_i1_sum_adc;
    wire signed [47:0] post_q0_q1_product_next = post_q0_sum_adc * post_q1_sum_adc;
    wire signed [47:0] post_q0_i1_product_next = post_q0_sum_adc * post_i1_sum_adc;
    wire signed [47:0] post_i0_q1_product_next = post_i0_sum_adc * post_q1_sum_adc;
    wire signed [63:0] rx0_corr_power_num_next = post_rx0_power_n_adc - {{16{post_i0_square_adc[47]}}, post_i0_square_adc} - {{16{post_q0_square_adc[47]}}, post_q0_square_adc};
    wire signed [63:0] rx1_corr_power_num_next = post_rx1_power_n_adc - {{16{post_i1_square_adc[47]}}, post_i1_square_adc} - {{16{post_q1_square_adc[47]}}, post_q1_square_adc};
    wire signed [63:0] corr_cross_re_num_next = post_cross_re_n_adc - {{16{post_i0_i1_product_adc[47]}}, post_i0_i1_product_adc} - {{16{post_q0_q1_product_adc[47]}}, post_q0_q1_product_adc};
    wire signed [63:0] corr_cross_im_num_next = post_cross_im_n_adc - {{16{post_q0_i1_product_adc[47]}}, post_q0_i1_product_adc} + {{16{post_i0_q1_product_adc[47]}}, post_i0_q1_product_adc};

    assign summary_valid = pending_sync_axi;
    assign irq = pending_sync_axi;

    always @(posedge adc_clk) begin
        if (adc_rst) begin
            enable_meta_adc <= 1'b0;
            enable_sync_adc <= 1'b0;
            frame_len_meta_adc <= DEFAULT_FRAME_LEN[15:0];
            frame_len_sync_adc <= DEFAULT_FRAME_LEN[15:0];
            clear_meta_adc <= 1'b0;
            clear_sync_adc <= 1'b0;
            clear_seen_adc <= 1'b0;
            pending_adc <= 1'b0;
            sample_index_adc <= 16'd0;
            peak_power_adc <= 40'd0;
            peak_index_adc <= 16'd0;
            sum_power_adc <= 48'd0;
            frame_count_adc <= 32'd0;
            last_power_adc <= 40'd0;
            frame_closing_adc <= 1'b0;
            square_valid_adc <= 1'b0;
            power_valid_adc <= 1'b0;
            square_frame_done_adc <= 1'b0;
            power_frame_done_adc <= 1'b0;
            square_sample_index_adc <= 16'd0;
            power_sample_index_adc <= 16'd0;
            i_square_adc <= 32'd0;
            q_square_adc <= 32'd0;
            i1_square_adc <= 32'd0;
            q1_square_adc <= 32'd0;
            cross_re_pipe_adc <= 33'sd0;
            cross_im_pipe_adc <= 33'sd0;
            power_pipe_adc <= 33'd0;
            power1_pipe_adc <= 33'd0;
            debug_heartbeat_div_adc <= 20'd0;
            debug_heartbeat_toggle_adc <= 1'b0;
            debug_valid_toggle_adc <= 1'b0;
            debug_accept_toggle_adc <= 1'b0;
            summary_sample_count_adc <= 16'd0;
            summary_peak_power_adc <= 40'd0;
            summary_peak_index_adc <= 16'd0;
            summary_sum_power_adc <= 48'd0;
            rx1_sum_power_adc <= 48'd0;
            rx1_peak_power_adc <= 40'd0;
            rx1_peak_index_adc <= 16'd0;
            cross_re_sum_adc <= 48'sd0;
            cross_im_sum_adc <= 48'sd0;
            i0_sum_adc <= 48'sd0;
            q0_sum_adc <= 48'sd0;
            i1_sum_adc <= 48'sd0;
            q1_sum_adc <= 48'sd0;
            summary_rx1_sum_power_adc <= 48'd0;
            summary_rx1_peak_power_adc <= 40'd0;
            summary_rx1_peak_index_adc <= 16'd0;
            summary_cross_re_sum_adc <= 48'sd0;
            summary_cross_im_sum_adc <= 48'sd0;
            summary_i0_sum_adc <= 48'sd0;
            summary_q0_sum_adc <= 48'sd0;
            summary_i1_sum_adc <= 48'sd0;
            summary_q1_sum_adc <= 48'sd0;
            summary_rx0_corr_power_num_adc <= 64'sd0;
            summary_rx1_corr_power_num_adc <= 64'sd0;
            summary_corr_cross_re_num_adc <= 64'sd0;
            summary_corr_cross_im_num_adc <= 64'sd0;
            summary_frame_count_adc <= 32'd0;
            summary_last_power_adc <= 40'd0;
            post_state_adc <= 3'd0;
            post_sample_count_adc <= 16'd0;
            post_rx0_power_adc <= 48'd0;
            post_rx1_power_adc <= 48'd0;
            post_cross_re_adc <= 48'sd0;
            post_cross_im_adc <= 48'sd0;
            post_i0_sum_adc <= 24'sd0;
            post_q0_sum_adc <= 24'sd0;
            post_i1_sum_adc <= 24'sd0;
            post_q1_sum_adc <= 24'sd0;
            post_rx0_power_n_adc <= 64'sd0;
            post_rx1_power_n_adc <= 64'sd0;
            post_cross_re_n_adc <= 64'sd0;
            post_cross_im_n_adc <= 64'sd0;
            post_i0_square_adc <= 48'sd0;
            post_q0_square_adc <= 48'sd0;
            post_i1_square_adc <= 48'sd0;
            post_q1_square_adc <= 48'sd0;
            post_i0_i1_product_adc <= 48'sd0;
            post_q0_q1_product_adc <= 48'sd0;
            post_q0_i1_product_adc <= 48'sd0;
            post_i0_q1_product_adc <= 48'sd0;
        end else begin
            enable_meta_adc <= enable_axi;
            enable_sync_adc <= enable_meta_adc;
            frame_len_meta_adc <= frame_len_axi;
            frame_len_sync_adc <= frame_len_meta_adc;
            clear_meta_adc <= clear_toggle_axi;
            clear_sync_adc <= clear_meta_adc;
            debug_heartbeat_div_adc <= debug_heartbeat_div_adc + 20'd1;
            if (debug_heartbeat_div_adc == 20'd0) begin
                debug_heartbeat_toggle_adc <= !debug_heartbeat_toggle_adc;
            end
            if (adc_valid) begin
                debug_valid_toggle_adc <= !debug_valid_toggle_adc;
            end

            if (clear_sync_adc != clear_seen_adc) begin
                clear_seen_adc <= clear_sync_adc;
                pending_adc <= 1'b0;
                sample_index_adc <= 16'd0;
                peak_power_adc <= 40'd0;
                peak_index_adc <= 16'd0;
                sum_power_adc <= 48'd0;
                rx1_sum_power_adc <= 48'd0;
                rx1_peak_power_adc <= 40'd0;
                rx1_peak_index_adc <= 16'd0;
                cross_re_sum_adc <= 48'sd0;
                cross_im_sum_adc <= 48'sd0;
                i0_sum_adc <= 48'sd0;
                q0_sum_adc <= 48'sd0;
                i1_sum_adc <= 48'sd0;
                q1_sum_adc <= 48'sd0;
                last_power_adc <= 40'd0;
                frame_closing_adc <= 1'b0;
                square_valid_adc <= 1'b0;
                power_valid_adc <= 1'b0;
                square_frame_done_adc <= 1'b0;
                power_frame_done_adc <= 1'b0;
                post_state_adc <= 3'd0;
            end else begin
                square_valid_adc <= accept_sample_adc;
                square_frame_done_adc <= frame_done;
                square_sample_index_adc <= sample_index_adc;
                if (accept_sample_adc) begin
                    debug_accept_toggle_adc <= !debug_accept_toggle_adc;
                    i_square_adc <= adc_i * adc_i;
                    q_square_adc <= adc_q * adc_q;
                    i1_square_adc <= adc_i1 * adc_i1;
                    q1_square_adc <= adc_q1 * adc_q1;
                    cross_re_pipe_adc <= {cross_re_i_adc[31], cross_re_i_adc} + {cross_re_q_adc[31], cross_re_q_adc};
                    cross_im_pipe_adc <= {cross_im_qi_adc[31], cross_im_qi_adc} - {cross_im_iq_adc[31], cross_im_iq_adc};
                    i0_sum_adc <= i0_sum_next;
                    q0_sum_adc <= q0_sum_next;
                    i1_sum_adc <= i1_sum_next;
                    q1_sum_adc <= q1_sum_next;
                    if (frame_done) begin
                        frame_closing_adc <= 1'b1;
                        sample_index_adc <= 16'd0;
                    end else begin
                        sample_index_adc <= sample_count_next;
                    end
                end

                power_valid_adc <= square_valid_adc;
                power_frame_done_adc <= square_frame_done_adc;
                power_sample_index_adc <= square_sample_index_adc;
                power_pipe_adc <= square_sum_adc;
                power1_pipe_adc <= square1_sum_adc;

                if (power_valid_adc) begin
                    last_power_adc <= power_40_next;
                    sum_power_adc <= sum_power_next;
                    peak_power_adc <= peak_power_next;
                    peak_index_adc <= peak_index_next;
                    rx1_sum_power_adc <= rx1_sum_power_next;
                    rx1_peak_power_adc <= rx1_peak_power_next;
                    rx1_peak_index_adc <= rx1_peak_index_next;
                    cross_re_sum_adc <= cross_re_sum_next;
                    cross_im_sum_adc <= cross_im_sum_next;

                    if (power_frame_done_adc) begin
                        frame_closing_adc <= 1'b0;
                        frame_count_adc <= frame_count_adc + 32'd1;
                        summary_sample_count_adc <= final_sample_count_adc;
                        summary_peak_power_adc <= peak_power_next;
                        summary_peak_index_adc <= peak_index_next;
                        summary_sum_power_adc <= sum_power_next;
                        summary_rx1_sum_power_adc <= rx1_sum_power_next;
                        summary_rx1_peak_power_adc <= rx1_peak_power_next;
                        summary_rx1_peak_index_adc <= rx1_peak_index_next;
                        summary_cross_re_sum_adc <= cross_re_sum_next;
                        summary_cross_im_sum_adc <= cross_im_sum_next;
                        summary_i0_sum_adc <= i0_sum_adc;
                        summary_q0_sum_adc <= q0_sum_adc;
                        summary_i1_sum_adc <= i1_sum_adc;
                        summary_q1_sum_adc <= q1_sum_adc;
                        summary_frame_count_adc <= frame_count_adc + 32'd1;
                        summary_last_power_adc <= power_40_next;
                        post_sample_count_adc <= final_sample_count_adc;
                        post_rx0_power_adc <= sum_power_next;
                        post_rx1_power_adc <= rx1_sum_power_next;
                        post_cross_re_adc <= cross_re_sum_next;
                        post_cross_im_adc <= cross_im_sum_next;
                        post_i0_sum_adc <= i0_sum_adc[23:0];
                        post_q0_sum_adc <= q0_sum_adc[23:0];
                        post_i1_sum_adc <= i1_sum_adc[23:0];
                        post_q1_sum_adc <= q1_sum_adc[23:0];
                        post_state_adc <= 3'd1;
                    end
                end

                case (post_state_adc)
                    3'd1: begin
                        post_rx0_power_n_adc <= post_rx0_power_n_next;
                        post_rx1_power_n_adc <= post_rx1_power_n_next;
                        post_cross_re_n_adc <= post_cross_re_n_next;
                        post_cross_im_n_adc <= post_cross_im_n_next;
                        post_i0_square_adc <= post_i0_square_next;
                        post_q0_square_adc <= post_q0_square_next;
                        post_i1_square_adc <= post_i1_square_next;
                        post_q1_square_adc <= post_q1_square_next;
                        post_i0_i1_product_adc <= post_i0_i1_product_next;
                        post_q0_q1_product_adc <= post_q0_q1_product_next;
                        post_q0_i1_product_adc <= post_q0_i1_product_next;
                        post_i0_q1_product_adc <= post_i0_q1_product_next;
                        post_state_adc <= 3'd2;
                    end
                    3'd2: begin
                        summary_rx0_corr_power_num_adc <= rx0_corr_power_num_next;
                        summary_rx1_corr_power_num_adc <= rx1_corr_power_num_next;
                        summary_corr_cross_re_num_adc <= corr_cross_re_num_next;
                        summary_corr_cross_im_num_adc <= corr_cross_im_num_next;
                        pending_adc <= 1'b1;
                        post_state_adc <= 3'd0;
                    end
                    default: begin
                    end
                endcase
            end
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            enable_axi <= 1'b0;
            frame_len_axi <= DEFAULT_FRAME_LEN[15:0];
            control_shadow_axi <= 32'd0;
            frame_len_shadow_axi <= DEFAULT_FRAME_LEN;
            clear_toggle_axi <= 1'b0;
            pending_meta_axi <= 1'b0;
            pending_sync_axi <= 1'b0;
            pending_sync_axi_d <= 1'b0;
            summary_sample_count_axi <= 16'd0;
            summary_peak_power_axi <= 40'd0;
            summary_peak_index_axi <= 16'd0;
            summary_sum_power_axi <= 48'd0;
            summary_rx1_sum_power_axi <= 48'd0;
            summary_rx1_peak_power_axi <= 40'd0;
            summary_rx1_peak_index_axi <= 16'd0;
            summary_cross_re_sum_axi <= 48'sd0;
            summary_cross_im_sum_axi <= 48'sd0;
            summary_i0_sum_axi <= 48'sd0;
            summary_q0_sum_axi <= 48'sd0;
            summary_i1_sum_axi <= 48'sd0;
            summary_q1_sum_axi <= 48'sd0;
            summary_rx0_corr_power_num_axi <= 64'sd0;
            summary_rx1_corr_power_num_axi <= 64'sd0;
            summary_corr_cross_re_num_axi <= 64'sd0;
            summary_corr_cross_im_num_axi <= 64'sd0;
            summary_frame_count_axi <= 32'd0;
            summary_last_power_axi <= 40'd0;
            summary_snapshot_count_axi <= 7'd0;
            snapshot_index_axi <= 6'd0;
            adc_rst_meta_axi <= 1'b0;
            adc_rst_sync_axi <= 1'b0;
            enable_adc_meta_axi <= 1'b0;
            enable_adc_sync_axi <= 1'b0;
            heartbeat_meta_axi <= 1'b0;
            heartbeat_sync_axi <= 1'b0;
            heartbeat_sync_axi_d <= 1'b0;
            valid_meta_axi <= 1'b0;
            valid_sync_axi <= 1'b0;
            valid_sync_axi_d <= 1'b0;
            accept_meta_axi <= 1'b0;
            accept_sync_axi <= 1'b0;
            accept_sync_axi_d <= 1'b0;
            debug_clk_count_axi <= 32'd0;
            debug_valid_count_axi <= 32'd0;
            debug_accept_count_axi <= 32'd0;
            s_axi_awready <= 1'b0;
            s_axi_wready <= 1'b0;
            s_axi_bresp <= 2'b00;
            s_axi_bvalid <= 1'b0;
        end else begin
            pending_meta_axi <= pending_adc;
            pending_sync_axi <= pending_meta_axi;
            pending_sync_axi_d <= pending_sync_axi;
            adc_rst_meta_axi <= adc_rst;
            adc_rst_sync_axi <= adc_rst_meta_axi;
            enable_adc_meta_axi <= enable_sync_adc;
            enable_adc_sync_axi <= enable_adc_meta_axi;
            heartbeat_meta_axi <= debug_heartbeat_toggle_adc;
            heartbeat_sync_axi <= heartbeat_meta_axi;
            heartbeat_sync_axi_d <= heartbeat_sync_axi;
            valid_meta_axi <= debug_valid_toggle_adc;
            valid_sync_axi <= valid_meta_axi;
            valid_sync_axi_d <= valid_sync_axi;
            accept_meta_axi <= debug_accept_toggle_adc;
            accept_sync_axi <= accept_meta_axi;
            accept_sync_axi_d <= accept_sync_axi;
            s_axi_awready <= 1'b0;
            s_axi_wready <= 1'b0;

            if (heartbeat_sync_axi != heartbeat_sync_axi_d) begin
                debug_clk_count_axi <= debug_clk_count_axi + 32'd1;
            end
            if (valid_sync_axi != valid_sync_axi_d) begin
                debug_valid_count_axi <= debug_valid_count_axi + 32'd1;
            end
            if (accept_sync_axi != accept_sync_axi_d) begin
                debug_accept_count_axi <= debug_accept_count_axi + 32'd1;
            end

            if (pending_sync_axi && !pending_sync_axi_d) begin
                summary_sample_count_axi <= summary_sample_count_adc;
                summary_peak_power_axi <= summary_peak_power_adc;
                summary_peak_index_axi <= summary_peak_index_adc;
                summary_sum_power_axi <= summary_sum_power_adc;
                summary_rx1_sum_power_axi <= summary_rx1_sum_power_adc;
                summary_rx1_peak_power_axi <= summary_rx1_peak_power_adc;
                summary_rx1_peak_index_axi <= summary_rx1_peak_index_adc;
                summary_cross_re_sum_axi <= summary_cross_re_sum_adc;
                summary_cross_im_sum_axi <= summary_cross_im_sum_adc;
                summary_i0_sum_axi <= summary_i0_sum_adc;
                summary_q0_sum_axi <= summary_q0_sum_adc;
                summary_i1_sum_axi <= summary_i1_sum_adc;
                summary_q1_sum_axi <= summary_q1_sum_adc;
                summary_rx0_corr_power_num_axi <= summary_rx0_corr_power_num_adc;
                summary_rx1_corr_power_num_axi <= summary_rx1_corr_power_num_adc;
                summary_corr_cross_re_num_axi <= summary_corr_cross_re_num_adc;
                summary_corr_cross_im_num_axi <= summary_corr_cross_im_num_adc;
                summary_frame_count_axi <= summary_frame_count_adc;
                summary_last_power_axi <= summary_last_power_adc;
                summary_snapshot_count_axi <= 7'd0;
            end

            if (!s_axi_bvalid && s_axi_awvalid && s_axi_wvalid) begin
                s_axi_awready <= 1'b1;
                s_axi_wready <= 1'b1;
                s_axi_bresp <= 2'b00;
                s_axi_bvalid <= 1'b1;

                case (s_axi_awaddr[7:0])
                    REG_CONTROL: begin
                        if (s_axi_wstrb[0]) begin
                            control_shadow_axi <= s_axi_wdata;
                            enable_axi <= s_axi_wdata[0];
                            if (s_axi_wdata[1]) begin
                                clear_toggle_axi <= !clear_toggle_axi;
                                debug_clk_count_axi <= 32'd0;
                                debug_valid_count_axi <= 32'd0;
                                debug_accept_count_axi <= 32'd0;
                            end
                        end
                    end
                    REG_FRAME_LEN: begin
                        if (|s_axi_wstrb) begin
                            frame_len_shadow_axi <= s_axi_wdata;
                            frame_len_axi <= (s_axi_wdata[15:0] == 16'd0) ? 16'd1 : s_axi_wdata[15:0];
                        end
                    end
                    REG_SNAPSHOT_INDEX: begin
                        if (|s_axi_wstrb) begin
                            snapshot_index_axi <= s_axi_wdata[5:0];
                        end
                    end
                    default: begin
                    end
                endcase
            end else if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_arready <= 1'b0;
            s_axi_rdata <= 32'd0;
            s_axi_rresp <= 2'b00;
            s_axi_rvalid <= 1'b0;
        end else begin
            s_axi_arready <= 1'b0;

            if (!s_axi_rvalid && s_axi_arvalid) begin
                s_axi_arready <= 1'b1;
                s_axi_rresp <= 2'b00;
                s_axi_rvalid <= 1'b1;

                case (s_axi_araddr[7:0])
                    REG_CONTROL:       s_axi_rdata <= {control_shadow_axi[31:2], 1'b0, enable_axi};
                    REG_FRAME_LEN:     s_axi_rdata <= {frame_len_shadow_axi[31:16], frame_len_axi};
                    REG_STATUS:        s_axi_rdata <= {29'd0, pending_sync_axi, pending_sync_axi, enable_axi};
                    REG_SAMPLE_COUNT:  s_axi_rdata <= {16'd0, summary_sample_count_axi};
                    REG_PEAK_POWER_LO: s_axi_rdata <= summary_peak_power_axi[31:0];
                    REG_PEAK_POWER_HI: s_axi_rdata <= {24'd0, summary_peak_power_axi[39:32]};
                    REG_PEAK_INDEX:    s_axi_rdata <= {16'd0, summary_peak_index_axi};
                    REG_SUM_POWER_LO:  s_axi_rdata <= summary_sum_power_axi[31:0];
                    REG_SUM_POWER_HI:  s_axi_rdata <= {16'd0, summary_sum_power_axi[47:32]};
                    REG_FRAME_COUNT:   s_axi_rdata <= summary_frame_count_axi;
                    REG_LAST_POWER_LO: s_axi_rdata <= summary_last_power_axi[31:0];
                    REG_LAST_POWER_HI: s_axi_rdata <= {24'd0, summary_last_power_axi[39:32]};
                    REG_DEBUG_FLAGS:   s_axi_rdata <= {24'd0, accept_sync_axi, valid_sync_axi, heartbeat_sync_axi, enable_adc_sync_axi, adc_rst_sync_axi, pending_sync_axi, pending_sync_axi, enable_axi};
                    REG_DEBUG_CLK:     s_axi_rdata <= debug_clk_count_axi;
                    REG_DEBUG_VALID:   s_axi_rdata <= debug_valid_count_axi;
                    REG_DEBUG_ACCEPT:  s_axi_rdata <= debug_accept_count_axi;
                    REG_SUMMARY_VERSION:  s_axi_rdata <= 32'h53554d35;
                    REG_SUMMARY_FLAGS:    s_axi_rdata <= {24'd0, accept_sync_axi, valid_sync_axi, heartbeat_sync_axi, enable_adc_sync_axi, adc_rst_sync_axi, pending_sync_axi, pending_sync_axi, enable_axi};
                    REG_SUMMARY_FRAME:    s_axi_rdata <= summary_frame_count_axi;
                    REG_SUMMARY_SAMPLES:  s_axi_rdata <= {16'd0, summary_sample_count_axi};
                    REG_SUMMARY_SUM_LO:   s_axi_rdata <= summary_sum_power_axi[31:0];
                    REG_SUMMARY_SUM_HI:   s_axi_rdata <= {16'd0, summary_sum_power_axi[47:32]};
                    REG_SUMMARY_PEAK:     s_axi_rdata <= summary_peak_power_axi[31:0];
                    REG_SUMMARY_PEAK_IDX: s_axi_rdata <= {16'd0, summary_peak_index_axi};
                    REG_SNAPSHOT_COUNT:   s_axi_rdata <= {25'd0, summary_snapshot_count_axi};
                    REG_SNAPSHOT_INDEX:   s_axi_rdata <= {26'd0, snapshot_index_axi};
                    REG_SNAPSHOT_DATA:    s_axi_rdata <= 32'd0;
                    REG_SNAPSHOT1_DATA:   s_axi_rdata <= 32'd0;
                    REG_DUAL_SAMPLES:     s_axi_rdata <= {16'd0, summary_sample_count_axi};
                    REG_RX0_POWER_LO:     s_axi_rdata <= summary_sum_power_axi[31:0];
                    REG_RX0_POWER_HI:     s_axi_rdata <= {16'd0, summary_sum_power_axi[47:32]};
                    REG_RX1_POWER_LO:     s_axi_rdata <= summary_rx1_sum_power_axi[31:0];
                    REG_RX1_POWER_HI:     s_axi_rdata <= {16'd0, summary_rx1_sum_power_axi[47:32]};
                    REG_CROSS_RE_LO:      s_axi_rdata <= summary_cross_re_sum_axi[31:0];
                    REG_CROSS_RE_HI:      s_axi_rdata <= {{16{summary_cross_re_sum_axi[47]}}, summary_cross_re_sum_axi[47:32]};
                    REG_CROSS_IM_LO:      s_axi_rdata <= summary_cross_im_sum_axi[31:0];
                    REG_CROSS_IM_HI:      s_axi_rdata <= {{16{summary_cross_im_sum_axi[47]}}, summary_cross_im_sum_axi[47:32]};
                    REG_RX1_PEAK_POWER:   s_axi_rdata <= summary_rx1_peak_power_axi[31:0];
                    REG_RX1_PEAK_IDX:     s_axi_rdata <= {16'd0, summary_rx1_peak_index_axi};
                    REG_I0_SUM_LO:        s_axi_rdata <= summary_i0_sum_axi[31:0];
                    REG_I0_SUM_HI:        s_axi_rdata <= {{16{summary_i0_sum_axi[47]}}, summary_i0_sum_axi[47:32]};
                    REG_Q0_SUM_LO:        s_axi_rdata <= summary_q0_sum_axi[31:0];
                    REG_Q0_SUM_HI:        s_axi_rdata <= {{16{summary_q0_sum_axi[47]}}, summary_q0_sum_axi[47:32]};
                    REG_I1_SUM_LO:        s_axi_rdata <= summary_i1_sum_axi[31:0];
                    REG_I1_SUM_HI:        s_axi_rdata <= {{16{summary_i1_sum_axi[47]}}, summary_i1_sum_axi[47:32]};
                    REG_Q1_SUM_LO:        s_axi_rdata <= summary_q1_sum_axi[31:0];
                    REG_Q1_SUM_HI:        s_axi_rdata <= {{16{summary_q1_sum_axi[47]}}, summary_q1_sum_axi[47:32]};
                    REG_RX0_CORR_PWR_LO:  s_axi_rdata <= summary_rx0_corr_power_num_axi[31:0];
                    REG_RX0_CORR_PWR_MID: s_axi_rdata <= summary_rx0_corr_power_num_axi[63:32];
                    REG_RX0_CORR_PWR_HI:  s_axi_rdata <= {32{summary_rx0_corr_power_num_axi[63]}};
                    REG_RX1_CORR_PWR_LO:  s_axi_rdata <= summary_rx1_corr_power_num_axi[31:0];
                    REG_RX1_CORR_PWR_MID: s_axi_rdata <= summary_rx1_corr_power_num_axi[63:32];
                    REG_RX1_CORR_PWR_HI:  s_axi_rdata <= {32{summary_rx1_corr_power_num_axi[63]}};
                    REG_CORR_CROSS_RE_LO: s_axi_rdata <= summary_corr_cross_re_num_axi[31:0];
                    REG_CORR_CROSS_RE_MID:s_axi_rdata <= summary_corr_cross_re_num_axi[63:32];
                    REG_CORR_CROSS_RE_HI: s_axi_rdata <= {32{summary_corr_cross_re_num_axi[63]}};
                    REG_CORR_CROSS_IM_LO: s_axi_rdata <= summary_corr_cross_im_num_axi[31:0];
                    REG_CORR_CROSS_IM_MID:s_axi_rdata <= summary_corr_cross_im_num_axi[63:32];
                    REG_CORR_CROSS_IM_HI: s_axi_rdata <= {32{summary_corr_cross_im_num_axi[63]}};
                    default:           s_axi_rdata <= 32'd0;
                endcase
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

endmodule
