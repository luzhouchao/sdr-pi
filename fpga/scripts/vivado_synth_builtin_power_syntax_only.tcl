set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set hdl_dir [file join $repo_dir hdl_out builtin_power p201pro_builtin_power_hdl_model]
set synth_dir [file join $repo_dir vivado_out builtin_power_syntax_only]
file mkdir $synth_dir

set parts [get_parts]
if {[llength $parts] == 0} {
    error "No Vivado parts are installed."
}
set fallback_part [lindex $parts 0]
puts "FALLBACK_PART=$fallback_part"

read_verilog [file join $hdl_dir peak_power.v]
read_verilog [file join $hdl_dir p201pro_builtin_power_hdl_model.v]

synth_design -top p201pro_builtin_power_hdl_model -part $fallback_part

report_utilization -file [file join $synth_dir utilization_fallback_part.txt]
report_timing_summary -file [file join $synth_dir timing_summary_fallback_part.txt]
write_checkpoint -force [file join $synth_dir p201pro_builtin_power_syntax_only.dcp]
