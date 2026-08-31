`timescale 1ns/1ps
`default_nettype none

module tb_p201_v10s5_combined_selftest_axi_regs;

    reg         clk;
    reg         rst_n;
    reg  [7:0]  awaddr;
    reg         awvalid;
    wire        awready;
    reg  [31:0] wdata;
    reg  [3:0]  wstrb;
    reg         wvalid;
    wire        wready;
    wire [1:0]  bresp;
    wire        bvalid;
    reg         bready;
    reg  [7:0]  araddr;
    reg         arvalid;
    wire        arready;
    wire [31:0] rdata;
    wire [1:0]  rresp;
    wire        rvalid;
    reg         rready;
    wire        irq;

    integer     errors;
    integer     poll_count;
    reg [31:0]  read_value;

    p201_v10s5_combined_selftest_axi_regs dut (
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
        input [7:0] addr;
        input [31:0] data;
        begin
            axi_write_strb(addr, data, 4'hf);
        end
    endtask

    task axi_write_strb;
        input [7:0] addr;
        input [31:0] data;
        input [3:0] strb;
        begin
            @(posedge clk);
            awaddr <= addr;
            wdata <= data;
            wstrb <= strb;
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
            @(posedge clk);
            wstrb <= 4'hf;
        end
    endtask

    task axi_read;
        input [7:0] addr;
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

    task run_selftest;
        input [31:0] expected_run_id;
        begin
            axi_write(8'h04, 32'h00000004);
            axi_read(8'h08, read_value);
            check32("status after clear", read_value & 32'h0000000e,
                    32'h00000000);

            axi_write(8'h04, 32'h00000003);
            read_value = 32'd0;
            poll_count = 0;
            while (((read_value & 32'h00000004) == 32'd0) &&
                   (poll_count < 300)) begin
                axi_read(8'h08, read_value);
                poll_count = poll_count + 1;
            end

            if (poll_count >= 300) begin
                $display("CHECK FAIL done timeout status=0x%08x", read_value);
                errors = errors + 1;
            end

            check32("status done/fail", read_value & 32'h0000000c,
                    32'h00000004);
            axi_read(8'h0c, read_value);
            check32("done mask", read_value, 32'h0000003f);
            axi_read(8'h10, read_value);
            check32("error mask", read_value, 32'h00000000);
            axi_read(8'h14, read_value);
            check32("run id", read_value, expected_run_id);
            axi_read(8'h7c, read_value);
            check32("combined run id", read_value, expected_run_id);
        end
    endtask

    task check_results;
        begin
            axi_read(8'h30, read_value);
            check32("fft status done bit", read_value & 32'h00000008,
                    32'h00000008);
            axi_read(8'h34, read_value);
            check32("fft done", read_value, 32'h00000007);
            axi_read(8'h38, read_value);
            check32("fft error", read_value, 32'h00000000);
            axi_read(8'h3c, read_value);
            check32("fft result0", read_value, 32'h46355430);
            axi_read(8'h40, read_value);
            check32("fft result1", read_value, 32'd256);
            axi_read(8'h44, read_value);
            check32("fft result2", read_value, 32'd6385);
            axi_read(8'h48, read_value);
            check32("fft result3", read_value, 32'h00211105);

            axi_read(8'h50, read_value);
            check32("nonfft status done bit", read_value & 32'h00000008,
                    32'h00000008);
            axi_read(8'h54, read_value);
            check32("nonfft done", read_value, 32'h00000007);
            axi_read(8'h58, read_value);
            check32("nonfft error", read_value, 32'h00000000);
            axi_read(8'h5c, read_value);
            check32("nonfft result0", read_value, 32'h4e355430);
            axi_read(8'h60, read_value);
            check32("nonfft result1", read_value, 32'd8);
            axi_read(8'h64, read_value);
            check32("nonfft result2", read_value, 32'd309);
            axi_read(8'h68, read_value);
            check32("nonfft result3", read_value, 32'h00008374);

            axi_read(8'h70, read_value);
            check32("combined signature", read_value, 32'h050e343a);
            axi_read(8'h74, read_value);
            check32("combined xor", read_value, 32'h0800003f);
            axi_read(8'h78, read_value);
            check32("combined sum", read_value, 32'd6958);
        end
    endtask

    task check_cleared_results;
        begin
            axi_read(8'h0c, read_value);
            check32("clear done mask", read_value, 32'h00000000);
            axi_read(8'h10, read_value);
            check32("clear error mask", read_value, 32'h00000000);
            axi_read(8'h34, read_value);
            check32("clear fft done", read_value, 32'h00000000);
            axi_read(8'h3c, read_value);
            check32("clear fft result0", read_value, 32'h00000000);
            axi_read(8'h54, read_value);
            check32("clear nonfft done", read_value, 32'h00000000);
            axi_read(8'h5c, read_value);
            check32("clear nonfft result0", read_value, 32'h00000000);
            axi_read(8'h70, read_value);
            check32("clear combined signature", read_value, 32'h00000000);
        end
    endtask

    initial begin
        errors = 0;
        poll_count = 0;
        rst_n = 1'b0;
        awaddr = 8'd0;
        awvalid = 1'b0;
        wdata = 32'd0;
        wstrb = 4'hf;
        wvalid = 1'b0;
        bready = 1'b1;
        araddr = 8'd0;
        arvalid = 1'b0;
        rready = 1'b1;

        repeat (8) @(posedge clk);
        rst_n <= 1'b1;
        repeat (4) @(posedge clk);

        axi_read(8'h00, read_value);
        check32("version", read_value, 32'h53355430);
        axi_read(8'h18, read_value);
        check32("capability", read_value, 32'h0000003f);
        axi_read(8'h1c, read_value);
        check32("build", read_value, 32'h56313035);
        axi_read(8'h20, read_value);
        check32("abi", read_value, 32'h000a5000);
        axi_read(8'he0, read_value);
        check32("expect done", read_value, 32'h0000003f);
        axi_read(8'he4, read_value);
        check32("expect error", read_value, 32'h00000000);
        axi_read(8'he8, read_value);
        check32("expect fft done", read_value, 32'h00000007);
        axi_read(8'hec, read_value);
        check32("expect nonfft done", read_value, 32'h00000007);
        axi_read(8'hf4, read_value);
        check32("test cap", read_value, 32'h0000003f);
        axi_read(8'hf8, read_value);
        check32("test build", read_value, 32'h56313035);
        axi_read(8'hfc, read_value);
        check32("test abi", read_value, 32'h000a5000);
        axi_read(8'h24, read_value);
        check32("reserved read zero", read_value, 32'h00000000);

        axi_write_strb(8'h04, 32'h00000003, 4'h1);
        repeat (8) @(posedge clk);
        axi_read(8'h08, read_value);
        check32("partial control ignored busy", read_value & 32'h00000002,
                32'h00000000);

        run_selftest(32'd1);
        check_results();

        if (irq !== 1'b1) begin
            $display("CHECK FAIL irq not asserted");
            errors = errors + 1;
        end

        run_selftest(32'd2);
        check_results();

        axi_write(8'h04, 32'h00000004);
        check_cleared_results();
        axi_read(8'h14, read_value);
        check32("run id persists after clear", read_value, 32'd2);

        axi_write(8'h04, 32'h00000003);
        repeat (2) @(posedge clk);
        axi_write(8'h04, 32'h00000000);
        repeat (8) @(posedge clk);
        axi_read(8'h08, read_value);
        check32("abort busy cleared", read_value & 32'h00000002,
                32'h00000000);
        check32("abort done cleared", read_value & 32'h00000004,
                32'h00000000);

        if (errors == 0) begin
            $display("TB_PASS p201_v10s5_combined_selftest_axi_regs");
        end else begin
            $display("TB_FAIL p201_v10s5_combined_selftest_axi_regs errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
