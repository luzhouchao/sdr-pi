`timescale 1ns / 1ps

module p201pro_ad9361_power_tap_axi_regs #
(
    parameter integer AXIL_ADDR_WIDTH = 12,
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

    localparam [11:0] REG_CONTROL          = 12'h000;
    localparam [11:0] REG_FRAME_LEN        = 12'h004;
    localparam [11:0] REG_STATUS           = 12'h008;
    localparam [11:0] REG_SAMPLE_COUNT     = 12'h00c;
    localparam [11:0] REG_PEAK_POWER_LO    = 12'h010;
    localparam [11:0] REG_PEAK_POWER_HI    = 12'h014;
    localparam [11:0] REG_PEAK_INDEX       = 12'h018;
    localparam [11:0] REG_SUM_POWER_LO     = 12'h01c;
    localparam [11:0] REG_SUM_POWER_HI     = 12'h020;
    localparam [11:0] REG_FRAME_COUNT      = 12'h024;
    localparam [11:0] REG_LAST_POWER_LO    = 12'h028;
    localparam [11:0] REG_LAST_POWER_HI    = 12'h02c;
    localparam [11:0] REG_DEBUG_FLAGS      = 12'h030;
    localparam [11:0] REG_DEBUG_CLK        = 12'h034;
    localparam [11:0] REG_DEBUG_VALID      = 12'h038;
    localparam [11:0] REG_DEBUG_ACCEPT     = 12'h03c;
    localparam [11:0] REG_SUMMARY_VERSION  = 12'h040;
    localparam [11:0] REG_SUMMARY_FLAGS    = 12'h044;
    localparam [11:0] REG_SUMMARY_FRAME    = 12'h048;
    localparam [11:0] REG_SUMMARY_SAMPLES  = 12'h04c;
    localparam [11:0] REG_SUMMARY_SUM_LO   = 12'h050;
    localparam [11:0] REG_SUMMARY_SUM_HI   = 12'h054;
    localparam [11:0] REG_SUMMARY_PEAK     = 12'h058;
    localparam [11:0] REG_SUMMARY_PEAK_IDX = 12'h05c;
    localparam [11:0] REG_SNAPSHOT_COUNT   = 12'h060;
    localparam [11:0] REG_SNAPSHOT_INDEX   = 12'h064;
    localparam [11:0] REG_SNAPSHOT_DATA    = 12'h068;
    localparam [11:0] REG_SNAPSHOT1_DATA   = 12'h06c;
    localparam [11:0] REG_DUAL_SAMPLES     = 12'h070;
    localparam [11:0] REG_RX0_POWER_LO     = 12'h074;
    localparam [11:0] REG_RX0_POWER_HI     = 12'h078;
    localparam [11:0] REG_RX1_POWER_LO     = 12'h07c;
    localparam [11:0] REG_RX1_POWER_HI     = 12'h080;
    localparam [11:0] REG_CROSS_RE_LO      = 12'h084;
    localparam [11:0] REG_CROSS_RE_HI      = 12'h088;
    localparam [11:0] REG_CROSS_IM_LO      = 12'h08c;
    localparam [11:0] REG_CROSS_IM_HI      = 12'h090;
    localparam [11:0] REG_RX1_PEAK_POWER   = 12'h094;
    localparam [11:0] REG_RX1_PEAK_IDX     = 12'h098;
    localparam [11:0] REG_I0_SUM_LO        = 12'h09c;
    localparam [11:0] REG_I0_SUM_HI        = 12'h0a0;
    localparam [11:0] REG_Q0_SUM_LO        = 12'h0a4;
    localparam [11:0] REG_Q0_SUM_HI        = 12'h0a8;
    localparam [11:0] REG_I1_SUM_LO        = 12'h0ac;
    localparam [11:0] REG_I1_SUM_HI        = 12'h0b0;
    localparam [11:0] REG_Q1_SUM_LO        = 12'h0b4;
    localparam [11:0] REG_Q1_SUM_HI        = 12'h0b8;
    localparam [11:0] REG_RX0_CORR_PWR_LO  = 12'h0bc;
    localparam [11:0] REG_RX0_CORR_PWR_MID = 12'h0c0;
    localparam [11:0] REG_RX0_CORR_PWR_HI  = 12'h0c4;
    localparam [11:0] REG_RX1_CORR_PWR_LO  = 12'h0c8;
    localparam [11:0] REG_RX1_CORR_PWR_MID = 12'h0cc;
    localparam [11:0] REG_RX1_CORR_PWR_HI  = 12'h0d0;
    localparam [11:0] REG_CORR_CROSS_RE_LO = 12'h0d4;
    localparam [11:0] REG_CORR_CROSS_RE_MID= 12'h0d8;
    localparam [11:0] REG_CORR_CROSS_RE_HI = 12'h0dc;
    localparam [11:0] REG_CORR_CROSS_IM_LO = 12'h0e0;
    localparam [11:0] REG_CORR_CROSS_IM_MID= 12'h0e4;
    localparam [11:0] REG_CORR_CROSS_IM_HI = 12'h0e8;
    localparam [11:0] REG_ABI_VERSION      = 12'h0ec;
    localparam [11:0] REG_CAPABILITY       = 12'h0f0;
    localparam [11:0] REG_LIMIT_FLAGS      = 12'h0f4;
    localparam [11:0] REG_MAX_CORR_FRAME   = 12'h0f8;
    localparam [11:0] REG_BUILD_ID         = 12'h0fc;
    localparam [11:0] REG_QUALITY_VERSION  = 12'h100;
    localparam [11:0] REG_QUALITY_FLAGS    = 12'h104;
    localparam [11:0] REG_QUALITY_FRAME    = 12'h108;
    localparam [11:0] REG_QUALITY_SAMPLES  = 12'h10c;
    localparam [11:0] REG_RX0_CLIP_COUNTS  = 12'h110;
    localparam [11:0] REG_RX1_CLIP_COUNTS  = 12'h114;
    localparam [11:0] REG_RX0_ZC_COUNTS    = 12'h118;
    localparam [11:0] REG_RX1_ZC_COUNTS    = 12'h11c;
    localparam [11:0] REG_SIGN_SAME_COUNTS = 12'h120;
    localparam [11:0] REG_QUAD_COUNTS      = 12'h124;
    localparam [11:0] REG_RX0_ABS_I_SUM    = 12'h128;
    localparam [11:0] REG_RX0_ABS_Q_SUM    = 12'h12c;
    localparam [11:0] REG_RX1_ABS_I_SUM    = 12'h130;
    localparam [11:0] REG_RX1_ABS_Q_SUM    = 12'h134;
    localparam [11:0] REG_QUALITY_CAP      = 12'h138;
    localparam [11:0] REG_QUALITY_BUILD_ID = 12'h13c;
    localparam [11:0] REG_AGG_SEQUENCE     = 12'h17c;
    localparam [11:0] REG_AGG_VERSION      = 12'h180;
    localparam [11:0] REG_AGG_CONTROL      = 12'h184;
    localparam [11:0] REG_AGG_TARGET       = 12'h188;
    localparam [11:0] REG_AGG_FRAMES       = 12'h18c;
    localparam [11:0] REG_AGG_SAMPLES      = 12'h190;
    localparam [11:0] REG_AGG_RX0_CORR_LO  = 12'h194;
    localparam [11:0] REG_AGG_RX0_CORR_MID = 12'h198;
    localparam [11:0] REG_AGG_RX0_CORR_HI  = 12'h19c;
    localparam [11:0] REG_AGG_RX1_CORR_LO  = 12'h1a0;
    localparam [11:0] REG_AGG_RX1_CORR_MID = 12'h1a4;
    localparam [11:0] REG_AGG_RX1_CORR_HI  = 12'h1a8;
    localparam [11:0] REG_AGG_CROSS_RE_LO  = 12'h1ac;
    localparam [11:0] REG_AGG_CROSS_RE_MID = 12'h1b0;
    localparam [11:0] REG_AGG_CROSS_RE_HI  = 12'h1b4;
    localparam [11:0] REG_AGG_CROSS_IM_LO  = 12'h1b8;
    localparam [11:0] REG_AGG_CROSS_IM_MID = 12'h1bc;
    localparam [11:0] REG_AGG_CROSS_IM_HI  = 12'h1c0;
    localparam [11:0] REG_AGG_RX0_RAW_LO   = 12'h1c4;
    localparam [11:0] REG_AGG_RX0_RAW_MID  = 12'h1c8;
    localparam [11:0] REG_AGG_RX0_RAW_HI   = 12'h1cc;
    localparam [11:0] REG_AGG_RX1_RAW_LO   = 12'h1d0;
    localparam [11:0] REG_AGG_RX1_RAW_MID  = 12'h1d4;
    localparam [11:0] REG_AGG_RX1_RAW_HI   = 12'h1d8;
    localparam [11:0] REG_AGG_RX0_CLIP     = 12'h1dc;
    localparam [11:0] REG_AGG_RX1_CLIP     = 12'h1e0;
    localparam [11:0] REG_AGG_RX0_ZC       = 12'h1e4;
    localparam [11:0] REG_AGG_RX1_ZC       = 12'h1e8;
    localparam [11:0] REG_AGG_SIGN_SAME    = 12'h1ec;
    localparam [11:0] REG_AGG_LAST_FRAME   = 12'h1f0;
    localparam [11:0] REG_AGG_CAP          = 12'h1f4;
    localparam [11:0] REG_AGG_BUILD_ID     = 12'h1f8;
    localparam [11:0] REG_AGG_LIMIT        = 12'h1fc;
    localparam [31:0] SUMMARY_VERSION_SUM8 = 32'h53554d38;
    localparam [31:0] SUMMARY_ABI_VERSION  = 32'h00010002;
    localparam [31:0] SUMMARY_CAPABILITY   = 32'h000003ff;
    localparam [31:0] SUMMARY_MAX_CORR_FRAME = 32'd65535;
    localparam [31:0] SUMMARY_BUILD_ID     = 32'h56384430;
    localparam [31:0] QUALITY_VERSION_SUM8 = 32'h51554138;
    localparam [31:0] QUALITY_CAPABILITY   = 32'h0000000f;
    localparam [31:0] QUALITY_BUILD_ID     = 32'h51384430;
    localparam [31:0] AGG_VERSION_SUM8     = 32'h41474738;
    localparam [31:0] AGG_CAPABILITY       = 32'h0000003f;
    localparam [31:0] AGG_BUILD_ID         = 32'h41384430;
    localparam [31:0] AGG_MAX_FRAMES       = 32'd65535;

    reg        enable_axi;
    reg [15:0] frame_len_axi;
    reg [31:0] control_shadow_axi;
    reg [31:0] frame_len_shadow_axi;
    reg        clear_toggle_axi;
    reg        agg_enable_axi;
    reg [15:0] agg_target_frames_axi;
    reg [31:0] agg_control_shadow_axi;
    reg        agg_clear_toggle_axi;
    reg        agg_auto_axi;
    (* ASYNC_REG = "TRUE" *) reg        pending_meta_axi;
    (* ASYNC_REG = "TRUE" *) reg        pending_sync_axi;
    reg        pending_sync_axi_d;
    (* ASYNC_REG = "TRUE" *) reg        agg_update_meta_axi;
    (* ASYNC_REG = "TRUE" *) reg        agg_update_sync_axi;
    reg        agg_update_sync_axi_d;
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
    (* max_fanout = 64 *) reg s_axi_aresetn_ctrl_axi = 1'b0;
    (* max_fanout = 64 *) reg s_axi_aresetn_read_axi = 1'b0;

    (* ASYNC_REG = "TRUE" *) reg        enable_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg        enable_sync_adc;
    (* ASYNC_REG = "TRUE" *) reg [15:0] frame_len_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg [15:0] frame_len_sync_adc;
    (* ASYNC_REG = "TRUE" *) reg        clear_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg        clear_sync_adc;
    (* ASYNC_REG = "TRUE" *) reg        agg_enable_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg        agg_enable_sync_adc;
    (* ASYNC_REG = "TRUE" *) reg [15:0] agg_target_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg [15:0] agg_target_sync_adc;
    (* ASYNC_REG = "TRUE" *) reg        agg_clear_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg        agg_clear_sync_adc;
    (* ASYNC_REG = "TRUE" *) reg        agg_auto_meta_adc;
    (* ASYNC_REG = "TRUE" *) reg        agg_auto_sync_adc;
    reg        agg_clear_seen_adc;
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
    reg signed [31:0] post_i0_sum_adc;
    reg signed [31:0] post_q0_sum_adc;
    reg signed [31:0] post_i1_sum_adc;
    reg signed [31:0] post_q1_sum_adc;
    reg post_i0_sum_overflow_adc;
    reg post_q0_sum_overflow_adc;
    reg post_i1_sum_overflow_adc;
    reg post_q1_sum_overflow_adc;
    reg summary_arithmetic_overflow_adc;
    reg summary_corrected_valid_adc;
    reg signed [63:0] post_rx0_power_n_adc;
    reg signed [63:0] post_rx1_power_n_adc;
    reg signed [63:0] post_cross_re_n_adc;
    reg signed [63:0] post_cross_im_n_adc;
    reg signed [63:0] post_i0_square_adc;
    reg signed [63:0] post_q0_square_adc;
    reg signed [63:0] post_i1_square_adc;
    reg signed [63:0] post_q1_square_adc;
    reg signed [63:0] post_i0_i1_product_adc;
    reg signed [63:0] post_q0_q1_product_adc;
    reg signed [63:0] post_q0_i1_product_adc;
    reg signed [63:0] post_i0_q1_product_adc;
    reg signed [63:0] rx0_corr_power_num_stage_adc;
    reg signed [63:0] rx1_corr_power_num_stage_adc;
    reg signed [63:0] corr_cross_re_num_stage_adc;
    reg signed [63:0] corr_cross_im_num_stage_adc;
    reg [15:0] rx0_i_clip_count_adc;
    reg [15:0] rx0_q_clip_count_adc;
    reg [15:0] rx1_i_clip_count_adc;
    reg [15:0] rx1_q_clip_count_adc;
    reg [15:0] rx0_i_zero_cross_count_adc;
    reg [15:0] rx0_q_zero_cross_count_adc;
    reg [15:0] rx1_i_zero_cross_count_adc;
    reg [15:0] rx1_q_zero_cross_count_adc;
    reg [15:0] same_i_sign_count_adc;
    reg [15:0] same_q_sign_count_adc;
    reg [15:0] i0q0_same_sign_count_adc;
    reg [15:0] i1q1_same_sign_count_adc;
    reg prev_valid_adc;
    reg prev_i0_sign_adc;
    reg prev_q0_sign_adc;
    reg prev_i1_sign_adc;
    reg prev_q1_sign_adc;
    reg [15:0] summary_rx0_i_clip_count_adc;
    reg [15:0] summary_rx0_q_clip_count_adc;
    reg [15:0] summary_rx1_i_clip_count_adc;
    reg [15:0] summary_rx1_q_clip_count_adc;
    reg [15:0] summary_rx0_i_zero_cross_count_adc;
    reg [15:0] summary_rx0_q_zero_cross_count_adc;
    reg [15:0] summary_rx1_i_zero_cross_count_adc;
    reg [15:0] summary_rx1_q_zero_cross_count_adc;
    reg [15:0] summary_same_i_sign_count_adc;
    reg [15:0] summary_same_q_sign_count_adc;
    reg [15:0] summary_i0q0_same_sign_count_adc;
    reg [15:0] summary_i1q1_same_sign_count_adc;
    reg agg_done_adc;
    reg agg_overflow_adc;
    reg [31:0] agg_frame_count_adc;
    reg [31:0] agg_sample_count_adc;
    reg signed [95:0] agg_rx0_corr_power_num_adc;
    reg signed [95:0] agg_rx1_corr_power_num_adc;
    reg signed [95:0] agg_corr_cross_re_num_adc;
    reg signed [95:0] agg_corr_cross_im_num_adc;
    reg [95:0] agg_rx0_raw_power_adc;
    reg [95:0] agg_rx1_raw_power_adc;
    reg [31:0] agg_rx0_clip_count_adc;
    reg [31:0] agg_rx1_clip_count_adc;
    reg [31:0] agg_rx0_zero_cross_count_adc;
    reg [31:0] agg_rx1_zero_cross_count_adc;
    reg [31:0] agg_same_sign_count_adc;
    reg [31:0] agg_last_frame_adc;
    reg [31:0] agg_sequence_adc;
    reg agg_update_toggle_adc;
    reg agg_latched_done_adc;
    reg agg_latched_overflow_adc;
    reg [31:0] agg_latched_frame_count_adc;
    reg [31:0] agg_latched_sample_count_adc;
    reg signed [95:0] agg_latched_rx0_corr_power_num_adc;
    reg signed [95:0] agg_latched_rx1_corr_power_num_adc;
    reg signed [95:0] agg_latched_corr_cross_re_num_adc;
    reg signed [95:0] agg_latched_corr_cross_im_num_adc;
    reg [95:0] agg_latched_rx0_raw_power_adc;
    reg [95:0] agg_latched_rx1_raw_power_adc;
    reg [31:0] agg_latched_rx0_clip_count_adc;
    reg [31:0] agg_latched_rx1_clip_count_adc;
    reg [31:0] agg_latched_rx0_zero_cross_count_adc;
    reg [31:0] agg_latched_rx1_zero_cross_count_adc;
    reg [31:0] agg_latched_same_sign_count_adc;
    reg [31:0] agg_latched_last_frame_adc;
    reg [31:0] agg_latched_sequence_adc;

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
    reg summary_arithmetic_overflow_axi;
    reg summary_corrected_valid_axi;
    reg [31:0] summary_frame_count_axi;
    reg [39:0] summary_last_power_axi;
    reg [6:0]  summary_snapshot_count_axi;
    reg [5:0]  snapshot_index_axi;
    reg [15:0] summary_rx0_i_clip_count_axi;
    reg [15:0] summary_rx0_q_clip_count_axi;
    reg [15:0] summary_rx1_i_clip_count_axi;
    reg [15:0] summary_rx1_q_clip_count_axi;
    reg [15:0] summary_rx0_i_zero_cross_count_axi;
    reg [15:0] summary_rx0_q_zero_cross_count_axi;
    reg [15:0] summary_rx1_i_zero_cross_count_axi;
    reg [15:0] summary_rx1_q_zero_cross_count_axi;
    reg [15:0] summary_same_i_sign_count_axi;
    reg [15:0] summary_same_q_sign_count_axi;
    reg [15:0] summary_i0q0_same_sign_count_axi;
    reg [15:0] summary_i1q1_same_sign_count_axi;
    reg agg_done_axi;
    reg agg_overflow_axi;
    reg [31:0] agg_frame_count_axi;
    reg [31:0] agg_sample_count_axi;
    reg signed [95:0] agg_rx0_corr_power_num_axi;
    reg signed [95:0] agg_rx1_corr_power_num_axi;
    reg signed [95:0] agg_corr_cross_re_num_axi;
    reg signed [95:0] agg_corr_cross_im_num_axi;
    reg [95:0] agg_rx0_raw_power_axi;
    reg [95:0] agg_rx1_raw_power_axi;
    reg [31:0] agg_rx0_clip_count_axi;
    reg [31:0] agg_rx1_clip_count_axi;
    reg [31:0] agg_rx0_zero_cross_count_axi;
    reg [31:0] agg_rx1_zero_cross_count_axi;
    reg [31:0] agg_same_sign_count_axi;
    reg [31:0] agg_last_frame_axi;
    reg [31:0] agg_sequence_axi;

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
    wire [15:0] agg_target_frames_adc = (agg_target_sync_adc == 16'd0) ? 16'd1 : agg_target_sync_adc;
    wire agg_target_done_next = ((agg_frame_count_adc + 32'd1) >= {16'd0, agg_target_frames_adc});
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
    wire signed [63:0] post_i0_square_next = post_i0_sum_adc * post_i0_sum_adc;
    wire signed [63:0] post_q0_square_next = post_q0_sum_adc * post_q0_sum_adc;
    wire signed [63:0] post_i1_square_next = post_i1_sum_adc * post_i1_sum_adc;
    wire signed [63:0] post_q1_square_next = post_q1_sum_adc * post_q1_sum_adc;
    wire signed [63:0] post_i0_i1_product_next = post_i0_sum_adc * post_i1_sum_adc;
    wire signed [63:0] post_q0_q1_product_next = post_q0_sum_adc * post_q1_sum_adc;
    wire signed [63:0] post_q0_i1_product_next = post_q0_sum_adc * post_i1_sum_adc;
    wire signed [63:0] post_i0_q1_product_next = post_i0_sum_adc * post_q1_sum_adc;
    wire signed [63:0] rx0_corr_power_num_next = rx0_corr_power_num_stage_adc - post_q0_square_adc;
    wire signed [63:0] rx1_corr_power_num_next = rx1_corr_power_num_stage_adc - post_q1_square_adc;
    wire signed [63:0] corr_cross_re_num_next = corr_cross_re_num_stage_adc - post_q0_q1_product_adc;
    wire signed [63:0] corr_cross_im_num_next = corr_cross_im_num_stage_adc + post_i0_q1_product_adc;
    wire i0_sum_fits_s32_adc = (i0_sum_adc[47:31] == 17'h00000) || (i0_sum_adc[47:31] == 17'h1ffff);
    wire q0_sum_fits_s32_adc = (q0_sum_adc[47:31] == 17'h00000) || (q0_sum_adc[47:31] == 17'h1ffff);
    wire i1_sum_fits_s32_adc = (i1_sum_adc[47:31] == 17'h00000) || (i1_sum_adc[47:31] == 17'h1ffff);
    wire q1_sum_fits_s32_adc = (q1_sum_adc[47:31] == 17'h00000) || (q1_sum_adc[47:31] == 17'h1ffff);
    wire corrected_valid_next_adc = i0_sum_fits_s32_adc && q0_sum_fits_s32_adc && i1_sum_fits_s32_adc && q1_sum_fits_s32_adc;
    wire agg_bad_frame_adc = !corrected_valid_next_adc;
    wire adc_i_clip = ((!adc_i[15]) && (&adc_i[14:4])) || (adc_i[15] && (~|adc_i[14:4]));
    wire adc_q_clip = ((!adc_q[15]) && (&adc_q[14:4])) || (adc_q[15] && (~|adc_q[14:4]));
    wire adc_i1_clip = ((!adc_i1[15]) && (&adc_i1[14:4])) || (adc_i1[15] && (~|adc_i1[14:4]));
    wire adc_q1_clip = ((!adc_q1[15]) && (&adc_q1[14:4])) || (adc_q1[15] && (~|adc_q1[14:4]));
    wire [15:0] rx0_i_clip_count_next = rx0_i_clip_count_adc + {15'd0, adc_i_clip};
    wire [15:0] rx0_q_clip_count_next = rx0_q_clip_count_adc + {15'd0, adc_q_clip};
    wire [15:0] rx1_i_clip_count_next = rx1_i_clip_count_adc + {15'd0, adc_i1_clip};
    wire [15:0] rx1_q_clip_count_next = rx1_q_clip_count_adc + {15'd0, adc_q1_clip};
    wire [15:0] rx0_i_zero_cross_count_next = rx0_i_zero_cross_count_adc + {15'd0, prev_valid_adc && (prev_i0_sign_adc != adc_i[15])};
    wire [15:0] rx0_q_zero_cross_count_next = rx0_q_zero_cross_count_adc + {15'd0, prev_valid_adc && (prev_q0_sign_adc != adc_q[15])};
    wire [15:0] rx1_i_zero_cross_count_next = rx1_i_zero_cross_count_adc + {15'd0, prev_valid_adc && (prev_i1_sign_adc != adc_i1[15])};
    wire [15:0] rx1_q_zero_cross_count_next = rx1_q_zero_cross_count_adc + {15'd0, prev_valid_adc && (prev_q1_sign_adc != adc_q1[15])};
    wire [15:0] same_i_sign_count_next = same_i_sign_count_adc + {15'd0, adc_i[15] == adc_i1[15]};
    wire [15:0] same_q_sign_count_next = same_q_sign_count_adc + {15'd0, adc_q[15] == adc_q1[15]};
    wire [15:0] i0q0_same_sign_count_next = i0q0_same_sign_count_adc + {15'd0, adc_i[15] == adc_q[15]};
    wire [15:0] i1q1_same_sign_count_next = i1q1_same_sign_count_adc + {15'd0, adc_i1[15] == adc_q1[15]};
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
            agg_enable_meta_adc <= 1'b0;
            agg_enable_sync_adc <= 1'b0;
            agg_target_meta_adc <= 16'd16;
            agg_target_sync_adc <= 16'd16;
            agg_clear_meta_adc <= 1'b0;
            agg_clear_sync_adc <= 1'b0;
            agg_auto_meta_adc <= 1'b0;
            agg_auto_sync_adc <= 1'b0;
            agg_clear_seen_adc <= 1'b0;
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
            post_i0_sum_adc <= 32'sd0;
            post_q0_sum_adc <= 32'sd0;
            post_i1_sum_adc <= 32'sd0;
            post_q1_sum_adc <= 32'sd0;
            post_i0_sum_overflow_adc <= 1'b0;
            post_q0_sum_overflow_adc <= 1'b0;
            post_i1_sum_overflow_adc <= 1'b0;
            post_q1_sum_overflow_adc <= 1'b0;
            summary_arithmetic_overflow_adc <= 1'b0;
            summary_corrected_valid_adc <= 1'b0;
            post_rx0_power_n_adc <= 64'sd0;
            post_rx1_power_n_adc <= 64'sd0;
            post_cross_re_n_adc <= 64'sd0;
            post_cross_im_n_adc <= 64'sd0;
            post_i0_square_adc <= 64'sd0;
            post_q0_square_adc <= 64'sd0;
            post_i1_square_adc <= 64'sd0;
            post_q1_square_adc <= 64'sd0;
            post_i0_i1_product_adc <= 64'sd0;
            post_q0_q1_product_adc <= 64'sd0;
            post_q0_i1_product_adc <= 64'sd0;
            post_i0_q1_product_adc <= 64'sd0;
            rx0_corr_power_num_stage_adc <= 64'sd0;
            rx1_corr_power_num_stage_adc <= 64'sd0;
            corr_cross_re_num_stage_adc <= 64'sd0;
            corr_cross_im_num_stage_adc <= 64'sd0;
            rx0_i_clip_count_adc <= 16'd0;
            rx0_q_clip_count_adc <= 16'd0;
            rx1_i_clip_count_adc <= 16'd0;
            rx1_q_clip_count_adc <= 16'd0;
            rx0_i_zero_cross_count_adc <= 16'd0;
            rx0_q_zero_cross_count_adc <= 16'd0;
            rx1_i_zero_cross_count_adc <= 16'd0;
            rx1_q_zero_cross_count_adc <= 16'd0;
            same_i_sign_count_adc <= 16'd0;
            same_q_sign_count_adc <= 16'd0;
            i0q0_same_sign_count_adc <= 16'd0;
            i1q1_same_sign_count_adc <= 16'd0;
            prev_valid_adc <= 1'b0;
            prev_i0_sign_adc <= 1'b0;
            prev_q0_sign_adc <= 1'b0;
            prev_i1_sign_adc <= 1'b0;
            prev_q1_sign_adc <= 1'b0;
            summary_rx0_i_clip_count_adc <= 16'd0;
            summary_rx0_q_clip_count_adc <= 16'd0;
            summary_rx1_i_clip_count_adc <= 16'd0;
            summary_rx1_q_clip_count_adc <= 16'd0;
            summary_rx0_i_zero_cross_count_adc <= 16'd0;
            summary_rx0_q_zero_cross_count_adc <= 16'd0;
            summary_rx1_i_zero_cross_count_adc <= 16'd0;
            summary_rx1_q_zero_cross_count_adc <= 16'd0;
            summary_same_i_sign_count_adc <= 16'd0;
            summary_same_q_sign_count_adc <= 16'd0;
            summary_i0q0_same_sign_count_adc <= 16'd0;
            summary_i1q1_same_sign_count_adc <= 16'd0;
            agg_done_adc <= 1'b0;
            agg_overflow_adc <= 1'b0;
            agg_frame_count_adc <= 32'd0;
            agg_sample_count_adc <= 32'd0;
            agg_rx0_corr_power_num_adc <= 96'sd0;
            agg_rx1_corr_power_num_adc <= 96'sd0;
            agg_corr_cross_re_num_adc <= 96'sd0;
            agg_corr_cross_im_num_adc <= 96'sd0;
            agg_rx0_raw_power_adc <= 96'd0;
            agg_rx1_raw_power_adc <= 96'd0;
            agg_rx0_clip_count_adc <= 32'd0;
            agg_rx1_clip_count_adc <= 32'd0;
            agg_rx0_zero_cross_count_adc <= 32'd0;
            agg_rx1_zero_cross_count_adc <= 32'd0;
            agg_same_sign_count_adc <= 32'd0;
            agg_last_frame_adc <= 32'd0;
            agg_sequence_adc <= 32'd0;
            agg_update_toggle_adc <= 1'b0;
            agg_latched_done_adc <= 1'b0;
            agg_latched_overflow_adc <= 1'b0;
            agg_latched_frame_count_adc <= 32'd0;
            agg_latched_sample_count_adc <= 32'd0;
            agg_latched_rx0_corr_power_num_adc <= 96'sd0;
            agg_latched_rx1_corr_power_num_adc <= 96'sd0;
            agg_latched_corr_cross_re_num_adc <= 96'sd0;
            agg_latched_corr_cross_im_num_adc <= 96'sd0;
            agg_latched_rx0_raw_power_adc <= 96'd0;
            agg_latched_rx1_raw_power_adc <= 96'd0;
            agg_latched_rx0_clip_count_adc <= 32'd0;
            agg_latched_rx1_clip_count_adc <= 32'd0;
            agg_latched_rx0_zero_cross_count_adc <= 32'd0;
            agg_latched_rx1_zero_cross_count_adc <= 32'd0;
            agg_latched_same_sign_count_adc <= 32'd0;
            agg_latched_last_frame_adc <= 32'd0;
            agg_latched_sequence_adc <= 32'd0;
        end else begin
            enable_meta_adc <= enable_axi;
            enable_sync_adc <= enable_meta_adc;
            frame_len_meta_adc <= frame_len_axi;
            frame_len_sync_adc <= frame_len_meta_adc;
            clear_meta_adc <= clear_toggle_axi;
            clear_sync_adc <= clear_meta_adc;
            agg_enable_meta_adc <= agg_enable_axi;
            agg_enable_sync_adc <= agg_enable_meta_adc;
            agg_target_meta_adc <= agg_target_frames_axi;
            agg_target_sync_adc <= agg_target_meta_adc;
            agg_clear_meta_adc <= agg_clear_toggle_axi;
            agg_clear_sync_adc <= agg_clear_meta_adc;
            agg_auto_meta_adc <= agg_auto_axi;
            agg_auto_sync_adc <= agg_auto_meta_adc;
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
                summary_arithmetic_overflow_adc <= 1'b0;
                summary_corrected_valid_adc <= 1'b0;
                agg_done_adc <= 1'b0;
                agg_overflow_adc <= 1'b0;
                agg_frame_count_adc <= 32'd0;
                agg_sample_count_adc <= 32'd0;
                agg_rx0_corr_power_num_adc <= 96'sd0;
                agg_rx1_corr_power_num_adc <= 96'sd0;
                agg_corr_cross_re_num_adc <= 96'sd0;
                agg_corr_cross_im_num_adc <= 96'sd0;
                agg_rx0_raw_power_adc <= 96'd0;
                agg_rx1_raw_power_adc <= 96'd0;
                agg_rx0_clip_count_adc <= 32'd0;
                agg_rx1_clip_count_adc <= 32'd0;
                agg_rx0_zero_cross_count_adc <= 32'd0;
                agg_rx1_zero_cross_count_adc <= 32'd0;
                agg_same_sign_count_adc <= 32'd0;
                agg_last_frame_adc <= 32'd0;
                agg_sequence_adc <= 32'd0;
                agg_update_toggle_adc <= 1'b0;
                agg_latched_done_adc <= 1'b0;
                agg_latched_overflow_adc <= 1'b0;
                agg_latched_frame_count_adc <= 32'd0;
                agg_latched_sample_count_adc <= 32'd0;
                agg_latched_rx0_corr_power_num_adc <= 96'sd0;
                agg_latched_rx1_corr_power_num_adc <= 96'sd0;
                agg_latched_corr_cross_re_num_adc <= 96'sd0;
                agg_latched_corr_cross_im_num_adc <= 96'sd0;
                agg_latched_rx0_raw_power_adc <= 96'd0;
                agg_latched_rx1_raw_power_adc <= 96'd0;
                agg_latched_rx0_clip_count_adc <= 32'd0;
                agg_latched_rx1_clip_count_adc <= 32'd0;
                agg_latched_rx0_zero_cross_count_adc <= 32'd0;
                agg_latched_rx1_zero_cross_count_adc <= 32'd0;
                agg_latched_same_sign_count_adc <= 32'd0;
                agg_latched_last_frame_adc <= 32'd0;
                agg_latched_sequence_adc <= 32'd0;
                rx0_i_clip_count_adc <= 16'd0;
                rx0_q_clip_count_adc <= 16'd0;
                rx1_i_clip_count_adc <= 16'd0;
                rx1_q_clip_count_adc <= 16'd0;
                rx0_i_zero_cross_count_adc <= 16'd0;
                rx0_q_zero_cross_count_adc <= 16'd0;
                rx1_i_zero_cross_count_adc <= 16'd0;
                rx1_q_zero_cross_count_adc <= 16'd0;
                same_i_sign_count_adc <= 16'd0;
                same_q_sign_count_adc <= 16'd0;
                i0q0_same_sign_count_adc <= 16'd0;
                i1q1_same_sign_count_adc <= 16'd0;
                prev_valid_adc <= 1'b0;
                prev_i0_sign_adc <= 1'b0;
                prev_q0_sign_adc <= 1'b0;
                prev_i1_sign_adc <= 1'b0;
                prev_q1_sign_adc <= 1'b0;
            end else if (agg_clear_sync_adc != agg_clear_seen_adc) begin
                agg_clear_seen_adc <= agg_clear_sync_adc;
                agg_done_adc <= 1'b0;
                agg_overflow_adc <= 1'b0;
                agg_frame_count_adc <= 32'd0;
                agg_sample_count_adc <= 32'd0;
                agg_rx0_corr_power_num_adc <= 96'sd0;
                agg_rx1_corr_power_num_adc <= 96'sd0;
                agg_corr_cross_re_num_adc <= 96'sd0;
                agg_corr_cross_im_num_adc <= 96'sd0;
                agg_rx0_raw_power_adc <= 96'd0;
                agg_rx1_raw_power_adc <= 96'd0;
                agg_rx0_clip_count_adc <= 32'd0;
                agg_rx1_clip_count_adc <= 32'd0;
                agg_rx0_zero_cross_count_adc <= 32'd0;
                agg_rx1_zero_cross_count_adc <= 32'd0;
                agg_same_sign_count_adc <= 32'd0;
                agg_last_frame_adc <= 32'd0;
                agg_sequence_adc <= 32'd0;
                agg_update_toggle_adc <= 1'b0;
                agg_latched_done_adc <= 1'b0;
                agg_latched_overflow_adc <= 1'b0;
                agg_latched_frame_count_adc <= 32'd0;
                agg_latched_sample_count_adc <= 32'd0;
                agg_latched_rx0_corr_power_num_adc <= 96'sd0;
                agg_latched_rx1_corr_power_num_adc <= 96'sd0;
                agg_latched_corr_cross_re_num_adc <= 96'sd0;
                agg_latched_corr_cross_im_num_adc <= 96'sd0;
                agg_latched_rx0_raw_power_adc <= 96'd0;
                agg_latched_rx1_raw_power_adc <= 96'd0;
                agg_latched_rx0_clip_count_adc <= 32'd0;
                agg_latched_rx1_clip_count_adc <= 32'd0;
                agg_latched_rx0_zero_cross_count_adc <= 32'd0;
                agg_latched_rx1_zero_cross_count_adc <= 32'd0;
                agg_latched_same_sign_count_adc <= 32'd0;
                agg_latched_last_frame_adc <= 32'd0;
                agg_latched_sequence_adc <= 32'd0;
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
                    rx0_i_clip_count_adc <= rx0_i_clip_count_next;
                    rx0_q_clip_count_adc <= rx0_q_clip_count_next;
                    rx1_i_clip_count_adc <= rx1_i_clip_count_next;
                    rx1_q_clip_count_adc <= rx1_q_clip_count_next;
                    rx0_i_zero_cross_count_adc <= rx0_i_zero_cross_count_next;
                    rx0_q_zero_cross_count_adc <= rx0_q_zero_cross_count_next;
                    rx1_i_zero_cross_count_adc <= rx1_i_zero_cross_count_next;
                    rx1_q_zero_cross_count_adc <= rx1_q_zero_cross_count_next;
                    same_i_sign_count_adc <= same_i_sign_count_next;
                    same_q_sign_count_adc <= same_q_sign_count_next;
                    i0q0_same_sign_count_adc <= i0q0_same_sign_count_next;
                    i1q1_same_sign_count_adc <= i1q1_same_sign_count_next;
                    prev_valid_adc <= 1'b1;
                    prev_i0_sign_adc <= adc_i[15];
                    prev_q0_sign_adc <= adc_q[15];
                    prev_i1_sign_adc <= adc_i1[15];
                    prev_q1_sign_adc <= adc_q1[15];
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
                        frame_closing_adc <= agg_enable_sync_adc;
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
                        summary_rx0_i_clip_count_adc <= rx0_i_clip_count_next;
                        summary_rx0_q_clip_count_adc <= rx0_q_clip_count_next;
                        summary_rx1_i_clip_count_adc <= rx1_i_clip_count_next;
                        summary_rx1_q_clip_count_adc <= rx1_q_clip_count_next;
                        summary_rx0_i_zero_cross_count_adc <= rx0_i_zero_cross_count_next;
                        summary_rx0_q_zero_cross_count_adc <= rx0_q_zero_cross_count_next;
                        summary_rx1_i_zero_cross_count_adc <= rx1_i_zero_cross_count_next;
                        summary_rx1_q_zero_cross_count_adc <= rx1_q_zero_cross_count_next;
                        summary_same_i_sign_count_adc <= same_i_sign_count_next;
                        summary_same_q_sign_count_adc <= same_q_sign_count_next;
                        summary_i0q0_same_sign_count_adc <= i0q0_same_sign_count_next;
                        summary_i1q1_same_sign_count_adc <= i1q1_same_sign_count_next;
                        post_sample_count_adc <= final_sample_count_adc;
                        post_rx0_power_adc <= sum_power_next;
                        post_rx1_power_adc <= rx1_sum_power_next;
                        post_cross_re_adc <= cross_re_sum_next;
                        post_cross_im_adc <= cross_im_sum_next;
                        post_i0_sum_adc <= i0_sum_adc[31:0];
                        post_q0_sum_adc <= q0_sum_adc[31:0];
                        post_i1_sum_adc <= i1_sum_adc[31:0];
                        post_q1_sum_adc <= q1_sum_adc[31:0];
                        post_i0_sum_overflow_adc <= !i0_sum_fits_s32_adc;
                        post_q0_sum_overflow_adc <= !q0_sum_fits_s32_adc;
                        post_i1_sum_overflow_adc <= !i1_sum_fits_s32_adc;
                        post_q1_sum_overflow_adc <= !q1_sum_fits_s32_adc;
                        summary_arithmetic_overflow_adc <= !i0_sum_fits_s32_adc || !q0_sum_fits_s32_adc || !i1_sum_fits_s32_adc || !q1_sum_fits_s32_adc;
                        summary_corrected_valid_adc <= i0_sum_fits_s32_adc && q0_sum_fits_s32_adc && i1_sum_fits_s32_adc && q1_sum_fits_s32_adc;
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
                        rx0_corr_power_num_stage_adc <= post_rx0_power_n_adc - post_i0_square_adc;
                        rx1_corr_power_num_stage_adc <= post_rx1_power_n_adc - post_i1_square_adc;
                        corr_cross_re_num_stage_adc <= post_cross_re_n_adc - post_i0_i1_product_adc;
                        corr_cross_im_num_stage_adc <= post_cross_im_n_adc - post_q0_i1_product_adc;
                        post_state_adc <= 3'd3;
                    end
                    3'd3: begin
                        summary_rx0_corr_power_num_adc <= rx0_corr_power_num_next;
                        summary_rx1_corr_power_num_adc <= rx1_corr_power_num_next;
                        summary_corr_cross_re_num_adc <= corr_cross_re_num_next;
                        summary_corr_cross_im_num_adc <= corr_cross_im_num_next;
                        if (agg_enable_sync_adc && (!agg_done_adc || agg_auto_sync_adc) && corrected_valid_next_adc) begin
                            agg_frame_count_adc <= agg_frame_count_adc + 32'd1;
                            agg_sample_count_adc <= agg_sample_count_adc + {16'd0, post_sample_count_adc};
                            agg_rx0_corr_power_num_adc <= agg_rx0_corr_power_num_adc + {{32{rx0_corr_power_num_next[63]}}, rx0_corr_power_num_next};
                            agg_rx1_corr_power_num_adc <= agg_rx1_corr_power_num_adc + {{32{rx1_corr_power_num_next[63]}}, rx1_corr_power_num_next};
                            agg_corr_cross_re_num_adc <= agg_corr_cross_re_num_adc + {{32{corr_cross_re_num_next[63]}}, corr_cross_re_num_next};
                            agg_corr_cross_im_num_adc <= agg_corr_cross_im_num_adc + {{32{corr_cross_im_num_next[63]}}, corr_cross_im_num_next};
                            agg_rx0_raw_power_adc <= agg_rx0_raw_power_adc + {48'd0, post_rx0_power_adc};
                            agg_rx1_raw_power_adc <= agg_rx1_raw_power_adc + {48'd0, post_rx1_power_adc};
                            agg_rx0_clip_count_adc <= agg_rx0_clip_count_adc + {16'd0, summary_rx0_i_clip_count_adc} + {16'd0, summary_rx0_q_clip_count_adc};
                            agg_rx1_clip_count_adc <= agg_rx1_clip_count_adc + {16'd0, summary_rx1_i_clip_count_adc} + {16'd0, summary_rx1_q_clip_count_adc};
                            agg_rx0_zero_cross_count_adc <= agg_rx0_zero_cross_count_adc + {16'd0, summary_rx0_i_zero_cross_count_adc} + {16'd0, summary_rx0_q_zero_cross_count_adc};
                            agg_rx1_zero_cross_count_adc <= agg_rx1_zero_cross_count_adc + {16'd0, summary_rx1_i_zero_cross_count_adc} + {16'd0, summary_rx1_q_zero_cross_count_adc};
                            agg_same_sign_count_adc <= agg_same_sign_count_adc + {16'd0, summary_same_i_sign_count_adc} + {16'd0, summary_same_q_sign_count_adc};
                            agg_last_frame_adc <= summary_frame_count_adc;
                            if (agg_target_done_next) begin
                                agg_done_adc <= !agg_auto_sync_adc;
                                agg_sequence_adc <= agg_sequence_adc + 32'd1;
                                agg_update_toggle_adc <= !agg_update_toggle_adc;
                                agg_latched_done_adc <= 1'b1;
                                agg_latched_overflow_adc <= agg_overflow_adc;
                                agg_latched_frame_count_adc <= agg_frame_count_adc + 32'd1;
                                agg_latched_sample_count_adc <= agg_sample_count_adc + {16'd0, post_sample_count_adc};
                                agg_latched_rx0_corr_power_num_adc <= agg_rx0_corr_power_num_adc + {{32{rx0_corr_power_num_next[63]}}, rx0_corr_power_num_next};
                                agg_latched_rx1_corr_power_num_adc <= agg_rx1_corr_power_num_adc + {{32{rx1_corr_power_num_next[63]}}, rx1_corr_power_num_next};
                                agg_latched_corr_cross_re_num_adc <= agg_corr_cross_re_num_adc + {{32{corr_cross_re_num_next[63]}}, corr_cross_re_num_next};
                                agg_latched_corr_cross_im_num_adc <= agg_corr_cross_im_num_adc + {{32{corr_cross_im_num_next[63]}}, corr_cross_im_num_next};
                                agg_latched_rx0_raw_power_adc <= agg_rx0_raw_power_adc + {48'd0, post_rx0_power_adc};
                                agg_latched_rx1_raw_power_adc <= agg_rx1_raw_power_adc + {48'd0, post_rx1_power_adc};
                                agg_latched_rx0_clip_count_adc <= agg_rx0_clip_count_adc + {16'd0, summary_rx0_i_clip_count_adc} + {16'd0, summary_rx0_q_clip_count_adc};
                                agg_latched_rx1_clip_count_adc <= agg_rx1_clip_count_adc + {16'd0, summary_rx1_i_clip_count_adc} + {16'd0, summary_rx1_q_clip_count_adc};
                                agg_latched_rx0_zero_cross_count_adc <= agg_rx0_zero_cross_count_adc + {16'd0, summary_rx0_i_zero_cross_count_adc} + {16'd0, summary_rx0_q_zero_cross_count_adc};
                                agg_latched_rx1_zero_cross_count_adc <= agg_rx1_zero_cross_count_adc + {16'd0, summary_rx1_i_zero_cross_count_adc} + {16'd0, summary_rx1_q_zero_cross_count_adc};
                                agg_latched_same_sign_count_adc <= agg_same_sign_count_adc + {16'd0, summary_same_i_sign_count_adc} + {16'd0, summary_same_q_sign_count_adc};
                                agg_latched_last_frame_adc <= summary_frame_count_adc;
                                agg_latched_sequence_adc <= agg_sequence_adc + 32'd1;
                                if (agg_auto_sync_adc) begin
                                    agg_overflow_adc <= 1'b0;
                                    agg_frame_count_adc <= 32'd0;
                                    agg_sample_count_adc <= 32'd0;
                                    agg_rx0_corr_power_num_adc <= 96'sd0;
                                    agg_rx1_corr_power_num_adc <= 96'sd0;
                                    agg_corr_cross_re_num_adc <= 96'sd0;
                                    agg_corr_cross_im_num_adc <= 96'sd0;
                                    agg_rx0_raw_power_adc <= 96'd0;
                                    agg_rx1_raw_power_adc <= 96'd0;
                                    agg_rx0_clip_count_adc <= 32'd0;
                                    agg_rx1_clip_count_adc <= 32'd0;
                                    agg_rx0_zero_cross_count_adc <= 32'd0;
                                    agg_rx1_zero_cross_count_adc <= 32'd0;
                                    agg_same_sign_count_adc <= 32'd0;
                                    agg_last_frame_adc <= 32'd0;
                                end
                            end
                        end else if (agg_enable_sync_adc && (!agg_done_adc || agg_auto_sync_adc)) begin
                            agg_overflow_adc <= !agg_auto_sync_adc;
                            agg_sequence_adc <= agg_sequence_adc + 32'd1;
                            agg_update_toggle_adc <= !agg_update_toggle_adc;
                            agg_latched_done_adc <= 1'b1;
                            agg_latched_overflow_adc <= 1'b1;
                            agg_latched_frame_count_adc <= agg_frame_count_adc;
                            agg_latched_sample_count_adc <= agg_sample_count_adc;
                            agg_latched_rx0_corr_power_num_adc <= agg_rx0_corr_power_num_adc;
                            agg_latched_rx1_corr_power_num_adc <= agg_rx1_corr_power_num_adc;
                            agg_latched_corr_cross_re_num_adc <= agg_corr_cross_re_num_adc;
                            agg_latched_corr_cross_im_num_adc <= agg_corr_cross_im_num_adc;
                            agg_latched_rx0_raw_power_adc <= agg_rx0_raw_power_adc;
                            agg_latched_rx1_raw_power_adc <= agg_rx1_raw_power_adc;
                            agg_latched_rx0_clip_count_adc <= agg_rx0_clip_count_adc;
                            agg_latched_rx1_clip_count_adc <= agg_rx1_clip_count_adc;
                            agg_latched_rx0_zero_cross_count_adc <= agg_rx0_zero_cross_count_adc;
                            agg_latched_rx1_zero_cross_count_adc <= agg_rx1_zero_cross_count_adc;
                            agg_latched_same_sign_count_adc <= agg_same_sign_count_adc;
                            agg_latched_last_frame_adc <= summary_frame_count_adc;
                            agg_latched_sequence_adc <= agg_sequence_adc + 32'd1;
                            if (agg_auto_sync_adc) begin
                                agg_frame_count_adc <= 32'd0;
                                agg_sample_count_adc <= 32'd0;
                                agg_rx0_corr_power_num_adc <= 96'sd0;
                                agg_rx1_corr_power_num_adc <= 96'sd0;
                                agg_corr_cross_re_num_adc <= 96'sd0;
                                agg_corr_cross_im_num_adc <= 96'sd0;
                                agg_rx0_raw_power_adc <= 96'd0;
                                agg_rx1_raw_power_adc <= 96'd0;
                                agg_rx0_clip_count_adc <= 32'd0;
                                agg_rx1_clip_count_adc <= 32'd0;
                                agg_rx0_zero_cross_count_adc <= 32'd0;
                                agg_rx1_zero_cross_count_adc <= 32'd0;
                                agg_same_sign_count_adc <= 32'd0;
                                agg_last_frame_adc <= 32'd0;
                            end
                        end
                        if (!agg_enable_sync_adc || agg_done_adc || agg_target_done_next || agg_bad_frame_adc) begin
                            pending_adc <= 1'b1;
                        end else begin
                            pending_adc <= 1'b0;
                        end
                        if (agg_enable_sync_adc) begin
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
                            rx0_i_clip_count_adc <= 16'd0;
                            rx0_q_clip_count_adc <= 16'd0;
                            rx1_i_clip_count_adc <= 16'd0;
                            rx1_q_clip_count_adc <= 16'd0;
                            rx0_i_zero_cross_count_adc <= 16'd0;
                            rx0_q_zero_cross_count_adc <= 16'd0;
                            rx1_i_zero_cross_count_adc <= 16'd0;
                            rx1_q_zero_cross_count_adc <= 16'd0;
                            same_i_sign_count_adc <= 16'd0;
                            same_q_sign_count_adc <= 16'd0;
                            i0q0_same_sign_count_adc <= 16'd0;
                            i1q1_same_sign_count_adc <= 16'd0;
                            prev_valid_adc <= 1'b0;
                            prev_i0_sign_adc <= 1'b0;
                            prev_q0_sign_adc <= 1'b0;
                            prev_i1_sign_adc <= 1'b0;
                            prev_q1_sign_adc <= 1'b0;
                            frame_closing_adc <= 1'b0;
                        end
                        post_state_adc <= 3'd0;
                    end
                    default: begin
                    end
                endcase
            end
        end
    end

    always @(posedge s_axi_aclk) begin
        s_axi_aresetn_ctrl_axi <= s_axi_aresetn;
        if (!s_axi_aresetn_ctrl_axi) begin
            enable_axi <= 1'b0;
            frame_len_axi <= DEFAULT_FRAME_LEN[15:0];
            control_shadow_axi <= 32'd0;
            frame_len_shadow_axi <= DEFAULT_FRAME_LEN;
            clear_toggle_axi <= 1'b0;
            agg_enable_axi <= 1'b0;
            agg_target_frames_axi <= 16'd16;
            agg_control_shadow_axi <= 32'd0;
            agg_clear_toggle_axi <= 1'b0;
            agg_auto_axi <= 1'b0;
            pending_meta_axi <= 1'b0;
            pending_sync_axi <= 1'b0;
            pending_sync_axi_d <= 1'b0;
            agg_update_meta_axi <= 1'b0;
            agg_update_sync_axi <= 1'b0;
            agg_update_sync_axi_d <= 1'b0;
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
            summary_arithmetic_overflow_axi <= 1'b0;
            summary_corrected_valid_axi <= 1'b0;
            summary_frame_count_axi <= 32'd0;
            summary_last_power_axi <= 40'd0;
            summary_snapshot_count_axi <= 7'd0;
            snapshot_index_axi <= 6'd0;
            summary_rx0_i_clip_count_axi <= 16'd0;
            summary_rx0_q_clip_count_axi <= 16'd0;
            summary_rx1_i_clip_count_axi <= 16'd0;
            summary_rx1_q_clip_count_axi <= 16'd0;
            summary_rx0_i_zero_cross_count_axi <= 16'd0;
            summary_rx0_q_zero_cross_count_axi <= 16'd0;
            summary_rx1_i_zero_cross_count_axi <= 16'd0;
            summary_rx1_q_zero_cross_count_axi <= 16'd0;
            summary_same_i_sign_count_axi <= 16'd0;
            summary_same_q_sign_count_axi <= 16'd0;
            summary_i0q0_same_sign_count_axi <= 16'd0;
            summary_i1q1_same_sign_count_axi <= 16'd0;
            agg_done_axi <= 1'b0;
            agg_overflow_axi <= 1'b0;
            agg_frame_count_axi <= 32'd0;
            agg_sample_count_axi <= 32'd0;
            agg_rx0_corr_power_num_axi <= 96'sd0;
            agg_rx1_corr_power_num_axi <= 96'sd0;
            agg_corr_cross_re_num_axi <= 96'sd0;
            agg_corr_cross_im_num_axi <= 96'sd0;
            agg_rx0_raw_power_axi <= 96'd0;
            agg_rx1_raw_power_axi <= 96'd0;
            agg_rx0_clip_count_axi <= 32'd0;
            agg_rx1_clip_count_axi <= 32'd0;
            agg_rx0_zero_cross_count_axi <= 32'd0;
            agg_rx1_zero_cross_count_axi <= 32'd0;
            agg_same_sign_count_axi <= 32'd0;
            agg_last_frame_axi <= 32'd0;
            agg_sequence_axi <= 32'd0;
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
            agg_update_meta_axi <= agg_update_toggle_adc;
            agg_update_sync_axi <= agg_update_meta_axi;
            agg_update_sync_axi_d <= agg_update_sync_axi;
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
                summary_arithmetic_overflow_axi <= summary_arithmetic_overflow_adc;
                summary_corrected_valid_axi <= summary_corrected_valid_adc;
                summary_frame_count_axi <= summary_frame_count_adc;
                summary_last_power_axi <= summary_last_power_adc;
                summary_snapshot_count_axi <= 7'd0;
                summary_rx0_i_clip_count_axi <= summary_rx0_i_clip_count_adc;
                summary_rx0_q_clip_count_axi <= summary_rx0_q_clip_count_adc;
                summary_rx1_i_clip_count_axi <= summary_rx1_i_clip_count_adc;
                summary_rx1_q_clip_count_axi <= summary_rx1_q_clip_count_adc;
                summary_rx0_i_zero_cross_count_axi <= summary_rx0_i_zero_cross_count_adc;
                summary_rx0_q_zero_cross_count_axi <= summary_rx0_q_zero_cross_count_adc;
                summary_rx1_i_zero_cross_count_axi <= summary_rx1_i_zero_cross_count_adc;
                summary_rx1_q_zero_cross_count_axi <= summary_rx1_q_zero_cross_count_adc;
                summary_same_i_sign_count_axi <= summary_same_i_sign_count_adc;
                summary_same_q_sign_count_axi <= summary_same_q_sign_count_adc;
                summary_i0q0_same_sign_count_axi <= summary_i0q0_same_sign_count_adc;
                summary_i1q1_same_sign_count_axi <= summary_i1q1_same_sign_count_adc;
                agg_done_axi <= agg_latched_done_adc;
                agg_overflow_axi <= agg_latched_overflow_adc;
                agg_frame_count_axi <= agg_latched_frame_count_adc;
                agg_sample_count_axi <= agg_latched_sample_count_adc;
                agg_rx0_corr_power_num_axi <= agg_latched_rx0_corr_power_num_adc;
                agg_rx1_corr_power_num_axi <= agg_latched_rx1_corr_power_num_adc;
                agg_corr_cross_re_num_axi <= agg_latched_corr_cross_re_num_adc;
                agg_corr_cross_im_num_axi <= agg_latched_corr_cross_im_num_adc;
                agg_rx0_raw_power_axi <= agg_latched_rx0_raw_power_adc;
                agg_rx1_raw_power_axi <= agg_latched_rx1_raw_power_adc;
                agg_rx0_clip_count_axi <= agg_latched_rx0_clip_count_adc;
                agg_rx1_clip_count_axi <= agg_latched_rx1_clip_count_adc;
                agg_rx0_zero_cross_count_axi <= agg_latched_rx0_zero_cross_count_adc;
                agg_rx1_zero_cross_count_axi <= agg_latched_rx1_zero_cross_count_adc;
                agg_same_sign_count_axi <= agg_latched_same_sign_count_adc;
                agg_last_frame_axi <= agg_latched_last_frame_adc;
                agg_sequence_axi <= agg_latched_sequence_adc;
            end

            if (agg_update_sync_axi != agg_update_sync_axi_d) begin
                agg_done_axi <= agg_latched_done_adc;
                agg_overflow_axi <= agg_latched_overflow_adc;
                agg_frame_count_axi <= agg_latched_frame_count_adc;
                agg_sample_count_axi <= agg_latched_sample_count_adc;
                agg_rx0_corr_power_num_axi <= agg_latched_rx0_corr_power_num_adc;
                agg_rx1_corr_power_num_axi <= agg_latched_rx1_corr_power_num_adc;
                agg_corr_cross_re_num_axi <= agg_latched_corr_cross_re_num_adc;
                agg_corr_cross_im_num_axi <= agg_latched_corr_cross_im_num_adc;
                agg_rx0_raw_power_axi <= agg_latched_rx0_raw_power_adc;
                agg_rx1_raw_power_axi <= agg_latched_rx1_raw_power_adc;
                agg_rx0_clip_count_axi <= agg_latched_rx0_clip_count_adc;
                agg_rx1_clip_count_axi <= agg_latched_rx1_clip_count_adc;
                agg_rx0_zero_cross_count_axi <= agg_latched_rx0_zero_cross_count_adc;
                agg_rx1_zero_cross_count_axi <= agg_latched_rx1_zero_cross_count_adc;
                agg_same_sign_count_axi <= agg_latched_same_sign_count_adc;
                agg_last_frame_axi <= agg_latched_last_frame_adc;
                agg_sequence_axi <= agg_latched_sequence_adc;
            end

            if (!s_axi_bvalid && s_axi_awvalid && s_axi_wvalid) begin
                s_axi_awready <= 1'b1;
                s_axi_wready <= 1'b1;
                s_axi_bresp <= 2'b00;
                s_axi_bvalid <= 1'b1;

                case (s_axi_awaddr[11:0])
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
                    REG_AGG_CONTROL: begin
                        if (s_axi_wstrb[0]) begin
                            agg_control_shadow_axi <= s_axi_wdata;
                            agg_enable_axi <= s_axi_wdata[0];
                            agg_auto_axi <= s_axi_wdata[2];
                            if (s_axi_wdata[1]) begin
                                agg_clear_toggle_axi <= !agg_clear_toggle_axi;
                                agg_done_axi <= 1'b0;
                                agg_overflow_axi <= 1'b0;
                                agg_frame_count_axi <= 32'd0;
                                agg_sample_count_axi <= 32'd0;
                                agg_sequence_axi <= 32'd0;
                            end
                        end
                    end
                    REG_AGG_TARGET: begin
                        if (|s_axi_wstrb) begin
                            agg_target_frames_axi <= (s_axi_wdata[15:0] == 16'd0) ? 16'd1 : s_axi_wdata[15:0];
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
        s_axi_aresetn_read_axi <= s_axi_aresetn;
        if (!s_axi_aresetn_read_axi) begin
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

                case (s_axi_araddr[11:0])
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
                    REG_SUMMARY_VERSION:  s_axi_rdata <= SUMMARY_VERSION_SUM8;
                    REG_SUMMARY_FLAGS:    s_axi_rdata <= {25'd0, 1'b1, summary_corrected_valid_axi, summary_arithmetic_overflow_axi, 1'b0, pending_sync_axi, pending_sync_axi, enable_axi};
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
                    REG_ABI_VERSION:      s_axi_rdata <= SUMMARY_ABI_VERSION;
                    REG_CAPABILITY:       s_axi_rdata <= SUMMARY_CAPABILITY;
                    REG_LIMIT_FLAGS:      s_axi_rdata <= {28'd0, 1'b1, summary_corrected_valid_axi, summary_arithmetic_overflow_axi, 1'b0};
                    REG_MAX_CORR_FRAME:   s_axi_rdata <= SUMMARY_MAX_CORR_FRAME;
                    REG_BUILD_ID:         s_axi_rdata <= SUMMARY_BUILD_ID;
                    REG_QUALITY_VERSION:  s_axi_rdata <= QUALITY_VERSION_SUM8;
                    REG_QUALITY_FLAGS:    s_axi_rdata <= {24'd0, 1'b1, summary_corrected_valid_axi, summary_arithmetic_overflow_axi, 1'b0, pending_sync_axi, pending_sync_axi, enable_axi};
                    REG_QUALITY_FRAME:    s_axi_rdata <= summary_frame_count_axi;
                    REG_QUALITY_SAMPLES:  s_axi_rdata <= {16'd0, summary_sample_count_axi};
                    REG_RX0_CLIP_COUNTS:  s_axi_rdata <= {summary_rx0_q_clip_count_axi, summary_rx0_i_clip_count_axi};
                    REG_RX1_CLIP_COUNTS:  s_axi_rdata <= {summary_rx1_q_clip_count_axi, summary_rx1_i_clip_count_axi};
                    REG_RX0_ZC_COUNTS:    s_axi_rdata <= {summary_rx0_q_zero_cross_count_axi, summary_rx0_i_zero_cross_count_axi};
                    REG_RX1_ZC_COUNTS:    s_axi_rdata <= {summary_rx1_q_zero_cross_count_axi, summary_rx1_i_zero_cross_count_axi};
                    REG_SIGN_SAME_COUNTS: s_axi_rdata <= {summary_same_q_sign_count_axi, summary_same_i_sign_count_axi};
                    REG_QUAD_COUNTS:      s_axi_rdata <= {summary_i1q1_same_sign_count_axi, summary_i0q0_same_sign_count_axi};
                    REG_RX0_ABS_I_SUM:    s_axi_rdata <= 32'd0;
                    REG_RX0_ABS_Q_SUM:    s_axi_rdata <= 32'd0;
                    REG_RX1_ABS_I_SUM:    s_axi_rdata <= 32'd0;
                    REG_RX1_ABS_Q_SUM:    s_axi_rdata <= 32'd0;
                    REG_QUALITY_CAP:      s_axi_rdata <= QUALITY_CAPABILITY;
                    REG_QUALITY_BUILD_ID: s_axi_rdata <= QUALITY_BUILD_ID;
                    REG_AGG_SEQUENCE:     s_axi_rdata <= agg_sequence_axi;
                    REG_AGG_VERSION:      s_axi_rdata <= AGG_VERSION_SUM8;
                    REG_AGG_CONTROL:      s_axi_rdata <= {26'd0, agg_overflow_axi, agg_done_axi, 1'b0, agg_auto_axi, 1'b0, agg_enable_axi};
                    REG_AGG_TARGET:       s_axi_rdata <= {16'd0, agg_target_frames_axi};
                    REG_AGG_FRAMES:       s_axi_rdata <= agg_frame_count_axi;
                    REG_AGG_SAMPLES:      s_axi_rdata <= agg_sample_count_axi;
                    REG_AGG_RX0_CORR_LO:  s_axi_rdata <= agg_rx0_corr_power_num_axi[31:0];
                    REG_AGG_RX0_CORR_MID: s_axi_rdata <= agg_rx0_corr_power_num_axi[63:32];
                    REG_AGG_RX0_CORR_HI:  s_axi_rdata <= agg_rx0_corr_power_num_axi[95:64];
                    REG_AGG_RX1_CORR_LO:  s_axi_rdata <= agg_rx1_corr_power_num_axi[31:0];
                    REG_AGG_RX1_CORR_MID: s_axi_rdata <= agg_rx1_corr_power_num_axi[63:32];
                    REG_AGG_RX1_CORR_HI:  s_axi_rdata <= agg_rx1_corr_power_num_axi[95:64];
                    REG_AGG_CROSS_RE_LO:  s_axi_rdata <= agg_corr_cross_re_num_axi[31:0];
                    REG_AGG_CROSS_RE_MID: s_axi_rdata <= agg_corr_cross_re_num_axi[63:32];
                    REG_AGG_CROSS_RE_HI:  s_axi_rdata <= agg_corr_cross_re_num_axi[95:64];
                    REG_AGG_CROSS_IM_LO:  s_axi_rdata <= agg_corr_cross_im_num_axi[31:0];
                    REG_AGG_CROSS_IM_MID: s_axi_rdata <= agg_corr_cross_im_num_axi[63:32];
                    REG_AGG_CROSS_IM_HI:  s_axi_rdata <= agg_corr_cross_im_num_axi[95:64];
                    REG_AGG_RX0_RAW_LO:   s_axi_rdata <= agg_rx0_raw_power_axi[31:0];
                    REG_AGG_RX0_RAW_MID:  s_axi_rdata <= agg_rx0_raw_power_axi[63:32];
                    REG_AGG_RX0_RAW_HI:   s_axi_rdata <= agg_rx0_raw_power_axi[95:64];
                    REG_AGG_RX1_RAW_LO:   s_axi_rdata <= agg_rx1_raw_power_axi[31:0];
                    REG_AGG_RX1_RAW_MID:  s_axi_rdata <= agg_rx1_raw_power_axi[63:32];
                    REG_AGG_RX1_RAW_HI:   s_axi_rdata <= agg_rx1_raw_power_axi[95:64];
                    REG_AGG_RX0_CLIP:     s_axi_rdata <= agg_rx0_clip_count_axi;
                    REG_AGG_RX1_CLIP:     s_axi_rdata <= agg_rx1_clip_count_axi;
                    REG_AGG_RX0_ZC:       s_axi_rdata <= agg_rx0_zero_cross_count_axi;
                    REG_AGG_RX1_ZC:       s_axi_rdata <= agg_rx1_zero_cross_count_axi;
                    REG_AGG_SIGN_SAME:    s_axi_rdata <= agg_same_sign_count_axi;
                    REG_AGG_LAST_FRAME:   s_axi_rdata <= agg_last_frame_axi;
                    REG_AGG_CAP:          s_axi_rdata <= AGG_CAPABILITY;
                    REG_AGG_BUILD_ID:     s_axi_rdata <= AGG_BUILD_ID;
                    REG_AGG_LIMIT:        s_axi_rdata <= AGG_MAX_FRAMES;
                    default:           s_axi_rdata <= 32'd0;
                endcase
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

endmodule
