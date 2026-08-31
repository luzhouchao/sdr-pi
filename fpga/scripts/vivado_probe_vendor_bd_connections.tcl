set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set proj_dir [file join $repo_dir vendor_experiments PZ_PZP201_PRO_NO_OS]
set xpr [file join $proj_dir PZ_PZP201_PRO_NO_OS.xpr]
set bd [file join $proj_dir PZ_PZP201_PRO_NO_OS.srcs sources_1 bd system system.bd]
set vendor_library [file join $proj_dir library]
set local_ip_repo [file join $repo_dir vivado ip_repo]
set reports_dir [file join $repo_dir reports stage4_vendor_project_probe]
set report_file [file join $reports_dir vendor_bd_connection_probe.md]
file mkdir $reports_dir

open_project $xpr
set_property ip_repo_paths [list $vendor_library $local_ip_repo] [current_project]
update_ip_catalog
open_bd_design $bd

proc pin_net_name {pin_name} {
    set p [get_bd_pins -quiet $pin_name]
    if {[llength $p] == 0} {
        return "<missing-pin>"
    }
    set n [get_bd_nets -quiet -of_objects $p]
    if {[llength $n] == 0} {
        return "<unconnected>"
    }
    return $n
}

set fh [open $report_file w]
puts $fh "# Vendor BD Connection Probe"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "## Key AD9361 Pins"
puts $fh ""
foreach p {
    /axi_ad9361/l_clk
    /axi_ad9361/rst
    /axi_ad9361/adc_data_i0
    /axi_ad9361/adc_data_q0
    /axi_ad9361/adc_data_i1
    /axi_ad9361/adc_data_q1
    /axi_ad9361/adc_valid_i0
    /axi_ad9361/adc_valid_q0
    /axi_ad9361/adc_valid_i1
    /axi_ad9361/adc_valid_q1
    /util_ad9361_adc_fifo/din_data_0
    /util_ad9361_adc_fifo/din_data_1
    /util_ad9361_adc_fifo/din_data_2
    /util_ad9361_adc_fifo/din_data_3
    /util_ad9361_adc_fifo/din_valid_0
    /util_ad9361_adc_fifo/dout_data_0
    /util_ad9361_adc_fifo/dout_data_1
    /util_ad9361_adc_pack/fifo_wr_data_0
    /util_ad9361_adc_pack/fifo_wr_data_1
    /util_ad9361_adc_pack/packed_fifo_wr_data
    /axi_ad9361_adc_dma/fifo_wr_clk
    /axi_ad9361_adc_dma/fifo_wr_data
    /axi_ad9361_adc_dma/fifo_wr_en
} {
    set pin [get_bd_pins -quiet $p]
    if {[llength $pin] > 0} {
        puts $fh "- `$p` dir=`[get_property DIR $pin]` width=`[get_property LEFT $pin]:[get_property RIGHT $pin]` net=`[pin_net_name $p]`"
    } else {
        puts $fh "- `$p` MISSING"
    }
}

puts $fh ""
puts $fh "## AXI CPU Interconnect Interfaces"
puts $fh ""
foreach intf [lsort [get_bd_intf_pins -quiet /axi_cpu_interconnect/*]] {
    set mode [get_property MODE $intf]
    set vlnv [get_property VLNV $intf]
    set net [get_bd_intf_nets -quiet -of_objects $intf]
    if {[llength $net] == 0} {
        set net "<unconnected>"
    }
    puts $fh "- `$intf` mode=`$mode` vlnv=`$vlnv` net=`$net`"
}

puts $fh ""
puts $fh "## Interrupt Concat Pins"
puts $fh ""
foreach p [lsort [get_bd_pins -quiet /sys_concat_intc/*]] {
    set net [get_bd_nets -quiet -of_objects $p]
    if {[llength $net] == 0} {
        set net "<unconnected>"
    }
    puts $fh "- `$p` dir=`[get_property DIR $p]` net=`$net`"
}

puts $fh ""
puts $fh "## Existing PS Address Segments"
puts $fh ""
foreach s [lsort [get_bd_addr_segs -quiet /sys_ps7/Data/SEG_data_*]] {
    puts $fh "- `$s` range=`[get_property range $s]` offset=`[get_property offset $s]`"
}

close $fh
puts "VENDOR_BD_CONNECTION_PROBE=$report_file"
close_project
