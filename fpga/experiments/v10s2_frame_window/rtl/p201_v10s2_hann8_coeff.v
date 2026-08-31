`timescale 1ns/1ps
`default_nettype none

module p201_v10s2_hann8_coeff #(
    parameter COEFF_WIDTH = 16,
    parameter INDEX_WIDTH = 3
) (
    input  wire [INDEX_WIDTH-1:0] index,
    output reg  [COEFF_WIDTH-1:0] coeff
);

    always @(*) begin
        case (index)
            3'd0: begin
                coeff = 16'd0;
            end
            3'd1: begin
                coeff = 16'd6170;
            end
            3'd2: begin
                coeff = 16'd20057;
            end
            3'd3: begin
                coeff = 16'd31229;
            end
            3'd4: begin
                coeff = 16'd31229;
            end
            3'd5: begin
                coeff = 16'd20057;
            end
            3'd6: begin
                coeff = 16'd6170;
            end
            default: begin
                coeff = 16'd0;
            end
        endcase
    end

endmodule

`default_nettype wire
