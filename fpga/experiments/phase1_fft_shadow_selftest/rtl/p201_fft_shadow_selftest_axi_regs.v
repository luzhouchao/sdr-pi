`timescale 1ns/1ps
`default_nettype none

module p201_fft_shadow_selftest_axi_regs #(
    parameter integer AXIL_ADDR_WIDTH = 12
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

    localparam [11:0] REG_MAGIC              = 12'h400;
    localparam [11:0] REG_BUILD_ID           = 12'h404;
    localparam [11:0] REG_ABI_VERSION        = 12'h408;
    localparam [11:0] REG_CAPABILITY         = 12'h40c;
    localparam [11:0] REG_SEQUENCE           = 12'h410;
    localparam [11:0] REG_STATUS             = 12'h414;
    localparam [11:0] REG_SAMPLE_COUNT       = 12'h418;
    localparam [11:0] REG_NFFT               = 12'h41c;
    localparam [11:0] REG_SAMPLE_RATE_HZ     = 12'h420;
    localparam [11:0] REG_WINDOW_ID          = 12'h424;
    localparam [11:0] REG_SCALE_EXP          = 12'h428;
    localparam [11:0] REG_COARSE_COUNT       = 12'h42c;
    localparam [11:0] REG_COARSE_STEP_Q16    = 12'h430;
    localparam [11:0] REG_RX_MASK            = 12'h434;
    localparam [11:0] REG_SOURCE_FRAME       = 12'h438;
    localparam [11:0] REG_RESERVED_43C       = 12'h43c;
    localparam [11:0] REG_RSSI_DBFS_X100     = 12'h440;
    localparam [11:0] REG_PEAK_BIN           = 12'h444;
    localparam [11:0] REG_PEAK_OFFSET_HZ     = 12'h448;
    localparam [11:0] REG_PEAK_POWER_X100    = 12'h44c;
    localparam [11:0] REG_NOISE_FLOOR_X100   = 12'h450;
    localparam [11:0] REG_PROMINENCE_X100    = 12'h454;
    localparam [11:0] REG_BAND_POWER_X100    = 12'h458;
    localparam [11:0] REG_SUMMARY_FLAGS      = 12'h45c;
    localparam [11:0] REG_TOP_COUNT          = 12'h460;
    localparam [11:0] REG_TOP_VALID_MASK     = 12'h464;
    localparam [11:0] REG_TOP0_BIN           = 12'h468;
    localparam [11:0] REG_TOP0_POWER_X100    = 12'h46c;
    localparam [11:0] REG_TOP1_BIN           = 12'h470;
    localparam [11:0] REG_TOP1_POWER_X100    = 12'h474;
    localparam [11:0] REG_TOP2_BIN           = 12'h478;
    localparam [11:0] REG_TOP2_POWER_X100    = 12'h47c;
    localparam [11:0] REG_TOP3_BIN           = 12'h480;
    localparam [11:0] REG_TOP3_POWER_X100    = 12'h484;
    localparam [11:0] REG_COARSE_BASE        = 12'h500;
    localparam [11:0] REG_COARSE_LAST        = 12'h6fc;

    localparam [31:0] MAGIC_WORD             = 32'h46465431;  // "FFT1"
    localparam [31:0] BUILD_WORD             = 32'h46505331;  // "FPS1"
    localparam [31:0] ABI_WORD               = 32'h00020000;
    localparam [31:0] CAPABILITY_WORD        = 32'h00000fff;
    localparam [31:0] STATUS_VALID_WORD      = 32'h00000001;

    localparam [31:0] SAMPLE_COUNT_WORD      = 32'd4096;
    localparam [31:0] NFFT_WORD              = 32'd2048;
    localparam [31:0] SAMPLE_RATE_WORD       = 32'd2000000;
    localparam [31:0] WINDOW_ID_WORD         = 32'd1;
    localparam [31:0] COARSE_COUNT_WORD      = 32'd96;
    localparam [31:0] COARSE_STEP_WORD       = 32'd1398101;
    localparam [31:0] RX_MASK_WORD           = 32'd1;

    reg [AXIL_ADDR_WIDTH-1:0] awaddr_hold;
    reg                       aw_hold_valid;
    reg [31:0]                wdata_hold;
    reg [3:0]                 wstrb_hold;
    reg                       w_hold_valid;

    wire                      aw_hs;
    wire                      w_hs;
    wire                      write_fire;
    wire                      read_fire;
    wire [11:0]               addr_rd;

    assign irq = 1'b0;
    assign aw_hs = s_axi_awvalid && s_axi_awready;
    assign w_hs = s_axi_wvalid && s_axi_wready;
    assign write_fire = !s_axi_bvalid &&
                        (aw_hold_valid || aw_hs) &&
                        (w_hold_valid || w_hs);
    assign read_fire = !s_axi_rvalid && s_axi_arvalid;
    assign addr_rd = s_axi_araddr[11:0];

    function [31:0] coarse_psd_word;
        input [6:0] index;
        begin
            case (index)
                7'd00: coarse_psd_word = 32'hFFFFCFC6;
                7'd01: coarse_psd_word = 32'hFFFFD020;
                7'd02: coarse_psd_word = 32'hFFFFCEE5;
                7'd03: coarse_psd_word = 32'hFFFFCF33;
                7'd04: coarse_psd_word = 32'hFFFFD195;
                7'd05: coarse_psd_word = 32'hFFFFD0E2;
                7'd06: coarse_psd_word = 32'hFFFFD092;
                7'd07: coarse_psd_word = 32'hFFFFD081;
                7'd08: coarse_psd_word = 32'hFFFFCEBA;
                7'd09: coarse_psd_word = 32'hFFFFCF84;
                7'd10: coarse_psd_word = 32'hFFFFD257;
                7'd11: coarse_psd_word = 32'hFFFFD1B5;
                7'd12: coarse_psd_word = 32'hFFFFD44C;
                7'd13: coarse_psd_word = 32'hFFFFD0CD;
                7'd14: coarse_psd_word = 32'hFFFFD15A;
                7'd15: coarse_psd_word = 32'hFFFFCF07;
                7'd16: coarse_psd_word = 32'hFFFFCEEA;
                7'd17: coarse_psd_word = 32'hFFFFD188;
                7'd18: coarse_psd_word = 32'hFFFFD1D2;
                7'd19: coarse_psd_word = 32'hFFFFD225;
                7'd20: coarse_psd_word = 32'hFFFFD00E;
                7'd21: coarse_psd_word = 32'hFFFFCE71;
                7'd22: coarse_psd_word = 32'hFFFFCFD9;
                7'd23: coarse_psd_word = 32'hFFFFCFA1;
                7'd24: coarse_psd_word = 32'hFFFFD032;
                7'd25: coarse_psd_word = 32'hFFFFD2BF;
                7'd26: coarse_psd_word = 32'hFFFFCF66;
                7'd27: coarse_psd_word = 32'hFFFFD019;
                7'd28: coarse_psd_word = 32'hFFFFD3BA;
                7'd29: coarse_psd_word = 32'hFFFFCF15;
                7'd30: coarse_psd_word = 32'hFFFFD5C8;
                7'd31: coarse_psd_word = 32'hFFFFD172;
                7'd32: coarse_psd_word = 32'hFFFFD715;
                7'd33: coarse_psd_word = 32'hFFFFFA2E;
                7'd34: coarse_psd_word = 32'hFFFFCF0A;
                7'd35: coarse_psd_word = 32'hFFFFD20D;
                7'd36: coarse_psd_word = 32'hFFFFCF8C;
                7'd37: coarse_psd_word = 32'hFFFFCE73;
                7'd38: coarse_psd_word = 32'hFFFFD1E1;
                7'd39: coarse_psd_word = 32'hFFFFCFEF;
                7'd40: coarse_psd_word = 32'hFFFFD12D;
                7'd41: coarse_psd_word = 32'hFFFFD081;
                7'd42: coarse_psd_word = 32'hFFFFD0B6;
                7'd43: coarse_psd_word = 32'hFFFFD009;
                7'd44: coarse_psd_word = 32'hFFFFD1F2;
                7'd45: coarse_psd_word = 32'hFFFFD035;
                7'd46: coarse_psd_word = 32'hFFFFD059;
                7'd47: coarse_psd_word = 32'hFFFFD06B;
                7'd48: coarse_psd_word = 32'hFFFFF1C0;
                7'd49: coarse_psd_word = 32'hFFFFCFED;
                7'd50: coarse_psd_word = 32'hFFFFD17A;
                7'd51: coarse_psd_word = 32'hFFFFD600;
                7'd52: coarse_psd_word = 32'hFFFFCFEB;
                7'd53: coarse_psd_word = 32'hFFFFFD0E;
                7'd54: coarse_psd_word = 32'hFFFFD86E;
                7'd55: coarse_psd_word = 32'hFFFFD01A;
                7'd56: coarse_psd_word = 32'hFFFFD581;
                7'd57: coarse_psd_word = 32'hFFFFD044;
                7'd58: coarse_psd_word = 32'hFFFFD280;
                7'd59: coarse_psd_word = 32'hFFFFD078;
                7'd60: coarse_psd_word = 32'hFFFFD0DD;
                7'd61: coarse_psd_word = 32'hFFFFD010;
                7'd62: coarse_psd_word = 32'hFFFFD076;
                7'd63: coarse_psd_word = 32'hFFFFCEA2;
                7'd64: coarse_psd_word = 32'hFFFFD0D9;
                7'd65: coarse_psd_word = 32'hFFFFD19C;
                7'd66: coarse_psd_word = 32'hFFFFCF11;
                7'd67: coarse_psd_word = 32'hFFFFD145;
                7'd68: coarse_psd_word = 32'hFFFFD0E3;
                7'd69: coarse_psd_word = 32'hFFFFD0EA;
                7'd70: coarse_psd_word = 32'hFFFFCF9F;
                7'd71: coarse_psd_word = 32'hFFFFF830;
                7'd72: coarse_psd_word = 32'hFFFFF5D7;
                7'd73: coarse_psd_word = 32'hFFFFCFB8;
                7'd74: coarse_psd_word = 32'hFFFFD4AC;
                7'd75: coarse_psd_word = 32'hFFFFCFB6;
                7'd76: coarse_psd_word = 32'hFFFFD015;
                7'd77: coarse_psd_word = 32'hFFFFD0A8;
                7'd78: coarse_psd_word = 32'hFFFFCF3C;
                7'd79: coarse_psd_word = 32'hFFFFD255;
                7'd80: coarse_psd_word = 32'hFFFFD090;
                7'd81: coarse_psd_word = 32'hFFFFD1B7;
                7'd82: coarse_psd_word = 32'hFFFFD01E;
                7'd83: coarse_psd_word = 32'hFFFFCF57;
                7'd84: coarse_psd_word = 32'hFFFFCDF9;
                7'd85: coarse_psd_word = 32'hFFFFD20E;
                7'd86: coarse_psd_word = 32'hFFFFD14A;
                7'd87: coarse_psd_word = 32'hFFFFD1AD;
                7'd88: coarse_psd_word = 32'hFFFFCFD5;
                7'd89: coarse_psd_word = 32'hFFFFD115;
                7'd90: coarse_psd_word = 32'hFFFFCE7B;
                7'd91: coarse_psd_word = 32'hFFFFCFDB;
                7'd92: coarse_psd_word = 32'hFFFFD080;
                7'd93: coarse_psd_word = 32'hFFFFCFAA;
                7'd94: coarse_psd_word = 32'hFFFFCFDB;
                7'd95: coarse_psd_word = 32'hFFFFD3B1;
                default: coarse_psd_word = 32'd0;
            endcase
        end
    endfunction

    function [31:0] read_reg;
        input [11:0] addr;
        begin
            if ((addr >= REG_COARSE_BASE) &&
                (addr <= REG_COARSE_LAST) &&
                (addr[1:0] == 2'b00)) begin
                read_reg = coarse_psd_word((addr - REG_COARSE_BASE) >> 2);
            end else begin
                case (addr)
                    REG_MAGIC:            read_reg = MAGIC_WORD;
                    REG_BUILD_ID:         read_reg = BUILD_WORD;
                    REG_ABI_VERSION:      read_reg = ABI_WORD;
                    REG_CAPABILITY:       read_reg = CAPABILITY_WORD;
                    REG_SEQUENCE:         read_reg = 32'd1;
                    REG_STATUS:           read_reg = STATUS_VALID_WORD;
                    REG_SAMPLE_COUNT:     read_reg = SAMPLE_COUNT_WORD;
                    REG_NFFT:             read_reg = NFFT_WORD;
                    REG_SAMPLE_RATE_HZ:   read_reg = SAMPLE_RATE_WORD;
                    REG_WINDOW_ID:        read_reg = WINDOW_ID_WORD;
                    REG_SCALE_EXP:        read_reg = 32'd0;
                    REG_COARSE_COUNT:     read_reg = COARSE_COUNT_WORD;
                    REG_COARSE_STEP_Q16:  read_reg = COARSE_STEP_WORD;
                    REG_RX_MASK:          read_reg = RX_MASK_WORD;
                    REG_SOURCE_FRAME:     read_reg = 32'd1;
                    REG_RESERVED_43C:     read_reg = 32'd0;
                    REG_RSSI_DBFS_X100:   read_reg = 32'hFFFFFD6C;
                    REG_PEAK_BIN:         read_reg = 32'd1147;
                    REG_PEAK_OFFSET_HZ:   read_reg = 32'h0001D535;
                    REG_PEAK_POWER_X100:  read_reg = 32'hFFFFFD0E;
                    REG_NOISE_FLOOR_X100: read_reg = 32'hFFFFCD2B;
                    REG_PROMINENCE_X100:  read_reg = 32'h00002FE3;
                    REG_BAND_POWER_X100:  read_reg = 32'hFFFFF12D;
                    REG_SUMMARY_FLAGS:    read_reg = 32'd0;
                    REG_TOP_COUNT:        read_reg = 32'd4;
                    REG_TOP_VALID_MASK:   read_reg = 32'h0000000f;
                    REG_TOP0_BIN:         read_reg = 32'd1147;
                    REG_TOP0_POWER_X100:  read_reg = 32'hFFFFFD0E;
                    REG_TOP1_BIN:         read_reg = 32'd707;
                    REG_TOP1_POWER_X100:  read_reg = 32'hFFFFFA2E;
                    REG_TOP2_BIN:         read_reg = 32'd1535;
                    REG_TOP2_POWER_X100:  read_reg = 32'hFFFFF830;
                    REG_TOP3_BIN:         read_reg = 32'd1041;
                    REG_TOP3_POWER_X100:  read_reg = 32'hFFFFF1C0;
                    default:              read_reg = 32'd0;
                endcase
            end
        end
    endfunction

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

endmodule

`default_nettype wire
