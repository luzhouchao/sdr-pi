`timescale 1ns/1ps
`default_nettype none

module tb_p201_fft_shadow_coarse96_reducer;

    reg                 clk;
    reg                 rst_n;
    reg                 enable;
    reg                 clear;
    reg                 bin_valid;
    wire                bin_ready;
    reg                 bin_last;
    reg  [11:0]         bin_index;
    reg  signed [31:0]  bin_power;
    reg                 coarse_read_strobe;
    reg  [6:0]          coarse_read_index;
    wire                coarse_read_valid;
    wire [6:0]          coarse_read_index_out;
    wire signed [31:0]  coarse_read_power;
    wire                summary_valid;
    wire [31:0]         summary_bin_count;
    wire [7:0]          coarse_bin_count;
    wire [31:0]         coarse_bin_step_q16;
    wire [31:0]         status_flags;

    integer             errors;
    integer             index;
    integer             coarse;
    integer             wait_cycles;

    p201_fft_shadow_coarse96_reducer dut (
        .clk                  (clk),
        .rst_n                (rst_n),
        .enable               (enable),
        .clear                (clear),
        .bin_valid            (bin_valid),
        .bin_ready            (bin_ready),
        .bin_last             (bin_last),
        .bin_index            (bin_index),
        .bin_power            (bin_power),
        .coarse_read_strobe   (coarse_read_strobe),
        .coarse_read_index    (coarse_read_index),
        .coarse_read_valid    (coarse_read_valid),
        .coarse_read_index_out(coarse_read_index_out),
        .coarse_read_power    (coarse_read_power),
        .summary_valid        (summary_valid),
        .summary_bin_count    (summary_bin_count),
        .coarse_bin_count     (coarse_bin_count),
        .coarse_bin_step_q16  (coarse_bin_step_q16),
        .status_flags         (status_flags)
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
            fixture_power = -32'sd20000 - (idx % 29);
            if (idx == 0) begin
                fixture_power = -32'sd6000;
            end
            if (idx == 21) begin
                fixture_power = -32'sd5000;
            end
            if (idx == 22) begin
                fixture_power = -32'sd4900;
            end
            if (idx == 63) begin
                fixture_power = -32'sd4700;
            end
            if (idx == 64) begin
                fixture_power = -32'sd4600;
            end
            if (idx == 707) begin
                fixture_power = -32'sd1490;
            end
            if (idx == 1041) begin
                fixture_power = -32'sd3648;
            end
            if (idx == 1147) begin
                fixture_power = -32'sd754;
            end
            if (idx == 1535) begin
                fixture_power = -32'sd2000;
            end
            if (idx == 2047) begin
                fixture_power = -32'sd3300;
            end
        end
    endfunction

    function integer coarse_start;
        input integer coarse_idx;
        begin
            coarse_start = (coarse_idx * 2048) / 96;
        end
    endfunction

    function integer coarse_stop;
        input integer coarse_idx;
        begin
            coarse_stop = ((coarse_idx + 1) * 2048) / 96;
        end
    endfunction

    function signed [31:0] expected_coarse_power;
        input integer coarse_idx;
        integer start_idx;
        integer stop_idx;
        integer scan_idx;
        reg signed [31:0] best_power;
        begin
            start_idx = coarse_start(coarse_idx);
            stop_idx = coarse_stop(coarse_idx);
            best_power = fixture_power(start_idx);
            for (scan_idx = start_idx + 1; scan_idx < stop_idx; scan_idx = scan_idx + 1) begin
                if (fixture_power(scan_idx) > best_power) begin
                    best_power = fixture_power(scan_idx);
                end
            end
            expected_coarse_power = best_power;
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
            while (!summary_valid && wait_cycles < 16) begin
                @(posedge clk);
                wait_cycles = wait_cycles + 1;
            end
        end
    endtask

    task read_and_check_coarse;
        input integer coarse_idx;
        reg signed [31:0] expected;
        begin
            expected = expected_coarse_power(coarse_idx);
            @(posedge clk);
            coarse_read_index <= coarse_idx[6:0];
            coarse_read_strobe <= 1'b1;
            @(posedge clk);
            coarse_read_strobe <= 1'b0;
            @(posedge clk);
            if (!coarse_read_valid) begin
                $display("CHECK FAIL coarse%0d read_valid not asserted", coarse_idx);
                errors = errors + 1;
            end
            check32("coarse index", {25'd0, coarse_read_index_out}, coarse_idx[31:0]);
            check32("coarse power", coarse_read_power, expected);
        end
    endtask

    initial begin
        errors = 0;
        index = 0;
        coarse = 0;
        wait_cycles = 0;
        rst_n = 1'b0;
        enable = 1'b0;
        clear = 1'b0;
        bin_valid = 1'b0;
        bin_last = 1'b0;
        bin_index = 12'd0;
        bin_power = 32'sd0;
        coarse_read_strobe = 1'b0;
        coarse_read_index = 7'd0;

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
        check32("coarse_bin_count", {24'd0, coarse_bin_count}, 32'd96);
        check32("coarse_bin_step_q16", coarse_bin_step_q16, 32'd1398101);

        for (coarse = 0; coarse < 96; coarse = coarse + 1) begin
            read_and_check_coarse(coarse);
        end

        clear <= 1'b1;
        repeat (2) @(posedge clk);
        clear <= 1'b0;
        repeat (2) @(posedge clk);
        if (summary_valid) begin
            $display("CHECK FAIL clear did not drop summary_valid");
            errors = errors + 1;
        end

        if (errors == 0) begin
            $display("TB_PASS p201_fft_shadow_coarse96_reducer");
        end else begin
            $display("TB_FAIL p201_fft_shadow_coarse96_reducer errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
