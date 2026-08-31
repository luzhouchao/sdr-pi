set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set hdl_dir [file join $repo_dir hdl]
set synth_dir [file join $repo_dir reports vivado_stream_wrapper_ooc_synth]
file mkdir $synth_dir

read_verilog [file join $hdl_dir p201pro_stream_power_axi_regs.v]

synth_design -top p201pro_stream_power_axi_regs -part xc7z020clg400-1 -mode out_of_context

create_clock -period 10.000 -name aclk [get_ports aclk]
report_utilization -file [file join $synth_dir utilization.txt]
report_timing_summary -file [file join $synth_dir timing_summary.txt]
write_checkpoint -force [file join $synth_dir p201pro_stream_power_axi_regs_ooc_synth.dcp]
