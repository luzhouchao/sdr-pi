set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set proj_dir [file join $repo_dir vendor_experiments PZ_PZP201_PRO_NO_OS_ACCEL]
set xpr [file join $proj_dir PZ_PZP201_PRO_NO_OS.xpr]
set bd [file join $proj_dir PZ_PZP201_PRO_NO_OS.srcs sources_1 bd system system.bd]
set vendor_library [file join $proj_dir library]
set local_ip_repo [file join $repo_dir vivado ip_repo]
set cdc_xdc [file join $repo_dir hdl p201pro_ad9361_power_tap_cdc.xdc]
set reports_dir [file join $repo_dir reports stage4_ad9361_tap_integration_v8l2_auto_roll_fix]
set report_file [file join $reports_dir ad9361_tap_integration_report.md]
set validate_file [file join $reports_dir validate_bd_design.txt]
file mkdir $reports_dir

open_project $xpr
set_property ip_repo_paths [list $vendor_library $local_ip_repo] [current_project]
update_ip_catalog
open_bd_design $bd

proc connect_bd_net_if_needed {src_pin dst_pin} {
    set dst_net [get_bd_nets -quiet -of_objects $dst_pin]
    if {[llength $dst_net] == 0} {
        connect_bd_net $src_pin $dst_pin
    }
}

proc connect_bd_intf_net_if_needed {src_pin dst_pin} {
    set dst_net [get_bd_intf_nets -quiet -of_objects $dst_pin]
    if {[llength $dst_net] == 0} {
        connect_bd_intf_net $src_pin $dst_pin
    }
}

if {[llength [get_files -quiet $cdc_xdc]] == 0} {
    add_files -fileset constrs_1 -norecurse $cdc_xdc
}
set_property used_in {synthesis implementation} [get_files $cdc_xdc]

set cell_name p201_tap0
if {[llength [get_bd_cells -quiet /$cell_name]] > 0} {
    delete_bd_objs [get_bd_cells /$cell_name]
}
create_bd_cell -type ip -vlnv p201pro.local:user:p201pro_ad9361_power_tap_axi_regs:1.0 $cell_name

set tap [get_bd_cells /$cell_name]

connect_bd_net_if_needed [get_bd_pins /axi_ad9361/l_clk] [get_bd_pins /$cell_name/adc_clk]
connect_bd_net_if_needed [get_bd_pins /axi_ad9361/rst] [get_bd_pins /$cell_name/adc_rst]
connect_bd_net_if_needed [get_bd_pins /axi_ad9361/adc_data_i0] [get_bd_pins /$cell_name/adc_i]
connect_bd_net_if_needed [get_bd_pins /axi_ad9361/adc_data_q0] [get_bd_pins /$cell_name/adc_q]
connect_bd_net_if_needed [get_bd_pins /axi_ad9361/adc_data_i1] [get_bd_pins /$cell_name/adc_i1]
connect_bd_net_if_needed [get_bd_pins /axi_ad9361/adc_data_q1] [get_bd_pins /$cell_name/adc_q1]
connect_bd_net_if_needed [get_bd_pins /axi_ad9361/adc_valid_i0] [get_bd_pins /$cell_name/adc_valid]
connect_bd_net_if_needed [get_bd_pins /axi_ad9361/adc_valid_i1] [get_bd_pins /$cell_name/adc_valid1]
connect_bd_net_if_needed [get_bd_pins /sys_ps7/FCLK_CLK0] [get_bd_pins /$cell_name/s_axi_aclk]
connect_bd_net_if_needed [get_bd_pins /sys_rstgen/peripheral_aresetn] [get_bd_pins /$cell_name/s_axi_aresetn]

set old_num_mi [get_property CONFIG.NUM_MI [get_bd_cells /axi_cpu_interconnect]]
if {$old_num_mi < 11} {
    set_property CONFIG.NUM_MI 11 [get_bd_cells /axi_cpu_interconnect]
}
connect_bd_intf_net_if_needed [get_bd_intf_pins /axi_cpu_interconnect/M10_AXI] [get_bd_intf_pins /$cell_name/s_axi]
connect_bd_net_if_needed [get_bd_pins /sys_ps7/FCLK_CLK0] [get_bd_pins /axi_cpu_interconnect/M10_ACLK]
connect_bd_net_if_needed [get_bd_pins /sys_rstgen/peripheral_aresetn] [get_bd_pins /axi_cpu_interconnect/M10_ARESETN]

set in0_net [get_bd_nets -quiet -of_objects [get_bd_pins /sys_concat_intc/In0]]
if {[llength $in0_net] > 0} {
    disconnect_bd_net $in0_net [get_bd_pins /sys_concat_intc/In0]
}
connect_bd_net [get_bd_pins /$cell_name/irq] [get_bd_pins /sys_concat_intc/In0]

assign_bd_address
set tap_segs [get_bd_addr_segs -quiet /$cell_name/s_axi/*]
set addr_seg [get_bd_addr_segs -quiet /sys_ps7/Data/SEG_${cell_name}_reg0]
if {[llength $addr_seg] > 0} {
    set_property range 0x00010000 $addr_seg
    set_property offset 0x43C00000 $addr_seg
}

set validate_status PASS
set validate_text ""
if {[catch {validate_bd_design} validate_text]} {
    set validate_status FAILED
}
set fh [open $validate_file w]
puts $fh $validate_text
close $fh

save_bd_design

set addr_seg [get_bd_addr_segs -quiet /sys_ps7/Data/SEG_${cell_name}_reg0]
set fh [open $report_file w]
puts $fh "# AD9361 Power Tap BD Integration Report V8L2 Auto-Roll Fix"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "- Project copy: `$proj_dir`"
puts $fh "- Added cell: `/$cell_name`"
puts $fh "- IP VLNV: `p201pro.local:user:p201pro_ad9361_power_tap_axi_regs:1.0`"
puts $fh "- V8L2 intent: rebuild BD against the V8-derived AGG8 continuous auto-roll fix IP package"
puts $fh "- validate_bd_design: `$validate_status`"
puts $fh "- AXI interconnect NUM_MI before: `$old_num_mi`"
puts $fh "- AXI interconnect NUM_MI after: `[get_property CONFIG.NUM_MI [get_bd_cells /axi_cpu_interconnect]]`"
puts $fh "- AXI-Lite address segment: `$addr_seg`"
if {[llength $addr_seg] > 0} {
    puts $fh "- AXI-Lite offset: `[get_property offset $addr_seg]`"
    puts $fh "- AXI-Lite range: `[get_property range $addr_seg]`"
}
puts $fh ""
puts $fh "## Connections"
puts $fh ""
puts $fh "- `adc_clk` <- `/axi_ad9361/l_clk`"
puts $fh "- `adc_rst` <- `/axi_ad9361/rst`"
puts $fh "- `adc_i` <- `/axi_ad9361/adc_data_i0`"
puts $fh "- `adc_q` <- `/axi_ad9361/adc_data_q0`"
puts $fh "- `adc_i1` <- `/axi_ad9361/adc_data_i1`"
puts $fh "- `adc_q1` <- `/axi_ad9361/adc_data_q1`"
puts $fh "- `adc_valid` <- `/axi_ad9361/adc_valid_i0`"
puts $fh "- `adc_valid1` <- `/axi_ad9361/adc_valid_i1`"
puts $fh "- `s_axi` <- `/axi_cpu_interconnect/M10_AXI`"
puts $fh "- `s_axi_aclk` <- `/sys_ps7/FCLK_CLK0`"
puts $fh "- `s_axi_aresetn` <- `/sys_rstgen/peripheral_aresetn`"
puts $fh "- `irq` -> `/sys_concat_intc/In0`"
puts $fh ""
puts $fh "No implementation, bitstream, or BOOT.bin was generated by this script."
close $fh

puts "AD9361_TAP_INTEGRATION_REPORT=$report_file"
puts "VALIDATE_BD_DESIGN=$validate_status"
close_project
