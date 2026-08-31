set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set exp_dir [file join $repo_dir experiments phase1_fft_shadow_selftest]
set rtl_dir [file join $exp_dir rtl]
set test_dir [file join $exp_dir test]
set reports_dir [file join $repo_dir reports stage_phase1_fft_shadow_selftest]
set sim_dir [file join $repo_dir vivado_out phase1_fft_shadow_selftest_xsim]
set report_file [file join $reports_dir xsim_report.md]
set sim_log [file join $reports_dir xsim.log]
set vivado_bin {E:/Xilinx/Vivado/2019.1/bin}
set xvlog_exe [file join $vivado_bin xvlog.bat]
set xelab_exe [file join $vivado_bin xelab.bat]
set xsim_exe [file join $vivado_bin xsim.bat]

file mkdir $reports_dir
file mkdir $sim_dir

set files [list \
    [file join $rtl_dir p201_fft_shadow_selftest_axi_regs.v] \
    [file join $rtl_dir p201_fft_shadow_top4_reducer.v] \
    [file join $rtl_dir p201_fft_shadow_coarse96_reducer.v] \
    [file join $rtl_dir p201_fft_shadow_fft4_smoke_core.v] \
    [file join $test_dir tb_p201_fft_shadow_selftest_axi_regs.v] \
    [file join $test_dir tb_p201_fft_shadow_top4_reducer.v] \
    [file join $test_dir tb_p201_fft_shadow_coarse96_reducer.v] \
    [file join $test_dir tb_p201_fft_shadow_fft4_smoke_core.v] \
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
        exec cmd /c $xelab_exe tb_p201_fft_shadow_selftest_axi_regs \
            -s tb_p201_fft_shadow_selftest_axi_regs_sim
        exec cmd /c $xsim_exe tb_p201_fft_shadow_selftest_axi_regs_sim \
            -runall -log $sim_log
        exec cmd /c $xelab_exe tb_p201_fft_shadow_top4_reducer \
            -s tb_p201_fft_shadow_top4_reducer_sim
        exec cmd /c $xsim_exe tb_p201_fft_shadow_top4_reducer_sim \
            -runall -log [file join $reports_dir xsim_top4.log]
        exec cmd /c $xelab_exe tb_p201_fft_shadow_coarse96_reducer \
            -s tb_p201_fft_shadow_coarse96_reducer_sim
        exec cmd /c $xsim_exe tb_p201_fft_shadow_coarse96_reducer_sim \
            -runall -log [file join $reports_dir xsim_coarse96.log]
        exec cmd /c $xelab_exe tb_p201_fft_shadow_fft4_smoke_core \
            -s tb_p201_fft_shadow_fft4_smoke_core_sim
        exec cmd /c $xsim_exe tb_p201_fft_shadow_fft4_smoke_core_sim \
            -runall -log [file join $reports_dir xsim_fft4_smoke.log]
    } err]} {
        set status FAILED
        set error_text $err
    }
}

if {$status eq "PASS"} {
    set fh [open $sim_log r]
    set log_text [read $fh]
    close $fh
    if {[string first "TB_PASS p201_fft_shadow_selftest_axi_regs" $log_text] < 0} {
        set status FAILED
        set error_text "TB_PASS marker not found"
    }
    set top4_log [file join $reports_dir xsim_top4.log]
    if {$status eq "PASS"} {
        set fh [open $top4_log r]
        set top4_text [read $fh]
        close $fh
        if {[string first "TB_PASS p201_fft_shadow_top4_reducer" $top4_text] < 0} {
            set status FAILED
            set error_text "TB_PASS marker not found for top4 reducer"
        }
    }
    set coarse96_log [file join $reports_dir xsim_coarse96.log]
    if {$status eq "PASS"} {
        set fh [open $coarse96_log r]
        set coarse96_text [read $fh]
        close $fh
        if {[string first "TB_PASS p201_fft_shadow_coarse96_reducer" $coarse96_text] < 0} {
            set status FAILED
            set error_text "TB_PASS marker not found for coarse96 reducer"
        }
    }
    set fft4_log [file join $reports_dir xsim_fft4_smoke.log]
    if {$status eq "PASS"} {
        set fh [open $fft4_log r]
        set fft4_text [read $fh]
        close $fh
        if {[string first "TB_PASS p201_fft_shadow_fft4_smoke_core" $fft4_text] < 0} {
            set status FAILED
            set error_text "TB_PASS marker not found for FFT4 smoke core"
        }
    }
}

cd $old_dir

set fh [open $report_file w]
puts $fh "# Phase 1 FFT Shadow Self-Test XSIM Report"
puts $fh ""
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "- XSIM: `$status`"
puts $fh "- Testbench: `tb_p201_fft_shadow_selftest_axi_regs`"
puts $fh "- Testbench: `tb_p201_fft_shadow_top4_reducer`"
puts $fh "- Testbench: `tb_p201_fft_shadow_coarse96_reducer`"
puts $fh "- Testbench: `tb_p201_fft_shadow_fft4_smoke_core`"
puts $fh "- Simulation log: `$sim_log`"
puts $fh "- Top4 simulation log: `[file join $reports_dir xsim_top4.log]`"
puts $fh "- Coarse96 simulation log: `[file join $reports_dir xsim_coarse96.log]`"
puts $fh "- FFT4 smoke simulation log: `[file join $reports_dir xsim_fft4_smoke.log]`"
puts $fh "- Scope: PC-only isolated register ABI fixture for `fpga_fft_shadow` offsets `0x400..0x6fc`."
puts $fh "- Fixture: P1.2 synthetic multi-tone summary, four top peaks, and 96 populated coarse PSD bins."
puts $fh "- Primitive: signed top-4 PSD peak reducer with guard-bin suppression."
puts $fh "- Primitive: exact 2048-to-96 coarse PSD max-hold reducer."
puts $fh "- Primitive: 4-point complex FFT smoke core with power and peak summary."
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

puts "PHASE1_FFT_SHADOW_XSIM_REPORT=$report_file"
puts "PHASE1_FFT_SHADOW_XSIM_STATUS=$status"

if {$status ne "PASS"} {
    error "Phase 1 FFT shadow self-test XSIM failed: $error_text"
}
