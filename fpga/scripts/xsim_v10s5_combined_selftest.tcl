set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set v10s0_rtl_dir [file join $repo_dir experiments v10s0_submodule_selftest rtl]
set v10s4_rtl_dir [file join $repo_dir experiments v10s4_nonfft_selftest rtl]
set v10s5_exp_dir [file join $repo_dir experiments v10s5_combined_selftest]
set v10s5_rtl_dir [file join $v10s5_exp_dir rtl]
set v10s5_test_dir [file join $v10s5_exp_dir test]
set reports_dir [file join $repo_dir reports stage_v10s5_combined_selftest]
set sim_dir [file join $repo_dir vivado_out v10s5_combined_selftest_xsim]
set report_file [file join $reports_dir xsim_report.md]
set sim_log [file join $reports_dir xsim.log]
set vivado_bin {E:/Xilinx/Vivado/2019.1/bin}
set xvlog_exe [file join $vivado_bin xvlog.bat]
set xelab_exe [file join $vivado_bin xelab.bat]
set xsim_exe [file join $vivado_bin xsim.bat]

file mkdir $reports_dir
file mkdir $sim_dir

set files [list \
    [file join $v10s0_rtl_dir p201_v10_fft_bin_power.v] \
    [file join $v10s0_rtl_dir p201_v10_fft_summary_reducer.v] \
    [file join $v10s0_rtl_dir p201_v10_fft_stream_summary_top.v] \
    [file join $v10s0_rtl_dir p201_fft_frame_packer.v] \
    [file join $v10s0_rtl_dir p201_bandpower_reducer.v] \
    [file join $v10s0_rtl_dir p201_v10_multilag_corr_module.v] \
    [file join $v10s0_rtl_dir p201_v10s0_submodule_selftest_axi_regs.v] \
    [file join $repo_dir experiments v10s1_quality_stats rtl p201_sdr_quality_stats.v] \
    [file join $repo_dir experiments v10s2_frame_window rtl p201_v10s2_hann8_coeff.v] \
    [file join $repo_dir experiments v10s2_frame_window rtl p201_v10s2_frame_window.v] \
    [file join $repo_dir experiments v10s3_energy_peak rtl p201_v10s3_energy_peak_reducer.v] \
    [file join $v10s4_rtl_dir p201_v10s4_nonfft_selftest_axi_regs.v] \
    [file join $v10s5_rtl_dir p201_v10s5_combined_selftest_axi_regs.v] \
    [file join $v10s5_test_dir tb_p201_v10s5_combined_selftest_axi_regs.v] \
]

set status PASS
set error_text ""

set old_dir [pwd]
cd $sim_dir

foreach f $files {
    if {![file exists $f]} {
        set status FAILED
        append error_text "Missing file: $f\n"
    }
}

if {$status eq "PASS"} {
    if {[catch {
        exec cmd /c $xvlog_exe -sv {*}$files
        exec cmd /c $xelab_exe tb_p201_v10s5_combined_selftest_axi_regs \
            -s tb_p201_v10s5_combined_selftest_axi_regs_sim
        exec cmd /c $xsim_exe tb_p201_v10s5_combined_selftest_axi_regs_sim \
            -runall -log $sim_log
    } err]} {
        set status FAILED
        set error_text $err
    }
}

if {$status eq "PASS"} {
    set fh [open $sim_log r]
    set log_text [read $fh]
    close $fh
    if {[string first "TB_PASS p201_v10s5_combined_selftest_axi_regs" $log_text] < 0} {
        set status FAILED
        set error_text "TB_PASS marker not found"
    }
}

cd $old_dir

set fh [open $report_file w]
puts $fh "# V10S5 Combined Self-Test XSIM Report"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "- XSIM: `$status`"
puts $fh "- Testbench: `tb_p201_v10s5_combined_selftest_axi_regs`"
puts $fh "- Simulation log: `$sim_log`"
puts $fh "- Scope: deterministic AXI start/readback self-test mirroring the planned V10S0 FFT-family and V10S4 non-FFT lanes."
puts $fh "- Note: the combined wrapper defaults to internal deterministic mirrors; external sidecar-core integration still needs a separate interface review."
puts $fh "- Intended isolated AXI-Lite address: `0x43C30000`"
puts $fh ""
puts $fh "No IP package, BD integration, bitstream, BOOT.bin, SD payload, SDR staging, or hardware validation is produced by this script."
if {$status ne "PASS"} {
    puts $fh ""
    puts $fh "## Error"
    puts $fh ""
    puts $fh "```text"
    puts $fh $error_text
    puts $fh "```"
}
close $fh

puts "V10S5_XSIM_REPORT=$report_file"
puts "V10S5_XSIM_STATUS=$status"

if {$status ne "PASS"} {
    error "V10S5 XSIM failed: $error_text"
}
