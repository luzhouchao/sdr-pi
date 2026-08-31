`timescale 1ns / 1ps

module p201pro_stream_power_axi_regs #
(
    parameter integer AXIL_ADDR_WIDTH = 6,
    parameter integer DEFAULT_FRAME_LEN = 64
)
(
    input  wire                         aclk,
    input  wire                         aresetn,

    input  wire [31:0]                  s_axis_tdata,
    input  wire                         s_axis_tvalid,
    output wire                         s_axis_tready,
    input  wire                         s_axis_tlast,

    input  wire [AXIL_ADDR_WIDTH-1:0]   s_axil_awaddr,
    input  wire                         s_axil_awvalid,
    output reg                          s_axil_awready,
    input  wire [31:0]                  s_axil_wdata,
    input  wire [3:0]                   s_axil_wstrb,
    input  wire                         s_axil_wvalid,
    output reg                          s_axil_wready,
    output reg  [1:0]                   s_axil_bresp,
    output reg                          s_axil_bvalid,
    input  wire                         s_axil_bready,
    input  wire [AXIL_ADDR_WIDTH-1:0]   s_axil_araddr,
    input  wire                         s_axil_arvalid,
    output reg                          s_axil_arready,
    output reg  [31:0]                  s_axil_rdata,
    output reg  [1:0]                   s_axil_rresp,
    output reg                          s_axil_rvalid,
    input  wire                         s_axil_rready,

    output wire                         summary_valid,
    output wire                         irq
);

    localparam [5:0] REG_CONTROL       = 6'h00;
    localparam [5:0] REG_FRAME_LEN     = 6'h04;
    localparam [5:0] REG_STATUS        = 6'h08;
    localparam [5:0] REG_SAMPLE_COUNT  = 6'h0c;
    localparam [5:0] REG_PEAK_POWER_LO = 6'h10;
    localparam [5:0] REG_PEAK_POWER_HI = 6'h14;
    localparam [5:0] REG_PEAK_INDEX    = 6'h18;
    localparam [5:0] REG_SUM_POWER_LO  = 6'h1c;
    localparam [5:0] REG_SUM_POWER_HI  = 6'h20;
    localparam [5:0] REG_FRAME_COUNT   = 6'h24;
    localparam [5:0] REG_LAST_POWER_LO = 6'h28;
    localparam [5:0] REG_LAST_POWER_HI = 6'h2c;

    reg        enable_reg;
    reg [15:0] frame_len_reg;
    reg        summary_valid_reg;
    reg        irq_reg;
    reg [15:0] sample_index_reg;
    reg [15:0] sample_count_reg;
    reg [39:0] peak_power_reg;
    reg [15:0] peak_index_reg;
    reg [47:0] sum_power_reg;
    reg [31:0] frame_count_reg;
    reg [39:0] last_power_reg;
    reg [31:0] control_shadow_reg;
    reg [31:0] frame_len_shadow_reg;

    wire signed [15:0] i_sample = s_axis_tdata[15:0];
    wire signed [15:0] q_sample = s_axis_tdata[31:16];
    wire signed [31:0] i_square = i_sample * i_sample;
    wire signed [31:0] q_square = q_sample * q_sample;
    wire [32:0] power_next = $unsigned(i_square) + $unsigned(q_square);
    wire [31:0] control_write_data = s_axil_wdata;
    wire [31:0] frame_len_write_data = s_axil_wdata;
    wire accept_sample = s_axis_tvalid && s_axis_tready;
    wire frame_len_hit = (sample_index_reg + 16'd1) >= frame_len_reg;
    wire frame_done = accept_sample && (s_axis_tlast || frame_len_hit);

    assign s_axis_tready = enable_reg && !summary_valid_reg;
    assign summary_valid = summary_valid_reg;
    assign irq = irq_reg;

    always @(posedge aclk) begin
        if (!aresetn) begin
            enable_reg <= 1'b0;
            frame_len_reg <= DEFAULT_FRAME_LEN[15:0];
            summary_valid_reg <= 1'b0;
            irq_reg <= 1'b0;
            sample_index_reg <= 16'd0;
            sample_count_reg <= 16'd0;
            peak_power_reg <= 40'd0;
            peak_index_reg <= 16'd0;
            sum_power_reg <= 48'd0;
            frame_count_reg <= 32'd0;
            last_power_reg <= 40'd0;
            control_shadow_reg <= 32'd0;
            frame_len_shadow_reg <= DEFAULT_FRAME_LEN;
            s_axil_awready <= 1'b0;
            s_axil_wready <= 1'b0;
            s_axil_bresp <= 2'b00;
            s_axil_bvalid <= 1'b0;
        end else begin
            s_axil_awready <= 1'b0;
            s_axil_wready <= 1'b0;

            if (!s_axil_bvalid && s_axil_awvalid && s_axil_wvalid) begin
                s_axil_awready <= 1'b1;
                s_axil_wready <= 1'b1;
                s_axil_bresp <= 2'b00;
                s_axil_bvalid <= 1'b1;

                case (s_axil_awaddr[5:0])
                    REG_CONTROL: begin
                        if (s_axil_wstrb[0]) begin
                            control_shadow_reg <= control_write_data;
                            enable_reg <= control_write_data[0];
                            if (control_write_data[1]) begin
                                summary_valid_reg <= 1'b0;
                                irq_reg <= 1'b0;
                                sample_index_reg <= 16'd0;
                                sample_count_reg <= 16'd0;
                                peak_power_reg <= 40'd0;
                                peak_index_reg <= 16'd0;
                                sum_power_reg <= 48'd0;
                                last_power_reg <= 40'd0;
                            end
                        end
                    end
                    REG_FRAME_LEN: begin
                        if (|s_axil_wstrb) begin
                            frame_len_shadow_reg <= frame_len_write_data;
                            frame_len_reg <= (frame_len_write_data[15:0] == 16'd0) ? 16'd1 : frame_len_write_data[15:0];
                        end
                    end
                    default: begin
                    end
                endcase
            end else if (s_axil_bvalid && s_axil_bready) begin
                s_axil_bvalid <= 1'b0;
            end

            if (accept_sample) begin
                last_power_reg <= {7'd0, power_next};
                sum_power_reg <= sum_power_reg + {15'd0, power_next};
                sample_count_reg <= sample_index_reg + 16'd1;

                if ((sample_index_reg == 16'd0) || ({7'd0, power_next} > peak_power_reg)) begin
                    peak_power_reg <= {7'd0, power_next};
                    peak_index_reg <= sample_index_reg;
                end

                if (frame_done) begin
                    summary_valid_reg <= 1'b1;
                    irq_reg <= 1'b1;
                    frame_count_reg <= frame_count_reg + 32'd1;
                    sample_index_reg <= 16'd0;
                end else begin
                    sample_index_reg <= sample_index_reg + 16'd1;
                end
            end
        end
    end

    always @(posedge aclk) begin
        if (!aresetn) begin
            s_axil_arready <= 1'b0;
            s_axil_rdata <= 32'd0;
            s_axil_rresp <= 2'b00;
            s_axil_rvalid <= 1'b0;
        end else begin
            s_axil_arready <= 1'b0;

            if (!s_axil_rvalid && s_axil_arvalid) begin
                s_axil_arready <= 1'b1;
                s_axil_rresp <= 2'b00;
                s_axil_rvalid <= 1'b1;

                case (s_axil_araddr[5:0])
                    REG_CONTROL:       s_axil_rdata <= {control_shadow_reg[31:2], 1'b0, enable_reg};
                    REG_FRAME_LEN:     s_axil_rdata <= {frame_len_shadow_reg[31:16], frame_len_reg};
                    REG_STATUS:        s_axil_rdata <= {29'd0, irq_reg, summary_valid_reg, enable_reg};
                    REG_SAMPLE_COUNT:  s_axil_rdata <= {16'd0, sample_count_reg};
                    REG_PEAK_POWER_LO: s_axil_rdata <= peak_power_reg[31:0];
                    REG_PEAK_POWER_HI: s_axil_rdata <= {24'd0, peak_power_reg[39:32]};
                    REG_PEAK_INDEX:    s_axil_rdata <= {16'd0, peak_index_reg};
                    REG_SUM_POWER_LO:  s_axil_rdata <= sum_power_reg[31:0];
                    REG_SUM_POWER_HI:  s_axil_rdata <= {16'd0, sum_power_reg[47:32]};
                    REG_FRAME_COUNT:   s_axil_rdata <= frame_count_reg;
                    REG_LAST_POWER_LO: s_axil_rdata <= last_power_reg[31:0];
                    REG_LAST_POWER_HI: s_axil_rdata <= {24'd0, last_power_reg[39:32]};
                    default:           s_axil_rdata <= 32'd0;
                endcase
            end else if (s_axil_rvalid && s_axil_rready) begin
                s_axil_rvalid <= 1'b0;
            end
        end
    end

endmodule
