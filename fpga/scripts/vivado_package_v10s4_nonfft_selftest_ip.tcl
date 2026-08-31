set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set vivado_dir [file join $repo_dir vivado]
set reports_dir [file join $repo_dir reports stage_v10s4_nonfft_selftest_ip]
set project_dir [file join $repo_dir vivado_out v10s4_nonfft_selftest_ip_packager_project]
set ip_root [file join $vivado_dir ip_repo p201_v10s4_nonfft_selftest_axi_regs_1.0]
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

set rtl_files [list \
    [file join $repo_dir experiments v10s1_quality_stats rtl p201_sdr_quality_stats.v] \
    [file join $repo_dir experiments v10s2_frame_window rtl p201_v10s2_hann8_coeff.v] \
    [file join $repo_dir experiments v10s2_frame_window rtl p201_v10s2_frame_window.v] \
    [file join $repo_dir experiments v10s3_energy_peak rtl p201_v10s3_energy_peak_reducer.v] \
    [file join $repo_dir experiments v10s4_nonfft_selftest rtl p201_v10s4_nonfft_selftest_axi_regs.v] \
]

create_project -force p201_v10s4_nonfft_selftest_ip $project_dir -part xc7z020clg400-2
foreach f $rtl_files {
    add_files -norecurse $f
}
set_property top p201_v10s4_nonfft_selftest_axi_regs [current_fileset]
update_compile_order -fileset sources_1

ipx::package_project \
    -root_dir $ip_root \
    -vendor p201pro.local \
    -library user \
    -taxonomy /UserIP \
    -import_files

set core [ipx::current_core]
set_property name p201_v10s4_nonfft_selftest_axi_regs $core
set_property display_name {P201Pro V10S4 Non-FFT Self-Test AXI Registers} $core
set_property description {Independent AXI-Lite deterministic self-test page for non-FFT SDR FPGA helper modules.} $core
set_property vendor_display_name {P201Pro SDR Accel} $core
set_property company_url {http://www.p201pro.local} $core
set_property version 1.0 $core
set_property supported_families {zynq Production} $core

foreach f $rtl_files {
    set src_name [file tail $f]
    set dst_file [file join $ip_root src $src_name]
    if {![file exists $dst_file]} {
        file copy -force $f $dst_file
    }
    foreach fg_name {xilinx_anylanguagesynthesis xilinx_anylanguagebehavioralsimulation xilinx_anylanguagesynthesis_view_fileset xilinx_anylanguagebehavioralsimulation_view_fileset} {
        set fg [ipx::get_file_groups $fg_name -of_objects $core]
        if {[llength $fg] > 0} {
            set exists 0
            foreach ip_file_obj [ipx::get_files -of_objects $fg] {
                if {[string equal [get_property name $ip_file_obj] "src/$src_name"]} {
                    set exists 1
                }
            }
            if {!$exists} {
                set new_file [ipx::add_file "src/$src_name" $fg]
                set_property type verilogSource $new_file
            }
        }
    }
}

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

set required_packaged_files [list \
    p201_sdr_quality_stats.v \
    p201_v10s2_hann8_coeff.v \
    p201_v10s2_frame_window.v \
    p201_v10s3_energy_peak_reducer.v \
    p201_v10s4_nonfft_selftest_axi_regs.v \
]

set packaged_file_check PASS
set packaged_file_errors ""
set component_text ""
if {[file exists $ip_file]} {
    set component_fh [open $ip_file r]
    set component_text [read $component_fh]
    close $component_fh
}
foreach src_name $required_packaged_files {
    set dst_file [file join $ip_root src $src_name]
    if {![file exists $dst_file]} {
        set packaged_file_check FAILED
        append packaged_file_errors "Missing packaged IP source: $dst_file\n"
    }
    if {[string first "src/$src_name" $component_text] < 0} {
        set packaged_file_check FAILED
        append packaged_file_errors "Missing component.xml reference: src/$src_name\n"
    }
}
if {$packaged_file_check ne "PASS"} {
    error "V10S4 packaged IP source check failed:\n$packaged_file_errors"
}

set integrity_file [file join $reports_dir ipx_check_integrity.txt]
set report_file [file join $reports_dir v10s4_nonfft_selftest_ip_report.md]

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
create_clock -period 8.138 -name s_axi_aclk [get_ports s_axi_aclk]
report_utilization -file [file join $reports_dir utilization.txt]
report_timing_summary -file [file join $reports_dir timing_summary.txt]
write_checkpoint -force [file join $reports_dir p201_v10s4_nonfft_selftest_synth.dcp]

set fh [open $report_file w]
puts $fh "# V10S4 Non-FFT Self-Test IP Report"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
if {$integrity_ok && [file exists $ip_file]} {
    puts $fh "- IP packaging: PASS"
} else {
    puts $fh "- IP packaging: BLOCKED"
}
puts $fh "- IP root: `$ip_root`"
puts $fh "- Component XML: `$ip_file`"
puts $fh "- Project part: `xc7z020clg400-2`"
puts $fh "- Synthesis status: `$synth_status`"
puts $fh "- Synthesis progress: `$synth_progress`"
puts $fh "- Packaged source check: `$packaged_file_check`"
puts $fh "- Clock: `s_axi_aclk` only; no AD9361 data-path connection"
puts $fh "- Intended BD address: `0x43C20000`"
puts $fh "- Covered reusable RTL: quality stats, frame/window, energy/peak"
puts $fh ""
puts $fh "No bitstream or BOOT.bin is produced by this script."
close $fh

puts "V10S4_IP_REPORT=$report_file"
puts "V10S4_IP_ROOT=$ip_root"
puts "SYNTH_STATUS=$synth_status"
puts "SYNTH_PROGRESS=$synth_progress"
close_project
