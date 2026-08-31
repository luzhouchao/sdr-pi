`timescale 1ns/1ps
`default_nettype none

module tb_p201_v10s3_energy_peak_reducer;

    reg          clk;
    reg          rst_n;
    reg          enable;
    reg          clear_summary;
    reg          sample_valid;
    wire         sample_ready;
    reg          sample_last;
    reg  [15:0]  sample_value;
    reg  [7:0]   sample_index;
    reg  [15:0]  threshold_value;
    wire [31:0]  summary_flags;
    wire [31:0]  summary_frame_id;
    wire [7:0]   summary_sample_count;
    wire [31:0]  summary_total_energy;
    wire [15:0]  summary_noise_floor;
    wire [15:0]  summary_peak_value;
    wire [7:0]   summary_peak_index;
    wire [15:0]  summary_second_peak_value;
    wire [7:0]   summary_second_peak_index;
    wire [15:0]  summary_prominence;
    wire [7:0]   summary_threshold_count;

    integer      errors;

    p201_v10s3_energy_peak_reducer #(
        .VALUE_WIDTH (16),
        .INDEX_WIDTH (8),
        .ACC_WIDTH   (32),
        .COUNT_WIDTH (8),
        .MAX_SAMPLES (8)
    ) dut (
        .clk                       (clk),
        .rst_n                     (rst_n),
        .enable                    (enable),
        .clear_summary             (clear_summary),
        .sample_valid              (sample_valid),
        .sample_ready              (sample_ready),
        .sample_last               (sample_last),
        .sample_value              (sample_value),
        .sample_index              (sample_index),
        .threshold_value           (threshold_value),
        .summary_flags             (summary_flags),
        .summary_frame_id          (summary_frame_id),
        .summary_sample_count      (summary_sample_count),
        .summary_total_energy      (summary_total_energy),
        .summary_noise_floor       (summary_noise_floor),
        .summary_peak_value        (summary_peak_value),
        .summary_peak_index        (summary_peak_index),
        .summary_second_peak_value (summary_second_peak_value),
        .summary_second_peak_index (summary_second_peak_index),
        .summary_prominence        (summary_prominence),
        .summary_threshold_count   (summary_threshold_count)
    );

    initial begin
        clk = 1'b0;
        forever begin
            #5 clk = ~clk;
        end
    end

    task send_sample;
        input [15:0] value;
        input [7:0] index;
        input last;
        begin
            @(posedge clk);
            sample_value <= value;
            sample_index <= index;
            sample_last <= last;
            sample_valid <= 1'b1;
            while (!sample_ready) begin
                @(posedge clk);
            end
            @(posedge clk);
            sample_valid <= 1'b0;
            sample_last <= 1'b0;
            sample_value <= 16'd0;
            sample_index <= 8'd0;
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

    task check16;
        input [255:0] name;
        input [15:0] got;
        input [15:0] exp;
        begin
            if (got !== exp) begin
                $display("CHECK FAIL %0s got=%0d exp=%0d",
                         name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task check8;
        input [255:0] name;
        input [7:0] got;
        input [7:0] exp;
        begin
            if (got !== exp) begin
                $display("CHECK FAIL %0s got=%0d exp=%0d",
                         name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task check_bin_window;
        begin
            check32("bin flags", summary_flags, 32'h00000111);
            check32("bin frame_id", summary_frame_id, 32'd1);
            check8("bin count", summary_sample_count, 8'd8);
            check32("bin total", summary_total_energy, 32'd309);
            check16("bin noise", summary_noise_floor, 16'd2);
            check16("bin peak value", summary_peak_value, 16'd100);
            check8("bin peak index", summary_peak_index, 8'd4);
            check16("bin second peak value", summary_second_peak_value, 16'd90);
            check8("bin second peak index", summary_second_peak_index, 8'd6);
            check16("bin prominence", summary_prominence, 16'd98);
            check8("bin threshold count", summary_threshold_count, 8'd3);
        end
    endtask

    task check_scalar_window;
        begin
            check32("scalar flags", summary_flags, 32'h00000111);
            check32("scalar frame_id", summary_frame_id, 32'd1);
            check8("scalar count", summary_sample_count, 8'd5);
            check32("scalar total", summary_total_energy, 32'd33);
            check16("scalar noise", summary_noise_floor, 16'd3);
            check16("scalar peak value", summary_peak_value, 16'd12);
            check8("scalar peak index", summary_peak_index, 8'd1);
            check16("scalar second peak value", summary_second_peak_value, 16'd9);
            check8("scalar second peak index", summary_second_peak_index, 8'd4);
            check16("scalar prominence", summary_prominence, 16'd9);
            check8("scalar threshold count", summary_threshold_count, 8'd2);
        end
    endtask

    initial begin
        errors = 0;
        rst_n = 1'b0;
        enable = 1'b0;
        clear_summary = 1'b0;
        sample_valid = 1'b0;
        sample_last = 1'b0;
        sample_value = 16'd0;
        sample_index = 8'd0;
        threshold_value = 16'd50;

        repeat (5) begin
            @(posedge clk);
        end
        rst_n = 1'b1;
        enable = 1'b1;

        send_sample(16'd5, 8'd0, 1'b0);
        send_sample(16'd7, 8'd1, 1'b0);
        send_sample(16'd50, 8'd2, 1'b0);
        send_sample(16'd2, 8'd3, 1'b0);
        send_sample(16'd100, 8'd4, 1'b0);
        send_sample(16'd25, 8'd5, 1'b0);
        send_sample(16'd90, 8'd6, 1'b0);
        send_sample(16'd30, 8'd7, 1'b1);
        @(posedge clk);
        check_bin_window();

        clear_summary = 1'b1;
        @(posedge clk);
        clear_summary = 1'b0;
        @(posedge clk);
        check32("clear flags", summary_flags, 32'd0);
        check32("clear total", summary_total_energy, 32'd0);

        threshold_value = 16'd9;
        send_sample(16'd4, 8'd0, 1'b0);
        send_sample(16'd12, 8'd1, 1'b0);
        send_sample(16'd3, 8'd2, 1'b0);
        send_sample(16'd5, 8'd3, 1'b0);
        send_sample(16'd9, 8'd4, 1'b1);
        @(posedge clk);
        check_scalar_window();

        if (errors == 0) begin
            $display("PASS tb_p201_v10s3_energy_peak_reducer");
        end else begin
            $display("FAIL tb_p201_v10s3_energy_peak_reducer errors=%0d",
                     errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
