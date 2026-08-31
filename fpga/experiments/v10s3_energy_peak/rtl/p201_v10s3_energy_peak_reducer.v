`timescale 1ns/1ps
`default_nettype none

module p201_v10s3_energy_peak_reducer #(
    parameter VALUE_WIDTH = 32,
    parameter INDEX_WIDTH = 16,
    parameter ACC_WIDTH   = 64,
    parameter COUNT_WIDTH = 16,
    parameter MAX_SAMPLES = 16
) (
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         enable,
    input  wire                         clear_summary,

    input  wire                         sample_valid,
    output wire                         sample_ready,
    input  wire                         sample_last,
    input  wire [VALUE_WIDTH-1:0]       sample_value,
    input  wire [INDEX_WIDTH-1:0]       sample_index,
    input  wire [VALUE_WIDTH-1:0]       threshold_value,

    output reg  [31:0]                  summary_flags,
    output reg  [31:0]                  summary_frame_id,
    output reg  [COUNT_WIDTH-1:0]       summary_sample_count,
    output reg  [ACC_WIDTH-1:0]         summary_total_energy,
    output reg  [VALUE_WIDTH-1:0]       summary_noise_floor,
    output reg  [VALUE_WIDTH-1:0]       summary_peak_value,
    output reg  [INDEX_WIDTH-1:0]       summary_peak_index,
    output reg  [VALUE_WIDTH-1:0]       summary_second_peak_value,
    output reg  [INDEX_WIDTH-1:0]       summary_second_peak_index,
    output reg  [VALUE_WIDTH-1:0]       summary_prominence,
    output reg  [COUNT_WIDTH-1:0]       summary_threshold_count
);

    localparam integer ACC_PAD_WIDTH = ACC_WIDTH - VALUE_WIDTH;
    localparam [COUNT_WIDTH-1:0] COUNT_ONE = {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
    localparam [COUNT_WIDTH-1:0] COUNT_TWO = {{(COUNT_WIDTH-2){1'b0}}, 2'd2};
    localparam [COUNT_WIDTH-1:0] MAX_SAMPLES_VALUE = MAX_SAMPLES;

    reg                         frame_active;
    reg  [COUNT_WIDTH-1:0]      sample_count_acc;
    reg  [ACC_WIDTH-1:0]        total_energy_acc;
    reg  [VALUE_WIDTH-1:0]      noise_floor_acc;
    reg  [VALUE_WIDTH-1:0]      peak_value_acc;
    reg  [INDEX_WIDTH-1:0]      peak_index_acc;
    reg  [VALUE_WIDTH-1:0]      second_peak_value_acc;
    reg  [INDEX_WIDTH-1:0]      second_peak_index_acc;
    reg  [COUNT_WIDTH-1:0]      threshold_count_acc;
    reg                         overflow_pending;

    reg  [VALUE_WIDTH-1:0]      running_peak_value;
    reg  [INDEX_WIDTH-1:0]      running_peak_index;
    reg  [VALUE_WIDTH-1:0]      running_second_peak_value;
    reg  [INDEX_WIDTH-1:0]      running_second_peak_index;

    wire                        accept_sample;
    wire                        start_frame;
    wire                        sample_crosses_threshold;
    wire [ACC_WIDTH-1:0]        sample_value_ext;
    wire [COUNT_WIDTH-1:0]      running_sample_count;
    wire [ACC_WIDTH-1:0]        total_energy_base;
    wire [ACC_WIDTH-1:0]        running_total_energy;
    wire                        running_overflow;
    wire [VALUE_WIDTH-1:0]      running_noise_floor;
    wire [COUNT_WIDTH-1:0]      running_threshold_count;
    wire                        have_second_peak;
    wire                        window_complete;
    wire                        auto_closed;
    wire [VALUE_WIDTH-1:0]      running_prominence;

    assign sample_ready = enable && !clear_summary;
    assign accept_sample = sample_valid && sample_ready;
    assign start_frame = !frame_active;
    assign sample_crosses_threshold = sample_value >= threshold_value;
    assign sample_value_ext = {{ACC_PAD_WIDTH{1'b0}}, sample_value};
    assign running_sample_count = start_frame ? COUNT_ONE :
                                  (sample_count_acc + COUNT_ONE);
    assign total_energy_base = start_frame ? {ACC_WIDTH{1'b0}} : total_energy_acc;
    assign running_total_energy = total_energy_base + sample_value_ext;
    assign running_overflow = (running_total_energy < total_energy_base);
    assign running_noise_floor = (start_frame || (sample_value < noise_floor_acc)) ?
                                 sample_value : noise_floor_acc;
    assign running_threshold_count =
        (start_frame ? {COUNT_WIDTH{1'b0}} : threshold_count_acc) +
        (sample_crosses_threshold ? COUNT_ONE : {COUNT_WIDTH{1'b0}});
    assign have_second_peak = !start_frame &&
                              (sample_count_acc >= COUNT_TWO);
    assign window_complete = sample_last ||
                             (running_sample_count == MAX_SAMPLES_VALUE);
    assign auto_closed = !sample_last &&
                         (running_sample_count == MAX_SAMPLES_VALUE);
    assign running_prominence =
        (running_peak_value >= running_noise_floor) ?
        (running_peak_value - running_noise_floor) : {VALUE_WIDTH{1'b0}};

    function is_better_peak;
        input [VALUE_WIDTH-1:0] candidate_value;
        input [INDEX_WIDTH-1:0] candidate_index;
        input [VALUE_WIDTH-1:0] stored_value;
        input [INDEX_WIDTH-1:0] stored_index;
        begin
            is_better_peak = (candidate_value > stored_value) ||
                             ((candidate_value == stored_value) &&
                              (candidate_index < stored_index));
        end
    endfunction

    always @(*) begin
        running_peak_value = peak_value_acc;
        running_peak_index = peak_index_acc;
        running_second_peak_value = second_peak_value_acc;
        running_second_peak_index = second_peak_index_acc;

        if (start_frame) begin
            running_peak_value = sample_value;
            running_peak_index = sample_index;
            running_second_peak_value = {VALUE_WIDTH{1'b0}};
            running_second_peak_index = {INDEX_WIDTH{1'b0}};
        end else if (is_better_peak(sample_value, sample_index,
                                    peak_value_acc, peak_index_acc)) begin
            running_peak_value = sample_value;
            running_peak_index = sample_index;
            running_second_peak_value = peak_value_acc;
            running_second_peak_index = peak_index_acc;
        end else if (!have_second_peak ||
                     is_better_peak(sample_value, sample_index,
                                    second_peak_value_acc,
                                    second_peak_index_acc)) begin
            running_second_peak_value = sample_value;
            running_second_peak_index = sample_index;
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            frame_active              <= 1'b0;
            sample_count_acc          <= {COUNT_WIDTH{1'b0}};
            total_energy_acc          <= {ACC_WIDTH{1'b0}};
            noise_floor_acc           <= {VALUE_WIDTH{1'b1}};
            peak_value_acc            <= {VALUE_WIDTH{1'b0}};
            peak_index_acc            <= {INDEX_WIDTH{1'b0}};
            second_peak_value_acc     <= {VALUE_WIDTH{1'b0}};
            second_peak_index_acc     <= {INDEX_WIDTH{1'b0}};
            threshold_count_acc       <= {COUNT_WIDTH{1'b0}};
            overflow_pending          <= 1'b0;
            summary_flags             <= 32'd0;
            summary_frame_id          <= 32'd0;
            summary_sample_count      <= {COUNT_WIDTH{1'b0}};
            summary_total_energy      <= {ACC_WIDTH{1'b0}};
            summary_noise_floor       <= {VALUE_WIDTH{1'b0}};
            summary_peak_value        <= {VALUE_WIDTH{1'b0}};
            summary_peak_index        <= {INDEX_WIDTH{1'b0}};
            summary_second_peak_value <= {VALUE_WIDTH{1'b0}};
            summary_second_peak_index <= {INDEX_WIDTH{1'b0}};
            summary_prominence        <= {VALUE_WIDTH{1'b0}};
            summary_threshold_count   <= {COUNT_WIDTH{1'b0}};
        end else begin
            if (clear_summary) begin
                frame_active              <= 1'b0;
                sample_count_acc          <= {COUNT_WIDTH{1'b0}};
                total_energy_acc          <= {ACC_WIDTH{1'b0}};
                noise_floor_acc           <= {VALUE_WIDTH{1'b1}};
                peak_value_acc            <= {VALUE_WIDTH{1'b0}};
                peak_index_acc            <= {INDEX_WIDTH{1'b0}};
                second_peak_value_acc     <= {VALUE_WIDTH{1'b0}};
                second_peak_index_acc     <= {INDEX_WIDTH{1'b0}};
                threshold_count_acc       <= {COUNT_WIDTH{1'b0}};
                overflow_pending          <= 1'b0;
                summary_flags             <= 32'd0;
                summary_frame_id          <= 32'd0;
                summary_sample_count      <= {COUNT_WIDTH{1'b0}};
                summary_total_energy      <= {ACC_WIDTH{1'b0}};
                summary_noise_floor       <= {VALUE_WIDTH{1'b0}};
                summary_peak_value        <= {VALUE_WIDTH{1'b0}};
                summary_peak_index        <= {INDEX_WIDTH{1'b0}};
                summary_second_peak_value <= {VALUE_WIDTH{1'b0}};
                summary_second_peak_index <= {INDEX_WIDTH{1'b0}};
                summary_prominence        <= {VALUE_WIDTH{1'b0}};
                summary_threshold_count   <= {COUNT_WIDTH{1'b0}};
            end else if (!enable) begin
                frame_active          <= 1'b0;
                sample_count_acc      <= {COUNT_WIDTH{1'b0}};
                total_energy_acc      <= {ACC_WIDTH{1'b0}};
                noise_floor_acc       <= {VALUE_WIDTH{1'b1}};
                peak_value_acc        <= {VALUE_WIDTH{1'b0}};
                peak_index_acc        <= {INDEX_WIDTH{1'b0}};
                second_peak_value_acc <= {VALUE_WIDTH{1'b0}};
                second_peak_index_acc <= {INDEX_WIDTH{1'b0}};
                threshold_count_acc   <= {COUNT_WIDTH{1'b0}};
                overflow_pending      <= 1'b0;
                summary_flags[1]      <= 1'b0;
            end else if (accept_sample) begin
                if (window_complete) begin
                    frame_active              <= 1'b0;
                    sample_count_acc          <= {COUNT_WIDTH{1'b0}};
                    total_energy_acc          <= {ACC_WIDTH{1'b0}};
                    noise_floor_acc           <= {VALUE_WIDTH{1'b1}};
                    peak_value_acc            <= {VALUE_WIDTH{1'b0}};
                    peak_index_acc            <= {INDEX_WIDTH{1'b0}};
                    second_peak_value_acc     <= {VALUE_WIDTH{1'b0}};
                    second_peak_index_acc     <= {INDEX_WIDTH{1'b0}};
                    threshold_count_acc       <= {COUNT_WIDTH{1'b0}};
                    overflow_pending          <= 1'b0;
                    summary_flags             <= 32'd0;
                    summary_flags[0]          <= 1'b1;
                    summary_flags[2]          <= overflow_pending ||
                                                 running_overflow;
                    summary_flags[3]          <= auto_closed;
                    summary_flags[4]          <= running_sample_count >
                                                 COUNT_ONE;
                    summary_flags[8]          <= 1'b1;
                    summary_frame_id          <= summary_frame_id + 32'd1;
                    summary_sample_count      <= running_sample_count;
                    summary_total_energy      <= running_total_energy;
                    summary_noise_floor       <= running_noise_floor;
                    summary_peak_value        <= running_peak_value;
                    summary_peak_index        <= running_peak_index;
                    summary_second_peak_value <= running_second_peak_value;
                    summary_second_peak_index <= running_second_peak_index;
                    summary_prominence        <= running_prominence;
                    summary_threshold_count   <= running_threshold_count;
                end else begin
                    frame_active          <= 1'b1;
                    sample_count_acc      <= running_sample_count;
                    total_energy_acc      <= running_total_energy;
                    noise_floor_acc       <= running_noise_floor;
                    peak_value_acc        <= running_peak_value;
                    peak_index_acc        <= running_peak_index;
                    second_peak_value_acc <= running_second_peak_value;
                    second_peak_index_acc <= running_second_peak_index;
                    threshold_count_acc   <= running_threshold_count;
                    overflow_pending      <= overflow_pending ||
                                             running_overflow;
                    summary_flags[1]      <= 1'b1;
                end
            end
        end
    end

endmodule

`default_nettype wire
