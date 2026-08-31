set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set proj_dir [file join $repo_dir vendor_experiments PZ_PZP201_PRO_NO_OS]
set xpr [file join $proj_dir PZ_PZP201_PRO_NO_OS.xpr]
set bd [file join $proj_dir PZ_PZP201_PRO_NO_OS.srcs sources_1 bd system system.bd]
set vendor_library [file join $proj_dir library]
set local_ip_repo [file join $repo_dir vivado ip_repo]
set reports_dir [file join $repo_dir reports stage4_vendor_project_probe]
set report_file [file join $reports_dir vendor_bd_integration_slots.md]
file mkdir $reports_dir

open_project $xpr
set_property ip_repo_paths [list $vendor_library $local_ip_repo] [current_project]
update_ip_catalog
open_bd_design $bd

set fh [open $report_file w]
puts $fh "# Vendor BD Integration Slots"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""

puts $fh "## Interconnect Config"
puts $fh ""
foreach prop {CONFIG.NUM_MI CONFIG.NUM_SI CONFIG.STRATEGY CONFIG.S00_HAS_REGSLICE CONFIG.M00_HAS_REGSLICE} {
    set value "<missing>"
    if {![catch {set value [get_property $prop [get_bd_cells /axi_cpu_interconnect]]}]} {
        puts $fh "- `$prop` = `$value`"
    }
}

puts $fh ""
puts $fh "## AXI Interface Net Endpoints"
puts $fh ""
foreach net [lsort [get_bd_intf_nets -quiet /axi_cpu_interconnect_*]] {
    set pins [get_bd_intf_pins -quiet -of_objects $net]
    puts $fh "- `$net`"
    foreach p [lsort $pins] {
        puts $fh "  - `$p` mode=`[get_property MODE $p]`"
    }
}

puts $fh ""
puts $fh "## Candidate AXI Clocks And Resets"
puts $fh ""
foreach p [lsort [get_bd_pins -quiet -hierarchical -filter {NAME =~ *aclk || NAME =~ *ACLK || NAME =~ *aresetn || NAME =~ *ARESETN || NAME =~ *peripheral_aresetn || NAME =~ *interconnect_aresetn}]] {
    set net [get_bd_nets -quiet -of_objects $p]
    if {[llength $net] == 0} { set net "<unconnected>" }
    puts $fh "- `$p` dir=`[get_property DIR $p]` type=`[get_property TYPE $p]` net=`$net`"
}

close $fh
puts "VENDOR_BD_INTEGRATION_SLOTS=$report_file"
close_project
