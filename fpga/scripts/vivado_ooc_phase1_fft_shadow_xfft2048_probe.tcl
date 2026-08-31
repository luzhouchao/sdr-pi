set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set reports_dir [file join $repo_dir reports stage_phase1_fft_shadow_xfft2048_probe]
set project_dir [file join $repo_dir vivado_out phase1_fft_shadow_xfft2048_probe_ooc_project]
set report_file [file join $reports_dir ooc_report.md]
set property_file [file join $reports_dir xfft_properties.txt]
set config_file [file join $reports_dir xfft_config.txt]
set status_file [file join $reports_dir ip_status.txt]
set util_file [file join $reports_dir ooc_utilization.txt]
set timing_file [file join $reports_dir ooc_timing_summary.txt]

file mkdir $reports_dir
file mkdir [file dirname $project_dir]
if {[file exists $project_dir]} {
    file delete -force $project_dir
}

set module_name p201_phase1_xfft2048_probe
set ip_status SKIPPED
set ip_config_status SKIPPED
set target_status SKIPPED
set ooc_status SKIPPED
set timing_status SKIPPED
set run_status SKIPPED
set run_progress SKIPPED
set setup_wns NA
set hold_whs NA
set error_text ""
set configured_pairs {}
set skipped_pairs {}

proc note_config {key value} {
    global configured_pairs
    lappend configured_pairs "$key=$value"
}

proc note_skipped {key value reason} {
    global skipped_pairs
    lappend skipped_pairs "$key=$value ($reason)"
}

proc set_ip_config_if_present {ip_obj key value} {
    set prop_name "CONFIG.$key"
    set props [list_property $ip_obj]
    if {[lsearch -exact $props $prop_name] >= 0} {
        if {[catch {set_property -dict [list $prop_name $value] $ip_obj} err]} {
            note_skipped $key $value $err
            return 0
        }
        note_config $key $value
        return 1
    }
    note_skipped $key $value "property not present"
    return 0
}

if {[catch {
    create_project -force phase1_fft_shadow_xfft2048_probe_ooc $project_dir -part xc7z020clg400-2
    set ip_status PASS

    create_ip -name xfft -vendor xilinx.com -library ip -module_name $module_name
    set ip_obj [get_ips $module_name]

    set property_fh [open $property_file w]
    foreach p [lsort [list_property $ip_obj]] {
        puts $property_fh $p
    }
    close $property_fh

    set_ip_config_if_present $ip_obj transform_length 2048
    set_ip_config_if_present $ip_obj data_format fixed_point
    set_ip_config_if_present $ip_obj input_width 16
    set_ip_config_if_present $ip_obj phase_factor_width 16
    set_ip_config_if_present $ip_obj scaling_options scaled
    set_ip_config_if_present $ip_obj rounding_modes convergent_rounding
    set_ip_config_if_present $ip_obj implementation_options pipelined_streaming_io
    set_ip_config_if_present $ip_obj run_time_configurable_transform_length false
    set_ip_config_if_present $ip_obj target_clock_frequency 123
    set_ip_config_if_present $ip_obj ACLK_INTF.FREQ_HZ 122880000

    set ip_config_status PASS
    generate_target all [get_files [get_property IP_FILE $ip_obj]]
    create_ip_run [get_files [get_property IP_FILE $ip_obj]]
    set target_status PASS

    set config_fh [open $config_file w]
    puts $config_fh "Configured properties:"
    foreach item $configured_pairs {
        puts $config_fh $item
    }
    puts $config_fh ""
    puts $config_fh "Skipped properties:"
    foreach item $skipped_pairs {
        puts $config_fh $item
    }
    puts $config_fh ""
    puts $config_fh "Final CONFIG properties:"
    foreach p [lsort [list_property $ip_obj]] {
        if {[string match "CONFIG.*" $p]} {
            if {[catch {set val [get_property $p $ip_obj]}]} {
                set val "<unreadable>"
            }
            puts $config_fh "$p=$val"
        }
    }
    close $config_fh

    report_ip_status -file $status_file

    set run_name "${module_name}_synth_1"
    if {[llength [get_runs -quiet $run_name]] == 0} {
        error "Expected IP OOC run not found: $run_name"
    }

    launch_runs $run_name -jobs 4
    wait_on_run $run_name
    set run_status [get_property STATUS [get_runs $run_name]]
    set run_progress [get_property PROGRESS [get_runs $run_name]]
    if {[string match "*Complete*" $run_status]} {
        set ooc_status PASS
        open_run $run_name -name phase1_fft_shadow_xfft2048_probe_ooc_synth
        report_utilization -file $util_file
        report_timing_summary -file $timing_file
        set timing_status PASS
        set timing_fh [open $timing_file r]
        set timing_text [read $timing_fh]
        close $timing_fh
        if {[regexp {Setup[ ]+:[ ]+[0-9]+[ ]+Failing Endpoints,[ ]+Worst Slack[ ]+([-0-9.]+)ns} $timing_text -> parsed_setup_wns]} {
            set setup_wns $parsed_setup_wns
        } else {
            set timing_status WARN
            append error_text "Could not parse setup WNS from timing report\n"
        }
        if {[regexp {Hold[ ]+:[ ]+[0-9]+[ ]+Failing Endpoints,[ ]+Worst Slack[ ]+([-0-9.]+)ns} $timing_text -> parsed_hold_whs]} {
            set hold_whs $parsed_hold_whs
        } else {
            set timing_status WARN
            append error_text "Could not parse hold WHS from timing report\n"
        }
        if {$setup_wns ne "NA" && $hold_whs ne "NA"} {
            if {[expr {$setup_wns < 0.0}] || [expr {$hold_whs < 0.0}]} {
                set timing_status FAILED
                append error_text "Timing failed: setup WNS=$setup_wns ns, hold WHS=$hold_whs ns\n"
            }
        }
    } else {
        set ooc_status FAILED
        append error_text "IP OOC run did not complete: $run_status, progress $run_progress\n"
    }
} err]} {
    append error_text $err
    if {$ip_status eq "SKIPPED"} {
        set ip_status FAILED
    } elseif {$ip_config_status eq "SKIPPED"} {
        set ip_config_status FAILED
    } elseif {$target_status eq "SKIPPED"} {
        set target_status FAILED
    } elseif {$ooc_status eq "SKIPPED"} {
        set ooc_status FAILED
    }
}

set report_fh [open $report_file w]
puts $report_fh "# Phase 1 FFT Shadow XFFT2048 Probe OOC Report"
puts $report_fh ""
puts $report_fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $report_fh ""
puts $report_fh "- Project setup / IP create: `$ip_status`"
puts $report_fh "- IP configuration: `$ip_config_status`"
puts $report_fh "- Target generation / IP OOC run create: `$target_status`"
puts $report_fh "- IP OOC synthesis: `$ooc_status`"
puts $report_fh "- Timing parse: `$timing_status`"
puts $report_fh "- Setup WNS: `$setup_wns ns`"
puts $report_fh "- Hold WHS: `$hold_whs ns`"
puts $report_fh "- Run status: `$run_status`"
puts $report_fh "- Run progress: `$run_progress`"
puts $report_fh "- IP module: `$module_name`"
puts $report_fh "- Part: `xc7z020clg400-2`"
puts $report_fh "- Target shape: Xilinx FFT IP, 2048-point fixed-point spectral primitive probe"
puts $report_fh "- Property list: `$property_file`"
puts $report_fh "- Config report: `$config_file`"
puts $report_fh "- IP status report: `$status_file`"
puts $report_fh "- Utilization report: `$util_file`"
puts $report_fh "- Timing report: `$timing_file`"
puts $report_fh ""
puts $report_fh "This is a PC-only IP/OOC probe entry for P1.4b. It does not instantiate AD9361, does not integrate the live tap, does not generate implementation, does not write a bitstream, does not run Bootgen, does not create a BOOT.bin, does not create an SD payload, does not stage to hardware, and is not hardware validation."
puts $report_fh ""
puts $report_fh "The probe covers the FFT IP creation/OOC entry only. Hann/window application, PSD square-sum/log scaling, top-4 composition, coarse96 composition, live AD9361 coupling, and register-page integration remain separate gates."
if {$error_text ne ""} {
    puts $report_fh ""
    puts $report_fh "## Notes / Errors"
    puts $report_fh ""
    puts $report_fh "```text"
    puts $report_fh $error_text
    puts $report_fh "```"
}
close $report_fh

puts "PHASE1_FFT_SHADOW_XFFT2048_OOC_REPORT=$report_file"
puts "PHASE1_FFT_SHADOW_XFFT2048_IP_STATUS=$ip_status"
puts "PHASE1_FFT_SHADOW_XFFT2048_CONFIG_STATUS=$ip_config_status"
puts "PHASE1_FFT_SHADOW_XFFT2048_TARGET_STATUS=$target_status"
puts "PHASE1_FFT_SHADOW_XFFT2048_OOC_STATUS=$ooc_status"
puts "PHASE1_FFT_SHADOW_XFFT2048_TIMING_STATUS=$timing_status"

if {[llength [get_projects -quiet]] > 0} {
    close_project
}

if {$ip_status ne "PASS" || $ip_config_status ne "PASS" || $target_status ne "PASS" || $ooc_status ne "PASS" || $timing_status eq "FAILED"} {
    error "Phase 1 FFT shadow XFFT2048 probe failed: $error_text"
}
