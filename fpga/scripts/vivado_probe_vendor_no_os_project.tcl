set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set proj_dir [file join $repo_dir vendor_experiments PZ_PZP201_PRO_NO_OS]
set xpr [file join $proj_dir PZ_PZP201_PRO_NO_OS.xpr]
set bd [file join $proj_dir PZ_PZP201_PRO_NO_OS.srcs sources_1 bd system system.bd]
set vendor_library [file join $proj_dir library]
set ip_repo [file join $repo_dir vivado ip_repo]
set reports_dir [file join $repo_dir reports stage4_vendor_project_probe]
set report_file [file join $reports_dir vendor_no_os_project_probe.md]
file mkdir $reports_dir

open_project $xpr
set merged_ip_repos [list $vendor_library $ip_repo]
set_property ip_repo_paths $merged_ip_repos [current_project]
update_ip_catalog

set fh [open $report_file w]
puts $fh "# Vendor NO-OS Vivado Project Probe"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "## Project"
puts $fh ""
puts $fh "- Copied project: `$proj_dir`"
puts $fh "- XPR: `$xpr`"
puts $fh "- Project part: `[get_property PART [current_project]]`"
puts $fh "- Default target language: `[get_property target_language [current_project]]`"
puts $fh "- Top in sources_1: `[get_property top [get_filesets sources_1]]`"
puts $fh "- IP repos: `$merged_ip_repos`"
puts $fh ""

set packaged_ip [get_ipdefs -all p201pro.local:user:p201pro_stream_power_axi_regs:1.0]
puts $fh "## Local Packaged IP Catalog"
puts $fh ""
if {[llength $packaged_ip] > 0} {
    puts $fh "- P201Pro wrapper IP visible in catalog: YES"
    puts $fh "- VLNV: `$packaged_ip`"
} else {
    puts $fh "- P201Pro wrapper IP visible in catalog: NO"
}
puts $fh ""

if {[file exists $bd]} {
    open_bd_design $bd
    puts $fh "## Block Design Cells"
    puts $fh ""
    foreach c [lsort [get_bd_cells -hierarchical]] {
        set vlnv [get_property VLNV $c]
        puts $fh "- `$c` : `$vlnv`"
    }
    puts $fh ""
    puts $fh "## Candidate AD9361 / DMA / Clock Interfaces"
    puts $fh ""
    foreach p [lsort [get_bd_pins -hierarchical -filter {NAME =~ *adc* || NAME =~ *dac* || NAME =~ *valid* || NAME =~ *data* || NAME =~ *clk* || NAME =~ *rst*}]] {
        set dir [get_property DIR $p]
        set type [get_property TYPE $p]
        puts $fh "- `$p` dir=`$dir` type=`$type`"
    }
    puts $fh ""
    puts $fh "## Address Segments"
    puts $fh ""
    foreach s [lsort [get_bd_addr_segs -hierarchical]] {
        puts $fh "- `$s` range=`[get_property range $s]` offset=`[get_property offset $s]`"
    }
} else {
    puts $fh "## Block Design"
    puts $fh ""
    puts $fh "- `system.bd` not found at expected path."
}

puts $fh ""
puts $fh "## Probe Result"
puts $fh ""
puts $fh "- The copied vendor NO-OS Vivado project opens under Vivado 2019.1."
puts $fh "- The packaged P201Pro wrapper IP is visible to this project if the catalog entry above says YES."
puts $fh "- This script intentionally does not modify the vendor block design or generate a replacement bitstream."
close $fh

puts "VENDOR_PROBE_REPORT=$report_file"
close_project
