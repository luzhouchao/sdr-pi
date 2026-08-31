`timescale 1ns/1ps
`default_nettype none

module tb_p201_fft_shadow_top4_reducer;

    reg                 clk;
    reg                 rst_n;
    reg                 enable;
    reg                 clear;
    reg                 bin_valid;
    wire                bin_ready;
    reg                 bin_last;
    reg  [11:0]         bin_index;
    reg  signed [31:0]  bin_power;
    wire                summary_valid;
    wire [31:0]         summary_bin_count;
    wire [2:0]          top_count;
    wire [11:0]         top0_bin;
    wire signed [31:0]  top0_power;
    wire [11:0]         top1_bin;
    wire signed [31:0]  top1_power;
    wire [11:0]         top2_bin;
    wire signed [31:0]  top2_power;
    wire [11:0]         top3_bin;
    wire signed [31:0]  top3_power;
    wire [31:0]         status_flags;

    integer             errors;
    integer             index;
    integer             wait_cycles;

    p201_fft_shadow_top4_reducer #(
        .BIN_INDEX_WIDTH (12),
        .POWER_WIDTH     (32),
        .GUARD_BINS      (3)
    ) dut (
        .clk               (clk),
        .rst_n             (rst_n),
        .enable            (enable),
        .clear             (clear),
        .bin_valid         (bin_valid),
        .bin_ready         (bin_ready),
        .bin_last          (bin_last),
        .bin_index         (bin_index),
        .bin_power         (bin_power),
        .summary_valid     (summary_valid),
        .summary_bin_count (summary_bin_count),
        .top_count         (top_count),
        .top0_bin          (top0_bin),
        .top0_power        (top0_power),
        .top1_bin          (top1_bin),
        .top1_power        (top1_power),
        .top2_bin          (top2_bin),
        .top2_power        (top2_power),
        .top3_bin          (top3_bin),
        .top3_power        (top3_power),
        .status_flags      (status_flags)
    );

    initial begin
        clk = 1'b0;
        forever begin
            #4 clk = ~clk;
        end
    end

    function signed [31:0] fixture_power;
        input integer idx;
        begin
            fixture_power = -32'sd12000 - (idx % 17);
            if (idx == 706) begin
                fixture_power = -32'sd1600;
            end
            if (idx == 707) begin
                fixture_power = -32'sd1490;
            end
            if (idx == 708) begin
                fixture_power = -32'sd1900;
            end
            if (idx == 1041) begin
                fixture_power = -32'sd3648;
            end
            if (idx == 1146) begin
                fixture_power = -32'sd1000;
            end
            if (idx == 1147) begin
                fixture_power = -32'sd754;
            end
            if (idx == 1148) begin
                fixture_power = -32'sd900;
            end
            if (idx == 1534) begin
                fixture_power = -32'sd2100;
            end
            if (idx == 1535) begin
                fixture_power = -32'sd2000;
            end
        end
    endfunction

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

    task send_bin;
        input integer idx;
        begin
            @(posedge clk);
            bin_index <= idx[11:0];
            bin_power <= fixture_power(idx);
            bin_last <= (idx == 2047);
            bin_valid <= 1'b1;
            while (!bin_ready) begin
                @(posedge clk);
            end
            @(posedge clk);
            bin_valid <= 1'b0;
            bin_last <= 1'b0;
        end
    endtask

    task run_frame;
        begin
            for (index = 0; index < 2048; index = index + 1) begin
                send_bin(index);
            end
            wait_cycles = 0;
            while (!summary_valid && wait_cycles < 64) begin
                @(posedge clk);
                wait_cycles = wait_cycles + 1;
            end
        end
    endtask

    initial begin
        errors = 0;
        index = 0;
        wait_cycles = 0;
        rst_n = 1'b0;
        enable = 1'b0;
        clear = 1'b0;
        bin_valid = 1'b0;
        bin_last = 1'b0;
        bin_index = 12'd0;
        bin_power = 32'sd0;

        repeat (8) @(posedge clk);
        rst_n <= 1'b1;
        enable <= 1'b1;
        repeat (4) @(posedge clk);

        run_frame();

        if (!summary_valid) begin
            $display("CHECK FAIL summary_valid not asserted");
            errors = errors + 1;
        end
        check32("summary_bin_count", summary_bin_count, 32'd2048);
        check32("top_count", {29'd0, top_count}, 32'd4);
        check32("top0 bin", {20'd0, top0_bin}, 32'd1147);
        check32("top0 power", top0_power, -32'sd754);
        check32("top1 bin", {20'd0, top1_bin}, 32'd707);
        check32("top1 power", top1_power, -32'sd1490);
        check32("top2 bin", {20'd0, top2_bin}, 32'd1535);
        check32("top2 power", top2_power, -32'sd2000);
        check32("top3 bin", {20'd0, top3_bin}, 32'd1041);
        check32("top3 power", top3_power, -32'sd3648);

        clear <= 1'b1;
        repeat (2) @(posedge clk);
        clear <= 1'b0;
        repeat (2) @(posedge clk);
        if (summary_valid) begin
            $display("CHECK FAIL clear did not drop summary_valid");
            errors = errors + 1;
        end

        if (errors == 0) begin
            $display("TB_PASS p201_fft_shadow_top4_reducer");
        end else begin
            $display("TB_FAIL p201_fft_shadow_top4_reducer errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
