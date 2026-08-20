function run_digital_twin(json_path)
%% ================================================================
%% run_digital_twin.m
%%
%% This file did NOT exist in the repo before this fix, even though
%% both the README and create_digital_twin_model.m's own comments
%% told you to run it as "the next step". That's the single biggest
%% reason the Digital Twin panel never showed anything: nothing was
%% ever loading the .slx model, running it, or exporting a result
%% for the Python dashboard to read.
%%
%% WHAT THIS DOES:
%%   1. Reads the analysis JSON that road_analyzer/core.py just wrote
%%      for one image (path passed in as an argument).
%%   2. Builds the "simIn" struct in the base workspace with the
%%      scalar values the Constant blocks in road_digital_twin.slx
%%      read (see create_digital_twin_model.m).
%%   3. Loads the model (builds it first via create_digital_twin_model
%%      if the .slx doesn't exist yet) and runs sim().
%%   4. Extracts the logged signals and writes dt_output.json next to
%%      this script — this is the file digital_twin_bridge.py polls.
%%
%% USAGE (called automatically by digital_twin_bridge.py):
%%   matlab -batch "run_digital_twin('/full/path/to/xxx_analysis.json')"
%%
%% USAGE (manual test from MATLAB command window):
%%   cd('path\to\road_analyzer_deploy\matlab_twin')
%%   run_digital_twin('C:\path\to\some_analysis.json')
%% ================================================================

if nargin < 1 || isempty(json_path)
    error('run_digital_twin:missingArg', ...
        'Pass the path to an *_analysis.json file, e.g. run_digital_twin(''C:\\...\\img_analysis.json'')');
end

MODEL_NAME = 'road_digital_twin';
here       = fileparts(mfilename('fullpath'));
slx_path   = fullfile(here, [MODEL_NAME '.slx']);
out_path   = fullfile(here, 'dt_output.json');
status_path = fullfile(here, 'dt_status.json');

write_status(status_path, 'running', '');

try
    %% ---- 1. Build the model if it hasn't been generated yet ----
    if ~isfile(slx_path)
        fprintf('road_digital_twin.slx not found — building it first...\n');
        run(fullfile(here, 'create_digital_twin_model.m'));
    end

    %% ---- 2. Load and parse the analysis JSON ----
    if ~isfile(json_path)
        error('run_digital_twin:badPath', 'JSON file not found: %s', json_path);
    end
    raw     = fileread(json_path);
    analysis = jsondecode(raw);

    ideal_dsv  = get_field(analysis, {'original_capacity_pcu_hr'}, 1500);
    defect_dsv = get_field(analysis, {'reduced_capacity_pcu_hr'}, ideal_dsv);
    cap_loss   = get_field(analysis, {'capacity_loss_pct'}, 0);

    % NOTE: core.py deliberately does NOT compute an A-F Level of Service
    % letter (see the header comment in core.py, point 2 — LOS needs a
    % real V/C ratio from a traffic count, which this project doesn't
    % measure). It only returns overall_guidance.band, one of
    % Minor/Moderate/Significant/Severe/Critical, keyed off capacity_loss_pct.
    % For the digital twin's LOS gauge we derive an approximate A-F letter
    % directly from capacity_loss_pct using the same thresholds the old
    % README documented — labelled an approximation, not core.py's output.
    los_numeric = cap_loss_pct_to_los_numeric(cap_loss);
    los_letter  = los_numeric_to_letter(los_numeric);

    worst_depth = 'unknown';
    try
        worst_depth = analysis.capacity_calculation.worst_pothole_depth;
    catch
        % no potholes in this image — leave as 'unknown'
    end
    pothole_speed_pct = pothole_depth_to_speed_pct(worst_depth);

    %% ---- 3. Build simIn in the base workspace ----
    simIn = struct( ...
        'ideal_dsv',        double(ideal_dsv), ...
        'defect_dsv',       double(defect_dsv), ...
        'cap_loss_pct',     double(cap_loss), ...
        'los_numeric',      double(los_numeric), ...
        'pothole_speed_pct', double(pothole_speed_pct) ...
    );
    assignin('base', 'simIn', simIn);

    fprintf('Digital Twin inputs:\n');
    fprintf('  ideal_dsv         = %.1f PCU/hr\n', simIn.ideal_dsv);
    fprintf('  defect_dsv        = %.1f PCU/hr\n', simIn.defect_dsv);
    fprintf('  cap_loss_pct      = %.1f %%\n',     simIn.cap_loss_pct);
    fprintf('  los_numeric       = %d (%s)\n',     simIn.los_numeric, los_letter);
    fprintf('  pothole_speed_pct = %.1f %%\n',     simIn.pothole_speed_pct);

    %% ---- 4. Load model and simulate ----
    load_system(slx_path);
    simOut = sim(MODEL_NAME, 'ReturnWorkspaceOutputs', 'on');

    dt_simout = simOut.get('dt_simout');   % Structure With Time, from the To Workspace block
    t  = dt_simout.time;
    yv = dt_simout.signals.values;         % N-by-5: [ideal_flow, defect_flow, cap_loss_pct, los, speed_kmh]

    ideal_series  = yv(:,1);
    defect_series = yv(:,2);
    speed_series  = yv(:,5);

    % IRC:106 design load factor (0.7) converts capacity -> design traffic volume
    DESIGN_LOAD_FACTOR = 0.7;
    ideal_vol  = simIn.ideal_dsv  * DESIGN_LOAD_FACTOR;
    defect_vol = simIn.defect_dsv * DESIGN_LOAD_FACTOR;

    free_flow_speed   = 50;   % km/h, matches FreeFlowSpeed_kmh constant in the model
    steady_state_speed = speed_series(end);
    speed_reduction_pct = max(0, (free_flow_speed - steady_state_speed) / free_flow_speed * 100);

    % ---- SHAPE MUST MATCH static/app.js dtRender()/dtPoll() EXACTLY ----
    % app.js does: data.twin_data.summary.<field>  and
    %              data.twin_data.<series arrays>   (top-level, not under summary)
    result = struct();
    result.generated_at   = datestr(now, 'yyyy-mm-ddTHH:MM:SS');
    result.source_json    = json_path;

    result.summary = struct( ...
        'ideal_capacity_pcu_hr',   simIn.ideal_dsv, ...
        'defect_capacity_pcu_hr',  simIn.defect_dsv, ...
        'ideal_volume_design_pcu', ideal_vol, ...
        'defect_volume_design_pcu', defect_vol, ...
        'steady_state_speed_kmh',  steady_state_speed, ...
        'capacity_loss_pct',       simIn.cap_loss_pct, ...
        'pothole_speed_impact_pct', simIn.pothole_speed_pct, ...
        'speed_reduction_pct',     speed_reduction_pct ...
    );

    result.simulation_time_s      = t;
    result.ideal_capacity_pcu_hr  = ideal_series;
    result.defect_capacity_pcu_hr = defect_series;
    result.vehicle_speed_kmh      = speed_series;

    %% ---- 5. Write dt_output.json for the Python bridge to read ----
    fid = fopen(out_path, 'w');
    if fid == -1
        error('run_digital_twin:writeFail', 'Could not open %s for writing.', out_path);
    end
    fwrite(fid, jsonencode(result));
    fclose(fid);

    fprintf('Digital Twin simulation complete. Output written to:\n  %s\n', out_path);
    write_status(status_path, 'complete', '');

catch ME
    fprintf(2, 'Digital Twin simulation FAILED: %s\n', ME.message);
    write_status(status_path, 'error', ME.message);
    rethrow(ME);
end

end % function run_digital_twin


%% ================================================================
%% HELPERS
%% ================================================================
function v = get_field(s, path_parts, default)
    v = default;
    try
        cur = s;
        for i = 1:numel(path_parts)
            cur = cur.(path_parts{i});
        end
        v = cur;
    catch
        v = default;
    end
end

function n = cap_loss_pct_to_los_numeric(pct)
    % Approximate mapping only — core.py has no V/C ratio to compute a
    % real LOS from. Bands loosely follow the original README's V/C
    % table but keyed off capacity_loss_pct instead, purely for the
    % digital twin's visual gauge.
    if     pct < 10,  n = 1;  % A
    elseif pct < 25,  n = 2;  % B
    elseif pct < 50,  n = 3;  % C
    elseif pct < 75,  n = 4;  % D
    elseif pct < 90,  n = 5;  % E
    else,             n = 6;  % F
    end
end

function letter = los_numeric_to_letter(n)
    letters = {'A','B','C','D','E','F'};
    n = max(1, min(6, round(n)));
    letter = letters{n};
end

function pct = pothole_depth_to_speed_pct(severity)
    % Rough, documented estimate of how much a pothole of this severity
    % slows a vehicle down, as a % of free-flow speed. Not a measured
    % value — tune these numbers if you have real speed-survey data.
    switch lower(strtrim(char(severity)))
        case 'deep',     pct = 30;
        case 'moderate', pct = 15;
        case 'shallow',  pct = 5;
        otherwise,       pct = 0;   % 'unknown' or no pothole present
    end
end

function write_status(path, status, err_msg)
    s = struct('status', status, 'error', err_msg, ...
                'updated_at', datestr(now, 'yyyy-mm-ddTHH:MM:SS'));
    fid = fopen(path, 'w');
    if fid ~= -1
        fwrite(fid, jsonencode(s));
        fclose(fid);
    end
end
