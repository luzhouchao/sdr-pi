`timescale 1ns/1ps
`default_nettype none

module p201_fft_frame_packer (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               enable,
    input  wire               clear,

    input  wire               iq_valid,
    input  wire signed [15:0] iq_i,
    input  wire signed [15:0] iq_q,

    output reg  [31:0]        m_axis_tdata,
    output reg                m_axis_tvalid,
    input  wire               m_axis_tready,
    output reg                m_axis_tlast,

    output reg  [31:0]        frame_id,
    output reg  [31:0]        accepted_count,
    output reg  [31:0]        dropped_count,
    output reg  [31:0]        overrun_count,
    output wire [31:0]        status_flags
);

    localparam [7:0] FRAME_SAMPLES = 8'd255;

    reg [7:0] sample_index;
    reg       overrun_seen;

    wire output_stall;
    wire output_accept;
    wire can_accept_input;
    wire input_accept;
    wire input_drop;
    wire frame_last_next;

    assign output_stall     = m_axis_tvalid && !m_axis_tready;
    assign output_accept    = m_axis_tvalid && m_axis_tready;
    assign can_accept_input = enable && !clear && (!m_axis_tvalid || m_axis_tready);
    assign input_accept     = iq_valid && can_accept_input;
    assign input_drop       = iq_valid && !can_accept_input;
    assign frame_last_next  = (sample_index == FRAME_SAMPLES);

    assign status_flags = {
        27'd0,
        overrun_seen,
        output_stall,
        m_axis_tvalid,
        enable,
        1'b1
    };

    always @(posedge clk) begin
        if (!rst_n) begin
            m_axis_tdata   <= 32'd0;
            m_axis_tvalid  <= 1'b0;
            m_axis_tlast   <= 1'b0;
            frame_id       <= 32'd0;
            accepted_count <= 32'd0;
            dropped_count  <= 32'd0;
            overrun_count  <= 32'd0;
            sample_index   <= 8'd0;
            overrun_seen   <= 1'b0;
        end else begin
            if (clear) begin
                m_axis_tdata   <= 32'd0;
                m_axis_tvalid  <= 1'b0;
                m_axis_tlast   <= 1'b0;
                frame_id       <= 32'd0;
                accepted_count <= 32'd0;
                dropped_count  <= 32'd0;
                overrun_count  <= 32'd0;
                sample_index   <= 8'd0;
                overrun_seen   <= 1'b0;
            end else if (!enable) begin
                m_axis_tvalid <= 1'b0;
                m_axis_tlast  <= 1'b0;
                sample_index  <= 8'd0;
            end else begin
                if (input_drop) begin
                    dropped_count <= dropped_count + 32'd1;
                    overrun_count <= overrun_count + 32'd1;
                    overrun_seen  <= 1'b1;
                end

                if (input_accept) begin
                    m_axis_tdata   <= {iq_q, iq_i};
                    m_axis_tvalid  <= 1'b1;
                    m_axis_tlast   <= frame_last_next;
                    accepted_count <= accepted_count + 32'd1;

                    if (frame_last_next) begin
                        sample_index <= 8'd0;
                        frame_id     <= frame_id + 32'd1;
                    end else begin
                        sample_index <= sample_index + 8'd1;
                    end
                end else if (output_accept) begin
                    m_axis_tvalid <= 1'b0;
                    m_axis_tlast  <= 1'b0;
                end
            end
        end
    end

endmodule

`default_nettype wire
