`timescale 1ns/1ps
`default_nettype none

module tb_p201_fft_shadow_fft4_smoke_core;

    reg                  clk;
    reg                  rst_n;
    reg                  enable;
    reg                  clear;
    reg                  sample_valid;
    wire                 sample_ready;
    reg                  sample_last;
    reg signed [15:0]    sample_i;
    reg signed [15:0]    sample_q;
    wire                 summary_valid;
    wire [31:0]          sample_count;
    wire [31:0]          nfft;
    wire [31:0]          peak_bin;
    wire [47:0]          peak_power;
    wire [47:0]          total_power;
    wire [47:0]          bin0_power;
    wire [47:0]          bin1_power;
    wire [47:0]          bin2_power;
    wire [47:0]          bin3_power;
    wire [31:0]          status_flags;

    integer              errors;
    integer              wait_cycles;

    p201_fft_shadow_fft4_smoke_core dut (
        .clk           (clk),
        .rst_n         (rst_n),
        .enable        (enable),
        .clear         (clear),
        .sample_valid  (sample_valid),
        .sample_ready  (sample_ready),
        .sample_last   (sample_last),
        .sample_i      (sample_i),
        .sample_q      (sample_q),
        .summary_valid (summary_valid),
        .sample_count  (sample_count),
        .nfft          (nfft),
        .peak_bin      (peak_bin),
        .peak_power    (peak_power),
        .total_power   (total_power),
        .bin0_power    (bin0_power),
        .bin1_power    (bin1_power),
        .bin2_power    (bin2_power),
        .bin3_power    (bin3_power),
        .status_flags  (status_flags)
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

    task check48;
        input [255:0] name;
        input [47:0] got;
        input [47:0] exp;
        begin
            if (got !== exp) begin
                $display("CHECK FAIL %0s got=0x%012x exp=0x%012x",
                         name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task send_sample;
        input signed [15:0] in_i;
        input signed [15:0] in_q;
        input               in_last;
        begin
            @(posedge clk);
            sample_i <= in_i;
            sample_q <= in_q;
            sample_last <= in_last;
            sample_valid <= 1'b1;
            while (!sample_ready) begin
                @(posedge clk);
            end
            @(posedge clk);
            sample_valid <= 1'b0;
            sample_last <= 1'b0;
        end
    endtask

    task run_bin1_tone_frame;
        begin
            send_sample(16'sd1000,  16'sd0,    1'b0);
            send_sample(16'sd0,     16'sd1000, 1'b0);
            send_sample(-16'sd1000, 16'sd0,    1'b0);
            send_sample(16'sd0,    -16'sd1000, 1'b1);
            wait_cycles = 0;
            while (!summary_valid && wait_cycles < 32) begin
                @(posedge clk);
                wait_cycles = wait_cycles + 1;
            end
        end
    endtask

    initial begin
        errors = 0;
        wait_cycles = 0;
        rst_n = 1'b0;
        enable = 1'b0;
        clear = 1'b0;
        sample_valid = 1'b0;
        sample_last = 1'b0;
        sample_i = 16'sd0;
        sample_q = 16'sd0;

        repeat (8) @(posedge clk);
        rst_n <= 1'b1;
        enable <= 1'b1;
        repeat (4) @(posedge clk);

        run_bin1_tone_frame();

        if (!summary_valid) begin
            $display("CHECK FAIL summary_valid not asserted");
            errors = errors + 1;
        end

        check32("sample_count", sample_count, 32'd4);
        check32("nfft", nfft, 32'd4);
        check32("peak_bin", peak_bin, 32'd1);
        check48("peak_power", peak_power, 48'd16000000);
        check48("total_power", total_power, 48'd16000000);
        check48("bin0_power", bin0_power, 48'd0);
        check48("bin1_power", bin1_power, 48'd16000000);
        check48("bin2_power", bin2_power, 48'd0);
        check48("bin3_power", bin3_power, 48'd0);
        check32("status_flags", status_flags, 32'h00000031);

        clear <= 1'b1;
        repeat (2) @(posedge clk);
        clear <= 1'b0;
        repeat (2) @(posedge clk);
        if (summary_valid) begin
            $display("CHECK FAIL clear did not drop summary_valid");
            errors = errors + 1;
        end

        if (errors == 0) begin
            $display("TB_PASS p201_fft_shadow_fft4_smoke_core");
        end else begin
            $display("TB_FAIL p201_fft_shadow_fft4_smoke_core errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
