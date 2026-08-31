set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set hdl_dir [file join $repo_dir experiments v8_derived_low_nx_load hdl]
set vivado_dir [file join $repo_dir vivado]
set reports_dir [file join $repo_dir reports stage4_ad9361_tap_ip_v8l1_auto_agg]
set project_dir [file join $repo_dir vivado_out ad9361_tap_ip_packager_project_v8l1_auto_agg]
set ip_root [file join $vivado_dir ip_repo p201pro_ad9361_power_tap_axi_regs_1.0]
set ip_file [file join $ip_root component.xml]

file mkdir $vivado_dir
file mkdir $reports_dir
file mkdir [file dirname $project_dir]
file mkdir [file dirname $ip_root]

if {[file exists $project_dir]} {
    file delete -force $project_dir
}
if {[file exists $ip_root]} {
    file delete -force $ip_root
}

create_project -force p201pro_ad9361_tap_ip $project_dir -part xc7z020clg400-2
add_files -norecurse [file join $hdl_dir p201pro_ad9361_power_tap_axi_regs.v]
set_property top p201pro_ad9361_power_tap_axi_regs [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project \
    -root_dir $ip_root \
    -vendor p201pro.local \
    -library user \
    -taxonomy /UserIP \
    -import_files

set core [ipx::current_core]
set_property name p201pro_ad9361_power_tap_axi_regs $core
set_property display_name {P201Pro AD9361 Power Tap AXI Registers} $core
set_property description {Dual-clock AD9361 RX IQ power summary tap with AXI-Lite control/status registers.} $core
set_property vendor_display_name {P201Pro SDR Accel} $core
set_property company_url {http://www.p201pro.local} $core
set_property version 1.0 $core
set_property supported_families {zynq Production} $core

set s_axi_clk [ipx::get_bus_interfaces s_axi_aclk -of_objects $core]
if {[llength $s_axi_clk] > 0} {
    set assoc_busif [ipx::get_bus_parameters ASSOCIATED_BUSIF -of_objects $s_axi_clk]
    if {[llength $assoc_busif] > 0} {
        set_property value {s_axi} $assoc_busif
    }
    set assoc_reset [ipx::get_bus_parameters ASSOCIATED_RESET -of_objects $s_axi_clk]
    if {[llength $assoc_reset] > 0} {
        set_property value {s_axi_aresetn} $assoc_reset
    }
}

set rst_bus [ipx::get_bus_interfaces s_axi_aresetn -of_objects $core]
if {[llength $rst_bus] > 0} {
    set polarity [ipx::get_bus_parameters POLARITY -of_objects $rst_bus]
    if {[llength $polarity] > 0} {
        set_property value ACTIVE_LOW $polarity
    }
}

ipx::save_core $core

set integrity_file [file join $reports_dir ipx_check_integrity.txt]
set report_file [file join $reports_dir stage4_ad9361_tap_ip_report.md]

set integrity_ok 1
set integrity_text ""
if {[catch {ipx::check_integrity $core} integrity_text]} {
    set integrity_ok 0
}
set fh [open $integrity_file w]
puts $fh $integrity_text
close $fh

reset_run synth_1
launch_runs synth_1 -jobs 4
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
set synth_progress [get_property PROGRESS [get_runs synth_1]]
open_run synth_1 -name synth_1
create_clock -period 10.000 -name s_axi_aclk [get_ports s_axi_aclk]
create_clock -period 8.138 -name adc_clk [get_ports adc_clk]
set_clock_groups -asynchronous -group [get_clocks s_axi_aclk] -group [get_clocks adc_clk]
report_utilization -file [file join $reports_dir utilization.txt]
report_timing_summary -file [file join $reports_dir timing_summary.txt]
write_checkpoint -force [file join $reports_dir p201pro_ad9361_power_tap_axi_regs_synth.dcp]

set fh [open $report_file w]
puts $fh "# Stage 4 AD9361 Tap IP Report V8L1 Auto Aggregate"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
if {$integrity_ok && [file exists $ip_file]} {
    puts $fh "- IP packaging: PASS"
} else {
    puts $fh "- IP packaging: BLOCKED"
}
puts $fh "- Candidate HDL: `[file join $hdl_dir p201pro_ad9361_power_tap_axi_regs.v]`"
puts $fh "- IP root: `$ip_root`"
puts $fh "- Component XML: `$ip_file`"
puts $fh "- Project part: `xc7z020clg400-2`"
puts $fh "- Synthesis status: `$synth_status`"
puts $fh "- Synthesis progress: `$synth_progress`"
puts $fh "- Clock domains: `adc_clk` for raw AD9361 RX tap, `s_axi_aclk` for AXI-Lite registers"
puts $fh "- V8L1 intent: SUM8/QUA8/AGG8 auto-roll low-NX-load candidate from pre-V9A snapshot"
puts $fh ""
puts $fh "## Integration Intent"
puts $fh ""
puts $fh "- Connect `adc_clk` to `axi_ad9361/l_clk`."
puts $fh "- Connect `adc_rst` to `axi_ad9361/rst`."
puts $fh "- Connect `adc_i` to `axi_ad9361/adc_data_i0`."
puts $fh "- Connect `adc_q` to `axi_ad9361/adc_data_q0`."
puts $fh "- Connect `adc_valid` to `axi_ad9361/adc_valid_i0`."
puts $fh "- Connect `s_axi` to the PS AXI-Lite interconnect."
puts $fh "- Connect `irq` through an unused `sys_concat_intc` input."
puts $fh ""
puts $fh "No bitstream or BOOT.bin is produced by this script."
close $fh

puts "AD9361_TAP_IP_REPORT=$report_file"
puts "AD9361_TAP_IP_ROOT=$ip_root"
puts "SYNTH_STATUS=$synth_status"
puts "SYNTH_PROGRESS=$synth_progress"
close_project
