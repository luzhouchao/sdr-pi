repoRoot = fileparts(fileparts(mfilename("fullpath")));
reportsDir = fullfile(repoRoot, "reports");
if ~exist(reportsDir, "dir")
    mkdir(reportsDir);
end

modelPath = fullfile(repoRoot, "vendor_matlab_demo_min", "Matlab", ...
    "CH10_FM_Complex_Delay_Demod", "pzsdr_complex_delay_demod.slx");
reportPath = fullfile(reportsDir, "vendor_model_analysis_r2025a.txt");
if exist(reportPath, "file")
    delete(reportPath);
end
diary(reportPath);
fprintf("P201Pro vendor model analysis\n");
fprintf("Generated: %s\n", datestr(now, 31));
fprintf("MATLAB version: %s\n", version);
fprintf("Model copy: vendor_matlab_demo_min/Matlab/CH10_FM_Complex_Delay_Demod/pzsdr_complex_delay_demod.slx\n\n");

try
    load_system(modelPath);
    [~, modelName] = fileparts(modelPath);
    blocks = find_system(modelName, "LookUnderMasks", "all", "FollowLinks", "on", "Type", "Block");
    fprintf("LOAD_OK model=%s block_count=%d\n\n", modelName, numel(blocks));
    for k = 1:numel(blocks)
        block = blocks{k};
        blockType = get_param(block, "BlockType");
        maskType = "";
        refBlock = "";
        try, maskType = get_param(block, "MaskType"); catch, end %#ok<CTCH>
        try, refBlock = get_param(block, "ReferenceBlock"); catch, end %#ok<CTCH>
        fprintf("BLOCK|%s|type=%s|mask=%s|ref=%s\n", block, blockType, maskType, refBlock);
    end
    fprintf("\nCandidate IQ extraction notes:\n");
    fprintf("- Pluto/P201Pro receive-source blocks are the likely IQ input boundary.\n");
    fprintf("- The FPGA offload insertion point should be immediately after complex IQ output and before FM delay demod blocks.\n");
    fprintf("- First prototype should not depend on the live device block; use logged/synthetic IQ frames for PSD verification.\n");
    close_system(modelName, 0);
catch ME
    fprintf("LOAD_FAIL\n%s\n", getReport(ME, "basic"));
end
diary off;
