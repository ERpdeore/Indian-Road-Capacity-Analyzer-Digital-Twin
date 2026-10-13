function A = twin_assets(prj, projectFolder)
%TWIN_ASSETS  Finds the vehicle and prop assets that REALLY exist in your
%   RoadRunner project, instead of hard-coding one file name.
%
%   A.vehicles.car / twoWheeler / truck / bus / van : cell arrays of assets
%   A.props.cone / barrier / barrel                 : one prop asset each
%
%   prj           : rrApi.Project
%   projectFolder : path of the RoadRunner project (used to list files on
%                   disk). If empty, only the known default names are tried.
%
%   Anything that cannot be found falls back to a car / a traffic cone, so
%   the scene always builds; a summary of what was found is printed.

    if nargin < 2, projectFolder = ''; end
    cats = {'car','twoWheeler','truck','bus','van'};
    A.vehicles = struct();
    for k = 1:numel(cats), A.vehicles.(cats{k}) = {}; end

    % file-name keywords -> category (first match wins)
    rules = { 'twoWheeler', ["motorcycle","motorbike","scooter","moped","bicycle","bike"]; ...
              'bus',        "bus"; ...
              'truck',      ["truck","lorry","trailer","semi"]; ...
              'van',        "van"; ...
              'car',        ["sedan","hatch","suv","coupe","wagon","taxi","pickup","car"] };

    %% ---- vehicles
    vehPaths = discoverAssets(projectFolder, 'Vehicles');
    if isempty(vehPaths), vehPaths = "Vehicles/Sedan.fbx"; end
    for k = 1:numel(vehPaths)
        asset = tryAsset(prj, vehPaths(k), "VehicleAsset");
        if isempty(asset), continue; end
        name = lower(lastPart(vehPaths(k)));
        cat = 'car';                                  % unknown vehicles count as cars
        for r = 1:size(rules,1)
            if any(contains(name, rules{r,2})), cat = rules{r,1}; break; end
        end
        A.vehicles.(cat){end+1} = asset;
    end
    if all(cellfun(@(c) isempty(A.vehicles.(c)), cats))
        error('twin_assets:NoVehicles', ...
            ['No vehicle asset could be loaded from the project.\n' ...
             'Check that Assets/Vehicles contains at least one vehicle (e.g. Sedan.fbx_rrx).']);
    end
    fprintf('      Vehicle assets found:');
    for k = 1:numel(cats), fprintf('  %s=%d', cats{k}, numel(A.vehicles.(cats{k}))); end
    fprintf('\n');

    %% ---- props (defect markers)
    propPaths = discoverAssets(projectFolder, 'Props');
    knownCone = "Props/TrafficControl/TrafficCone01.fbx";
    A.props.cone = firstProp(prj, propPaths, ["cone"], ["guardrail","wall"], knownCone);
    if isempty(A.props.cone)
        error('twin_assets:NoCone', 'Could not load %s from the project.', knownCone);
    end
    A.props.barrier = firstProp(prj, propPaths, ["barricade","barrier","blockade"], ...
                                ["guardrail","wall","rail"], "");
    A.props.barrel  = firstProp(prj, propPaths, ["barrel","drum","bin","trash","garbage"], ...
                                strings(1,0), "");
    if isempty(A.props.barrier), A.props.barrier = A.props.cone; end
    if isempty(A.props.barrel),  A.props.barrel  = A.props.cone; end
end

%% ---------------------------------------------------------------- helpers
function paths = discoverAssets(projectFolder, sub)
% List <project>/Assets/<sub>/**/*_rrx and return paths as getAsset expects
% them: relative to Assets, forward slashes, without the trailing "_rrx".
    paths = strings(0,1);
    if isempty(projectFolder), return; end
    root = fullfile(projectFolder, 'Assets');
    if ~isfolder(fullfile(root, sub)), return; end
    d = dir(fullfile(root, sub, '**', '*_rrx'));
    d = d(~[d.isdir]);
    for k = 1:numel(d)
        full = string(fullfile(d(k).folder, d(k).name));
        rel  = extractAfter(full, string(root) + filesep);
        rel  = replace(rel, filesep, "/");
        paths(end+1,1) = regexprep(rel, '_rrx$', ''); %#ok<AGROW>
    end
end

function asset = tryAsset(prj, path, type)
    try
        asset = getAsset(prj, path, type);
    catch
        asset = [];
    end
end

function s = lastPart(path)
    parts = split(string(path), "/");
    s = parts(end);
end

function asset = firstProp(prj, propPaths, include, exclude, fallback)
% First loadable prop whose FILE NAME contains an include word and no exclude word.
    asset = [];
    for k = 1:numel(propPaths)
        name = lower(lastPart(propPaths(k)));
        if any(contains(name, include)) && ~any(contains(name, exclude))
            asset = tryAsset(prj, propPaths(k), "MovableObjectAsset");
            if ~isempty(asset), return; end
        end
    end
    if strlength(fallback) > 0
        asset = tryAsset(prj, fallback, "MovableObjectAsset");
    end
end
