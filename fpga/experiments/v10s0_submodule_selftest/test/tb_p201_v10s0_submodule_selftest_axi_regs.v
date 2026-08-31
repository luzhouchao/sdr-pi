`timescale 1ns/1ps
`default_nettype none

module tb_p201_v10s0_submodule_selftest_axi_regs;

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

    p201_v10s0_submodule_selftest_axi_regs dut (
        .s_axi_aclk(clk),
        .s_axi_aresetn(rst_n),
        .s_axi_awaddr(awaddr),
        .s_axi_awvalid(awvalid),
        .s_axi_awready(awready),
        .s_axi_wdata(wdata),
        .s_axi_wstrb(wstrb),
        .s_axi_wvalid(wvalid),
        .s_axi_wready(wready),
        .s_axi_bresp(bresp),
        .s_axi_bvalid(bvalid),
        .s_axi_bready(bready),
        .s_axi_araddr(araddr),
        .s_axi_arvalid(arvalid),
        .s_axi_arready(arready),
        .s_axi_rdata(rdata),
        .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid),
        .s_axi_rready(rready),
        .irq(irq)
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

    task run_self_test_once;
        input [31:0] expected_run_id;
        begin
            axi_write(8'h04, 32'h00000004);
            axi_read(8'h08, read_value);
            check32("status after clear", read_value & 32'h0000000e,
                    32'h00000000);

            axi_write(8'h04, 32'h00000003);

            poll_count = 0;
            read_value = 32'd0;
            while (((read_value & 32'h00000004) == 32'd0) &&
                   poll_count < 2000) begin
                axi_read(8'h08, read_value);
                poll_count = poll_count + 1;
            end

            if (poll_count >= 2000) begin
                $display("CHECK FAIL done poll timeout status=0x%08x",
                         read_value);
                errors = errors + 1;
            end

            check32("status_done_fail_bits", read_value & 32'h0000000c,
                    32'h00000004);

            axi_read(8'h0c, read_value);
            check32("done_mask", read_value, 32'h0000000f);
            axi_read(8'h10, read_value);
            check32("error_mask", read_value, 32'h00000000);
            axi_read(8'h14, read_value);
            check32("run_id", read_value, expected_run_id);
        end
    endtask

    task check_result_page;
        begin
            axi_read(8'h34, read_value);
            check32("packer accepted", read_value, 32'd256);
            axi_read(8'h38, read_value);
            check32("packer dropped", read_value, 32'd0);
            axi_read(8'h40, read_value);
            check32("packer observed", read_value, 32'd256);

            axi_read(8'h54, read_value);
            check32("fft nfft", read_value, 32'd256);
            axi_read(8'h58, read_value);
            check32("fft peak bin", read_value, 32'd5);
            axi_read(8'h5c, read_value);
            check32("fft peak power", read_value, 32'd4096);
            axi_read(8'h60, read_value);
            check32("fft total", read_value, 32'd6385);
            axi_read(8'h64, read_value);
            check32("fft top bins", read_value, 32'h00211105);

            axi_read(8'h74, read_value);
            check32("band nfft", read_value, 32'd256);
            axi_read(8'h78, read_value);
            check32("band peak/top bins", read_value, 32'h002ac864);
            axi_read(8'h7c, read_value);
            check32("band total", read_value, 32'd56622);
            axi_read(8'h80, read_value);
            check32("band0", read_value, 32'd12062);
            axi_read(8'h84, read_value);
            check32("band1", read_value, 32'd12126);
            axi_read(8'h88, read_value);
            check32("band2", read_value, 32'd13186);
            axi_read(8'h8c, read_value);
            check32("band3", read_value, 32'd19248);

            axi_read(8'ha4, read_value);
            check32("corr samples", read_value, 32'h003d0040);
            axi_read(8'ha8, read_value);
            check32("corr lag0 re", read_value, 32'd155328);
            axi_read(8'hac, read_value);
            check32("corr lag0 im", read_value, 32'd552128);
            axi_read(8'hc4, read_value);
            check32("corr lag3 im", read_value, 32'd513681);
        end
    endtask

    task check_cleared_result_page;
        begin
            axi_read(8'h34, read_value);
            check32("clear packer accepted", read_value, 32'd0);
            axi_read(8'h40, read_value);
            check32("clear packer observed", read_value, 32'd0);
            axi_read(8'h54, read_value);
            check32("clear fft nfft", read_value, 32'd0);
            axi_read(8'h5c, read_value);
            check32("clear fft peak power", read_value, 32'd0);
            axi_read(8'h7c, read_value);
            check32("clear band total", read_value, 32'd0);
            axi_read(8'h80, read_value);
            check32("clear band0", read_value, 32'd0);
            axi_read(8'ha4, read_value);
            check32("clear corr samples", read_value, 32'd0);
            axi_read(8'ha8, read_value);
            check32("clear corr lag0 re", read_value, 32'd0);
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
        check32("version", read_value, 32'h53305430);
        axi_read(8'h18, read_value);
        check32("capability", read_value, 32'h0000000f);
        axi_read(8'h1c, read_value);
        check32("build", read_value, 32'h56313053);
        axi_read(8'h20, read_value);
        check32("abi", read_value, 32'h000a2000);
        axi_read(8'he0, read_value);
        check32("expect done mask", read_value, 32'h0000000f);
        axi_read(8'he4, read_value);
        check32("expect error", read_value, 32'h00000000);
        axi_read(8'hf4, read_value);
        check32("test capability", read_value, 32'h0000000f);
        axi_read(8'hf8, read_value);
        check32("test build", read_value, 32'h56313053);
        axi_read(8'hfc, read_value);
        check32("test abi", read_value, 32'h000a2000);
        axi_read(8'h24, read_value);
        check32("reserved read zero", read_value, 32'h00000000);

        axi_write_strb(8'h04, 32'h00000003, 4'h1);
        repeat (8) @(posedge clk);
        axi_read(8'h08, read_value);
        check32("partial control write ignored", read_value & 32'h00000002,
                32'h00000000);

        run_self_test_once(32'h00000001);
        check_result_page();

        if (irq !== 1'b1) begin
            $display("CHECK FAIL irq not asserted");
            errors = errors + 1;
        end

        run_self_test_once(32'h00000002);
        check_result_page();

        axi_write(8'h04, 32'h00000004);
        axi_read(8'h0c, read_value);
        check32("done mask after clear", read_value, 32'h00000000);
        axi_read(8'h10, read_value);
        check32("error mask after clear", read_value, 32'h00000000);
        axi_read(8'h14, read_value);
        check32("run_id persists after clear", read_value, 32'h00000002);
        check_cleared_result_page();

        axi_write(8'h04, 32'h00000003);
        repeat (20) @(posedge clk);
        axi_write(8'h04, 32'h00000000);
        repeat (8) @(posedge clk);
        axi_read(8'h08, read_value);
        check32("abort busy cleared", read_value & 32'h00000002,
                32'h00000000);
        check32("abort done cleared", read_value & 32'h00000004,
                32'h00000000);

        if (errors == 0) begin
            $display("TB_PASS p201_v10s0_submodule_selftest_axi_regs");
        end else begin
            $display("TB_FAIL p201_v10s0_submodule_selftest_axi_regs errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
