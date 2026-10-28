function run_digital_twin(json_path)
%% ================================================================
%% run_digital_twin.m — simulate road_digital_twin.slx for one analysis
%%
%% USAGE
%%   run_digital_twin('C:\path\to\<photo>_roadrunner_capacity.json')
%%   run_digital_twin('C:\path\to\<photo>_analysis.json')
%%
%% Reads ideal capacity C0, reduced capacity C and demand q (PCU/h), runs
%% the Simulink point-queue model for one hour, and writes dt_output.json
%% next to this file with the stored queue (PCU) for both roads.
%%
%% Demand: twin.demand_pcu_h from the capacity JSON (observed volume, or
%% the LOS-C service volume 0.70 x C0 when no count was entered). From an
%% analysis JSON: level_of_service.observed_volume_pcu_h, else 0.70 x C0.
%%
%% No LOS letter is produced here: LOS needs V/C from a real count and is
%% computed in Python only when the user enters one.
%% ================================================================

if nargin < 1 || isempty(json_path)
    error('run_digital_twin:noInput', ...
        'Pass the path to a *_roadrunner_capacity.json or *_analysis.json file.');
end

here       = fileparts(mfilename('fullpath'));
slx_path   = fullfile(here, 'road_digital_twin.slx');
out_path   = fullfile(here, 'dt_output.json');
MODEL_NAME = 'road_digital_twin';

if ~isfile(slx_path)
    fprintf('road_digital_twin.slx not found — building it first...\n');
    create_digital_twin_model();
end
if ~isfile(json_path)
    error('run_digital_twin:badPath', 'JSON file not found: %s', json_path);
end
a = jsondecode(fileread(json_path));

c0 = get_field(a, {'base_capacity_pcu_h'}, NaN);
c  = get_field(a, {'reduced_capacity_pcu_h'}, c0);
if isnan(c0)
    error('run_digital_twin:noCapacity', 'No base_capacity_pcu_h in %s.', json_path);
end
q = get_field(a, {'twin', 'demand_pcu_h'}, NaN);
demand_src = get_field(a, {'twin', 'demand_source'}, '');
if isnan(q)
    q = get_field(a, {'level_of_service', 'observed_volume_pcu_h'}, NaN);
    demand_src = 'observed volume';
end
if isnan(q)
    % No volume is ever assumed: the user must enter one for this road.
    error('run_digital_twin:noVolume', ...
        'No observed volume in %s. Enter the observed volume (PCU/h) for this road and re-run the analysis.', json_path);
end

simIn = struct('demand_pcu_h', double(q), 'ideal_cap', double(c0), 'defect_cap', double(c));
assignin('base', 'simIn', simIn);
fprintf('Demand %.0f PCU/h (%s)\n  C0 = %.0f PCU/h, C = %.0f PCU/h\n', q, demand_src, c0, c);

load_system(slx_path);
simOut = sim(MODEL_NAME, 'ReturnWorkspaceOutputs', 'on');
s = simOut.get('dt_simout');

result = struct();
result.generated_at       = datestr(now, 'yyyy-mm-ddTHH:MM:SS');
result.source_json        = json_path;
result.engine             = 'simulink point queue';
result.demand_pcu_h       = q;
result.demand_source      = demand_src;
result.ideal_capacity_pcu_h  = c0;
result.defect_capacity_pcu_h = c;
result.time_min           = s.time / 60;
result.queue_pcu_ideal    = s.signals.values(:, 1);
result.queue_pcu_defect   = s.signals.values(:, 2);

fid = fopen(out_path, 'w');
if fid == -1
    error('run_digital_twin:writeFail', 'Could not open %s for writing.', out_path);
end
fwrite(fid, jsonencode(result));
fclose(fid);
fprintf('Queue after 60 min: ideal %.0f PCU, current %.0f PCU\n', ...
    result.queue_pcu_ideal(end), result.queue_pcu_defect(end));
fprintf('Output written to %s\n', out_path);
end


function v = get_field(s, path_parts, default)
    v = default;
    try
        cur = s;
        for i = 1:numel(path_parts)
            cur = cur.(path_parts{i});
        end
        if ~isempty(cur), v = cur; end
    catch
        v = default;
    end
end
