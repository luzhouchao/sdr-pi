set p201_tap_adc_regs [get_cells -hierarchical -quiet -filter {(REF_NAME =~ FD* || REF_NAME =~ LD*) && (NAME =~ *p201_tap0/*adc_reg* || NAME =~ *p201_tap0/pending_adc_reg)}]
set p201_tap_axi_regs [get_cells -hierarchical -quiet -filter {(REF_NAME =~ FD* || REF_NAME =~ LD*) && NAME =~ *p201_tap0/*axi_reg*}]
set p201_tap_cdc_first_stage_regs [get_cells -hierarchical -quiet -filter {(REF_NAME =~ FD* || REF_NAME =~ LD*) && NAME =~ *p201_tap0/inst/*_meta_*_reg}]

set_false_path -quiet -from $p201_tap_adc_regs -to $p201_tap_axi_regs
set_false_path -quiet -from $p201_tap_axi_regs -to $p201_tap_adc_regs
set_false_path -quiet -to $p201_tap_cdc_first_stage_regs
