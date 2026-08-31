set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set reports_dir [file join $repo_dir reports stage_v10s4_nonfft_selftest]
set project_dir [file join $repo_dir vivado_out v10s4_nonfft_selftest_ooc_project]
set report_file [file join $reports_dir ooc_report.md]
set util_file [file join $reports_dir ooc_utilization.txt]
set timing_file [file join $reports_dir ooc_timing_summary.txt]
set xdc_file [file join $reports_dir ooc_clock.xdc]

file mkdir $reports_dir
file mkdir [file dirname $project_dir]
if {[file exists $project_dir]} {
    file delete -force $project_dir
}

set rtl_files [list \
    [file join $repo_dir experiments v10s1_quality_stats rtl p201_sdr_quality_stats.v] \
    [file join $repo_dir experiments v10s2_frame_window rtl p201_v10s2_hann8_coeff.v] \
    [file join $repo_dir experiments v10s2_frame_window rtl p201_v10s2_frame_window.v] \
    [file join $repo_dir experiments v10s3_energy_peak rtl p201_v10s3_energy_peak_reducer.v] \
    [file join $repo_dir experiments v10s4_nonfft_selftest rtl p201_v10s4_nonfft_selftest_axi_regs.v] \
]

set project_status PASS
set synth_status SKIPPED
set run_status SKIPPED
set synth_progress SKIPPED
set error_text ""

foreach f $rtl_files {
    if {![file exists $f]} {
        set project_status FAILED
        append error_text "Missing RTL file: $f\n"
    }
}

if {$project_status eq "PASS"} {
    if {[catch {
        create_project -force p201_v10s4_nonfft_selftest_ooc $project_dir -part xc7z020clg400-2
        foreach f $rtl_files {
            add_files -norecurse $f
        }
        set_property top p201_v10s4_nonfft_selftest_axi_regs [current_fileset]
        update_compile_order -fileset sources_1
        set fh [open $xdc_file w]
        puts $fh "create_clock -period 8.138 -name s_axi_aclk \[get_ports s_axi_aclk\]"
        close $fh
        add_files -fileset constrs_1 $xdc_file
        launch_runs synth_1 -jobs 4
        wait_on_run synth_1
        set run_status [get_property STATUS [get_runs synth_1]]
        set synth_progress [get_property PROGRESS [get_runs synth_1]]
        if {[string match "*Complete*" $run_status]} {
            set synth_status PASS
            open_run synth_1 -name v10s4_ooc_synth
            report_utilization -file $util_file
            report_timing_summary -file $timing_file
        } else {
            set synth_status FAILED
        }
    } err]} {
        set project_status FAILED
        set synth_status FAILED
        set error_text $err
    }
}

set fh [open $report_file w]
puts $fh "# V10S4 Non-FFT Self-Test OOC Report"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "- Project setup: `$project_status`"
puts $fh "- Synthesis: `$synth_status`"
puts $fh "- Run status: `$run_status`"
puts $fh "- Run progress: `$synth_progress`"
puts $fh "- Top: `p201_v10s4_nonfft_selftest_axi_regs`"
puts $fh "- Clock target: `8.138 ns`"
puts $fh "- Utilization report: `$util_file`"
puts $fh "- Timing report: `$timing_file`"
puts $fh "- Scope: isolated AXI-Lite self-test wrapper for V10S1/S2/S3 non-FFT modules."
puts $fh ""
puts $fh "No IP package, BD integration, bitstream, BOOT.bin, SD payload, SDR staging, or hardware validation is produced by this script."
if {$project_status ne "PASS" || $synth_status ne "PASS"} {
    puts $fh ""
    puts $fh "## Error"
    puts $fh ""
    puts $fh "```text"
    puts $fh $error_text
    puts $fh "```"
}
close $fh

puts "V10S4_OOC_REPORT=$report_file"
puts "V10S4_OOC_PROJECT_STATUS=$project_status"
puts "V10S4_OOC_SYNTH_STATUS=$synth_status"

if {[llength [get_projects -quiet]] > 0} {
    close_project
}

if {$project_status ne "PASS" || $synth_status ne "PASS"} {
    error "V10S4 OOC failed: $error_text"
}
