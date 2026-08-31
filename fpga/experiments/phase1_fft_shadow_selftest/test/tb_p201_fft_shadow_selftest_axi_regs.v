`timescale 1ns/1ps
`default_nettype none

module tb_p201_fft_shadow_selftest_axi_regs;

    reg          clk;
    reg          rst_n;
    reg  [11:0]  awaddr;
    reg          awvalid;
    wire         awready;
    reg  [31:0]  wdata;
    reg  [3:0]   wstrb;
    reg          wvalid;
    wire         wready;
    wire [1:0]   bresp;
    wire         bvalid;
    reg          bready;
    reg  [11:0]  araddr;
    reg          arvalid;
    wire         arready;
    wire [31:0]  rdata;
    wire [1:0]   rresp;
    wire         rvalid;
    reg          rready;
    wire         irq;

    integer      errors;
    integer      index;
    reg [31:0]   read_value;
    reg [11:0]   coarse_addr;

    p201_fft_shadow_selftest_axi_regs dut (
        .s_axi_aclk    (clk),
        .s_axi_aresetn (rst_n),
        .s_axi_awaddr  (awaddr),
        .s_axi_awvalid (awvalid),
        .s_axi_awready (awready),
        .s_axi_wdata   (wdata),
        .s_axi_wstrb   (wstrb),
        .s_axi_wvalid  (wvalid),
        .s_axi_wready  (wready),
        .s_axi_bresp   (bresp),
        .s_axi_bvalid  (bvalid),
        .s_axi_bready  (bready),
        .s_axi_araddr  (araddr),
        .s_axi_arvalid (arvalid),
        .s_axi_arready (arready),
        .s_axi_rdata   (rdata),
        .s_axi_rresp   (rresp),
        .s_axi_rvalid  (rvalid),
        .s_axi_rready  (rready),
        .irq           (irq)
    );

    initial begin
        clk = 1'b0;
        forever begin
            #4 clk = ~clk;
        end
    end

    task axi_write;
        input [11:0] addr;
        input [31:0] data;
        begin
            @(posedge clk);
            awaddr <= addr;
            wdata <= data;
            wstrb <= 4'hf;
            awvalid <= 1'b1;
            wvalid <= 1'b1;
            while (!(awready && wready)) begin
                @(posedge clk);
            end
            @(posedge clk);
            awvalid <= 1'b0;
            wvalid <= 1'b0;
            while (!bvalid) begin
                @(posedge clk);
            end
            if (bresp !== 2'b00) begin
                $display("CHECK FAIL write bresp addr=0x%03x bresp=%0d",
                         addr, bresp);
                errors = errors + 1;
            end
            @(posedge clk);
        end
    endtask

    task axi_read;
        input [11:0] addr;
        output [31:0] data;
        begin
            @(posedge clk);
            araddr <= addr;
            arvalid <= 1'b1;
            while (!arready) begin
                @(posedge clk);
            end
            @(posedge clk);
            arvalid <= 1'b0;
            while (!rvalid) begin
                @(posedge clk);
            end
            data = rdata;
            if (rresp !== 2'b00) begin
                $display("CHECK FAIL read rresp addr=0x%03x rresp=%0d",
                         addr, rresp);
                errors = errors + 1;
            end
            @(posedge clk);
        end
    endtask

    task check32;
        input [255:0] name;
        input [31:0] got;
        input [31:0] exp;
        begin
            if (got !== exp) begin
                $display("CHECK FAIL %0s got=0x%08x exp=0x%08x",
                         name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    function [31:0] expected_coarse;
        input [6:0] coarse_index;
        begin
            case (coarse_index)
                7'd00: expected_coarse = 32'hFFFFCFC6;
                7'd01: expected_coarse = 32'hFFFFD020;
                7'd02: expected_coarse = 32'hFFFFCEE5;
                7'd03: expected_coarse = 32'hFFFFCF33;
                7'd04: expected_coarse = 32'hFFFFD195;
                7'd05: expected_coarse = 32'hFFFFD0E2;
                7'd06: expected_coarse = 32'hFFFFD092;
                7'd07: expected_coarse = 32'hFFFFD081;
                7'd08: expected_coarse = 32'hFFFFCEBA;
                7'd09: expected_coarse = 32'hFFFFCF84;
                7'd10: expected_coarse = 32'hFFFFD257;
                7'd11: expected_coarse = 32'hFFFFD1B5;
                7'd12: expected_coarse = 32'hFFFFD44C;
                7'd13: expected_coarse = 32'hFFFFD0CD;
                7'd14: expected_coarse = 32'hFFFFD15A;
                7'd15: expected_coarse = 32'hFFFFCF07;
                7'd16: expected_coarse = 32'hFFFFCEEA;
                7'd17: expected_coarse = 32'hFFFFD188;
                7'd18: expected_coarse = 32'hFFFFD1D2;
                7'd19: expected_coarse = 32'hFFFFD225;
                7'd20: expected_coarse = 32'hFFFFD00E;
                7'd21: expected_coarse = 32'hFFFFCE71;
                7'd22: expected_coarse = 32'hFFFFCFD9;
                7'd23: expected_coarse = 32'hFFFFCFA1;
                7'd24: expected_coarse = 32'hFFFFD032;
                7'd25: expected_coarse = 32'hFFFFD2BF;
                7'd26: expected_coarse = 32'hFFFFCF66;
                7'd27: expected_coarse = 32'hFFFFD019;
                7'd28: expected_coarse = 32'hFFFFD3BA;
                7'd29: expected_coarse = 32'hFFFFCF15;
                7'd30: expected_coarse = 32'hFFFFD5C8;
                7'd31: expected_coarse = 32'hFFFFD172;
                7'd32: expected_coarse = 32'hFFFFD715;
                7'd33: expected_coarse = 32'hFFFFFA2E;
                7'd34: expected_coarse = 32'hFFFFCF0A;
                7'd35: expected_coarse = 32'hFFFFD20D;
                7'd36: expected_coarse = 32'hFFFFCF8C;
                7'd37: expected_coarse = 32'hFFFFCE73;
                7'd38: expected_coarse = 32'hFFFFD1E1;
                7'd39: expected_coarse = 32'hFFFFCFEF;
                7'd40: expected_coarse = 32'hFFFFD12D;
                7'd41: expected_coarse = 32'hFFFFD081;
                7'd42: expected_coarse = 32'hFFFFD0B6;
                7'd43: expected_coarse = 32'hFFFFD009;
                7'd44: expected_coarse = 32'hFFFFD1F2;
                7'd45: expected_coarse = 32'hFFFFD035;
                7'd46: expected_coarse = 32'hFFFFD059;
                7'd47: expected_coarse = 32'hFFFFD06B;
                7'd48: expected_coarse = 32'hFFFFF1C0;
                7'd49: expected_coarse = 32'hFFFFCFED;
                7'd50: expected_coarse = 32'hFFFFD17A;
                7'd51: expected_coarse = 32'hFFFFD600;
                7'd52: expected_coarse = 32'hFFFFCFEB;
                7'd53: expected_coarse = 32'hFFFFFD0E;
                7'd54: expected_coarse = 32'hFFFFD86E;
                7'd55: expected_coarse = 32'hFFFFD01A;
                7'd56: expected_coarse = 32'hFFFFD581;
                7'd57: expected_coarse = 32'hFFFFD044;
                7'd58: expected_coarse = 32'hFFFFD280;
                7'd59: expected_coarse = 32'hFFFFD078;
                7'd60: expected_coarse = 32'hFFFFD0DD;
                7'd61: expected_coarse = 32'hFFFFD010;
                7'd62: expected_coarse = 32'hFFFFD076;
                7'd63: expected_coarse = 32'hFFFFCEA2;
                7'd64: expected_coarse = 32'hFFFFD0D9;
                7'd65: expected_coarse = 32'hFFFFD19C;
                7'd66: expected_coarse = 32'hFFFFCF11;
                7'd67: expected_coarse = 32'hFFFFD145;
                7'd68: expected_coarse = 32'hFFFFD0E3;
                7'd69: expected_coarse = 32'hFFFFD0EA;
                7'd70: expected_coarse = 32'hFFFFCF9F;
                7'd71: expected_coarse = 32'hFFFFF830;
                7'd72: expected_coarse = 32'hFFFFF5D7;
                7'd73: expected_coarse = 32'hFFFFCFB8;
                7'd74: expected_coarse = 32'hFFFFD4AC;
                7'd75: expected_coarse = 32'hFFFFCFB6;
                7'd76: expected_coarse = 32'hFFFFD015;
                7'd77: expected_coarse = 32'hFFFFD0A8;
                7'd78: expected_coarse = 32'hFFFFCF3C;
                7'd79: expected_coarse = 32'hFFFFD255;
                7'd80: expected_coarse = 32'hFFFFD090;
                7'd81: expected_coarse = 32'hFFFFD1B7;
                7'd82: expected_coarse = 32'hFFFFD01E;
                7'd83: expected_coarse = 32'hFFFFCF57;
                7'd84: expected_coarse = 32'hFFFFCDF9;
                7'd85: expected_coarse = 32'hFFFFD20E;
                7'd86: expected_coarse = 32'hFFFFD14A;
                7'd87: expected_coarse = 32'hFFFFD1AD;
                7'd88: expected_coarse = 32'hFFFFCFD5;
                7'd89: expected_coarse = 32'hFFFFD115;
                7'd90: expected_coarse = 32'hFFFFCE7B;
                7'd91: expected_coarse = 32'hFFFFCFDB;
                7'd92: expected_coarse = 32'hFFFFD080;
                7'd93: expected_coarse = 32'hFFFFCFAA;
                7'd94: expected_coarse = 32'hFFFFCFDB;
                7'd95: expected_coarse = 32'hFFFFD3B1;
                default: expected_coarse = 32'd0;
            endcase
        end
    endfunction

    task check_identity_and_summary;
        begin
            axi_read(12'h400, read_value);
            check32("magic", read_value, 32'h46465431);
            axi_read(12'h404, read_value);
            check32("build id", read_value, 32'h46505331);
            axi_read(12'h408, read_value);
            check32("abi", read_value, 32'h00020000);
            axi_read(12'h40c, read_value);
            check32("capability", read_value, 32'h00000fff);
            axi_read(12'h410, read_value);
            check32("sequence", read_value, 32'd1);
            axi_read(12'h414, read_value);
            check32("status valid only", read_value, 32'h00000001);
            axi_read(12'h418, read_value);
            check32("sample count", read_value, 32'd4096);
            axi_read(12'h41c, read_value);
            check32("nfft", read_value, 32'd2048);
            axi_read(12'h420, read_value);
            check32("sample rate", read_value, 32'd2000000);
            axi_read(12'h424, read_value);
            check32("window id", read_value, 32'd1);
            axi_read(12'h428, read_value);
            check32("scale exp", read_value, 32'd0);
            axi_read(12'h42c, read_value);
            check32("coarse count", read_value, 32'd96);
            axi_read(12'h430, read_value);
            check32("coarse step", read_value, 32'd1398101);
            axi_read(12'h434, read_value);
            check32("rx mask", read_value, 32'd1);
            axi_read(12'h438, read_value);
            check32("source frame", read_value, 32'd1);
            axi_read(12'h43c, read_value);
            check32("reserved 43c", read_value, 32'd0);
            axi_read(12'h440, read_value);
            check32("rssi", read_value, 32'hFFFFFD6C);
            axi_read(12'h444, read_value);
            check32("peak bin", read_value, 32'd1147);
            axi_read(12'h448, read_value);
            check32("peak offset", read_value, 32'h0001D535);
            axi_read(12'h44c, read_value);
            check32("peak power", read_value, 32'hFFFFFD0E);
            axi_read(12'h450, read_value);
            check32("noise floor", read_value, 32'hFFFFCD2B);
            axi_read(12'h454, read_value);
            check32("prominence", read_value, 32'h00002FE3);
            axi_read(12'h458, read_value);
            check32("band power", read_value, 32'hFFFFF12D);
            axi_read(12'h45c, read_value);
            check32("summary flags", read_value, 32'd0);
        end
    endtask

    task check_top_peaks;
        begin
            axi_read(12'h460, read_value);
            check32("top peak count", read_value, 32'd4);
            axi_read(12'h464, read_value);
            check32("top peak valid mask", read_value, 32'h0000000f);
            axi_read(12'h468, read_value);
            check32("top0 bin", read_value, 32'd1147);
            axi_read(12'h46c, read_value);
            check32("top0 power", read_value, 32'hFFFFFD0E);
            axi_read(12'h470, read_value);
            check32("top1 bin", read_value, 32'd707);
            axi_read(12'h474, read_value);
            check32("top1 power", read_value, 32'hFFFFFA2E);
            axi_read(12'h478, read_value);
            check32("top2 bin", read_value, 32'd1535);
            axi_read(12'h47c, read_value);
            check32("top2 power", read_value, 32'hFFFFF830);
            axi_read(12'h480, read_value);
            check32("top3 bin", read_value, 32'd1041);
            axi_read(12'h484, read_value);
            check32("top3 power", read_value, 32'hFFFFF1C0);
        end
    endtask

    task check_coarse_psd;
        begin
            for (index = 0; index < 128; index = index + 1) begin
                coarse_addr = 12'h500 + (index[11:0] << 2);
                axi_read(coarse_addr, read_value);
                check32("coarse psd", read_value, expected_coarse(index[6:0]));
            end
        end
    endtask

    initial begin
        errors = 0;
        index = 0;
        rst_n = 1'b0;
        awaddr = 12'd0;
        awvalid = 1'b0;
        wdata = 32'd0;
        wstrb = 4'hf;
        wvalid = 1'b0;
        bready = 1'b1;
        araddr = 12'd0;
        arvalid = 1'b0;
        rready = 1'b1;

        repeat (8) @(posedge clk);
        rst_n <= 1'b1;
        repeat (4) @(posedge clk);

        check_identity_and_summary();
        check_top_peaks();
        check_coarse_psd();

        axi_read(12'h488, read_value);
        check32("reserved after top peaks", read_value, 32'd0);
        axi_read(12'h4fc, read_value);
        check32("reserved before coarse", read_value, 32'd0);
        axi_read(12'h700, read_value);
        check32("reserved after coarse", read_value, 32'd0);

        axi_write(12'h414, 32'hFFFFFFFF);
        axi_read(12'h414, read_value);
        check32("status write ignored", read_value, 32'h00000001);

        if (irq !== 1'b0) begin
            $display("CHECK FAIL irq asserted unexpectedly");
            errors = errors + 1;
        end

        if (errors == 0) begin
            $display("TB_PASS p201_fft_shadow_selftest_axi_regs");
        end else begin
            $display("TB_FAIL p201_fft_shadow_selftest_axi_regs errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
