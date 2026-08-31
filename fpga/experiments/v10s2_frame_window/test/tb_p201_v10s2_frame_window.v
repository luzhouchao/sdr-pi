`timescale 1ns/1ps
`default_nettype none

module tb_p201_v10s2_frame_window;

    reg                 clk;
    reg                 rst_n;
    reg                 enable;
    reg                 clear;
    reg  [7:0]          decim_factor;
    reg                 window_mode;
    reg                 sample_valid;
    wire                sample_ready;
    reg  signed [15:0]  sample_i;
    reg  signed [15:0]  sample_q;
    wire                out_valid;
    reg                 out_ready;
    wire                last_out;
    wire signed [15:0]  out_i;
    wire signed [15:0]  out_q;
    wire [2:0]          frame_index;
    wire [31:0]         frame_id;
    wire [31:0]         raw_sample_count;
    wire [31:0]         accepted_count;
    wire [31:0]         dropped_count;
    wire [31:0]         overflow_count;
    wire [31:0]         status_flags;

    integer             errors;
    integer             k;

    p201_v10s2_frame_window dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable(enable),
        .clear(clear),
        .decim_factor(decim_factor),
        .window_mode(window_mode),
        .sample_valid(sample_valid),
        .sample_ready(sample_ready),
        .sample_i(sample_i),
        .sample_q(sample_q),
        .out_valid(out_valid),
        .out_ready(out_ready),
        .last_out(last_out),
        .out_i(out_i),
        .out_q(out_q),
        .frame_index(frame_index),
        .frame_id(frame_id),
        .raw_sample_count(raw_sample_count),
        .accepted_count(accepted_count),
        .dropped_count(dropped_count),
        .overflow_count(overflow_count),
        .status_flags(status_flags)
    );

    initial begin
        clk = 1'b0;
        forever begin
            #5 clk = ~clk;
        end
    end

    function signed [15:0] hann_expected;
        input signed [15:0] sample_value;
        input integer index;
        reg [15:0] coeff_value;
        reg signed [32:0] product;
        begin
            case (index)
                0: coeff_value = 16'd0;
                1: coeff_value = 16'd6170;
                2: coeff_value = 16'd20057;
                3: coeff_value = 16'd31229;
                4: coeff_value = 16'd31229;
                5: coeff_value = 16'd20057;
                6: coeff_value = 16'd6170;
                default: coeff_value = 16'd0;
            endcase
            product = sample_value * $signed({1'b0, coeff_value});
            hann_expected = product[30:15];
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

    task check_signed16;
        input [255:0] name;
        input signed [15:0] got;
        input signed [15:0] exp;
        begin
            if (got !== exp) begin
                $display("CHECK FAIL %0s got=%0d exp=%0d",
                         name, got, exp);
                errors = errors + 1;
            end
        end
    endtask

    task send_sample;
        input signed [15:0] value_i;
        input signed [15:0] value_q;
        begin
            @(posedge clk);
            sample_i <= value_i;
            sample_q <= value_q;
            sample_valid <= 1'b1;
            @(posedge clk);
            sample_valid <= 1'b0;
            sample_i <= 16'sd0;
            sample_q <= 16'sd0;
        end
    endtask

    task wait_output;
        begin
            while (!out_valid) begin
                @(posedge clk);
            end
        end
    endtask

    task consume_output;
        begin
            @(posedge clk);
            while (out_valid) begin
                @(posedge clk);
            end
        end
    endtask

    initial begin
        errors = 0;
        rst_n = 1'b0;
        enable = 1'b0;
        clear = 1'b0;
        decim_factor = 8'd2;
        window_mode = 1'b0;
        sample_valid = 1'b0;
        sample_i = 16'sd0;
        sample_q = 16'sd0;
        out_ready = 1'b1;

        repeat (6) @(posedge clk);
        rst_n <= 1'b1;
        repeat (2) @(posedge clk);
        enable <= 1'b1;
        repeat (2) @(posedge clk);

        for (k = 0; k < 16; k = k + 1) begin
            send_sample(16'sd100 + k[15:0], -16'sd100 - k[15:0]);
            if ((k % 2) == 0) begin
                wait_output();
                check_signed16("rect i", out_i, 16'sd100 + k[15:0]);
                check_signed16("rect q", out_q, -16'sd100 - k[15:0]);
                if ((k == 14) && (last_out !== 1'b1)) begin
                    $display("CHECK FAIL rect last_out missing");
                    errors = errors + 1;
                end
                consume_output();
            end
        end
        @(posedge clk);

        check32("rect raw samples", raw_sample_count, 32'd16);
        check32("rect accepted", accepted_count, 32'd8);
        check32("rect frame id", frame_id, 32'd1);
        check32("rect drops", dropped_count, 32'd0);
        check32("rect overflow", overflow_count, 32'd0);

        clear <= 1'b1;
        @(posedge clk);
        clear <= 1'b0;
        window_mode <= 1'b1;
        decim_factor <= 8'd1;
        repeat (2) @(posedge clk);

        for (k = 0; k < 8; k = k + 1) begin
            send_sample(16'sd1000, -16'sd1000);
            wait_output();
            check_signed16("hann i", out_i, hann_expected(16'sd1000, k));
            check_signed16("hann q", out_q, hann_expected(-16'sd1000, k));
            if ((k == 7) && (last_out !== 1'b1)) begin
                $display("CHECK FAIL hann last_out missing");
                errors = errors + 1;
            end
            consume_output();
        end
        @(posedge clk);

        check32("hann raw samples", raw_sample_count, 32'd8);
        check32("hann accepted", accepted_count, 32'd8);
        check32("hann frame id", frame_id, 32'd1);

        out_ready <= 1'b0;
        send_sample(16'sd11, 16'sd22);
        wait_output();
        send_sample(16'sd33, 16'sd44);
        repeat (2) @(posedge clk);
        check32("backpressure drop", dropped_count, 32'd1);
        check32("backpressure overflow", overflow_count, 32'd1);
        if (status_flags[7] !== 1'b1) begin
            $display("CHECK FAIL overflow status bit not set");
            errors = errors + 1;
        end
        out_ready <= 1'b1;
        consume_output();

        if (errors == 0) begin
            $display("TB_PASS p201_v10s2_frame_window");
        end else begin
            $display("TB_FAIL p201_v10s2_frame_window errors=%0d", errors);
        end
        $finish;
    end

endmodule

`default_nettype wire
