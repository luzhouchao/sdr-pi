`timescale 1ns/1ps
`default_nettype none

module tb_p201_v10s5_nonfft_selftest_core;

    localparam [31:0] EXPECT_DONE   = 32'h00000007;
    localparam [31:0] EXPECT_ERROR  = 32'h00000000;
    localparam [31:0] EXPECT_RESULT = 32'h400f75cf;

    reg         clk;
    reg         rst_n;
    reg         start;
    wire        busy;
    wire [31:0] done;
    wire [31:0] error;
    wire [31:0] result;

    integer     errors;
    integer     timeout;

    p201_v10s5_nonfft_selftest_core dut (
        .clk    (clk),
        .rst_n  (rst_n),
        .start  (start),
        .busy   (busy),
        .done   (done),
        .error  (error),
        .result (result)
    );

    initial begin
        clk = 1'b0;
        forever begin
            #5 clk = ~clk;
        end
    end

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
        begin
            @(posedge clk);
            start <= 1'b1;
            @(posedge clk);
            start <= 1'b0;

            timeout = 0;
            while (!busy && (timeout < 20)) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (timeout >= 20) begin
                $display("CHECK FAIL busy did not assert");
                errors = errors + 1;
            end

            timeout = 0;
            while (busy && (timeout < 200)) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (timeout >= 200) begin
                $display("CHECK FAIL self-test timeout");
                errors = errors + 1;
            end

            check32("done mask", done, EXPECT_DONE);
            check32("error mask", error, EXPECT_ERROR);
            check32("result", result, EXPECT_RESULT);
        end
    endtask

    initial begin
        errors = 0;
        rst_n = 1'b0;
        start = 1'b0;

        repeat (5) begin
            @(posedge clk);
        end
        rst_n = 1'b1;
        repeat (3) begin
            @(posedge clk);
        end

        check32("reset done", done, 32'd0);
        check32("reset error", error, 32'd0);
        check32("reset result", result, 32'd0);

        run_selftest();
        run_selftest();

        if (errors == 0) begin
            $display("TB_PASS p201_v10s5_nonfft_selftest_core");
        end else begin
            $display("TB_FAIL p201_v10s5_nonfft_selftest_core errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
