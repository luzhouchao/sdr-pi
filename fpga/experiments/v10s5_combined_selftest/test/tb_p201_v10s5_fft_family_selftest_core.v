`timescale 1ns/1ps
`default_nettype none

module tb_p201_v10s5_fft_family_selftest_core;

    localparam [31:0] EXPECT_DONE_MASK = 32'h0000000f;
    localparam [31:0] EXPECT_ERROR     = 32'h00000000;
    localparam [31:0] EXPECT_RESULT0   = 32'h0000000f;
    localparam [31:0] EXPECT_RESULT1   = 32'h5608ccf1;
    localparam [31:0] EXPECT_RESULT2   = 32'h000a5000;
    localparam [31:0] EXPECT_RESULT3   = 32'h00000000;

    reg         clk;
    reg         rst_n;
    reg         start;
    wire        busy;
    wire        done;
    wire        error;
    wire [31:0] done_mask;
    wire [31:0] error_mask;
    wire [31:0] result0;
    wire [31:0] result1;
    wire [31:0] result2;
    wire [31:0] result3;

    integer errors;
    integer poll_count;

    p201_v10s5_fft_family_selftest_core dut (
        .clk        (clk),
        .rst_n      (rst_n),
        .start      (start),
        .busy       (busy),
        .done       (done),
        .error      (error),
        .done_mask  (done_mask),
        .error_mask (error_mask),
        .result0    (result0),
        .result1    (result1),
        .result2    (result2),
        .result3    (result3)
    );

    initial begin
        clk = 1'b0;
        forever begin
            #4 clk = ~clk;
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

    task run_selftest_once;
        begin
            @(posedge clk);
            start <= 1'b1;
            @(posedge clk);
            start <= 1'b0;

            poll_count = 0;
            while (!done && (poll_count < 2000)) begin
                @(posedge clk);
                poll_count = poll_count + 1;
            end

            if (poll_count >= 2000) begin
                $display("CHECK FAIL done timeout");
                errors = errors + 1;
            end

            if (busy !== 1'b0) begin
                $display("CHECK FAIL busy stuck high");
                errors = errors + 1;
            end

            if (error !== 1'b0) begin
                $display("CHECK FAIL error asserted error_mask=0x%08x",
                         error_mask);
                errors = errors + 1;
            end

            check32("done_mask", done_mask, EXPECT_DONE_MASK);
            check32("error_mask", error_mask, EXPECT_ERROR);
            check32("result0", result0, EXPECT_RESULT0);
            check32("result1", result1, EXPECT_RESULT1);
            check32("result2", result2, EXPECT_RESULT2);
            check32("result3", result3, EXPECT_RESULT3);
        end
    endtask

    initial begin
        errors = 0;
        poll_count = 0;
        rst_n = 1'b0;
        start = 1'b0;

        repeat (8) begin
            @(posedge clk);
        end
        rst_n <= 1'b1;
        repeat (4) begin
            @(posedge clk);
        end

        check32("reset done mask", done_mask, 32'h00000000);
        check32("reset error mask", error_mask, 32'h00000000);
        check32("reset result2", result2, EXPECT_RESULT2);

        run_selftest_once();

        repeat (8) begin
            @(posedge clk);
        end

        run_selftest_once();

        if (errors == 0) begin
            $display("TB_PASS p201_v10s5_fft_family_selftest_core");
        end else begin
            $display("TB_FAIL p201_v10s5_fft_family_selftest_core errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
