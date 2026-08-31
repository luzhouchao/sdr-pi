set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set rtl_dir [file join $repo_dir experiments phase1_fft_shadow_selftest rtl]
set reports_dir [file join $repo_dir reports stage_phase1_fft_shadow_top4_reducer]
set project_dir [file join $repo_dir vivado_out phase1_fft_shadow_top4_reducer_ooc_project]
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
    [file join $rtl_dir p201_fft_shadow_top4_reducer.v] \
]

set project_status PASS
set synth_status SKIPPED
set timing_status SKIPPED
set run_status SKIPPED
set synth_progress SKIPPED
set setup_wns NA
set hold_whs NA
set error_text ""

foreach f $rtl_files {
    if {![file exists $f]} {
        set project_status FAILED
        append error_text "Missing RTL file: $f\n"
    }
}

if {$project_status eq "PASS"} {
    if {[catch {
        create_project -force phase1_fft_shadow_top4_reducer_ooc $project_dir -part xc7z020clg400-2
        foreach f $rtl_files {
            add_files -norecurse $f
        }
        set_property top p201_fft_shadow_top4_reducer [current_fileset]
        update_compile_order -fileset sources_1
        set fh [open $xdc_file w]
        puts $fh "create_clock -period 8.138 -name clk \[get_ports clk\]"
        close $fh
        add_files -fileset constrs_1 $xdc_file
        launch_runs synth_1 -jobs 4
        wait_on_run synth_1
        set run_status [get_property STATUS [get_runs synth_1]]
        set synth_progress [get_property PROGRESS [get_runs synth_1]]
        if {[string match "*Complete*" $run_status]} {
            set synth_status PASS
            open_run synth_1 -name phase1_fft_shadow_top4_ooc_synth
            report_utilization -file $util_file
            report_timing_summary -file $timing_file
            set timing_status PASS
            set fh [open $timing_file r]
            set timing_text [read $fh]
            close $fh
            if {![regexp {Setup[ ]+:[ ]+[0-9]+[ ]+Failing Endpoints,[ ]+Worst Slack[ ]+([-0-9.]+)ns} $timing_text -> setup_wns]} {
                set timing_status FAILED
                append error_text "Could not parse setup WNS from timing report\n"
            }
            if {![regexp {Hold[ ]+:[ ]+[0-9]+[ ]+Failing Endpoints,[ ]+Worst Slack[ ]+([-0-9.]+)ns} $timing_text -> hold_whs]} {
                set timing_status FAILED
                append error_text "Could not parse hold WHS from timing report\n"
            }
            if {$timing_status eq "PASS"} {
                if {[expr {$setup_wns < 0.0}] || [expr {$hold_whs < 0.0}]} {
                    set timing_status FAILED
                    append error_text "Timing failed: setup WNS=$setup_wns ns, hold WHS=$hold_whs ns\n"
                }
            }
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
puts $fh "# Phase 1 FFT Shadow Top4 Reducer OOC Report"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "- Project setup: `$project_status`"
puts $fh "- Synthesis: `$synth_status`"
puts $fh "- Timing: `$timing_status`"
puts $fh "- Setup WNS: `$setup_wns ns`"
puts $fh "- Hold WHS: `$hold_whs ns`"
puts $fh "- Run status: `$run_status`"
puts $fh "- Run progress: `$synth_progress`"
puts $fh "- Top: `p201_fft_shadow_top4_reducer`"
puts $fh "- Clock target: `8.138 ns`"
puts $fh "- Utilization report: `$util_file`"
puts $fh "- Timing report: `$timing_file`"
puts $fh "- Scope: PC-only signed PSD top-4 reducer primitive with guard-bin suppression; no live AD9361 coupling."
puts $fh ""
puts $fh "No IP package, BD integration, bitstream, BOOT.bin, SD payload, SDR staging, or hardware validation is produced by this script."
if {$project_status ne "PASS" || $synth_status ne "PASS" || $timing_status ne "PASS"} {
    puts $fh ""
    puts $fh "## Error"
    puts $fh ""
    puts $fh "```text"
    puts $fh $error_text
    puts $fh "```"
}
close $fh

puts "PHASE1_FFT_SHADOW_TOP4_OOC_REPORT=$report_file"
puts "PHASE1_FFT_SHADOW_TOP4_OOC_PROJECT_STATUS=$project_status"
puts "PHASE1_FFT_SHADOW_TOP4_OOC_SYNTH_STATUS=$synth_status"
puts "PHASE1_FFT_SHADOW_TOP4_OOC_TIMING_STATUS=$timing_status"

if {[llength [get_projects -quiet]] > 0} {
    close_project
}

if {$project_status ne "PASS" || $synth_status ne "PASS" || $timing_status ne "PASS"} {
    error "Phase 1 FFT shadow top4 reducer OOC failed: $error_text"
}
