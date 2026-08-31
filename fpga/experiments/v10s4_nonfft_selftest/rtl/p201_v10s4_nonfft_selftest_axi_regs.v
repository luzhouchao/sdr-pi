`timescale 1ns/1ps
`default_nettype none

module p201_v10s4_nonfft_selftest_axi_regs #(
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

    localparam [7:0] REG_VERSION        = 8'h00;
    localparam [7:0] REG_CONTROL        = 8'h04;
    localparam [7:0] REG_STATUS         = 8'h08;
    localparam [7:0] REG_DONE_MASK      = 8'h0c;
    localparam [7:0] REG_ERROR_MASK     = 8'h10;
    localparam [7:0] REG_RUN_ID         = 8'h14;
    localparam [7:0] REG_CAPABILITY     = 8'h18;
    localparam [7:0] REG_BUILD_ID       = 8'h1c;
    localparam [7:0] REG_ABI_VERSION    = 8'h20;

    localparam [7:0] REG_QUAL_FLAGS     = 8'h30;
    localparam [7:0] REG_QUAL_COUNT     = 8'h34;
    localparam [7:0] REG_QUAL_SUM_I     = 8'h38;
    localparam [7:0] REG_QUAL_SUM_Q     = 8'h3c;
    localparam [7:0] REG_QUAL_SUM_I2    = 8'h40;
    localparam [7:0] REG_QUAL_SUM_Q2    = 8'h44;
    localparam [7:0] REG_QUAL_SUM_IQ    = 8'h48;
    localparam [7:0] REG_QUAL_PEAK      = 8'h4c;
    localparam [7:0] REG_QUAL_CLIP      = 8'h50;
    localparam [7:0] REG_QUAL_SAT       = 8'h54;
    localparam [7:0] REG_QUAL_VALID     = 8'h58;
    localparam [7:0] REG_QUAL_DROP      = 8'h5c;

    localparam [7:0] REG_WIN_FLAGS      = 8'h70;
    localparam [7:0] REG_WIN_RAW        = 8'h74;
    localparam [7:0] REG_WIN_ACCEPTED   = 8'h78;
    localparam [7:0] REG_WIN_DROPPED    = 8'h7c;
    localparam [7:0] REG_WIN_OVERFLOW   = 8'h80;
    localparam [7:0] REG_WIN_FRAME_ID   = 8'h84;
    localparam [7:0] REG_WIN_INDEX      = 8'h88;

    localparam [7:0] REG_EN_FLAGS       = 8'ha0;
    localparam [7:0] REG_EN_FRAME_ID    = 8'ha4;
    localparam [7:0] REG_EN_COUNT       = 8'ha8;
    localparam [7:0] REG_EN_TOTAL       = 8'hac;
    localparam [7:0] REG_EN_NOISE       = 8'hb0;
    localparam [7:0] REG_EN_PEAK        = 8'hb4;
    localparam [7:0] REG_EN_PEAK_INDEX  = 8'hb8;
    localparam [7:0] REG_EN_SECOND      = 8'hbc;
    localparam [7:0] REG_EN_SECOND_IDX  = 8'hc0;
    localparam [7:0] REG_EN_PROM        = 8'hc4;
    localparam [7:0] REG_EN_THRESH      = 8'hc8;

    localparam [7:0] REG_EXPECT_DONE    = 8'he0;
    localparam [7:0] REG_EXPECT_ERROR   = 8'he4;
    localparam [7:0] REG_TEST_CAP       = 8'hf4;
    localparam [7:0] REG_TEST_BUILD     = 8'hf8;
    localparam [7:0] REG_TEST_ABI       = 8'hfc;

    localparam [31:0] VERSION_WORD      = 32'h53345430;  // "S4T0"
    localparam [31:0] CAP_WORD          = 32'h00000007;  // quality, window, energy
    localparam [31:0] BUILD_WORD        = 32'h56313034;  // "V104"
    localparam [31:0] ABI_WORD          = 32'h000a4000;

    localparam [31:0] DONE_QUALITY      = 32'h00000001;
    localparam [31:0] DONE_WINDOW       = 32'h00000002;
    localparam [31:0] DONE_ENERGY       = 32'h00000004;
    localparam [31:0] DONE_ALL          = 32'h00000007;

    localparam [2:0] STATE_IDLE         = 3'd0;
    localparam [2:0] STATE_CLEAR        = 3'd1;
    localparam [2:0] STATE_RUN          = 3'd2;
    localparam [2:0] STATE_WAIT         = 3'd3;
    localparam [2:0] STATE_DONE         = 3'd4;
    localparam [2:0] STATE_PRIME        = 3'd5;

    localparam [31:0] EXPECT_SUM_I      = 32'h00008374;
    localparam [31:0] EXPECT_SUM_Q      = 32'hffff7b9c;
    localparam [31:0] EXPECT_SUM_I2     = 32'h400e6d8c;
    localparam [31:0] EXPECT_SUM_Q2     = 32'h400fe730;
    localparam [31:0] EXPECT_SUM_IQ     = 32'hbff187e8;
    localparam [31:0] EXPECT_EN_TOTAL   = 32'd309;
    localparam [31:0] EXPECT_EN_NOISE   = 32'd2;
    localparam [31:0] EXPECT_EN_PEAK    = 32'd100;
    localparam [31:0] EXPECT_EN_SECOND  = 32'd90;
    localparam [31:0] EXPECT_EN_PROM    = 32'd98;

    reg [AXIL_ADDR_WIDTH-1:0] awaddr_hold;
    reg                       aw_hold_valid;
    reg [31:0]                wdata_hold;
    reg [3:0]                 wstrb_hold;
    reg                       w_hold_valid;

    reg [31:0]                control_shadow;
    reg                       enable_reg;
    reg [2:0]                 state_reg;
    reg [3:0]                 gen_index;
    reg [3:0]                 wait_count;
    reg [31:0]                run_id_reg;
    reg [31:0]                done_mask_reg;
    reg [31:0]                error_mask_reg;
    reg                       done_reg;
    reg                       irq_reg;

    reg                       clear_modules;
    reg                       feed_valid;
    reg                       feed_last;
    reg signed [15:0]         feed_i;
    reg signed [15:0]         feed_q;
    reg [31:0]                feed_energy;
    reg [15:0]                feed_energy_index;

    wire                      quality_frame_done;
    wire                      quality_stats_valid;
    wire                      quality_overflow;
    wire                      quality_protocol_error;
    wire [31:0]               quality_count;
    wire signed [47:0]        quality_sum_i;
    wire signed [47:0]        quality_sum_q;
    wire [63:0]               quality_sum_i2;
    wire [63:0]               quality_sum_q2;
    wire signed [63:0]        quality_sum_iq;
    wire [15:0]               quality_abs_peak;
    wire [31:0]               quality_clip_i;
    wire [31:0]               quality_clip_q;
    wire [31:0]               quality_sat_i;
    wire [31:0]               quality_sat_q;
    wire [31:0]               quality_valid_count;
    wire [31:0]               quality_drop_count;

    wire                      window_sample_ready;
    wire                      window_out_valid;
    wire                      window_last_out;
    wire signed [15:0]        window_out_i;
    wire signed [15:0]        window_out_q;
    wire [2:0]                window_frame_index;
    wire [31:0]               window_frame_id;
    wire [31:0]               window_raw_count;
    wire [31:0]               window_accepted_count;
    wire [31:0]               window_dropped_count;
    wire [31:0]               window_overflow_count;
    wire [31:0]               window_status_flags;

    wire                      energy_sample_ready;
    wire [31:0]               energy_flags;
    wire [31:0]               energy_frame_id;
    wire [15:0]               energy_sample_count;
    wire [63:0]               energy_total;
    wire [31:0]               energy_noise;
    wire [31:0]               energy_peak;
    wire [15:0]               energy_peak_index;
    wire [31:0]               energy_second_peak;
    wire [15:0]               energy_second_index;
    wire [31:0]               energy_prominence;
    wire [15:0]               energy_threshold_count;
    wire [31:0]               control_write_value;

    assign irq = irq_reg;
    assign control_write_value = apply_wstrb(control_shadow, wdata_hold, wstrb_hold);

    p201_sdr_quality_stats u_quality_stats (
        .clk            (s_axi_aclk),
        .rst_n          (s_axi_aresetn),
        .enable         (enable_reg),
        .clear          (clear_modules),
        .frame_start    (feed_valid && (gen_index == 4'd0)),
        .frame_end      (feed_valid && (gen_index == 4'd7)),
        .sample_valid   (feed_valid),
        .sample_drop    (1'b0),
        .sample_i       (feed_i),
        .sample_q       (feed_q),
        .frame_active   (),
        .frame_done     (quality_frame_done),
        .stats_valid    (quality_stats_valid),
        .overflow       (quality_overflow),
        .protocol_error (quality_protocol_error),
        .sample_count   (quality_count),
        .sum_i          (quality_sum_i),
        .sum_q          (quality_sum_q),
        .sum_i2         (quality_sum_i2),
        .sum_q2         (quality_sum_q2),
        .sum_iq         (quality_sum_iq),
        .abs_peak       (quality_abs_peak),
        .clip_i_count   (quality_clip_i),
        .clip_q_count   (quality_clip_q),
        .sat_i_count    (quality_sat_i),
        .sat_q_count    (quality_sat_q),
        .valid_count    (quality_valid_count),
        .drop_count     (quality_drop_count)
    );

    p201_v10s2_frame_window u_frame_window (
        .clk              (s_axi_aclk),
        .rst_n            (s_axi_aresetn),
        .enable           (enable_reg),
        .clear            (clear_modules),
        .decim_factor     (8'd1),
        .window_mode      (1'b1),
        .sample_valid     (feed_valid),
        .sample_ready     (window_sample_ready),
        .sample_i         (feed_i),
        .sample_q         (feed_q),
        .out_valid        (window_out_valid),
        .out_ready        (1'b1),
        .last_out         (window_last_out),
        .out_i            (window_out_i),
        .out_q            (window_out_q),
        .frame_index      (window_frame_index),
        .frame_id         (window_frame_id),
        .raw_sample_count (window_raw_count),
        .accepted_count   (window_accepted_count),
        .dropped_count    (window_dropped_count),
        .overflow_count   (window_overflow_count),
        .status_flags     (window_status_flags)
    );

    p201_v10s3_energy_peak_reducer u_energy_peak (
        .clk                       (s_axi_aclk),
        .rst_n                     (s_axi_aresetn),
        .enable                    (enable_reg),
        .clear_summary             (clear_modules),
        .sample_valid              (feed_valid),
        .sample_ready              (energy_sample_ready),
        .sample_last               (feed_last),
        .sample_value              (feed_energy),
        .sample_index              (feed_energy_index),
        .threshold_value           (32'd50),
        .summary_flags             (energy_flags),
        .summary_frame_id          (energy_frame_id),
        .summary_sample_count      (energy_sample_count),
        .summary_total_energy      (energy_total),
        .summary_noise_floor       (energy_noise),
        .summary_peak_value        (energy_peak),
        .summary_peak_index        (energy_peak_index),
        .summary_second_peak_value (energy_second_peak),
        .summary_second_peak_index (energy_second_index),
        .summary_prominence        (energy_prominence),
        .summary_threshold_count   (energy_threshold_count)
    );

    function [31:0] apply_wstrb;
        input [31:0] old_value;
        input [31:0] new_value;
        input [3:0]  strb;
        begin
            apply_wstrb[7:0]   = strb[0] ? new_value[7:0]   : old_value[7:0];
            apply_wstrb[15:8]  = strb[1] ? new_value[15:8]  : old_value[15:8];
            apply_wstrb[23:16] = strb[2] ? new_value[23:16] : old_value[23:16];
            apply_wstrb[31:24] = strb[3] ? new_value[31:24] : old_value[31:24];
        end
    endfunction

    function signed [15:0] sample_i_for_index;
        input [3:0] index;
        begin
            case (index)
                4'd0: sample_i_for_index = 16'sd3;
                4'd1: sample_i_for_index = -16'sd5;
                4'd2: sample_i_for_index = 16'sd32767;
                4'd3: sample_i_for_index = -16'sd100;
                4'd4: sample_i_for_index = 16'sd10;
                4'd5: sample_i_for_index = -16'sd30;
                4'd6: sample_i_for_index = 16'sd1000;
                default: sample_i_for_index = 16'sd7;
            endcase
        end
    endfunction

    function signed [15:0] sample_q_for_index;
        input [3:0] index;
        begin
            case (index)
                4'd0: sample_q_for_index = -16'sd4;
                4'd1: sample_q_for_index = 16'sd12;
                4'd2: sample_q_for_index = -16'sd32768;
                4'd3: sample_q_for_index = -16'sd200;
                4'd4: sample_q_for_index = 16'sd20;
                4'd5: sample_q_for_index = 16'sd40;
                4'd6: sample_q_for_index = -16'sd1000;
                default: sample_q_for_index = 16'sd8;
            endcase
        end
    endfunction

    function [31:0] energy_for_index;
        input [3:0] index;
        begin
            case (index)
                4'd0: energy_for_index = 32'd5;
                4'd1: energy_for_index = 32'd7;
                4'd2: energy_for_index = 32'd50;
                4'd3: energy_for_index = 32'd2;
                4'd4: energy_for_index = 32'd100;
                4'd5: energy_for_index = 32'd25;
                4'd6: energy_for_index = 32'd90;
                default: energy_for_index = 32'd30;
            endcase
        end
    endfunction

    function [31:0] read_reg;
        input [7:0] addr;
        begin
            case (addr)
                REG_VERSION:       read_reg = VERSION_WORD;
                REG_CONTROL:       read_reg = control_shadow;
                REG_STATUS:        read_reg = {28'd0, (error_mask_reg != 32'd0), done_reg, irq_reg, (state_reg != STATE_IDLE) && (state_reg != STATE_DONE)};
                REG_DONE_MASK:     read_reg = done_mask_reg;
                REG_ERROR_MASK:    read_reg = error_mask_reg;
                REG_RUN_ID:        read_reg = run_id_reg;
                REG_CAPABILITY:    read_reg = CAP_WORD;
                REG_BUILD_ID:      read_reg = BUILD_WORD;
                REG_ABI_VERSION:   read_reg = ABI_WORD;
                REG_QUAL_FLAGS:    read_reg = {28'd0, quality_protocol_error, quality_overflow, quality_stats_valid, quality_frame_done};
                REG_QUAL_COUNT:    read_reg = quality_count;
                REG_QUAL_SUM_I:    read_reg = quality_sum_i[31:0];
                REG_QUAL_SUM_Q:    read_reg = quality_sum_q[31:0];
                REG_QUAL_SUM_I2:   read_reg = quality_sum_i2[31:0];
                REG_QUAL_SUM_Q2:   read_reg = quality_sum_q2[31:0];
                REG_QUAL_SUM_IQ:   read_reg = quality_sum_iq[31:0];
                REG_QUAL_PEAK:     read_reg = {16'd0, quality_abs_peak};
                REG_QUAL_CLIP:     read_reg = {quality_clip_q[15:0], quality_clip_i[15:0]};
                REG_QUAL_SAT:      read_reg = {quality_sat_q[15:0], quality_sat_i[15:0]};
                REG_QUAL_VALID:    read_reg = quality_valid_count;
                REG_QUAL_DROP:     read_reg = quality_drop_count;
                REG_WIN_FLAGS:     read_reg = window_status_flags;
                REG_WIN_RAW:       read_reg = window_raw_count;
                REG_WIN_ACCEPTED:  read_reg = window_accepted_count;
                REG_WIN_DROPPED:   read_reg = window_dropped_count;
                REG_WIN_OVERFLOW:  read_reg = window_overflow_count;
                REG_WIN_FRAME_ID:  read_reg = window_frame_id;
                REG_WIN_INDEX:     read_reg = {29'd0, window_frame_index};
                REG_EN_FLAGS:      read_reg = energy_flags;
                REG_EN_FRAME_ID:   read_reg = energy_frame_id;
                REG_EN_COUNT:      read_reg = {16'd0, energy_sample_count};
                REG_EN_TOTAL:      read_reg = energy_total[31:0];
                REG_EN_NOISE:      read_reg = energy_noise;
                REG_EN_PEAK:       read_reg = energy_peak;
                REG_EN_PEAK_INDEX: read_reg = {16'd0, energy_peak_index};
                REG_EN_SECOND:     read_reg = energy_second_peak;
                REG_EN_SECOND_IDX: read_reg = {16'd0, energy_second_index};
                REG_EN_PROM:       read_reg = energy_prominence;
                REG_EN_THRESH:     read_reg = {16'd0, energy_threshold_count};
                REG_EXPECT_DONE:   read_reg = DONE_ALL;
                REG_EXPECT_ERROR:  read_reg = 32'd0;
                REG_TEST_CAP:      read_reg = CAP_WORD;
                REG_TEST_BUILD:    read_reg = BUILD_WORD;
                REG_TEST_ABI:      read_reg = ABI_WORD;
                default:           read_reg = 32'd0;
            endcase
        end
    endfunction

    task clear_results;
        begin
            done_mask_reg  <= 32'd0;
            error_mask_reg <= 32'd0;
            done_reg       <= 1'b0;
            irq_reg        <= 1'b0;
            gen_index      <= 4'd0;
            wait_count     <= 4'd0;
        end
    endtask

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_awready <= 1'b0;
            s_axi_wready  <= 1'b0;
            s_axi_bresp   <= 2'b00;
            s_axi_bvalid  <= 1'b0;
            s_axi_arready <= 1'b0;
            s_axi_rdata   <= 32'd0;
            s_axi_rresp   <= 2'b00;
            s_axi_rvalid  <= 1'b0;
            awaddr_hold   <= {AXIL_ADDR_WIDTH{1'b0}};
            aw_hold_valid <= 1'b0;
            wdata_hold    <= 32'd0;
            wstrb_hold    <= 4'd0;
            w_hold_valid  <= 1'b0;
        end else begin
            s_axi_awready <= 1'b0;
            s_axi_wready  <= 1'b0;
            s_axi_arready <= 1'b0;

            if (!aw_hold_valid && !s_axi_bvalid && s_axi_awvalid) begin
                awaddr_hold   <= s_axi_awaddr;
                aw_hold_valid <= 1'b1;
                s_axi_awready <= 1'b1;
            end

            if (!w_hold_valid && !s_axi_bvalid && s_axi_wvalid) begin
                wdata_hold   <= s_axi_wdata;
                wstrb_hold   <= s_axi_wstrb;
                w_hold_valid <= 1'b1;
                s_axi_wready <= 1'b1;
            end

            if (aw_hold_valid && w_hold_valid && !s_axi_bvalid) begin
                aw_hold_valid <= 1'b0;
                w_hold_valid  <= 1'b0;
                s_axi_bresp   <= 2'b00;
                s_axi_bvalid  <= 1'b1;
            end else if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end

            if (!s_axi_rvalid && s_axi_arvalid) begin
                s_axi_arready <= 1'b1;
                s_axi_rdata   <= read_reg(s_axi_araddr[7:0]);
                s_axi_rresp   <= 2'b00;
                s_axi_rvalid  <= 1'b1;
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            control_shadow <= 32'd0;
            enable_reg     <= 1'b0;
            state_reg      <= STATE_IDLE;
            run_id_reg     <= 32'd0;
            clear_modules  <= 1'b0;
            feed_valid     <= 1'b0;
            feed_last      <= 1'b0;
            feed_i         <= 16'sd0;
            feed_q         <= 16'sd0;
            feed_energy    <= 32'd0;
            feed_energy_index <= 16'd0;
            clear_results();
        end else begin
            clear_modules <= 1'b0;
            feed_valid    <= 1'b0;
            feed_last     <= 1'b0;
            feed_i        <= 16'sd0;
            feed_q        <= 16'sd0;
            feed_energy   <= 32'd0;
            feed_energy_index <= 16'd0;
            enable_reg    <= control_shadow[0];

            if (aw_hold_valid && w_hold_valid && !s_axi_bvalid &&
                awaddr_hold[7:0] == REG_CONTROL) begin
                control_shadow <= control_write_value;
                if (control_write_value[2]) begin
                    clear_modules <= 1'b1;
                    state_reg <= STATE_IDLE;
                    clear_results();
                end else if (control_write_value[1] && control_write_value[0]) begin
                    clear_modules <= 1'b1;
                    state_reg <= STATE_CLEAR;
                    run_id_reg <= run_id_reg + 32'd1;
                    clear_results();
                end
            end else begin
                case (state_reg)
                    STATE_IDLE: begin
                        if (!enable_reg) begin
                            done_reg <= 1'b0;
                            irq_reg <= 1'b0;
                        end
                    end
                    STATE_CLEAR: begin
                        clear_modules <= 1'b1;
                        gen_index <= 4'd0;
                        wait_count <= 4'd0;
                        state_reg <= STATE_PRIME;
                    end
                    STATE_PRIME: begin
                        feed_valid <= 1'b1;
                        feed_last <= 1'b0;
                        feed_i <= sample_i_for_index(4'd0);
                        feed_q <= sample_q_for_index(4'd0);
                        feed_energy <= energy_for_index(4'd0);
                        feed_energy_index <= 16'd0;
                        state_reg <= STATE_RUN;
                    end
                    STATE_RUN: begin
                        if (gen_index == 4'd7) begin
                            feed_valid <= 1'b0;
                            feed_last <= 1'b0;
                            feed_i <= 16'sd0;
                            feed_q <= 16'sd0;
                            feed_energy <= 32'd0;
                            feed_energy_index <= 16'd0;
                            gen_index <= 4'd0;
                            wait_count <= 4'd0;
                            state_reg <= STATE_WAIT;
                        end else begin
                            feed_valid <= 1'b1;
                            feed_last <= (gen_index == 4'd6);
                            feed_i <= sample_i_for_index(gen_index + 4'd1);
                            feed_q <= sample_q_for_index(gen_index + 4'd1);
                            feed_energy <= energy_for_index(gen_index + 4'd1);
                            feed_energy_index <= {12'd0, gen_index + 4'd1};
                            gen_index <= gen_index + 4'd1;
                        end
                    end
                    STATE_WAIT: begin
                        wait_count <= wait_count + 4'd1;
                        if (wait_count == 4'd4) begin
                            done_mask_reg <=
                                ((quality_stats_valid &&
                                  (quality_count == 32'd8) &&
                                  (quality_sum_i[31:0] == EXPECT_SUM_I) &&
                                  (quality_sum_q[31:0] == EXPECT_SUM_Q) &&
                                  (quality_sum_i2[31:0] == EXPECT_SUM_I2) &&
                                  (quality_sum_q2[31:0] == EXPECT_SUM_Q2) &&
                                  (quality_sum_iq[31:0] == EXPECT_SUM_IQ) &&
                                  (quality_abs_peak == 16'd32768) &&
                                  (quality_clip_i == 32'd1) &&
                                  (quality_clip_q == 32'd1) &&
                                  (quality_sat_i == 32'd1) &&
                                  (quality_sat_q == 32'd1) &&
                                  (quality_valid_count == 32'd8) &&
                                  (quality_drop_count == 32'd0) &&
                                  !quality_overflow &&
                                  !quality_protocol_error) ? DONE_QUALITY : 32'd0) |
                                (((window_raw_count == 32'd8) &&
                                  (window_accepted_count == 32'd8) &&
                                  (window_dropped_count == 32'd0) &&
                                  (window_overflow_count == 32'd0) &&
                                  (window_frame_id == 32'd1)) ? DONE_WINDOW : 32'd0) |
                                (((energy_flags & 32'h00000111) == 32'h00000111) &&
                                  (energy_frame_id == 32'd1) &&
                                  (energy_sample_count == 16'd8) &&
                                  (energy_total[31:0] == EXPECT_EN_TOTAL) &&
                                  (energy_noise == EXPECT_EN_NOISE) &&
                                  (energy_peak == EXPECT_EN_PEAK) &&
                                  (energy_peak_index == 16'd4) &&
                                  (energy_second_peak == EXPECT_EN_SECOND) &&
                                  (energy_second_index == 16'd6) &&
                                  (energy_prominence == EXPECT_EN_PROM) &&
                                  (energy_threshold_count == 16'd3) ? DONE_ENERGY : 32'd0);

                            error_mask_reg <=
                                ((quality_stats_valid &&
                                  (quality_count == 32'd8) &&
                                  (quality_sum_i[31:0] == EXPECT_SUM_I) &&
                                  (quality_sum_q[31:0] == EXPECT_SUM_Q) &&
                                  (quality_sum_i2[31:0] == EXPECT_SUM_I2) &&
                                  (quality_sum_q2[31:0] == EXPECT_SUM_Q2) &&
                                  (quality_sum_iq[31:0] == EXPECT_SUM_IQ) &&
                                  (quality_abs_peak == 16'd32768) &&
                                  (quality_clip_i == 32'd1) &&
                                  (quality_clip_q == 32'd1) &&
                                  (quality_sat_i == 32'd1) &&
                                  (quality_sat_q == 32'd1) &&
                                  (quality_valid_count == 32'd8) &&
                                  (quality_drop_count == 32'd0) &&
                                  !quality_overflow &&
                                  !quality_protocol_error) ? 32'd0 : DONE_QUALITY) |
                                (((window_raw_count == 32'd8) &&
                                  (window_accepted_count == 32'd8) &&
                                  (window_dropped_count == 32'd0) &&
                                  (window_overflow_count == 32'd0) &&
                                  (window_frame_id == 32'd1)) ? 32'd0 : DONE_WINDOW) |
                                ((((energy_flags & 32'h00000111) == 32'h00000111) &&
                                  (energy_frame_id == 32'd1) &&
                                  (energy_sample_count == 16'd8) &&
                                  (energy_total[31:0] == EXPECT_EN_TOTAL) &&
                                  (energy_noise == EXPECT_EN_NOISE) &&
                                  (energy_peak == EXPECT_EN_PEAK) &&
                                  (energy_peak_index == 16'd4) &&
                                  (energy_second_peak == EXPECT_EN_SECOND) &&
                                  (energy_second_index == 16'd6) &&
                                  (energy_prominence == EXPECT_EN_PROM) &&
                                  (energy_threshold_count == 16'd3)) ? 32'd0 : DONE_ENERGY);
                            done_reg <= 1'b1;
                            irq_reg <= 1'b1;
                            state_reg <= STATE_DONE;
                        end
                    end
                    STATE_DONE: begin
                        if (!enable_reg) begin
                            state_reg <= STATE_IDLE;
                            irq_reg <= 1'b0;
                        end
                    end
                    default: begin
                        state_reg <= STATE_IDLE;
                    end
                endcase
            end
        end
    end

endmodule

`default_nettype wire
