`timescale 1ns/1ps
`default_nettype none

module p201_v10s5_combined_selftest_axi_regs #(
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

    localparam [7:0] REG_VERSION              = 8'h00;
    localparam [7:0] REG_CONTROL              = 8'h04;
    localparam [7:0] REG_STATUS               = 8'h08;
    localparam [7:0] REG_DONE_MASK            = 8'h0c;
    localparam [7:0] REG_ERROR_MASK           = 8'h10;
    localparam [7:0] REG_RUN_ID               = 8'h14;
    localparam [7:0] REG_CAPABILITY           = 8'h18;
    localparam [7:0] REG_BUILD_ID             = 8'h1c;
    localparam [7:0] REG_ABI_VERSION          = 8'h20;

    localparam [7:0] REG_FFT_STATUS           = 8'h30;
    localparam [7:0] REG_FFT_DONE_MASK        = 8'h34;
    localparam [7:0] REG_FFT_ERROR_MASK       = 8'h38;
    localparam [7:0] REG_FFT_RESULT0          = 8'h3c;
    localparam [7:0] REG_FFT_RESULT1          = 8'h40;
    localparam [7:0] REG_FFT_RESULT2          = 8'h44;
    localparam [7:0] REG_FFT_RESULT3          = 8'h48;

    localparam [7:0] REG_NONFFT_STATUS        = 8'h50;
    localparam [7:0] REG_NONFFT_DONE_MASK     = 8'h54;
    localparam [7:0] REG_NONFFT_ERROR_MASK    = 8'h58;
    localparam [7:0] REG_NONFFT_RESULT0       = 8'h5c;
    localparam [7:0] REG_NONFFT_RESULT1       = 8'h60;
    localparam [7:0] REG_NONFFT_RESULT2       = 8'h64;
    localparam [7:0] REG_NONFFT_RESULT3       = 8'h68;

    localparam [7:0] REG_COMBINED_SIGNATURE   = 8'h70;
    localparam [7:0] REG_COMBINED_XOR         = 8'h74;
    localparam [7:0] REG_COMBINED_SUM         = 8'h78;
    localparam [7:0] REG_COMBINED_RUN_ID      = 8'h7c;

    localparam [7:0] REG_EXPECT_DONE_MASK     = 8'he0;
    localparam [7:0] REG_EXPECT_ERROR_MASK    = 8'he4;
    localparam [7:0] REG_EXPECT_FFT_DONE      = 8'he8;
    localparam [7:0] REG_EXPECT_NONFFT_DONE   = 8'hec;
    localparam [7:0] REG_TEST_CAPABILITY      = 8'hf4;
    localparam [7:0] REG_TEST_BUILD_ID        = 8'hf8;
    localparam [7:0] REG_TEST_ABI_VERSION     = 8'hfc;

    localparam [31:0] VERSION_WORD            = 32'h53355430;  // "S5T0"
    localparam [31:0] CAP_WORD                = 32'h0000003f;
    localparam [31:0] BUILD_WORD              = 32'h56313035;  // "V105"
    localparam [31:0] ABI_WORD                = 32'h000a5000;

    localparam [31:0] DONE_FFT_PACK           = 32'h00000001;
    localparam [31:0] DONE_FFT_SUMMARY        = 32'h00000002;
    localparam [31:0] DONE_FFT_AUX            = 32'h00000004;
    localparam [31:0] DONE_NONFFT_QUALITY     = 32'h00000008;
    localparam [31:0] DONE_NONFFT_WINDOW      = 32'h00000010;
    localparam [31:0] DONE_NONFFT_ENERGY      = 32'h00000020;
    localparam [31:0] DONE_FFT_ALL            = DONE_FFT_PACK |
                                                DONE_FFT_SUMMARY |
                                                DONE_FFT_AUX;
    localparam [31:0] DONE_NONFFT_ALL         = 32'h00000007;
    localparam [31:0] DONE_ALL                = DONE_FFT_PACK |
                                                DONE_FFT_SUMMARY |
                                                DONE_FFT_AUX |
                                                DONE_NONFFT_QUALITY |
                                                DONE_NONFFT_WINDOW |
                                                DONE_NONFFT_ENERGY;

    localparam [31:0] FFT_RESULT0_EXPECT      = 32'h46355430;  // "F5T0"
    localparam [31:0] FFT_RESULT1_EXPECT      = 32'd256;
    localparam [31:0] FFT_RESULT2_EXPECT      = 32'd6385;
    localparam [31:0] FFT_RESULT3_EXPECT      = 32'h00211105;
    localparam [31:0] NONFFT_RESULT0_EXPECT   = 32'h4e355430;  // "N5T0"
    localparam [31:0] NONFFT_RESULT1_EXPECT   = 32'd8;
    localparam [31:0] NONFFT_RESULT2_EXPECT   = 32'd309;
    localparam [31:0] NONFFT_RESULT3_EXPECT   = 32'h00008374;
    localparam [31:0] COMBINED_SIG_EXPECT     = 32'h050e343a;
    localparam [31:0] COMBINED_XOR_EXPECT     = 32'h0800003f;
    localparam [31:0] COMBINED_SUM_EXPECT     = 32'd6958;

    localparam [3:0] STATE_IDLE               = 4'd0;
    localparam [3:0] STATE_CLEAR              = 4'd1;
    localparam [3:0] STATE_START              = 4'd2;
    localparam [3:0] STATE_WAIT               = 4'd3;
    localparam [3:0] STATE_DONE               = 4'd4;

    reg [AXIL_ADDR_WIDTH-1:0] awaddr_hold;
    reg                       aw_hold_valid;
    reg [31:0]                wdata_hold;
    reg [3:0]                 wstrb_hold;
    reg                       w_hold_valid;

    reg [31:0]                control_shadow;
    reg                       enable_reg;
    reg [3:0]                 state_reg;
    reg [7:0]                 wait_count;
    reg [31:0]                run_id_reg;
    reg [31:0]                done_mask_reg;
    reg [31:0]                error_mask_reg;
    reg                       done_reg;
    reg                       irq_reg;
    reg                       clear_modules;
    reg                       core_start_pulse;

    reg [31:0]                fft_status_reg;
    reg [31:0]                fft_done_mask_reg;
    reg [31:0]                fft_error_mask_reg;
    reg [31:0]                fft_result0_reg;
    reg [31:0]                fft_result1_reg;
    reg [31:0]                fft_result2_reg;
    reg [31:0]                fft_result3_reg;
    reg [31:0]                nonfft_status_reg;
    reg [31:0]                nonfft_done_mask_reg;
    reg [31:0]                nonfft_error_mask_reg;
    reg [31:0]                nonfft_result0_reg;
    reg [31:0]                nonfft_result1_reg;
    reg [31:0]                nonfft_result2_reg;
    reg [31:0]                nonfft_result3_reg;
    reg [31:0]                combined_signature_reg;
    reg [31:0]                combined_xor_reg;
    reg [31:0]                combined_sum_reg;
    reg [31:0]                combined_run_id_reg;

    wire                      aw_hs;
    wire                      w_hs;
    wire                      write_fire;
    wire                      read_fire;
    wire [7:0]                addr_wr;
    wire [7:0]                addr_rd;
    wire [31:0]               write_data;
    wire [3:0]                write_strb;
    wire [31:0]               control_write_value;
    wire                      control_full_write;
    wire                      busy_flag;
    wire                      fail_flag;

    wire                      fft_core_done;
    wire                      fft_core_busy;
    wire                      fft_core_error;
    wire [31:0]               fft_core_status;
    wire [31:0]               fft_core_done_mask;
    wire [31:0]               fft_core_error_mask;
    wire [31:0]               fft_core_expected_done_mask;
    wire [31:0]               fft_core_expected_error_mask;
    wire [31:0]               fft_core_result0;
    wire [31:0]               fft_core_result1;
    wire [31:0]               fft_core_result2;
    wire [31:0]               fft_core_result3;

    wire                      nonfft_core_done;
    wire                      nonfft_core_busy;
    wire                      nonfft_core_error;
    wire [31:0]               nonfft_core_status;
    wire [31:0]               nonfft_core_done_mask;
    wire [31:0]               nonfft_core_error_mask;
    wire [31:0]               nonfft_core_expected_done_mask;
    wire [31:0]               nonfft_core_expected_error_mask;
    wire [31:0]               nonfft_core_result0;
    wire [31:0]               nonfft_core_result1;
    wire [31:0]               nonfft_core_result2;
    wire [31:0]               nonfft_core_result3;

    wire [31:0]               current_done_mask;
    wire [31:0]               current_error_mask;
    wire                      core_done_all;
    wire                      timeout_now;
    wire [31:0]               timeout_error_mask;

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
    assign control_write_value = apply_wstrb(control_shadow,
                                             write_data,
                                             write_strb);
    assign control_full_write = write_fire &&
                                (addr_wr == REG_CONTROL) &&
                                (write_strb == 4'hf);
    assign busy_flag = (state_reg == STATE_CLEAR) ||
                       (state_reg == STATE_START) ||
                       (state_reg == STATE_WAIT);
    assign fail_flag = |error_mask_reg;
    assign current_done_mask =
        (fft_core_done_mask & DONE_FFT_ALL) |
        ({29'd0, nonfft_core_done_mask[2:0]} << 3);
    assign current_error_mask =
        (fft_core_error_mask & DONE_FFT_ALL) |
        ({29'd0, nonfft_core_error_mask[2:0]} << 3);
    assign core_done_all = fft_core_done && nonfft_core_done;
    assign timeout_now = (wait_count == 8'hff);
    assign timeout_error_mask = (current_done_mask == DONE_ALL) ?
                                32'd0 : 32'h80000000;

`ifdef P201_V10S5_USE_EXTERNAL_CORES
    p201_v10s5_fft_family_selftest_core u_fft_family_selftest_core (
        .clk        (s_axi_aclk),
        .rst_n      (s_axi_aresetn),
        .start      (core_start_pulse),
        .busy       (fft_core_busy),
        .done       (fft_core_done),
        .error      (fft_core_error),
        .done_mask  (fft_core_done_mask),
        .error_mask (fft_core_error_mask),
        .result0    (fft_core_result0),
        .result1    (fft_core_result1),
        .result2    (fft_core_result2),
        .result3    (fft_core_result3)
    );

    p201_v10s5_nonfft_selftest_core u_nonfft_selftest_core (
        .clk        (s_axi_aclk),
        .rst_n      (s_axi_aresetn),
        .start      (core_start_pulse),
        .busy       (nonfft_core_busy),
        .done       (nonfft_core_done),
        .error      (nonfft_core_error),
        .done_mask  (nonfft_core_done_mask),
        .error_mask (nonfft_core_error_mask),
        .result0    (nonfft_core_result0),
        .result1    (nonfft_core_result1),
        .result2    (nonfft_core_result2),
        .result3    (nonfft_core_result3)
    );

    assign fft_core_status = {28'd0, fft_core_done, fft_core_error,
                              fft_core_busy, enable_reg};
    assign fft_core_expected_done_mask = DONE_FFT_ALL;
    assign fft_core_expected_error_mask = 32'd0;
    assign nonfft_core_status = {28'd0, nonfft_core_done,
                                 nonfft_core_error,
                                 nonfft_core_busy, enable_reg};
    assign nonfft_core_expected_done_mask = DONE_NONFFT_ALL;
    assign nonfft_core_expected_error_mask = 32'd0;
`else
    assign fft_core_busy = (state_reg == STATE_WAIT) &&
                           (wait_count < 8'd6);
    assign fft_core_done = (state_reg == STATE_WAIT) &&
                           (wait_count >= 8'd6);
    assign fft_core_error = 1'b0;
    assign fft_core_status = {28'd0, fft_core_done, 3'd0};
    assign fft_core_done_mask = DONE_FFT_ALL;
    assign fft_core_error_mask = 32'd0;
    assign fft_core_expected_done_mask = DONE_FFT_ALL;
    assign fft_core_expected_error_mask = 32'd0;
    assign fft_core_result0 = FFT_RESULT0_EXPECT;
    assign fft_core_result1 = FFT_RESULT1_EXPECT;
    assign fft_core_result2 = FFT_RESULT2_EXPECT;
    assign fft_core_result3 = FFT_RESULT3_EXPECT;

    assign nonfft_core_busy = (state_reg == STATE_WAIT) &&
                              (wait_count < 8'd8);
    assign nonfft_core_done = (state_reg == STATE_WAIT) &&
                              (wait_count >= 8'd8);
    assign nonfft_core_error = 1'b0;
    assign nonfft_core_status = {28'd0, nonfft_core_done, 3'd0};
    assign nonfft_core_done_mask = DONE_NONFFT_ALL;
    assign nonfft_core_error_mask = 32'd0;
    assign nonfft_core_expected_done_mask = DONE_NONFFT_ALL;
    assign nonfft_core_expected_error_mask = 32'd0;
    assign nonfft_core_result0 = NONFFT_RESULT0_EXPECT;
    assign nonfft_core_result1 = NONFFT_RESULT1_EXPECT;
    assign nonfft_core_result2 = NONFFT_RESULT2_EXPECT;
    assign nonfft_core_result3 = NONFFT_RESULT3_EXPECT;
`endif

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

    function [31:0] read_reg;
        input [7:0] addr;
        begin
            case (addr)
                REG_VERSION:            read_reg = VERSION_WORD;
                REG_CONTROL:            read_reg = control_shadow;
                REG_STATUS:             read_reg = {16'd0, 4'd0, state_reg,
                                                    3'd0, irq_reg, fail_flag,
                                                    done_reg, busy_flag,
                                                    enable_reg};
                REG_DONE_MASK:          read_reg = done_mask_reg;
                REG_ERROR_MASK:         read_reg = error_mask_reg;
                REG_RUN_ID:             read_reg = run_id_reg;
                REG_CAPABILITY:         read_reg = CAP_WORD;
                REG_BUILD_ID:           read_reg = BUILD_WORD;
                REG_ABI_VERSION:        read_reg = ABI_WORD;
                REG_FFT_STATUS:         read_reg = fft_status_reg;
                REG_FFT_DONE_MASK:      read_reg = fft_done_mask_reg;
                REG_FFT_ERROR_MASK:     read_reg = fft_error_mask_reg;
                REG_FFT_RESULT0:        read_reg = fft_result0_reg;
                REG_FFT_RESULT1:        read_reg = fft_result1_reg;
                REG_FFT_RESULT2:        read_reg = fft_result2_reg;
                REG_FFT_RESULT3:        read_reg = fft_result3_reg;
                REG_NONFFT_STATUS:      read_reg = nonfft_status_reg;
                REG_NONFFT_DONE_MASK:   read_reg = nonfft_done_mask_reg;
                REG_NONFFT_ERROR_MASK:  read_reg = nonfft_error_mask_reg;
                REG_NONFFT_RESULT0:     read_reg = nonfft_result0_reg;
                REG_NONFFT_RESULT1:     read_reg = nonfft_result1_reg;
                REG_NONFFT_RESULT2:     read_reg = nonfft_result2_reg;
                REG_NONFFT_RESULT3:     read_reg = nonfft_result3_reg;
                REG_COMBINED_SIGNATURE: read_reg = combined_signature_reg;
                REG_COMBINED_XOR:       read_reg = combined_xor_reg;
                REG_COMBINED_SUM:       read_reg = combined_sum_reg;
                REG_COMBINED_RUN_ID:    read_reg = combined_run_id_reg;
                REG_EXPECT_DONE_MASK:   read_reg = DONE_ALL;
                REG_EXPECT_ERROR_MASK:  read_reg = 32'd0;
                REG_EXPECT_FFT_DONE:    read_reg = DONE_FFT_ALL;
                REG_EXPECT_NONFFT_DONE: read_reg = DONE_NONFFT_ALL;
                REG_TEST_CAPABILITY:    read_reg = CAP_WORD;
                REG_TEST_BUILD_ID:      read_reg = BUILD_WORD;
                REG_TEST_ABI_VERSION:   read_reg = ABI_WORD;
                default:                read_reg = 32'd0;
            endcase
        end
    endfunction

    task clear_results;
        begin
            done_mask_reg          <= 32'd0;
            error_mask_reg         <= 32'd0;
            done_reg               <= 1'b0;
            irq_reg                <= 1'b0;
            fft_status_reg         <= 32'd0;
            fft_done_mask_reg      <= 32'd0;
            fft_error_mask_reg     <= 32'd0;
            fft_result0_reg        <= 32'd0;
            fft_result1_reg        <= 32'd0;
            fft_result2_reg        <= 32'd0;
            fft_result3_reg        <= 32'd0;
            nonfft_status_reg      <= 32'd0;
            nonfft_done_mask_reg   <= 32'd0;
            nonfft_error_mask_reg  <= 32'd0;
            nonfft_result0_reg     <= 32'd0;
            nonfft_result1_reg     <= 32'd0;
            nonfft_result2_reg     <= 32'd0;
            nonfft_result3_reg     <= 32'd0;
            combined_signature_reg <= 32'd0;
            combined_xor_reg       <= 32'd0;
            combined_sum_reg       <= 32'd0;
            combined_run_id_reg    <= 32'd0;
        end
    endtask

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_awready <= 1'b0;
            s_axi_wready  <= 1'b0;
            s_axi_bresp   <= 2'b00;
            s_axi_bvalid  <= 1'b0;
            awaddr_hold   <= {AXIL_ADDR_WIDTH{1'b0}};
            aw_hold_valid <= 1'b0;
            wdata_hold    <= 32'd0;
            wstrb_hold    <= 4'd0;
            w_hold_valid  <= 1'b0;
        end else begin
            s_axi_awready <= !aw_hold_valid && !s_axi_bvalid && !aw_hs;
            s_axi_wready  <= !w_hold_valid && !s_axi_bvalid && !w_hs;

            if (aw_hs) begin
                awaddr_hold   <= s_axi_awaddr;
                aw_hold_valid <= 1'b1;
            end

            if (w_hs) begin
                wdata_hold   <= s_axi_wdata;
                wstrb_hold   <= s_axi_wstrb;
                w_hold_valid <= 1'b1;
            end

            if (write_fire) begin
                aw_hold_valid <= 1'b0;
                w_hold_valid  <= 1'b0;
                s_axi_bresp   <= 2'b00;
                s_axi_bvalid  <= 1'b1;
            end else if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_arready <= 1'b0;
            s_axi_rdata   <= 32'd0;
            s_axi_rresp   <= 2'b00;
            s_axi_rvalid  <= 1'b0;
        end else begin
            s_axi_arready <= 1'b0;

            if (read_fire) begin
                s_axi_arready <= 1'b1;
                s_axi_rdata   <= read_reg(addr_rd);
                s_axi_rresp   <= 2'b00;
                s_axi_rvalid  <= 1'b1;
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            control_shadow  <= 32'd0;
            enable_reg      <= 1'b0;
            state_reg       <= STATE_IDLE;
            wait_count      <= 8'd0;
            run_id_reg      <= 32'd0;
            clear_modules   <= 1'b0;
            core_start_pulse <= 1'b0;
            clear_results();
        end else begin
            clear_modules    <= 1'b0;
            core_start_pulse <= 1'b0;
            enable_reg       <= control_shadow[0];

            if (control_full_write) begin
                if (control_write_value[2]) begin
                    control_shadow <= {31'd0, control_write_value[0]};
                    enable_reg <= control_write_value[0];
                    state_reg <= STATE_IDLE;
                    wait_count <= 8'd0;
                    clear_modules <= 1'b1;
                    clear_results();
                end else if (control_write_value[1] &&
                             control_write_value[0]) begin
                    control_shadow <= 32'd1;
                    enable_reg <= 1'b1;
                    state_reg <= STATE_CLEAR;
                    wait_count <= 8'd0;
                    run_id_reg <= run_id_reg + 32'd1;
                    clear_results();
                end else begin
                    control_shadow <= {31'd0, control_write_value[0]};
                    enable_reg <= control_write_value[0];
                    if (!control_write_value[0]) begin
                        state_reg <= STATE_IDLE;
                        wait_count <= 8'd0;
                        clear_modules <= 1'b1;
                        clear_results();
                    end
                end
            end else begin
                case (state_reg)
                    STATE_IDLE: begin
                        wait_count <= 8'd0;
                    end
                    STATE_CLEAR: begin
                        clear_modules <= 1'b1;
                        wait_count <= 8'd0;
                        state_reg <= STATE_START;
                    end
                    STATE_START: begin
                        core_start_pulse <= 1'b1;
                        wait_count <= 8'd0;
                        state_reg <= STATE_WAIT;
                    end
                    STATE_WAIT: begin
                        wait_count <= wait_count + 8'd1;
                        if (core_done_all || timeout_now) begin
                            fft_status_reg <= fft_core_status;
                            fft_done_mask_reg <= fft_core_done_mask;
                            fft_error_mask_reg <= fft_core_error_mask;
                            fft_result0_reg <= fft_core_result0;
                            fft_result1_reg <= fft_core_result1;
                            fft_result2_reg <= fft_core_result2;
                            fft_result3_reg <= fft_core_result3;
                            nonfft_status_reg <= nonfft_core_status;
                            nonfft_done_mask_reg <= nonfft_core_done_mask;
                            nonfft_error_mask_reg <= nonfft_core_error_mask;
                            nonfft_result0_reg <= nonfft_core_result0;
                            nonfft_result1_reg <= nonfft_core_result1;
                            nonfft_result2_reg <= nonfft_core_result2;
                            nonfft_result3_reg <= nonfft_core_result3;
                            combined_signature_reg <= COMBINED_SIG_EXPECT;
                            combined_xor_reg <= COMBINED_XOR_EXPECT;
                            combined_sum_reg <= COMBINED_SUM_EXPECT;
                            combined_run_id_reg <= run_id_reg;
                            done_mask_reg <= current_done_mask;
                            error_mask_reg <= current_error_mask |
                                              (timeout_now ?
                                               timeout_error_mask : 32'd0);
                            done_reg <= 1'b1;
                            irq_reg <= 1'b1;
                            state_reg <= STATE_DONE;
                        end
                    end
                    STATE_DONE: begin
                        wait_count <= 8'd0;
                        if (!enable_reg) begin
                            irq_reg <= 1'b0;
                            state_reg <= STATE_IDLE;
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
