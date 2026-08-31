set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set rtl_file [file join $repo_dir experiments v8_derived_low_nx_load hdl p201pro_ad9361_power_tap_axi_regs.v]
set reports_dir [file join $repo_dir reports stage_v8_derived_low_nx_load ooc_synth]
set summary_file [file join $reports_dir ooc_summary.md]
set util_file [file join $reports_dir ooc_utilization.txt]
set timing_file [file join $reports_dir ooc_timing_summary.txt]
set cdc_file [file join $reports_dir ooc_cdc.txt]
set check_timing_file [file join $reports_dir ooc_check_timing.txt]
set dcp_file [file join $reports_dir p201_v8_derived_low_nx_load_ooc_synth.dcp]

file mkdir $reports_dir

proc write_file {path text} {
    set fh [open $path w]
    puts $fh $text
    close $fh
}

set synth_status "NOT_RUN"
set report_status "NOT_RUN"
set synth_error ""

read_verilog $rtl_file

if {[catch {
    synth_design -mode out_of_context \
        -top p201pro_ad9361_power_tap_axi_regs \
        -part xc7z020clg400-2 \
        -flatten_hierarchy rebuilt
} synth_error]} {
    set synth_status "FAILED"
} else {
    set synth_status "PASS"
    set synth_error ""
}

if {$synth_status eq "PASS"} {
    if {[llength [get_ports -quiet adc_clk]] > 0} {
        create_clock -period 8.138 -name adc_clk [get_ports adc_clk]
    }
    if {[llength [get_ports -quiet s_axi_aclk]] > 0} {
        create_clock -period 8.138 -name s_axi_aclk [get_ports s_axi_aclk]
    }
    if {[llength [get_clocks -quiet adc_clk]] > 0 && [llength [get_clocks -quiet s_axi_aclk]] > 0} {
        set_clock_groups -asynchronous -group [get_clocks adc_clk] -group [get_clocks s_axi_aclk]
    }

    check_timing -file $check_timing_file
    report_utilization -file $util_file
    report_timing_summary -file $timing_file
    if {[catch {report_cdc -file $cdc_file} cdc_error]} {
        write_file $cdc_file "report_cdc failed: $cdc_error"
    }
    write_checkpoint -force $dcp_file
    set report_status "REPORTS_WRITTEN"
}

set fh [open $summary_file w]
puts $fh "# V8-Derived Low-NX-Load OOC Synthesis"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "## Scope"
puts $fh ""
puts $fh "- PC-side OOC synthesis only."
puts $fh "- NOT BURNABLE."
puts $fh "- NOT HARDWARE VALIDATED."
puts $fh "- No BOOT.bin, no SD payload, no SDR /sd write."
puts $fh ""
puts $fh "## Inputs"
puts $fh ""
puts $fh "- RTL: `$rtl_file`"
puts $fh "- Top: `p201pro_ad9361_power_tap_axi_regs`"
puts $fh "- Part: `xc7z020clg400-2`"
puts $fh "- Clocks: `adc_clk` 8.138 ns, `s_axi_aclk` 8.138 ns, asynchronous groups"
puts $fh ""
puts $fh "## Result"
puts $fh ""
puts $fh "- Synthesis: `$synth_status`"
puts $fh "- Reports: `$report_status`"
if {$synth_error ne ""} {
    puts $fh "- Synthesis error: `$synth_error`"
}
puts $fh ""
puts $fh "## Evidence"
puts $fh ""
puts $fh "- Utilization: `$util_file`"
puts $fh "- Timing summary: `$timing_file`"
puts $fh "- CDC report: `$cdc_file`"
puts $fh "- Check timing: `$check_timing_file`"
puts $fh "- Synth checkpoint: `$dcp_file`"
close $fh

puts "V8_LOW_NX_OOC_SUMMARY=$summary_file"
puts "V8_LOW_NX_OOC_SYNTH_STATUS=$synth_status"
puts "V8_LOW_NX_OOC_REPORT_STATUS=$report_status"

if {$synth_status ne "PASS"} {
    exit 1
}
