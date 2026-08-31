`timescale 1ns/1ps
`default_nettype none

module tb_p201_sdr_quality_stats;

    reg                 clk;
    reg                 rst_n;
    reg                 enable;
    reg                 clear;
    reg                 frame_start;
    reg                 frame_end;
    reg                 sample_valid;
    reg                 sample_drop;
    reg signed [15:0]   sample_i;
    reg signed [15:0]   sample_q;
    wire                frame_active;
    wire                frame_done;
    wire                stats_valid;
    wire                overflow;
    wire                protocol_error;
    wire [31:0]         sample_count;
    wire signed [47:0]  sum_i;
    wire signed [47:0]  sum_q;
    wire [63:0]         sum_i2;
    wire [63:0]         sum_q2;
    wire signed [63:0]  sum_iq;
    wire [15:0]         abs_peak;
    wire [31:0]         clip_i_count;
    wire [31:0]         clip_q_count;
    wire [31:0]         sat_i_count;
    wire [31:0]         sat_q_count;
    wire [31:0]         valid_count;
    wire [31:0]         drop_count;

    integer errors;

    p201_sdr_quality_stats dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear(clear),
        .frame_start(frame_start),
        .frame_end(frame_end),
        .sample_valid(sample_valid),
        .sample_drop(sample_drop),
        .sample_i(sample_i),
        .sample_q(sample_q),
        .frame_active(frame_active),
        .frame_done(frame_done),
        .stats_valid(stats_valid),
        .overflow(overflow),
        .protocol_error(protocol_error),
        .sample_count(sample_count),
        .sum_i(sum_i),
        .sum_q(sum_q),
        .sum_i2(sum_i2),
        .sum_q2(sum_q2),
        .sum_iq(sum_iq),
        .abs_peak(abs_peak),
        .clip_i_count(clip_i_count),
        .clip_q_count(clip_q_count),
        .sat_i_count(sat_i_count),
        .sat_q_count(sat_q_count),
        .valid_count(valid_count),
        .drop_count(drop_count)
    );

    initial begin
        clk = 1'b0;
        forever begin
            #5 clk = ~clk;
        end
    end

    task pulse_start;
        begin
            @(negedge clk);
            frame_start <= 1'b1;
            @(negedge clk);
            frame_start <= 1'b0;
        end
    endtask

    task start_with_sample;
        input signed [15:0] i_value;
        input signed [15:0] q_value;
        begin
            @(negedge clk);
            frame_start <= 1'b1;
            sample_i <= i_value;
            sample_q <= q_value;
            sample_valid <= 1'b1;
            @(negedge clk);
            frame_start <= 1'b0;
            sample_valid <= 1'b0;
            sample_i <= 16'sd0;
            sample_q <= 16'sd0;
        end
    endtask

    task pulse_end;
        begin
            @(negedge clk);
            frame_end <= 1'b1;
            @(negedge clk);
            frame_end <= 1'b0;
        end
    endtask

    task send_sample;
        input signed [15:0] i_value;
        input signed [15:0] q_value;
        begin
            @(negedge clk);
            sample_i <= i_value;
            sample_q <= q_value;
            sample_valid <= 1'b1;
            @(negedge clk);
            sample_valid <= 1'b0;
            sample_i <= 16'sd0;
            sample_q <= 16'sd0;
        end
    endtask

    task send_drop;
        begin
            @(negedge clk);
            sample_drop <= 1'b1;
            @(negedge clk);
            sample_drop <= 1'b0;
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

    task check48s;
        input [255:0] name;
        input signed [47:0] got;
        input signed [47:0] exp;
        begin
            if (got !== exp) begin
                $display("CHECK FAIL %0s got=%0d exp=%0d",
                         name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task check64;
        input [255:0] name;
        input [63:0] got;
        input [63:0] exp;
        begin
            if (got !== exp) begin
                $display("CHECK FAIL %0s got=0x%016x exp=0x%016x",
                         name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task check64s;
        input [255:0] name;
        input signed [63:0] got;
        input signed [63:0] exp;
        begin
            if (got !== exp) begin
                $display("CHECK FAIL %0s got=%0d exp=%0d",
                         name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    initial begin
        errors = 0;
        rst_n = 1'b0;
        enable = 1'b0;
        clear = 1'b0;
        frame_start = 1'b0;
        frame_end = 1'b0;
        sample_valid = 1'b0;
        sample_drop = 1'b0;
        sample_i = 16'sd0;
        sample_q = 16'sd0;

        repeat (4) begin
            @(posedge clk);
        end

        rst_n = 1'b1;
        enable = 1'b1;

        start_with_sample(16'sd3, -16'sd4);
        send_sample(-16'sd5, 16'sd12);
        send_sample(16'sd32767, -16'sd32768);
        send_drop();
        send_sample(-16'sd100, -16'sd200);
        pulse_end();

        check32("stats_valid", {31'd0, stats_valid}, 32'd1);
        check32("frame_done", {31'd0, frame_done}, 32'd1);
        check32("overflow", {31'd0, overflow}, 32'd0);
        check32("protocol_error", {31'd0, protocol_error}, 32'd0);
        check32("sample_count", sample_count, 32'd4);
        check48s("sum_i", sum_i, 48'sd32665);
        check48s("sum_q", sum_q, -48'sd32960);
        check64("sum_i2", sum_i2, 64'd1073686323);
        check64("sum_q2", sum_q2, 64'd1073781984);
        check64s("sum_iq", sum_iq, -64'sd1073689128);
        check32("abs_peak", {16'd0, abs_peak}, 32'd32768);
        check32("clip_i_count", clip_i_count, 32'd1);
        check32("clip_q_count", clip_q_count, 32'd1);
        check32("sat_i_count", sat_i_count, 32'd1);
        check32("sat_q_count", sat_q_count, 32'd1);
        check32("valid_count", valid_count, 32'd4);
        check32("drop_count", drop_count, 32'd1);

        @(posedge clk);
        clear <= 1'b1;
        @(posedge clk);
        clear <= 1'b0;
        @(posedge clk);
        check32("clear sample_count", sample_count, 32'd0);
        check32("clear stats_valid", {31'd0, stats_valid}, 32'd0);

        pulse_start();
        send_sample(16'sd10, 16'sd10);
        pulse_end();
        @(posedge clk);

        check32("second sample_count", sample_count, 32'd1);
        check48s("second sum_i", sum_i, 48'sd10);
        check48s("second sum_q", sum_q, 48'sd10);
        check64("second sum_i2", sum_i2, 64'd100);
        check64("second sum_q2", sum_q2, 64'd100);
        check64s("second sum_iq", sum_iq, 64'sd100);

        if (errors == 0) begin
            $display("PASS tb_p201_sdr_quality_stats");
        end else begin
            $display("FAIL tb_p201_sdr_quality_stats errors=%0d", errors);
        end

        $finish;
    end

endmodule

`default_nettype wire
