set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set hdl_dir [file join $repo_dir hdl]
set vivado_dir [file join $repo_dir vivado]
set reports_dir [file join $repo_dir reports stage3_ip_packaging]
set project_dir [file join $vivado_dir ip_packager_project]
set ip_root [file join $vivado_dir ip_repo p201pro_stream_power_axi_regs_1.0]
set ip_file [file join $ip_root component.xml]

file mkdir $vivado_dir
file mkdir $reports_dir
file mkdir [file dirname $ip_root]

if {[file exists $project_dir]} {
    file delete -force $project_dir
}
if {[file exists $ip_root]} {
    file delete -force $ip_root
}

create_project -force p201pro_stream_power_ip $project_dir -part xc7z020clg400-1
add_files -norecurse [file join $hdl_dir p201pro_stream_power_axi_regs.v]
set_property top p201pro_stream_power_axi_regs [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project \
    -root_dir $ip_root \
    -vendor p201pro.local \
    -library user \
    -taxonomy /UserIP \
    -import_files

set core [ipx::current_core]
set_property name p201pro_stream_power_axi_regs $core
set_property display_name {P201Pro Stream Power AXI Registers} $core
set_property description {Low-IO AXI-Stream IQ power and frame summary wrapper for P201Pro 2T2R SDR integration experiments.} $core
set_property vendor_display_name {P201Pro SDR Accel} $core
set_property company_url {http://www.p201pro.local} $core
set_property version 1.0 $core
set_property supported_families {zynq Production} $core

set clk_bus [ipx::get_bus_interfaces aclk -of_objects $core]
if {[llength $clk_bus] > 0} {
    set assoc_busif [ipx::get_bus_parameters ASSOCIATED_BUSIF -of_objects $clk_bus]
    if {[llength $assoc_busif] > 0} {
        set_property value {s_axis:s_axil} $assoc_busif
    }
}

ipx::save_core $core

set integrity_file [file join $reports_dir ipx_check_integrity.txt]
set synth_log_file [file join $reports_dir package_synth_check.log]
set report_file [file join $reports_dir stage3_ip_packaging_report.md]

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
report_utilization -file [file join $reports_dir utilization.txt]
report_timing_summary -file [file join $reports_dir timing_summary.txt]
write_checkpoint -force [file join $reports_dir p201pro_stream_power_axi_regs_packaged_ip_synth.dcp]

set fh [open $report_file w]
puts $fh "# Stage 3 Vivado IP Packaging Report"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "## Result"
puts $fh ""
if {$integrity_ok && [file exists $ip_file]} {
    puts $fh "- IP packaging: PASS"
} else {
    puts $fh "- IP packaging: BLOCKED"
}
puts $fh "- IP root: `$ip_root`"
puts $fh "- Component XML: `$ip_file`"
puts $fh "- Vivado project: `$project_dir`"
puts $fh "- Synthesis status: `$synth_status`"
puts $fh "- Synthesis progress: `$synth_progress`"
puts $fh ""
puts $fh "## Packaged RTL"
puts $fh ""
puts $fh "- Top: `p201pro_stream_power_axi_regs`"
puts $fh "- Part used for validation: `xc7z020clg400-1`"
puts $fh "- Input stream: 32-bit IQ samples, `I=s_axis_tdata[15:0]`, `Q=s_axis_tdata[31:16]`"
puts $fh "- Control/status: AXI-Lite-style register pins"
puts $fh "- Summary outputs: `summary_valid`, `irq`"
puts $fh ""
puts $fh "## Register Map"
puts $fh ""
puts $fh "| Offset | Name | Direction | Description |"
puts $fh "| --- | --- | --- | --- |"
puts $fh "| 0x00 | CONTROL | RW | bit0 enable, bit1 clear summary/IRQ and frame accumulators |"
puts $fh "| 0x04 | FRAME_LEN | RW | Samples per frame; zero is coerced to one |"
puts $fh "| 0x08 | STATUS | RO | bit0 enable, bit1 summary_valid, bit2 irq |"
puts $fh "| 0x0c | SAMPLE_COUNT | RO | Samples accepted in the most recent/current frame |"
puts $fh "| 0x10 | PEAK_POWER_LO | RO | peak I^2+Q^2 bits 31:0 |"
puts $fh "| 0x14 | PEAK_POWER_HI | RO | peak I^2+Q^2 bits 39:32 |"
puts $fh "| 0x18 | PEAK_INDEX | RO | sample index of peak within frame |"
puts $fh "| 0x1c | SUM_POWER_LO | RO | frame accumulated power bits 31:0 |"
puts $fh "| 0x20 | SUM_POWER_HI | RO | frame accumulated power bits 47:32 |"
puts $fh "| 0x24 | FRAME_COUNT | RO | completed frame counter |"
puts $fh "| 0x28 | LAST_POWER_LO | RO | latest sample power bits 31:0 |"
puts $fh "| 0x2c | LAST_POWER_HI | RO | latest sample power bits 39:32 |"
puts $fh ""
puts $fh "## Integration Assumptions"
puts $fh ""
puts $fh "- Clock/reset must come from the AD9361 receive data path clock domain or a CDC wrapper must be added."
puts $fh "- The stream producer must hold `tvalid` until `tready` accepts the sample."
puts $fh "- `tlast` may terminate a frame early; otherwise `FRAME_LEN` terminates the frame."
puts $fh "- Software must clear CONTROL bit1 after consuming summary registers because the current wrapper back-pressures input while `summary_valid` is set."
puts $fh "- Board-level address mapping, interrupt connection, PS configuration, and device tree nodes remain outside this standalone IP package."
puts $fh ""
puts $fh "## Board-Level Blocker"
puts $fh ""
puts $fh "A real P201Pro bitstream and replacement `BOOT.bin` are still blocked until a copied board project or equivalent reconstruction material is available:"
puts $fh ""
puts $fh "1. P201Pro 2T2R/AD9361 Vivado project or TCL block design."
puts $fh "2. P201Pro board XDC constraints and PS7 configuration."
puts $fh "3. Existing `.xsa`/`.hdf` or reproducible bitstream source."
puts $fh "4. Bootgen `.bif` and exact boot payload order."
puts $fh "5. FSBL source or trusted `fsbl.elf` matched to the board."
puts $fh "6. U-Boot ELF/source version used by the vendor SD image."
puts $fh "7. Device tree source matching the vendor `devicetree.dtb`."
puts $fh "8. Vendor SD boot image rebuild instructions."
puts $fh ""
puts $fh "No `BOOT.bin` was generated by this Stage 3 script."
close $fh

puts "STAGE3_REPORT=$report_file"
puts "IP_ROOT=$ip_root"
puts "IP_COMPONENT=$ip_file"
puts "SYNTH_STATUS=$synth_status"
puts "SYNTH_PROGRESS=$synth_progress"

close_project
