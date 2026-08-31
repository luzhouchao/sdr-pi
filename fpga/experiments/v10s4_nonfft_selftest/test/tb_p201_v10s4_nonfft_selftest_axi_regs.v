`timescale 1ns/1ps
`default_nettype none

module tb_p201_v10s4_nonfft_selftest_axi_regs;

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

    p201_v10s4_nonfft_selftest_axi_regs dut (
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
            @(posedge clk);
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
            axi_write(8'h04, 32'h00000003);
            read_value = 32'd0;
            poll_count = 0;
            while (((read_value & 32'h00000004) == 32'd0) &&
                   poll_count < 200) begin
                axi_read(8'h08, read_value);
                poll_count = poll_count + 1;
            end
            if (poll_count >= 200) begin
                $display("CHECK FAIL done timeout status=0x%08x", read_value);
                errors = errors + 1;
            end
            check32("status done/fail", read_value & 32'h0000000c,
                    32'h00000004);
            axi_read(8'h0c, read_value);
            check32("done mask", read_value, 32'h00000007);
            axi_read(8'h10, read_value);
            check32("error mask", read_value, 32'h00000000);
            axi_read(8'h14, read_value);
            check32("run id", read_value, expected_run_id);
        end
    endtask

    task check_results;
        begin
            axi_read(8'h34, read_value);
            check32("quality count", read_value, 32'd8);
            axi_read(8'h38, read_value);
            check32("quality sum i", read_value, 32'h00008374);
            axi_read(8'h3c, read_value);
            check32("quality sum q", read_value, 32'hffff7b9c);
            axi_read(8'h40, read_value);
            check32("quality sum i2", read_value, 32'h400e6d8c);
            axi_read(8'h44, read_value);
            check32("quality sum q2", read_value, 32'h400fe730);
            axi_read(8'h48, read_value);
            check32("quality sum iq", read_value, 32'hbff187e8);
            axi_read(8'h4c, read_value);
            check32("quality peak", read_value, 32'd32768);
            axi_read(8'h50, read_value);
            check32("quality clip", read_value, 32'h00010001);
            axi_read(8'h54, read_value);
            check32("quality sat", read_value, 32'h00010001);
            axi_read(8'h58, read_value);
            check32("quality valid", read_value, 32'd8);
            axi_read(8'h5c, read_value);
            check32("quality drop", read_value, 32'd0);

            axi_read(8'h74, read_value);
            check32("window raw", read_value, 32'd8);
            axi_read(8'h78, read_value);
            check32("window accepted", read_value, 32'd8);
            axi_read(8'h7c, read_value);
            check32("window dropped", read_value, 32'd0);
            axi_read(8'h80, read_value);
            check32("window overflow", read_value, 32'd0);
            axi_read(8'h84, read_value);
            check32("window frame id", read_value, 32'd1);

            axi_read(8'ha0, read_value);
            check32("energy flags", read_value & 32'h00000117,
                    32'h00000111);
            axi_read(8'ha4, read_value);
            check32("energy frame id", read_value, 32'd1);
            axi_read(8'ha8, read_value);
            check32("energy count", read_value, 32'd8);
            axi_read(8'hac, read_value);
            check32("energy total", read_value, 32'd309);
            axi_read(8'hb0, read_value);
            check32("energy noise", read_value, 32'd2);
            axi_read(8'hb4, read_value);
            check32("energy peak", read_value, 32'd100);
            axi_read(8'hb8, read_value);
            check32("energy peak index", read_value, 32'd4);
            axi_read(8'hbc, read_value);
            check32("energy second", read_value, 32'd90);
            axi_read(8'hc0, read_value);
            check32("energy second index", read_value, 32'd6);
            axi_read(8'hc4, read_value);
            check32("energy prominence", read_value, 32'd98);
            axi_read(8'hc8, read_value);
            check32("energy threshold count", read_value, 32'd3);
        end
    endtask

    initial begin
        errors = 0;
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

        repeat (5) begin
            @(posedge clk);
        end
        rst_n = 1'b1;
        repeat (4) begin
            @(posedge clk);
        end

        axi_read(8'h00, read_value);
        check32("version", read_value, 32'h53345430);
        axi_read(8'h18, read_value);
        check32("capability", read_value, 32'h00000007);
        axi_read(8'h1c, read_value);
        check32("build", read_value, 32'h56313034);
        axi_read(8'h20, read_value);
        check32("abi", read_value, 32'h000a4000);

        run_selftest(32'd1);
        check_results();
        run_selftest(32'd2);
        check_results();

        if (errors == 0) begin
            $display("TB_PASS p201_v10s4_nonfft_selftest_axi_regs");
        end else begin
            $display("TB_FAIL p201_v10s4_nonfft_selftest_axi_regs errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
