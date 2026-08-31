set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set proj_dir [file join $repo_dir vendor_experiments PZ_PZP201_PRO_NO_OS_ACCEL]
set xpr [file join $proj_dir PZ_PZP201_PRO_NO_OS.xpr]
set bd [file join $proj_dir PZ_PZP201_PRO_NO_OS.srcs sources_1 bd system system.bd]
set reports_dir [file join $repo_dir reports stage4_ad9361_tap_integration]
set report_file [file join $reports_dir ad9361_bd_pin_probe.txt]
file mkdir $reports_dir

open_project $xpr
open_bd_design $bd

set fh [open $report_file w]
puts $fh "AD9361 BD pin probe"
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "Pins matching adc_data/adc_valid/l_clk/rst:"
foreach pin [lsort [get_bd_pins -quiet /axi_ad9361/*]] {
    set name [get_property NAME $pin]
    if {[regexp {^(adc_data_|adc_valid|l_clk|rst)} $name]} {
        puts $fh "$pin DIR=[get_property DIR $pin] TYPE=[get_property TYPE $pin]"
    }
}
puts $fh ""
puts $fh "All axi_ad9361 pins:"
foreach pin [lsort [get_bd_pins -quiet /axi_ad9361/*]] {
    puts $fh "$pin DIR=[get_property DIR $pin] TYPE=[get_property TYPE $pin]"
}
close $fh

puts "AD9361_BD_PIN_PROBE=$report_file"
close_project
