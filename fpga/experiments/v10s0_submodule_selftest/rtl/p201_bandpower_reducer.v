`timescale 1ns/1ps
`default_nettype none

module p201_bandpower_reducer (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        enable,
    input  wire        clear_summary,

    input  wire        bin_valid,
    output wire        bin_ready,
    input  wire        bin_last,
    input  wire [7:0]  bin_index,
    input  wire [47:0] bin_power,

    output wire [31:0] summary_flags,
    output reg         summary_valid,
    output reg         summary_overrun,
    output reg         summary_length_error,
    output reg         summary_missing_last,
    output reg  [31:0] summary_frame_id,
    output reg  [31:0] summary_nfft,
    output reg  [63:0] summary_total_power,
    output reg  [7:0]  summary_peak_bin,
    output reg  [47:0] summary_peak_power,
    output reg  [7:0]  summary_top1_bin,
    output reg  [47:0] summary_top1_power,
    output reg  [7:0]  summary_top2_bin,
    output reg  [47:0] summary_top2_power,
    output reg  [7:0]  summary_top3_bin,
    output reg  [47:0] summary_top3_power,
    output reg  [47:0] summary_noise_floor,
    output reg  [47:0] summary_prominence,
    output reg  [63:0] summary_band0_power,
    output reg  [63:0] summary_band1_power,
    output reg  [63:0] summary_band2_power,
    output reg  [63:0] summary_band3_power
);

    localparam [8:0] FRAME_BINS = 9'd256;

    reg         frame_active;
    reg  [8:0] frame_bin_count;
    reg  [63:0] total_power_acc;
    reg  [47:0] peak_power_acc;
    reg  [7:0]  peak_bin_acc;
    reg  [47:0] noise_floor_acc;
    reg  [47:0] top1_power_acc;
    reg  [47:0] top2_power_acc;
    reg  [47:0] top3_power_acc;
    reg  [7:0]  top1_bin_acc;
    reg  [7:0]  top2_bin_acc;
    reg  [7:0]  top3_bin_acc;
    reg  [63:0] band0_power_acc;
    reg  [63:0] band1_power_acc;
    reg  [63:0] band2_power_acc;
    reg  [63:0] band3_power_acc;

    reg  [47:0] running_top1_power;
    reg  [47:0] running_top2_power;
    reg  [47:0] running_top3_power;
    reg  [7:0]  running_top1_bin;
    reg  [7:0]  running_top2_bin;
    reg  [7:0]  running_top3_bin;

    wire        accept_bin;
    wire        start_frame;
    wire        have_top2;
    wire        have_top3;
    wire [63:0] bin_power_ext;
    wire [8:0]  running_bin_count;
    wire        frame_done;
    wire [63:0] running_total_power;
    wire [47:0] running_peak_power;
    wire [7:0]  running_peak_bin;
    wire [47:0] running_noise_floor;
    wire [47:0] running_prominence;
    wire [63:0] band0_base;
    wire [63:0] band1_base;
    wire [63:0] band2_base;
    wire [63:0] band3_base;
    wire [63:0] running_band0_power;
    wire [63:0] running_band1_power;
    wire [63:0] running_band2_power;
    wire [63:0] running_band3_power;

    assign bin_ready = enable && !clear_summary;
    assign accept_bin = bin_valid && bin_ready;
    assign start_frame = !frame_active;
    assign have_top2 = !start_frame && (frame_bin_count >= 9'd2);
    assign have_top3 = !start_frame && (frame_bin_count >= 9'd3);
    assign bin_power_ext = {16'd0, bin_power};
    assign running_bin_count = start_frame ? 9'd1 : (frame_bin_count + 9'd1);
    assign frame_done = bin_last || (running_bin_count == FRAME_BINS);
    assign running_total_power = (start_frame ? 64'd0 : total_power_acc) +
                                 bin_power_ext;
    assign running_peak_power =
        (start_frame || is_better(bin_power, bin_index,
                                  peak_power_acc, peak_bin_acc)) ?
        bin_power : peak_power_acc;
    assign running_peak_bin =
        (start_frame || is_better(bin_power, bin_index,
                                  peak_power_acc, peak_bin_acc)) ?
        bin_index : peak_bin_acc;
    assign running_noise_floor =
        (start_frame || (bin_power < noise_floor_acc)) ?
        bin_power : noise_floor_acc;
    assign running_prominence =
        (running_peak_power >= running_noise_floor) ?
        (running_peak_power - running_noise_floor) : 48'd0;

    assign band0_base = start_frame ? 64'd0 : band0_power_acc;
    assign band1_base = start_frame ? 64'd0 : band1_power_acc;
    assign band2_base = start_frame ? 64'd0 : band2_power_acc;
    assign band3_base = start_frame ? 64'd0 : band3_power_acc;
    assign running_band0_power =
        band0_base + ((bin_index[7:6] == 2'b00) ? bin_power_ext : 64'd0);
    assign running_band1_power =
        band1_base + ((bin_index[7:6] == 2'b01) ? bin_power_ext : 64'd0);
    assign running_band2_power =
        band2_base + ((bin_index[7:6] == 2'b10) ? bin_power_ext : 64'd0);
    assign running_band3_power =
        band3_base + ((bin_index[7:6] == 2'b11) ? bin_power_ext : 64'd0);

    assign summary_flags = {23'd0,
                            1'b1,
                            3'd0,
                            summary_missing_last,
                            summary_length_error,
                            summary_overrun,
                            frame_active,
                            summary_valid};

    function is_better;
        input [47:0] candidate_power;
        input [7:0]  candidate_bin;
        input [47:0] stored_power;
        input [7:0]  stored_bin;
        begin
            is_better = (candidate_power > stored_power) ||
                        ((candidate_power == stored_power) &&
                         (candidate_bin < stored_bin));
        end
    endfunction

    always @(*) begin
        running_top1_power = top1_power_acc;
        running_top2_power = top2_power_acc;
        running_top3_power = top3_power_acc;
        running_top1_bin   = top1_bin_acc;
        running_top2_bin   = top2_bin_acc;
        running_top3_bin   = top3_bin_acc;

        if (start_frame) begin
            running_top1_power = bin_power;
            running_top1_bin   = bin_index;
            running_top2_power = 48'd0;
            running_top2_bin   = 8'd0;
            running_top3_power = 48'd0;
            running_top3_bin   = 8'd0;
        end else if (is_better(bin_power, bin_index,
                               top1_power_acc, top1_bin_acc)) begin
            running_top1_power = bin_power;
            running_top1_bin   = bin_index;
            running_top2_power = top1_power_acc;
            running_top2_bin   = top1_bin_acc;
            running_top3_power = have_top2 ? top2_power_acc : 48'd0;
            running_top3_bin   = have_top2 ? top2_bin_acc : 8'd0;
        end else if (!have_top2 ||
                     is_better(bin_power, bin_index,
                               top2_power_acc, top2_bin_acc)) begin
            running_top2_power = bin_power;
            running_top2_bin   = bin_index;
            running_top3_power = have_top2 ? top2_power_acc : 48'd0;
            running_top3_bin   = have_top2 ? top2_bin_acc : 8'd0;
        end else if (!have_top3 ||
                     is_better(bin_power, bin_index,
                               top3_power_acc, top3_bin_acc)) begin
            running_top3_power = bin_power;
            running_top3_bin   = bin_index;
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            frame_active         <= 1'b0;
            frame_bin_count      <= 9'd0;
            total_power_acc      <= 64'd0;
            peak_power_acc       <= 48'd0;
            peak_bin_acc         <= 8'd0;
            noise_floor_acc      <= {48{1'b1}};
            top1_power_acc       <= 48'd0;
            top2_power_acc       <= 48'd0;
            top3_power_acc       <= 48'd0;
            top1_bin_acc         <= 8'd0;
            top2_bin_acc         <= 8'd0;
            top3_bin_acc         <= 8'd0;
            band0_power_acc      <= 64'd0;
            band1_power_acc      <= 64'd0;
            band2_power_acc      <= 64'd0;
            band3_power_acc      <= 64'd0;
            summary_valid        <= 1'b0;
            summary_overrun      <= 1'b0;
            summary_length_error <= 1'b0;
            summary_missing_last <= 1'b0;
            summary_frame_id     <= 32'd0;
            summary_nfft         <= 32'd0;
            summary_total_power  <= 64'd0;
            summary_peak_bin     <= 8'd0;
            summary_peak_power   <= 48'd0;
            summary_top1_bin     <= 8'd0;
            summary_top1_power   <= 48'd0;
            summary_top2_bin     <= 8'd0;
            summary_top2_power   <= 48'd0;
            summary_top3_bin     <= 8'd0;
            summary_top3_power   <= 48'd0;
            summary_noise_floor  <= 48'd0;
            summary_prominence   <= 48'd0;
            summary_band0_power  <= 64'd0;
            summary_band1_power  <= 64'd0;
            summary_band2_power  <= 64'd0;
            summary_band3_power  <= 64'd0;
        end else begin
            if (clear_summary) begin
                frame_active         <= 1'b0;
                frame_bin_count      <= 9'd0;
                total_power_acc      <= 64'd0;
                peak_power_acc       <= 48'd0;
                peak_bin_acc         <= 8'd0;
                noise_floor_acc      <= {48{1'b1}};
                top1_power_acc       <= 48'd0;
                top2_power_acc       <= 48'd0;
                top3_power_acc       <= 48'd0;
                top1_bin_acc         <= 8'd0;
                top2_bin_acc         <= 8'd0;
                top3_bin_acc         <= 8'd0;
                band0_power_acc      <= 64'd0;
                band1_power_acc      <= 64'd0;
                band2_power_acc      <= 64'd0;
                band3_power_acc      <= 64'd0;
                summary_valid        <= 1'b0;
                summary_overrun      <= 1'b0;
                summary_length_error <= 1'b0;
                summary_missing_last <= 1'b0;
                summary_frame_id     <= 32'd0;
                summary_nfft         <= 32'd0;
                summary_total_power  <= 64'd0;
                summary_peak_bin     <= 8'd0;
                summary_peak_power   <= 48'd0;
                summary_top1_bin     <= 8'd0;
                summary_top1_power   <= 48'd0;
                summary_top2_bin     <= 8'd0;
                summary_top2_power   <= 48'd0;
                summary_top3_bin     <= 8'd0;
                summary_top3_power   <= 48'd0;
                summary_noise_floor  <= 48'd0;
                summary_prominence   <= 48'd0;
                summary_band0_power  <= 64'd0;
                summary_band1_power  <= 64'd0;
                summary_band2_power  <= 64'd0;
                summary_band3_power  <= 64'd0;
            end else if (!enable) begin
                frame_active    <= 1'b0;
                frame_bin_count <= 9'd0;
                total_power_acc <= 64'd0;
                peak_power_acc  <= 48'd0;
                peak_bin_acc    <= 8'd0;
                noise_floor_acc <= {48{1'b1}};
                top1_power_acc  <= 48'd0;
                top2_power_acc  <= 48'd0;
                top3_power_acc  <= 48'd0;
                top1_bin_acc    <= 8'd0;
                top2_bin_acc    <= 8'd0;
                top3_bin_acc    <= 8'd0;
                band0_power_acc <= 64'd0;
                band1_power_acc <= 64'd0;
                band2_power_acc <= 64'd0;
                band3_power_acc <= 64'd0;
            end else if (accept_bin) begin
                if (frame_done) begin
                    frame_active         <= 1'b0;
                    frame_bin_count      <= 9'd0;
                    total_power_acc      <= 64'd0;
                    peak_power_acc       <= 48'd0;
                    peak_bin_acc         <= 8'd0;
                    noise_floor_acc      <= {48{1'b1}};
                    top1_power_acc       <= 48'd0;
                    top2_power_acc       <= 48'd0;
                    top3_power_acc       <= 48'd0;
                    top1_bin_acc         <= 8'd0;
                    top2_bin_acc         <= 8'd0;
                    top3_bin_acc         <= 8'd0;
                    band0_power_acc      <= 64'd0;
                    band1_power_acc      <= 64'd0;
                    band2_power_acc      <= 64'd0;
                    band3_power_acc      <= 64'd0;
                    summary_valid        <= 1'b1;
                    summary_overrun      <= summary_overrun || summary_valid;
                    summary_length_error <= (running_bin_count != FRAME_BINS);
                    summary_missing_last <= (running_bin_count == FRAME_BINS) &&
                                            !bin_last;
                    summary_frame_id     <= summary_frame_id + 32'd1;
                    summary_nfft         <= {23'd0, running_bin_count};
                    summary_total_power  <= running_total_power;
                    summary_peak_bin     <= running_peak_bin;
                    summary_peak_power   <= running_peak_power;
                    summary_top1_bin     <= running_top1_bin;
                    summary_top1_power   <= running_top1_power;
                    summary_top2_bin     <= running_top2_bin;
                    summary_top2_power   <= running_top2_power;
                    summary_top3_bin     <= running_top3_bin;
                    summary_top3_power   <= running_top3_power;
                    summary_noise_floor  <= running_noise_floor;
                    summary_prominence   <= running_prominence;
                    summary_band0_power  <= running_band0_power;
                    summary_band1_power  <= running_band1_power;
                    summary_band2_power  <= running_band2_power;
                    summary_band3_power  <= running_band3_power;
                end else begin
                    frame_active    <= 1'b1;
                    frame_bin_count <= running_bin_count;
                    total_power_acc <= running_total_power;
                    peak_power_acc  <= running_peak_power;
                    peak_bin_acc    <= running_peak_bin;
                    noise_floor_acc <= running_noise_floor;
                    top1_power_acc  <= running_top1_power;
                    top2_power_acc  <= running_top2_power;
                    top3_power_acc  <= running_top3_power;
                    top1_bin_acc    <= running_top1_bin;
                    top2_bin_acc    <= running_top2_bin;
                    top3_bin_acc    <= running_top3_bin;
                    band0_power_acc <= running_band0_power;
                    band1_power_acc <= running_band1_power;
                    band2_power_acc <= running_band2_power;
                    band3_power_acc <= running_band3_power;
                end
            end
        end
    end

endmodule

`default_nettype wire
