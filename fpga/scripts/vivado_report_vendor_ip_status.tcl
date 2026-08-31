set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set proj_dir [file join $repo_dir vendor_experiments PZ_PZP201_PRO_NO_OS]
set xpr [file join $proj_dir PZ_PZP201_PRO_NO_OS.xpr]
set bd [file join $proj_dir PZ_PZP201_PRO_NO_OS.srcs sources_1 bd system system.bd]
set vendor_library [file join $proj_dir library]
set local_ip_repo [file join $repo_dir vivado ip_repo]
set reports_dir [file join $repo_dir reports stage4_vendor_project_probe]
file mkdir $reports_dir

open_project $xpr
set_property ip_repo_paths [list $vendor_library $local_ip_repo] [current_project]
update_ip_catalog

if {[file exists $bd]} {
    open_bd_design $bd
}

set status_report [file join $reports_dir vendor_report_ip_status.txt]
set bd_report [file join $reports_dir vendor_validate_bd_design.txt]
set summary_report [file join $reports_dir vendor_ip_status_summary.md]

report_ip_status -file $status_report

set validate_status "NOT_RUN"
set validate_text ""
if {[catch {validate_bd_design} validate_text]} {
    set validate_status "FAILED"
} else {
    set validate_status "PASS"
}
set fh [open $bd_report w]
puts $fh $validate_text
close $fh

set locked_ips [get_ips -quiet -filter {IS_LOCKED == 1}]
set upgrade_ips [get_ips -quiet -filter {UPGRADE_VERSIONS != ""}]

set fh [open $summary_report w]
puts $fh "# Vendor IP Status Summary"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "- Project: `$xpr`"
puts $fh "- Vendor IP repo: `$vendor_library`"
puts $fh "- Local P201Pro IP repo: `$local_ip_repo`"
puts $fh "- validate_bd_design: `$validate_status`"
puts $fh "- Locked IP count: [llength $locked_ips]"
puts $fh "- Upgrade candidate count: [llength $upgrade_ips]"
puts $fh ""
puts $fh "## Locked IPs"
puts $fh ""
foreach ip [lsort $locked_ips] {
    puts $fh "- `$ip` VLNV=`[get_property IPDEF $ip]`"
}
puts $fh ""
puts $fh "## Upgrade Candidates"
puts $fh ""
foreach ip [lsort $upgrade_ips] {
    puts $fh "- `$ip` upgrade_versions=`[get_property UPGRADE_VERSIONS $ip]`"
}
puts $fh ""
puts $fh "## Report Files"
puts $fh ""
puts $fh "- IP status: `$status_report`"
puts $fh "- BD validation: `$bd_report`"
close $fh

puts "VENDOR_IP_STATUS_SUMMARY=$summary_report"
puts "LOCKED_IP_COUNT=[llength $locked_ips]"
puts "UPGRADE_IP_COUNT=[llength $upgrade_ips]"
puts "VALIDATE_BD_DESIGN=$validate_status"
close_project
