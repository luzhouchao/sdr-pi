set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set dcp_path [file join $repo_dir reports stage4_ad9361_tap_bitstream_physopt system_top_with_p201_tap_physopt_impl.dcp]
set out_dir [file join $repo_dir reports v9a_ad9361_interface_diagnostics_20260608]
file mkdir $out_dir

proc run_report {label cmd out_file} {
    puts "RUN_REPORT $label"
    if {[catch {uplevel 1 $cmd} err]} {
        set fh [open $out_file w]
        puts $fh "FAILED: $err"
        close $fh
        puts "RUN_REPORT_FAILED $label $err"
        return 0
    }
    return 1
}

proc cell_count_by_ref {cells out_file} {
    array unset counts
    foreach cell $cells {
        set ref [get_property REF_NAME $cell]
        if {$ref eq ""} {
            set ref "<none>"
        }
        if {![info exists counts($ref)]} {
            set counts($ref) 0
        }
        incr counts($ref)
    }
    set fh [open $out_file w]
    puts $fh "ref_name,count"
    foreach ref [lsort [array names counts]] {
        puts $fh "$ref,$counts($ref)"
    }
    close $fh
}

proc write_ports_csv {ports out_file} {
    set fh [open $out_file w]
    puts $fh "name,direction,package_pin,iostandard,loc,clock_dedicated_route,slew,drive"
    foreach port [lsort -dictionary $ports] {
        foreach prop {DIRECTION PACKAGE_PIN IOSTANDARD LOC CLOCK_DEDICATED_ROUTE SLEW DRIVE} {
            if {[catch {set $prop [get_property $prop $port]}]} {
                set $prop ""
            }
        }
        puts $fh "[get_property NAME $port],$DIRECTION,$PACKAGE_PIN,$IOSTANDARD,$LOC,$CLOCK_DEDICATED_ROUTE,$SLEW,$DRIVE"
    }
    close $fh
}

proc write_cells_csv {cells out_file limit} {
    set fh [open $out_file w]
    puts $fh "name,ref_name,loc,bel"
    set n 0
    foreach cell [lsort -dictionary $cells] {
        if {$n >= $limit} {
            puts $fh "TRUNCATED,$limit,,"
            break
        }
        foreach prop {REF_NAME LOC BEL} {
            if {[catch {set $prop [get_property $prop $cell]}]} {
                set $prop ""
            }
        }
        puts $fh "[get_property NAME $cell],$REF_NAME,$LOC,$BEL"
        incr n
    }
    close $fh
}

if {![file exists $dcp_path]} {
    error "Missing DCP: $dcp_path"
}

open_checkpoint $dcp_path

set summary [file join $out_dir summary.txt]
set fh [open $summary w]
puts $fh "V9A AD9361 interface diagnostics"
puts $fh "Generated: [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh "DCP: $dcp_path"
puts $fh "Design: [current_design]"
if {![catch {set part_name [get_property PART [current_design]]}]} {
    puts $fh "Part: $part_name"
}
puts $fh ""

set all_ports [get_ports -quiet *]
set ad9361_ports [get_ports -quiet {rx_* tx_* adc_* dac_* data_* enable_* txnrx* clk_* *clk* *rst* *reset*}]
puts $fh "All ports: [llength $all_ports]"
puts $fh "AD9361-like ports: [llength $ad9361_ports]"

set p201_cells [get_cells -hierarchical -quiet -filter {NAME =~ *p201_tap0*}]
set axi_ad9361_cells [get_cells -hierarchical -quiet -filter {NAME =~ *axi_ad9361*}]
set tx_cells [get_cells -hierarchical -quiet -filter {NAME =~ *axi_ad9361*tx*}]
set rx_cells [get_cells -hierarchical -quiet -filter {NAME =~ *axi_ad9361*rx*}]
puts $fh "p201_tap0 cells: [llength $p201_cells]"
puts $fh "axi_ad9361 cells: [llength $axi_ad9361_cells]"
puts $fh "axi_ad9361 tx cells: [llength $tx_cells]"
puts $fh "axi_ad9361 rx cells: [llength $rx_cells]"
puts $fh ""

set clocks [get_clocks -quiet *]
puts $fh "Clocks:"
foreach clk [lsort -dictionary $clocks] {
    if {[catch {set period [get_property PERIOD $clk]}]} {
        set period ""
    }
    puts $fh "  [get_property NAME $clk] period=$period"
}
close $fh

write_ports_csv $all_ports [file join $out_dir ports_all.csv]
write_ports_csv $ad9361_ports [file join $out_dir ports_ad9361_like.csv]
write_cells_csv $p201_cells [file join $out_dir p201_tap_cells.csv] 20000
cell_count_by_ref $p201_cells [file join $out_dir p201_tap_ref_counts.csv]
cell_count_by_ref $tx_cells [file join $out_dir axi_ad9361_tx_ref_counts.csv]
cell_count_by_ref $rx_cells [file join $out_dir axi_ad9361_rx_ref_counts.csv]

run_report "report_io" {
    report_io -file [file join $out_dir report_io.rpt]
} [file join $out_dir report_io.error.txt]

run_report "report_timing_summary" {
    report_timing_summary -max_paths 20 -file [file join $out_dir timing_summary.rpt]
} [file join $out_dir timing_summary.error.txt]

run_report "report_route_status" {
    report_route_status -file [file join $out_dir route_status.rpt]
} [file join $out_dir route_status.error.txt]

run_report "report_drc" {
    report_drc -file [file join $out_dir drc.rpt]
} [file join $out_dir drc.error.txt]

run_report "report_utilization_hier" {
    report_utilization -hierarchical -hierarchical_depth 5 -file [file join $out_dir utilization_hierarchical.rpt]
} [file join $out_dir utilization_hierarchical.error.txt]

run_report "report_clock_interaction" {
    report_clock_interaction -file [file join $out_dir clock_interaction.rpt]
} [file join $out_dir clock_interaction.error.txt]

run_report "report_clock_networks" {
    report_clock_networks -file [file join $out_dir clock_networks.rpt]
} [file join $out_dir clock_networks.error.txt]

run_report "report_control_sets" {
    report_control_sets -verbose -file [file join $out_dir control_sets.rpt]
} [file join $out_dir control_sets.error.txt]

run_report "report_high_fanout_nets" {
    report_high_fanout_nets -max_nets 100 -file [file join $out_dir high_fanout_nets.rpt]
} [file join $out_dir high_fanout_nets.error.txt]

run_report "report_congestion" {
    report_design_analysis -congestion -file [file join $out_dir congestion.rpt]
} [file join $out_dir congestion.error.txt]

set rx_clk [get_clocks -quiet rx_clk]
set clk_fpga_0 [get_clocks -quiet clk_fpga_0]
if {[llength $rx_clk] > 0} {
    run_report "timing_rx_clk" {
        report_timing -from $rx_clk -to $rx_clk -nworst 20 -max_paths 20 -file [file join $out_dir timing_rx_clk.rpt]
    } [file join $out_dir timing_rx_clk.error.txt]
}
if {[llength $clk_fpga_0] > 0} {
    run_report "timing_clk_fpga_0" {
        report_timing -from $clk_fpga_0 -to $clk_fpga_0 -nworst 20 -max_paths 20 -file [file join $out_dir timing_clk_fpga_0.rpt]
    } [file join $out_dir timing_clk_fpga_0.error.txt]
}

set p201_pins [get_pins -hierarchical -quiet -of_objects $p201_cells]
if {[llength $p201_pins] > 0} {
    run_report "timing_through_p201_tap0" {
        report_timing -through $p201_pins -nworst 20 -max_paths 20 -file [file join $out_dir timing_through_p201_tap0.rpt]
    } [file join $out_dir timing_through_p201_tap0.error.txt]
}

close_design
puts "V9A_AD9361_INTERFACE_DIAGNOSTICS=$out_dir"
