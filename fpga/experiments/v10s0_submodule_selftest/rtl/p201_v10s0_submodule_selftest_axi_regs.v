`timescale 1ns/1ps
`default_nettype none

module p201_v10s0_submodule_selftest_axi_regs #(
    parameter integer AXIL_ADDR_WIDTH = 8
) (
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
    output wire                         irq
);

    localparam [7:0] REG_VERSION          = 8'h00;
    localparam [7:0] REG_CONTROL          = 8'h04;
    localparam [7:0] REG_STATUS           = 8'h08;
    localparam [7:0] REG_DONE_MASK        = 8'h0c;
    localparam [7:0] REG_ERROR_MASK       = 8'h10;
    localparam [7:0] REG_RUN_ID           = 8'h14;
    localparam [7:0] REG_CAPABILITY       = 8'h18;
    localparam [7:0] REG_BUILD_ID         = 8'h1c;
    localparam [7:0] REG_ABI_VERSION      = 8'h20;
    localparam [7:0] REG_PACK_STATUS      = 8'h30;
    localparam [7:0] REG_PACK_ACCEPTED    = 8'h34;
    localparam [7:0] REG_PACK_DROPPED     = 8'h38;
    localparam [7:0] REG_PACK_OVERRUN     = 8'h3c;
    localparam [7:0] REG_PACK_OBSERVED    = 8'h40;
    localparam [7:0] REG_FFT_FLAGS        = 8'h50;
    localparam [7:0] REG_FFT_NFFT         = 8'h54;
    localparam [7:0] REG_FFT_PEAK_BIN     = 8'h58;
    localparam [7:0] REG_FFT_PEAK_POWER   = 8'h5c;
    localparam [7:0] REG_FFT_TOTAL_LO     = 8'h60;
    localparam [7:0] REG_FFT_TOP_BINS     = 8'h64;
    localparam [7:0] REG_BAND_FLAGS       = 8'h70;
    localparam [7:0] REG_BAND_NFFT        = 8'h74;
    localparam [7:0] REG_BAND_PEAK        = 8'h78;
    localparam [7:0] REG_BAND_TOTAL_LO    = 8'h7c;
    localparam [7:0] REG_BAND0_LO         = 8'h80;
    localparam [7:0] REG_BAND1_LO         = 8'h84;
    localparam [7:0] REG_BAND2_LO         = 8'h88;
    localparam [7:0] REG_BAND3_LO         = 8'h8c;
    localparam [7:0] REG_CORR_FLAGS       = 8'ha0;
    localparam [7:0] REG_CORR_SAMPLES     = 8'ha4;
    localparam [7:0] REG_CORR_LAG0_RE_LO  = 8'ha8;
    localparam [7:0] REG_CORR_LAG0_IM_LO  = 8'hac;
    localparam [7:0] REG_CORR_LAG1_RE_LO  = 8'hb0;
    localparam [7:0] REG_CORR_LAG1_IM_LO  = 8'hb4;
    localparam [7:0] REG_CORR_LAG2_RE_LO  = 8'hb8;
    localparam [7:0] REG_CORR_LAG2_IM_LO  = 8'hbc;
    localparam [7:0] REG_CORR_LAG3_RE_LO  = 8'hc0;
    localparam [7:0] REG_CORR_LAG3_IM_LO  = 8'hc4;
    localparam [7:0] REG_EXPECT_DONE_MASK = 8'he0;
    localparam [7:0] REG_EXPECT_ERROR     = 8'he4;
    localparam [7:0] REG_TEST_CAPABILITY  = 8'hf4;
    localparam [7:0] REG_TEST_BUILD_ID    = 8'hf8;
    localparam [7:0] REG_TEST_ABI_VERSION = 8'hfc;

    localparam [31:0] VERSION_WORD = 32'h53305430;  // "S0T0"
    localparam [31:0] CAP_WORD     = 32'h0000000f;  // packer, FFT summary, band, corr
    localparam [31:0] BUILD_WORD   = 32'h56313053;  // "V10S"
    localparam [31:0] ABI_WORD     = 32'h000a2000;

    localparam [3:0] STATE_IDLE  = 4'd0;
    localparam [3:0] STATE_CLEAR = 4'd1;
    localparam [3:0] STATE_RUN   = 4'd2;
    localparam [3:0] STATE_WAIT  = 4'd3;
    localparam [3:0] STATE_DONE  = 4'd4;

    localparam [31:0] DONE_PACK = 32'h00000001;
    localparam [31:0] DONE_FFT  = 32'h00000002;
    localparam [31:0] DONE_BAND = 32'h00000004;
    localparam [31:0] DONE_CORR = 32'h00000008;
    localparam [31:0] DONE_ALL  = 32'h0000000f;

    localparam [31:0] EXPECT_FFT_TOTAL = 32'd6385;
    localparam [31:0] EXPECT_BAND_TOTAL = 32'd56622;
    localparam [31:0] EXPECT_BAND0 = 32'd12062;
    localparam [31:0] EXPECT_BAND1 = 32'd12126;
    localparam [31:0] EXPECT_BAND2 = 32'd13186;
    localparam [31:0] EXPECT_BAND3 = 32'd19248;
    localparam signed [63:0] EXPECT_LAG0_RE = 64'sd155328;
    localparam signed [63:0] EXPECT_LAG0_IM = 64'sd552128;
    localparam signed [63:0] EXPECT_LAG1_RE = 64'sd152754;
    localparam signed [63:0] EXPECT_LAG1_IM = 64'sd539322;
    localparam signed [63:0] EXPECT_LAG2_RE = 64'sd150164;
    localparam signed [63:0] EXPECT_LAG2_IM = 64'sd526504;
    localparam signed [63:0] EXPECT_LAG3_RE = 64'sd147559;
    localparam signed [63:0] EXPECT_LAG3_IM = 64'sd513681;

    reg [AXIL_ADDR_WIDTH-1:0] awaddr_hold;
    reg                       aw_hold_valid;
    reg [31:0]                wdata_hold;
    reg [3:0]                 wstrb_hold;
    reg                       w_hold_valid;

    reg                       enable_reg;
    reg [31:0]                control_shadow;
    reg [3:0]                 state_reg;
    reg [8:0]                 gen_index;
    reg [7:0]                 wait_count;
    reg [31:0]                run_id_reg;
    reg [31:0]                done_mask_reg;
    reg [31:0]                error_mask_reg;
    reg                       done_reg;
    reg                       irq_reg;

    reg                       clear_modules;
    reg                       pack_iq_valid;
    reg signed [15:0]         pack_iq_i;
    reg signed [15:0]         pack_iq_q;
    wire [31:0]               pack_tdata;
    wire                      pack_tvalid;
    wire                      pack_tlast;
    wire [31:0]               pack_frame_id;
    wire [31:0]               pack_accepted_count;
    wire [31:0]               pack_dropped_count;
    wire [31:0]               pack_overrun_count;
    wire [31:0]               pack_status_flags;
    reg [31:0]                pack_observed_count;
    reg [31:0]                pack_last_count;

    reg                       fft_valid;
    wire                      fft_ready;
    reg                       fft_last;
    reg [7:0]                 fft_index;
    reg signed [15:0]         fft_real;
    reg signed [15:0]         fft_imag;
    wire [31:0]               fft_summary_flags;
    wire [31:0]               fft_summary_frame_id;
    wire [31:0]               fft_summary_nfft;
    wire [31:0]               fft_summary_peak_bin;
    wire [47:0]               fft_summary_peak_power;
    wire [63:0]               fft_summary_total_power;
    wire [47:0]               fft_summary_noise_floor;
    wire [47:0]               fft_summary_prominence;
    wire [31:0]               fft_summary_top1_bin;
    wire [31:0]               fft_summary_top2_bin;
    wire [31:0]               fft_summary_top3_bin;
    wire [47:0]               fft_summary_top1_power;
    wire [47:0]               fft_summary_top2_power;
    wire [47:0]               fft_summary_top3_power;
    wire [31:0]               fft_version;
    wire [31:0]               fft_capability;
    wire [31:0]               fft_build_id;
    wire [31:0]               fft_abi_version;
    reg [31:0]                fft_start_frame_id;

    reg                       band_valid;
    wire                      band_ready;
    reg                       band_last;
    reg [7:0]                 band_index;
    reg [47:0]                band_power;
    wire [31:0]               band_summary_flags;
    wire                      band_summary_valid;
    wire                      band_summary_overrun;
    wire                      band_summary_length_error;
    wire                      band_summary_missing_last;
    wire [31:0]               band_summary_frame_id;
    wire [31:0]               band_summary_nfft;
    wire [63:0]               band_summary_total_power;
    wire [7:0]                band_summary_peak_bin;
    wire [47:0]               band_summary_peak_power;
    wire [7:0]                band_summary_top1_bin;
    wire [47:0]               band_summary_top1_power;
    wire [7:0]                band_summary_top2_bin;
    wire [47:0]               band_summary_top2_power;
    wire [7:0]                band_summary_top3_bin;
    wire [47:0]               band_summary_top3_power;
    wire [47:0]               band_summary_noise_floor;
    wire [47:0]               band_summary_prominence;
    wire [63:0]               band_summary_band0_power;
    wire [63:0]               band_summary_band1_power;
    wire [63:0]               band_summary_band2_power;
    wire [63:0]               band_summary_band3_power;
    reg [31:0]                band_start_frame_id;

    reg                       corr_valid;
    reg signed [15:0]         corr_rx0_i;
    reg signed [15:0]         corr_rx0_q;
    reg signed [15:0]         corr_rx1_i;
    reg signed [15:0]         corr_rx1_q;
    wire                      corr_summary_valid;
    wire                      corr_summary_strobe;
    wire [31:0]               corr_summary_frame_id;
    wire [15:0]               corr_summary_samples;
    wire [15:0]               corr_lag0_samples;
    wire [15:0]               corr_lag1_samples;
    wire [15:0]               corr_lag2_samples;
    wire [15:0]               corr_lag3_samples;
    wire signed [63:0]        corr_lag0_re;
    wire signed [63:0]        corr_lag0_im;
    wire signed [63:0]        corr_lag1_re;
    wire signed [63:0]        corr_lag1_im;
    wire signed [63:0]        corr_lag2_re;
    wire signed [63:0]        corr_lag2_im;
    wire signed [63:0]        corr_lag3_re;
    wire signed [63:0]        corr_lag3_im;
    wire [3:0]                corr_lag_valid_mask;
    reg [31:0]                corr_start_frame_id;

    wire                      aw_hs;
    wire                      w_hs;
    wire                      write_fire;
    wire                      read_fire;
    wire [7:0]                addr_wr;
    wire [7:0]                addr_rd;
    wire [31:0]               write_data;
    wire [3:0]                write_strb;
    wire                      busy_flag;
    wire                      fail_flag;
    wire [31:0]               status_word;
    wire                      run_accept;
    wire                      pack_done_now;
    wire                      fft_done_now;
    wire                      band_done_now;
    wire                      corr_done_now;
    wire [31:0]               observed_done_mask;
    wire                      control_full_write;

    assign irq = irq_reg;
    assign aw_hs = s_axi_awvalid && s_axi_awready;
    assign w_hs = s_axi_wvalid && s_axi_wready;
    assign write_fire = !s_axi_bvalid &&
                        (aw_hold_valid || aw_hs) &&
                        (w_hold_valid || w_hs);
    assign read_fire = !s_axi_rvalid && s_axi_arvalid;
    assign addr_wr = aw_hold_valid ? awaddr_hold[7:0] : s_axi_awaddr[7:0];
    assign addr_rd = s_axi_araddr[7:0];
    assign write_data = w_hold_valid ? wdata_hold : s_axi_wdata;
    assign write_strb = w_hold_valid ? wstrb_hold : s_axi_wstrb;
    assign control_full_write = write_fire &&
                                (addr_wr == REG_CONTROL) &&
                                (write_strb == 4'hf);
    assign busy_flag = (state_reg == STATE_CLEAR) ||
                       (state_reg == STATE_RUN) ||
                       (state_reg == STATE_WAIT);
    assign fail_flag = |error_mask_reg;
    assign status_word = {
        16'd0,
        state_reg,
        irq_reg,
        fail_flag,
        done_reg,
        busy_flag,
        enable_reg
    };
    assign run_accept = (state_reg == STATE_RUN) &&
                        fft_ready && band_ready &&
                        (gen_index < 9'd256);
    assign pack_done_now = (pack_frame_id == 32'd1);
    assign fft_done_now = (fft_summary_frame_id != fft_start_frame_id);
    assign band_done_now = (band_summary_frame_id != band_start_frame_id);
    assign corr_done_now = (corr_summary_frame_id != corr_start_frame_id);
    assign observed_done_mask =
        done_mask_reg |
        (pack_done_now ? DONE_PACK : 32'd0) |
        (fft_done_now ? DONE_FFT : 32'd0) |
        (band_done_now ? DONE_BAND : 32'd0) |
        (corr_done_now ? DONE_CORR : 32'd0);

    p201_fft_frame_packer u_frame_packer (
        .clk(s_axi_aclk),
        .rst_n(s_axi_aresetn),
        .enable(enable_reg),
        .clear(clear_modules),
        .iq_valid(pack_iq_valid),
        .iq_i(pack_iq_i),
        .iq_q(pack_iq_q),
        .m_axis_tdata(pack_tdata),
        .m_axis_tvalid(pack_tvalid),
        .m_axis_tready(1'b1),
        .m_axis_tlast(pack_tlast),
        .frame_id(pack_frame_id),
        .accepted_count(pack_accepted_count),
        .dropped_count(pack_dropped_count),
        .overrun_count(pack_overrun_count),
        .status_flags(pack_status_flags)
    );

    p201_v10_fft_stream_summary_top u_fft_summary (
        .clk(s_axi_aclk),
        .rst_n(s_axi_aresetn),
        .enable(enable_reg),
        .clear_summary(clear_modules),
        .fft_valid(fft_valid),
        .fft_ready(fft_ready),
        .fft_last(fft_last),
        .fft_index(fft_index),
        .fft_real(fft_real),
        .fft_imag(fft_imag),
        .fft_version(fft_version),
        .fft_capability(fft_capability),
        .fft_build_id(fft_build_id),
        .fft_abi_version(fft_abi_version),
        .summary_flags(fft_summary_flags),
        .summary_frame_id(fft_summary_frame_id),
        .summary_nfft(fft_summary_nfft),
        .summary_peak_bin(fft_summary_peak_bin),
        .summary_peak_power(fft_summary_peak_power),
        .summary_total_power(fft_summary_total_power),
        .summary_noise_floor(fft_summary_noise_floor),
        .summary_prominence(fft_summary_prominence),
        .summary_top1_bin(fft_summary_top1_bin),
        .summary_top1_power(fft_summary_top1_power),
        .summary_top2_bin(fft_summary_top2_bin),
        .summary_top2_power(fft_summary_top2_power),
        .summary_top3_bin(fft_summary_top3_bin),
        .summary_top3_power(fft_summary_top3_power)
    );

    p201_bandpower_reducer u_bandpower (
        .clk(s_axi_aclk),
        .rst_n(s_axi_aresetn),
        .enable(enable_reg),
        .clear_summary(clear_modules),
        .bin_valid(band_valid),
        .bin_ready(band_ready),
        .bin_last(band_last),
        .bin_index(band_index),
        .bin_power(band_power),
        .summary_flags(band_summary_flags),
        .summary_valid(band_summary_valid),
        .summary_overrun(band_summary_overrun),
        .summary_length_error(band_summary_length_error),
        .summary_missing_last(band_summary_missing_last),
        .summary_frame_id(band_summary_frame_id),
        .summary_nfft(band_summary_nfft),
        .summary_total_power(band_summary_total_power),
        .summary_peak_bin(band_summary_peak_bin),
        .summary_peak_power(band_summary_peak_power),
        .summary_top1_bin(band_summary_top1_bin),
        .summary_top1_power(band_summary_top1_power),
        .summary_top2_bin(band_summary_top2_bin),
        .summary_top2_power(band_summary_top2_power),
        .summary_top3_bin(band_summary_top3_bin),
        .summary_top3_power(band_summary_top3_power),
        .summary_noise_floor(band_summary_noise_floor),
        .summary_prominence(band_summary_prominence),
        .summary_band0_power(band_summary_band0_power),
        .summary_band1_power(band_summary_band1_power),
        .summary_band2_power(band_summary_band2_power),
        .summary_band3_power(band_summary_band3_power)
    );

    p201_v10_multilag_corr_module #(
        .DATA_WIDTH(16),
        .ACC_WIDTH(64),
        .FRAME_LEN(64)
    ) u_multilag_corr (
        .clk(s_axi_aclk),
        .rst_n(s_axi_aresetn),
        .enable(enable_reg),
        .clear(clear_modules),
        .sample_valid(corr_valid),
        .rx0_i(corr_rx0_i),
        .rx0_q(corr_rx0_q),
        .rx1_i(corr_rx1_i),
        .rx1_q(corr_rx1_q),
        .summary_valid(corr_summary_valid),
        .summary_strobe(corr_summary_strobe),
        .summary_frame_id(corr_summary_frame_id),
        .summary_samples(corr_summary_samples),
        .lag0_samples(corr_lag0_samples),
        .lag1_samples(corr_lag1_samples),
        .lag2_samples(corr_lag2_samples),
        .lag3_samples(corr_lag3_samples),
        .lag0_corr_re(corr_lag0_re),
        .lag0_corr_im(corr_lag0_im),
        .lag1_corr_re(corr_lag1_re),
        .lag1_corr_im(corr_lag1_im),
        .lag2_corr_re(corr_lag2_re),
        .lag2_corr_im(corr_lag2_im),
        .lag3_corr_re(corr_lag3_re),
        .lag3_corr_im(corr_lag3_im),
        .lag_valid_mask(corr_lag_valid_mask)
    );

    function [47:0] band_frame_power;
        input [7:0] idx;
        begin
            case (idx)
                8'd5:   band_frame_power = 48'd3000;
                8'd42:  band_frame_power = 48'd9000;
                8'd100: band_frame_power = 48'd12000;
                8'd170: band_frame_power = 48'd6000;
                8'd191: band_frame_power = 48'd7000;
                8'd200: band_frame_power = 48'd11000;
                8'd255: band_frame_power = 48'd8000;
                default: begin
                    case (idx[7:6])
                        2'b00: band_frame_power = 48'd1;
                        2'b01: band_frame_power = 48'd2;
                        2'b10: band_frame_power = 48'd3;
                        default: band_frame_power = 48'd4;
                    endcase
                end
            endcase
        end
    endfunction

    function signed [15:0] corr_rx0_i_word;
        input [7:0] idx;
        begin
            corr_rx0_i_word = {8'd0, idx} + 16'sd1;
        end
    endfunction

    function signed [15:0] corr_rx0_q_word;
        input [7:0] idx;
        begin
            corr_rx0_q_word = ($signed({8'd0, idx}) <<< 1) - 16'sd7;
        end
    endfunction

    function signed [15:0] corr_rx1_i_word;
        input [7:0] idx;
        begin
            corr_rx1_i_word = ($signed({8'd0, idx}) * 16'sd3) + 16'sd5;
        end
    endfunction

    function signed [15:0] corr_rx1_q_word;
        input [7:0] idx;
        begin
            corr_rx1_q_word = 16'sd11 - $signed({8'd0, idx});
        end
    endfunction

    function signed [15:0] fft_real_word;
        input [7:0] idx;
        begin
            case (idx)
                8'd0:  fft_real_word = 16'sd1;
                8'd5:  fft_real_word = 16'sd64;
                8'd17: fft_real_word = 16'sd32;
                8'd33: fft_real_word = -16'sd16;
                default: fft_real_word = 16'sd2;
            endcase
        end
    endfunction

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            pack_observed_count <= 32'd0;
            pack_last_count <= 32'd0;
        end else if (clear_modules) begin
            pack_observed_count <= 32'd0;
            pack_last_count <= 32'd0;
        end else if (pack_tvalid) begin
            pack_observed_count <= pack_observed_count + 32'd1;
            if (pack_tlast) begin
                pack_last_count <= pack_last_count + 32'd1;
            end
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            enable_reg <= 1'b0;
            control_shadow <= 32'd0;
            state_reg <= STATE_IDLE;
            gen_index <= 9'd0;
            wait_count <= 8'd0;
            run_id_reg <= 32'd0;
            done_mask_reg <= 32'd0;
            error_mask_reg <= 32'd0;
            done_reg <= 1'b0;
            irq_reg <= 1'b0;
            clear_modules <= 1'b0;
            fft_start_frame_id <= 32'd0;
            band_start_frame_id <= 32'd0;
            corr_start_frame_id <= 32'd0;
            awaddr_hold <= {AXIL_ADDR_WIDTH{1'b0}};
            aw_hold_valid <= 1'b0;
            wdata_hold <= 32'd0;
            wstrb_hold <= 4'd0;
            w_hold_valid <= 1'b0;
            s_axi_awready <= 1'b0;
            s_axi_wready <= 1'b0;
            s_axi_bresp <= 2'b00;
            s_axi_bvalid <= 1'b0;
        end else begin
            s_axi_awready <= !aw_hold_valid && !s_axi_bvalid && !aw_hs;
            s_axi_wready <= !w_hold_valid && !s_axi_bvalid && !w_hs;
            clear_modules <= 1'b0;

            if (aw_hs) begin
                awaddr_hold <= s_axi_awaddr;
                aw_hold_valid <= 1'b1;
            end

            if (w_hs) begin
                wdata_hold <= s_axi_wdata;
                wstrb_hold <= s_axi_wstrb;
                w_hold_valid <= 1'b1;
            end

            if (write_fire) begin
                aw_hold_valid <= 1'b0;
                w_hold_valid <= 1'b0;
                s_axi_bresp <= 2'b00;
                s_axi_bvalid <= 1'b1;

                if (control_full_write) begin
                    if (write_data[1]) begin
                        control_shadow <= 32'd1;
                        enable_reg <= 1'b1;
                        done_reg <= 1'b0;
                        irq_reg <= 1'b0;
                        done_mask_reg <= 32'd0;
                        error_mask_reg <= 32'd0;
                        state_reg <= STATE_CLEAR;
                    end else if (write_data[2]) begin
                        control_shadow <= {31'd0, write_data[0]};
                        enable_reg <= write_data[0];
                        done_reg <= 1'b0;
                        irq_reg <= 1'b0;
                        done_mask_reg <= 32'd0;
                        error_mask_reg <= 32'd0;
                        clear_modules <= 1'b1;
                        state_reg <= STATE_IDLE;
                        gen_index <= 9'd0;
                        wait_count <= 8'd0;
                    end else begin
                        control_shadow <= {31'd0, write_data[0]};
                        enable_reg <= write_data[0];
                        if (!write_data[0]) begin
                            done_reg <= 1'b0;
                            irq_reg <= 1'b0;
                            done_mask_reg <= 32'd0;
                            error_mask_reg <= 32'd0;
                            clear_modules <= 1'b1;
                            state_reg <= STATE_IDLE;
                            gen_index <= 9'd0;
                            wait_count <= 8'd0;
                        end
                    end
                end
            end else if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end

            if (!control_full_write) begin
                case (state_reg)
                    STATE_IDLE: begin
                        gen_index <= 9'd0;
                        wait_count <= 8'd0;
                    end
                    STATE_CLEAR: begin
                        clear_modules <= 1'b1;
                        gen_index <= 9'd0;
                        wait_count <= 8'd0;
                        fft_start_frame_id <= 32'd0;
                        band_start_frame_id <= 32'd0;
                        corr_start_frame_id <= 32'd0;
                        state_reg <= STATE_RUN;
                    end
                    STATE_RUN: begin
                        if (run_accept) begin
                            if (gen_index == 9'd255) begin
                                state_reg <= STATE_WAIT;
                            end
                            gen_index <= gen_index + 9'd1;
                        end
                    end
                    STATE_WAIT: begin
                        wait_count <= wait_count + 8'd1;

                        done_mask_reg <= observed_done_mask;

                        if ((observed_done_mask == DONE_ALL) ||
                            (wait_count == 8'hff)) begin
                            error_mask_reg[0] <= (pack_frame_id != 32'd1);
                            error_mask_reg[1] <= (pack_accepted_count != 32'd256);
                            error_mask_reg[2] <= (pack_dropped_count != 32'd0) ||
                                                 (pack_overrun_count != 32'd0);
                            error_mask_reg[3] <= (pack_observed_count != 32'd256) ||
                                                 (pack_last_count != 32'd1);
                            error_mask_reg[4] <= (fft_summary_nfft != 32'd256);
                            error_mask_reg[5] <= (fft_summary_peak_bin != 32'd5) ||
                                                 (fft_summary_peak_power != 48'd4096);
                            error_mask_reg[6] <= (fft_summary_total_power[31:0] != EXPECT_FFT_TOTAL) ||
                                                 (fft_summary_total_power[63:32] != 32'd0);
                            error_mask_reg[7] <= (fft_summary_noise_floor != 48'd1) ||
                                                 (fft_summary_prominence != 48'd4095) ||
                                                 (fft_summary_top1_bin != 32'd5) ||
                                                 (fft_summary_top2_bin != 32'd17) ||
                                                 (fft_summary_top3_bin != 32'd33);
                            error_mask_reg[8] <= (band_summary_nfft != 32'd256) ||
                                                 (band_summary_total_power[31:0] != EXPECT_BAND_TOTAL) ||
                                                 (band_summary_total_power[63:32] != 32'd0);
                            error_mask_reg[9] <= (band_summary_peak_bin != 8'd100) ||
                                                 (band_summary_peak_power != 48'd12000) ||
                                                 (band_summary_top1_bin != 8'd100) ||
                                                 (band_summary_top2_bin != 8'd200) ||
                                                 (band_summary_top3_bin != 8'd42);
                            error_mask_reg[10] <= (band_summary_band0_power[31:0] != EXPECT_BAND0) ||
                                                  (band_summary_band1_power[31:0] != EXPECT_BAND1) ||
                                                  (band_summary_band2_power[31:0] != EXPECT_BAND2) ||
                                                  (band_summary_band3_power[31:0] != EXPECT_BAND3);
                            error_mask_reg[11] <= !corr_summary_valid ||
                                                  (corr_summary_samples != 16'd64) ||
                                                  (corr_lag_valid_mask != 4'hf);
                            error_mask_reg[12] <= (corr_lag0_re != EXPECT_LAG0_RE) ||
                                                  (corr_lag0_im != EXPECT_LAG0_IM);
                            error_mask_reg[13] <= (corr_lag1_re != EXPECT_LAG1_RE) ||
                                                  (corr_lag1_im != EXPECT_LAG1_IM);
                            error_mask_reg[14] <= (corr_lag2_re != EXPECT_LAG2_RE) ||
                                                  (corr_lag2_im != EXPECT_LAG2_IM);
                            error_mask_reg[15] <= (corr_lag3_re != EXPECT_LAG3_RE) ||
                                                  (corr_lag3_im != EXPECT_LAG3_IM);
                            error_mask_reg[16] <= (observed_done_mask != DONE_ALL);
                            done_mask_reg <= observed_done_mask;
                            run_id_reg <= run_id_reg + 32'd1;
                            done_reg <= 1'b1;
                            irq_reg <= 1'b1;
                            state_reg <= STATE_DONE;
                        end
                    end
                    STATE_DONE: begin
                        gen_index <= 9'd0;
                        wait_count <= 8'd0;
                    end
                    default: begin
                        state_reg <= STATE_IDLE;
                    end
                endcase
            end
        end
    end

    always @(*) begin
        pack_iq_valid = run_accept;
        pack_iq_i = $signed({7'd0, gen_index[8:0]});
        pack_iq_q = -$signed({7'd0, gen_index[8:0]});

        fft_valid = run_accept;
        fft_last = (gen_index == 9'd255);
        fft_index = gen_index[7:0];
        fft_real = fft_real_word(gen_index[7:0]);
        fft_imag = 16'sd0;

        band_valid = run_accept;
        band_last = (gen_index == 9'd255);
        band_index = gen_index[7:0];
        band_power = band_frame_power(gen_index[7:0]);

        corr_valid = run_accept && (gen_index < 9'd64);
        corr_rx0_i = corr_rx0_i_word(gen_index[7:0]);
        corr_rx0_q = corr_rx0_q_word(gen_index[7:0]);
        corr_rx1_i = corr_rx1_i_word(gen_index[7:0]);
        corr_rx1_q = corr_rx1_q_word(gen_index[7:0]);
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_arready <= 1'b0;
            s_axi_rdata <= 32'd0;
            s_axi_rresp <= 2'b00;
            s_axi_rvalid <= 1'b0;
        end else begin
            s_axi_arready <= 1'b0;

            if (read_fire) begin
                s_axi_arready <= 1'b1;
                s_axi_rresp <= 2'b00;
                s_axi_rvalid <= 1'b1;

                case (addr_rd)
                    REG_VERSION:          s_axi_rdata <= VERSION_WORD;
                    REG_CONTROL:          s_axi_rdata <= control_shadow;
                    REG_STATUS:           s_axi_rdata <= status_word;
                    REG_DONE_MASK:        s_axi_rdata <= done_mask_reg;
                    REG_ERROR_MASK:       s_axi_rdata <= error_mask_reg;
                    REG_RUN_ID:           s_axi_rdata <= run_id_reg;
                    REG_CAPABILITY:       s_axi_rdata <= CAP_WORD;
                    REG_BUILD_ID:         s_axi_rdata <= BUILD_WORD;
                    REG_ABI_VERSION:      s_axi_rdata <= ABI_WORD;
                    REG_PACK_STATUS:      s_axi_rdata <= pack_status_flags;
                    REG_PACK_ACCEPTED:    s_axi_rdata <= pack_accepted_count;
                    REG_PACK_DROPPED:     s_axi_rdata <= pack_dropped_count;
                    REG_PACK_OVERRUN:     s_axi_rdata <= pack_overrun_count;
                    REG_PACK_OBSERVED:    s_axi_rdata <= pack_observed_count;
                    REG_FFT_FLAGS:        s_axi_rdata <= fft_summary_flags;
                    REG_FFT_NFFT:         s_axi_rdata <= fft_summary_nfft;
                    REG_FFT_PEAK_BIN:     s_axi_rdata <= fft_summary_peak_bin;
                    REG_FFT_PEAK_POWER:   s_axi_rdata <= fft_summary_peak_power[31:0];
                    REG_FFT_TOTAL_LO:     s_axi_rdata <= fft_summary_total_power[31:0];
                    REG_FFT_TOP_BINS:     s_axi_rdata <= {8'd0, fft_summary_top3_bin[7:0], fft_summary_top2_bin[7:0], fft_summary_top1_bin[7:0]};
                    REG_BAND_FLAGS:       s_axi_rdata <= band_summary_flags;
                    REG_BAND_NFFT:        s_axi_rdata <= band_summary_nfft;
                    REG_BAND_PEAK:        s_axi_rdata <= {8'd0, band_summary_top3_bin, band_summary_top2_bin, band_summary_peak_bin};
                    REG_BAND_TOTAL_LO:    s_axi_rdata <= band_summary_total_power[31:0];
                    REG_BAND0_LO:         s_axi_rdata <= band_summary_band0_power[31:0];
                    REG_BAND1_LO:         s_axi_rdata <= band_summary_band1_power[31:0];
                    REG_BAND2_LO:         s_axi_rdata <= band_summary_band2_power[31:0];
                    REG_BAND3_LO:         s_axi_rdata <= band_summary_band3_power[31:0];
                    REG_CORR_FLAGS:       s_axi_rdata <= {16'd0, corr_lag_valid_mask, 3'd0, corr_summary_valid, corr_summary_frame_id[7:0]};
                    REG_CORR_SAMPLES:     s_axi_rdata <= {corr_lag3_samples, corr_summary_samples};
                    REG_CORR_LAG0_RE_LO:  s_axi_rdata <= corr_lag0_re[31:0];
                    REG_CORR_LAG0_IM_LO:  s_axi_rdata <= corr_lag0_im[31:0];
                    REG_CORR_LAG1_RE_LO:  s_axi_rdata <= corr_lag1_re[31:0];
                    REG_CORR_LAG1_IM_LO:  s_axi_rdata <= corr_lag1_im[31:0];
                    REG_CORR_LAG2_RE_LO:  s_axi_rdata <= corr_lag2_re[31:0];
                    REG_CORR_LAG2_IM_LO:  s_axi_rdata <= corr_lag2_im[31:0];
                    REG_CORR_LAG3_RE_LO:  s_axi_rdata <= corr_lag3_re[31:0];
                    REG_CORR_LAG3_IM_LO:  s_axi_rdata <= corr_lag3_im[31:0];
                    REG_EXPECT_DONE_MASK: s_axi_rdata <= DONE_ALL;
                    REG_EXPECT_ERROR:     s_axi_rdata <= 32'd0;
                    REG_TEST_CAPABILITY:  s_axi_rdata <= CAP_WORD;
                    REG_TEST_BUILD_ID:    s_axi_rdata <= BUILD_WORD;
                    REG_TEST_ABI_VERSION: s_axi_rdata <= ABI_WORD;
                    default:              s_axi_rdata <= 32'd0;
                endcase
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

endmodule

`default_nettype wire
