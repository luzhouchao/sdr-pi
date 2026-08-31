set script_dir [file dirname [file normalize [info script]]]
set repo_dir [file dirname $script_dir]
set dcp [file join $repo_dir reports stage4_ad9361_tap_integrated_synth system_top_with_p201_tap_synth.dcp]
open_checkpoint $dcp

set adc_regs [get_cells -hierarchical -quiet -filter {NAME =~ *p201_tap0/*adc_reg* || NAME =~ *p201_tap0/pending_adc_reg}]
set axi_regs [get_cells -hierarchical -quiet -filter {NAME =~ *p201_tap0/*axi_reg*}]
puts "ADC_REG_COUNT=[llength $adc_regs]"
puts "AXI_REG_COUNT=[llength $axi_regs]"
puts "ADC_REG_SAMPLE=[lrange $adc_regs 0 10]"
puts "AXI_REG_SAMPLE=[lrange $axi_regs 0 10]"

set pending_adc [get_cells -hierarchical -quiet -filter {NAME =~ *p201_tap0/*pending_adc_reg*}]
set pending_meta_axi [get_cells -hierarchical -quiet -filter {NAME =~ *p201_tap0/*pending_meta_axi_reg*}]
set clear_axi [get_cells -hierarchical -quiet -filter {NAME =~ *p201_tap0/*clear_toggle_axi_reg*}]
set clear_adc [get_cells -hierarchical -quiet -filter {NAME =~ *p201_tap0/*clear_meta_adc_reg*}]
puts "PENDING_ADC=[llength $pending_adc] $pending_adc"
puts "PENDING_META_AXI=[llength $pending_meta_axi] $pending_meta_axi"
puts "CLEAR_AXI=[llength $clear_axi] $clear_axi"
puts "CLEAR_ADC=[llength $clear_adc] $clear_adc"

close_project
