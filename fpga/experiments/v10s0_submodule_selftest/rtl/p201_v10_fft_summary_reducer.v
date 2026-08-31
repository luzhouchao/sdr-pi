`timescale 1ns / 1ps
`default_nettype none

module p201_v10_fft_summary_reducer #(
    parameter NFFT_LOG2  = 8,
    parameter POWER_WIDTH = 48,
    parameter ACC_WIDTH   = 64
) (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    enable,
    input  wire                    clear_summary,

    input  wire                    bin_valid,
    output wire                    bin_ready,
    input  wire                    bin_last,
    input  wire [NFFT_LOG2-1:0]    bin_index,
    input  wire [POWER_WIDTH-1:0]  bin_power,

    output wire [31:0]             fft_version,
    output wire [31:0]             fft_capability,
    output wire [31:0]             fft_build_id,
    output wire [31:0]             fft_abi_version,

    output reg  [31:0]             summary_flags,
    output reg  [31:0]             summary_frame_id,
    output reg  [31:0]             summary_nfft,
    output reg  [31:0]             summary_peak_bin,
    output reg  [POWER_WIDTH-1:0]  summary_peak_power,
    output reg  [ACC_WIDTH-1:0]    summary_total_power,
    output reg  [POWER_WIDTH-1:0]  summary_noise_floor,
    output reg  [POWER_WIDTH-1:0]  summary_prominence,
    output reg  [31:0]             summary_top1_bin,
    output reg  [POWER_WIDTH-1:0]  summary_top1_power,
    output reg  [31:0]             summary_top2_bin,
    output reg  [POWER_WIDTH-1:0]  summary_top2_power,
    output reg  [31:0]             summary_top3_bin,
    output reg  [POWER_WIDTH-1:0]  summary_top3_power
);

    localparam [31:0] VERSION_WORD = 32'h46543130;  // "FT10"
    localparam [31:0] CAP_WORD     = 32'h0000000f;
    localparam [31:0] BUILD_WORD   = 32'h56313042;  // "V10B"
    localparam [31:0] ABI_WORD     = 32'h000a0000;

    localparam integer BIN_PAD_WIDTH = 32 - NFFT_LOG2;
    localparam integer ACC_PAD_WIDTH = ACC_WIDTH - POWER_WIDTH;

    reg                     frame_active;
    reg [31:0]              frame_bin_count;
    reg [ACC_WIDTH-1:0]     total_power_acc;
    reg [POWER_WIDTH-1:0]   peak_power_acc;
    reg [NFFT_LOG2-1:0]     peak_bin_acc;
    reg [POWER_WIDTH-1:0]   noise_floor_acc;
    reg [POWER_WIDTH-1:0]   top1_power_acc;
    reg [POWER_WIDTH-1:0]   top2_power_acc;
    reg [POWER_WIDTH-1:0]   top3_power_acc;
    reg [NFFT_LOG2-1:0]     top1_bin_acc;
    reg [NFFT_LOG2-1:0]     top2_bin_acc;
    reg [NFFT_LOG2-1:0]     top3_bin_acc;
    reg                     overflow_pending;

    wire                    accept_bin;
    wire                    start_frame;
    wire [ACC_WIDTH-1:0]    bin_power_ext;
    wire [ACC_WIDTH-1:0]    total_power_sum;
    wire                    total_power_overflow;
    wire [ACC_WIDTH-1:0]    running_total_power;
    wire [31:0]             running_bin_count;
    wire [POWER_WIDTH-1:0]  running_peak_power;
    wire [NFFT_LOG2-1:0]    running_peak_bin;
    wire [POWER_WIDTH-1:0]  running_noise_floor;
    wire [POWER_WIDTH-1:0]  running_prominence;
    wire                    new_top1;
    wire                    new_top2;
    wire                    new_top3;
    wire [POWER_WIDTH-1:0]  running_top1_power;
    wire [POWER_WIDTH-1:0]  running_top2_power;
    wire [POWER_WIDTH-1:0]  running_top3_power;
    wire [NFFT_LOG2-1:0]    running_top1_bin;
    wire [NFFT_LOG2-1:0]    running_top2_bin;
    wire [NFFT_LOG2-1:0]    running_top3_bin;

    assign fft_version     = VERSION_WORD;
    assign fft_capability  = CAP_WORD;
    assign fft_build_id    = BUILD_WORD;
    assign fft_abi_version = ABI_WORD;

    assign bin_ready = enable;
    assign accept_bin = bin_valid && bin_ready;
    assign start_frame = !frame_active || (bin_index == {NFFT_LOG2{1'b0}});
    assign bin_power_ext = {{ACC_PAD_WIDTH{1'b0}}, bin_power};
    assign total_power_sum = total_power_acc + bin_power_ext;
    assign total_power_overflow = !start_frame && (total_power_sum < total_power_acc);
    assign running_total_power = start_frame ? bin_power_ext : total_power_sum;
    assign running_bin_count = start_frame ? 32'd1 : (frame_bin_count + 32'd1);
    assign running_peak_power = (start_frame || (bin_power > peak_power_acc)) ? bin_power : peak_power_acc;
    assign running_peak_bin = (start_frame || (bin_power > peak_power_acc)) ? bin_index : peak_bin_acc;
    assign running_noise_floor = (start_frame || (bin_power < noise_floor_acc)) ? bin_power : noise_floor_acc;
    assign running_prominence = (running_peak_power >= running_noise_floor) ?
                                (running_peak_power - running_noise_floor) :
                                {POWER_WIDTH{1'b0}};

    assign new_top1 = !start_frame && (bin_power >= top1_power_acc);
    assign new_top2 = !start_frame && !new_top1 && (bin_power >= top2_power_acc);
    assign new_top3 = !start_frame && !new_top1 && !new_top2 && (bin_power >= top3_power_acc);

    assign running_top1_power = start_frame ? bin_power :
                                (new_top1 ? bin_power : top1_power_acc);
    assign running_top1_bin = start_frame ? bin_index :
                              (new_top1 ? bin_index : top1_bin_acc);

    assign running_top2_power = start_frame ? {POWER_WIDTH{1'b0}} :
                                (new_top1 ? top1_power_acc :
                                (new_top2 ? bin_power : top2_power_acc));
    assign running_top2_bin = start_frame ? {NFFT_LOG2{1'b0}} :
                              (new_top1 ? top1_bin_acc :
                              (new_top2 ? bin_index : top2_bin_acc));

    assign running_top3_power = start_frame ? {POWER_WIDTH{1'b0}} :
                                (new_top1 ? top2_power_acc :
                                (new_top2 ? top2_power_acc :
                                (new_top3 ? bin_power : top3_power_acc)));
    assign running_top3_bin = start_frame ? {NFFT_LOG2{1'b0}} :
                              (new_top1 ? top2_bin_acc :
                              (new_top2 ? top2_bin_acc :
                              (new_top3 ? bin_index : top3_bin_acc)));

    always @(posedge clk) begin
        if (!rst_n) begin
            frame_active          <= 1'b0;
            frame_bin_count       <= 32'd0;
            total_power_acc       <= {ACC_WIDTH{1'b0}};
            peak_power_acc        <= {POWER_WIDTH{1'b0}};
            peak_bin_acc          <= {NFFT_LOG2{1'b0}};
            noise_floor_acc       <= {POWER_WIDTH{1'b1}};
            top1_power_acc        <= {POWER_WIDTH{1'b0}};
            top2_power_acc        <= {POWER_WIDTH{1'b0}};
            top3_power_acc        <= {POWER_WIDTH{1'b0}};
            top1_bin_acc          <= {NFFT_LOG2{1'b0}};
            top2_bin_acc          <= {NFFT_LOG2{1'b0}};
            top3_bin_acc          <= {NFFT_LOG2{1'b0}};
            overflow_pending      <= 1'b0;
            summary_flags         <= 32'd0;
            summary_frame_id      <= 32'd0;
            summary_nfft          <= 32'd0;
            summary_peak_bin      <= 32'd0;
            summary_peak_power    <= {POWER_WIDTH{1'b0}};
            summary_total_power   <= {ACC_WIDTH{1'b0}};
            summary_noise_floor   <= {POWER_WIDTH{1'b0}};
            summary_prominence    <= {POWER_WIDTH{1'b0}};
            summary_top1_bin      <= 32'd0;
            summary_top1_power    <= {POWER_WIDTH{1'b0}};
            summary_top2_bin      <= 32'd0;
            summary_top2_power    <= {POWER_WIDTH{1'b0}};
            summary_top3_bin      <= 32'd0;
            summary_top3_power    <= {POWER_WIDTH{1'b0}};
        end else begin
            if (clear_summary) begin
                frame_active          <= 1'b0;
                frame_bin_count       <= 32'd0;
                total_power_acc       <= {ACC_WIDTH{1'b0}};
                peak_power_acc        <= {POWER_WIDTH{1'b0}};
                peak_bin_acc          <= {NFFT_LOG2{1'b0}};
                noise_floor_acc       <= {POWER_WIDTH{1'b1}};
                top1_power_acc        <= {POWER_WIDTH{1'b0}};
                top2_power_acc        <= {POWER_WIDTH{1'b0}};
                top3_power_acc        <= {POWER_WIDTH{1'b0}};
                top1_bin_acc          <= {NFFT_LOG2{1'b0}};
                top2_bin_acc          <= {NFFT_LOG2{1'b0}};
                top3_bin_acc          <= {NFFT_LOG2{1'b0}};
                overflow_pending      <= 1'b0;
                summary_flags         <= 32'd0;
                summary_frame_id      <= 32'd0;
                summary_nfft          <= 32'd0;
                summary_peak_bin      <= 32'd0;
                summary_peak_power    <= {POWER_WIDTH{1'b0}};
                summary_total_power   <= {ACC_WIDTH{1'b0}};
                summary_noise_floor   <= {POWER_WIDTH{1'b0}};
                summary_prominence    <= {POWER_WIDTH{1'b0}};
                summary_top1_bin      <= 32'd0;
                summary_top1_power    <= {POWER_WIDTH{1'b0}};
                summary_top2_bin      <= 32'd0;
                summary_top2_power    <= {POWER_WIDTH{1'b0}};
                summary_top3_bin      <= 32'd0;
                summary_top3_power    <= {POWER_WIDTH{1'b0}};
            end else if (!enable) begin
                frame_active     <= 1'b0;
                frame_bin_count  <= 32'd0;
                overflow_pending <= 1'b0;
                summary_flags[1] <= 1'b0;
            end else if (accept_bin) begin
                summary_flags[1] <= frame_active;
                frame_active     <= !bin_last;
                frame_bin_count  <= bin_last ? 32'd0 : running_bin_count;
                total_power_acc  <= bin_last ? {ACC_WIDTH{1'b0}} : running_total_power;
                peak_power_acc   <= bin_last ? {POWER_WIDTH{1'b0}} : running_peak_power;
                peak_bin_acc     <= bin_last ? {NFFT_LOG2{1'b0}} : running_peak_bin;
                noise_floor_acc  <= bin_last ? {POWER_WIDTH{1'b1}} : running_noise_floor;
                top1_power_acc   <= bin_last ? {POWER_WIDTH{1'b0}} : running_top1_power;
                top2_power_acc   <= bin_last ? {POWER_WIDTH{1'b0}} : running_top2_power;
                top3_power_acc   <= bin_last ? {POWER_WIDTH{1'b0}} : running_top3_power;
                top1_bin_acc     <= bin_last ? {NFFT_LOG2{1'b0}} : running_top1_bin;
                top2_bin_acc     <= bin_last ? {NFFT_LOG2{1'b0}} : running_top2_bin;
                top3_bin_acc     <= bin_last ? {NFFT_LOG2{1'b0}} : running_top3_bin;
                overflow_pending <= bin_last ? 1'b0 : (overflow_pending || total_power_overflow);

                if (bin_last) begin
                    summary_flags        <= 32'd0;
                    summary_flags[0]     <= 1'b1;
                    summary_flags[2]     <= overflow_pending || total_power_overflow;
                    summary_flags[3]     <= summary_flags[0];
                    summary_flags[4]     <= 1'b1;
                    summary_flags[8]     <= 1'b1;
                    summary_frame_id     <= summary_frame_id + 32'd1;
                    summary_nfft         <= running_bin_count;
                    summary_peak_bin     <= {{BIN_PAD_WIDTH{1'b0}}, running_peak_bin};
                    summary_peak_power   <= running_peak_power;
                    summary_total_power  <= running_total_power;
                    summary_noise_floor  <= running_noise_floor;
                    summary_prominence   <= running_prominence;
                    summary_top1_bin     <= {{BIN_PAD_WIDTH{1'b0}}, running_top1_bin};
                    summary_top1_power   <= running_top1_power;
                    summary_top2_bin     <= {{BIN_PAD_WIDTH{1'b0}}, running_top2_bin};
                    summary_top2_power   <= running_top2_power;
                    summary_top3_bin     <= {{BIN_PAD_WIDTH{1'b0}}, running_top3_bin};
                    summary_top3_power   <= running_top3_power;
                end
            end
        end
    end

endmodule

`default_nettype wire
