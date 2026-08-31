set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set proj_dir [file join $repo_dir vendor_experiments PZ_PZP201_PRO_NO_OS_ACCEL]
set xpr [file join $proj_dir PZ_PZP201_PRO_NO_OS.xpr]
set bd [file join $proj_dir PZ_PZP201_PRO_NO_OS.srcs sources_1 bd system system.bd]
set vendor_library [file join $proj_dir library]
set local_ip_repo [file join $repo_dir vivado ip_repo]
set reports_dir [file join $repo_dir reports stage_v10s5_combined_selftest_integration]
set report_file [file join $reports_dir integration_report.md]
set validate_file [file join $reports_dir validate_bd_design.txt]
file mkdir $reports_dir

set rtl_files [list \
    [file join $repo_dir experiments v10s0_submodule_selftest rtl p201_v10_fft_bin_power.v] \
    [file join $repo_dir experiments v10s0_submodule_selftest rtl p201_v10_fft_summary_reducer.v] \
    [file join $repo_dir experiments v10s0_submodule_selftest rtl p201_v10_fft_stream_summary_top.v] \
    [file join $repo_dir experiments v10s0_submodule_selftest rtl p201_fft_frame_packer.v] \
    [file join $repo_dir experiments v10s0_submodule_selftest rtl p201_bandpower_reducer.v] \
    [file join $repo_dir experiments v10s0_submodule_selftest rtl p201_v10_multilag_corr_module.v] \
    [file join $repo_dir experiments v10s0_submodule_selftest rtl p201_v10s0_submodule_selftest_axi_regs.v] \
    [file join $repo_dir experiments v10s1_quality_stats rtl p201_sdr_quality_stats.v] \
    [file join $repo_dir experiments v10s2_frame_window rtl p201_v10s2_hann8_coeff.v] \
    [file join $repo_dir experiments v10s2_frame_window rtl p201_v10s2_frame_window.v] \
    [file join $repo_dir experiments v10s3_energy_peak rtl p201_v10s3_energy_peak_reducer.v] \
    [file join $repo_dir experiments v10s4_nonfft_selftest rtl p201_v10s4_nonfft_selftest_axi_regs.v] \
    [file join $repo_dir experiments v10s5_combined_selftest rtl p201_v10s5_combined_selftest_axi_regs.v] \
]

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

foreach old_cell {p201_v10s0_selftest0 p201_v10s4_selftest0 p201_v10s5_selftest0} {
    if {[llength [get_bd_cells -quiet /$old_cell]] > 0} {
        delete_bd_objs [get_bd_cells /$old_cell]
    }
}

set cell_name p201_v10s5_selftest0
create_bd_cell -type ip -vlnv p201pro.local:user:p201_v10s5_combined_selftest_axi_regs:1.0 $cell_name

set direct_rtl_files [list]
set ip_component [file join $local_ip_repo p201_v10s5_combined_selftest_axi_regs_1.0 component.xml]
set ip_src_dir [file join [file dirname $ip_component] src]
set component_text ""
if {[file exists $ip_component]} {
    set component_fh [open $ip_component r]
    set component_text [read $component_fh]
    close $component_fh
}
foreach f $rtl_files {
    set src_name [file tail $f]
    set listed_in_ip [expr {[string first "src/$src_name" $component_text] >= 0}]
    if {![file exists [file join $ip_src_dir $src_name]] || !$listed_in_ip} {
        lappend direct_rtl_files $f
    }
}
foreach f $direct_rtl_files {
    if {[llength [get_files -quiet $f]] == 0} {
        add_files -norecurse $f
    }
}
if {[llength $direct_rtl_files] > 0} {
    update_compile_order -fileset sources_1
}

set old_num_mi [get_property CONFIG.NUM_MI [get_bd_cells /axi_cpu_interconnect]]
if {$old_num_mi < 12} {
    set_property CONFIG.NUM_MI 12 [get_bd_cells /axi_cpu_interconnect]
}

connect_bd_intf_net_if_needed [get_bd_intf_pins /axi_cpu_interconnect/M11_AXI] [get_bd_intf_pins /$cell_name/s_axi]
connect_bd_net_if_needed [get_bd_pins /sys_ps7/FCLK_CLK0] [get_bd_pins /$cell_name/s_axi_aclk]
connect_bd_net_if_needed [get_bd_pins /sys_rstgen/peripheral_aresetn] [get_bd_pins /$cell_name/s_axi_aresetn]
connect_bd_net_if_needed [get_bd_pins /sys_ps7/FCLK_CLK0] [get_bd_pins /axi_cpu_interconnect/M11_ACLK]
connect_bd_net_if_needed [get_bd_pins /sys_rstgen/peripheral_aresetn] [get_bd_pins /axi_cpu_interconnect/M11_ARESETN]

set irq_connect_status "POLL_ONLY_GND_IN1"
if {[llength [get_bd_pins -quiet /sys_concat_intc/In1]] > 0} {
    set in1_net [get_bd_nets -quiet -of_objects [get_bd_pins /sys_concat_intc/In1]]
    if {[llength $in1_net] > 0} {
        disconnect_bd_net $in1_net [get_bd_pins /sys_concat_intc/In1]
    }
    if {[llength [get_bd_pins -quiet /GND_1/dout]] > 0} {
        connect_bd_net [get_bd_pins /GND_1/dout] [get_bd_pins /sys_concat_intc/In1]
    } else {
        set irq_connect_status "POLL_ONLY_IN1_LEFT_OPEN"
    }
}
foreach orphan_net [get_bd_nets -quiet p201_v10s5_selftest0_irq*] {
    if {[llength [get_bd_pins -quiet -of_objects $orphan_net]] == 0} {
        delete_bd_objs $orphan_net
    }
}

assign_bd_address
set addr_seg [get_bd_addr_segs -quiet /sys_ps7/Data/SEG_${cell_name}_reg0]
if {[llength $addr_seg] > 0} {
    set_property range 0x00010000 $addr_seg
    set_property offset 0x43C30000 $addr_seg
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
puts $fh "# V10S5 Combined Self-Test BD Integration Report"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "- Project copy: `$proj_dir`"
puts $fh "- Added cell: `/$cell_name`"
puts $fh "- IP VLNV: `p201pro.local:user:p201_v10s5_combined_selftest_axi_regs:1.0`"
puts $fh "- Base route: V8D0/V8L1-style AD9361 tap remains at `0x43C00000`"
puts $fh "- V10S5 self-test page target: `0x43C30000`"
puts $fh "- validate_bd_design: `$validate_status`"
puts $fh "- IRQ connection: `$irq_connect_status`"
puts $fh "- AXI interconnect NUM_MI before: `$old_num_mi`"
puts $fh "- AXI interconnect NUM_MI after: `[get_property CONFIG.NUM_MI [get_bd_cells /axi_cpu_interconnect]]`"
puts $fh "- AXI-Lite address segment: `$addr_seg`"
puts $fh "- Direct RTL fallback files: `[join $direct_rtl_files {, }]`"
if {[llength $addr_seg] > 0} {
    puts $fh "- AXI-Lite offset: `[get_property offset $addr_seg]`"
    puts $fh "- AXI-Lite range: `[get_property range $addr_seg]`"
}
puts $fh ""
puts $fh "## Connections"
puts $fh ""
puts $fh "- `s_axi` <- `/axi_cpu_interconnect/M11_AXI`"
puts $fh "- `s_axi_aclk` <- `/sys_ps7/FCLK_CLK0`"
puts $fh "- `s_axi_aresetn` <- `/sys_rstgen/peripheral_aresetn`"
puts $fh "- `irq` is intentionally left unconnected; `/sys_concat_intc/In1` is tied to GND when available"
puts $fh ""
puts $fh "No AD9361 sample, valid, clock, or reset net is connected to this self-test IP."
puts $fh "No implementation, bitstream, or BOOT.bin was generated by this script."
close $fh

puts "V10S5_INTEGRATION_REPORT=$report_file"
puts "VALIDATE_BD_DESIGN=$validate_status"
close_project
