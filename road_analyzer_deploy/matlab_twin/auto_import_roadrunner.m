function auto_import_roadrunner(mode, xodr_path, project_folder)
%AUTO_IMPORT_ROADRUNNER  One-call RoadRunner import + vehicles + simulation.
%
%   mode: 'ideal' or 'nonideal'

    if nargin < 1 || isempty(mode)
        error('auto_import_roadrunner:MissingMode', ...
            "Specify mode as 'ideal' or 'nonideal', e.g. auto_import_roadrunner('ideal')");
    end
    mode = lower(mode);
    if ~ismember(mode, {'ideal', 'nonideal'})
        error('auto_import_roadrunner:BadMode', "mode must be 'ideal' or 'nonideal', got '%s'.", mode);
    end

    % Inputs (.xodr + _roadrunner_capacity.json) are looked for in the
    % folder this script lives in: keep the bundle files together.
    RESULTS_DIR = fileparts(mfilename('fullpath'));
    if nargin < 3 || isempty(project_folder)
        project_folder = resolve_project_folder(RESULTS_DIR);
    end
    if strcmp(mode, 'ideal')
        filePattern = '*_roadrunner_ideal.xodr';
        corridorFile = 'roadrunner_corridor_ideal.xodr';
    else
        filePattern = '*_roadrunner.xodr';
        corridorFile = 'roadrunner_corridor.xodr';
    end

    if nargin < 2 || isempty(xodr_path)
        fprintf('No file given -- looking for the most recent "%s" export in:\n  %s\n', mode, RESULTS_DIR);
        matches = dir(fullfile(RESULTS_DIR, filePattern));   % non-recursive: Downloads is flat
        if strcmp(mode, 'nonideal')
            matches = matches(~contains({matches.name}, '_ideal.xodr'));
        end
        if isempty(matches)
            % Fall back to a multi-photo corridor export, if you used
            % that instead of a single-photo one.
            corridorPath = fullfile(RESULTS_DIR, corridorFile);
            if isfile(corridorPath)
                xodr_path = corridorPath;
                fprintf('No single-photo export found -- using corridor file instead: %s\n', xodr_path);
            else
                error('auto_import_roadrunner:NoneFound', ...
                    ['No %s files found in %s, and no %s corridor file either.\n' ...
                     'Did you click "Download .xodr" (or the corridor download button) on the website yet? ' ...
                     'That has to happen before this script can find anything.'], ...
                    filePattern, RESULTS_DIR, corridorFile);
            end
        else
            [~, idx] = max([matches.datenum]);
            xodr_path = fullfile(matches(idx).folder, matches(idx).name);
            fprintf('Using most recent file: %s\n', xodr_path);
        end
    end

    if ~isfile(xodr_path)
        error('auto_import_roadrunner:FileNotFound', 'XODR file not found: %s', xodr_path);
    end
    if ~isfolder(project_folder)
        error('auto_import_roadrunner:ProjectNotFound', ...
            ['RoadRunner project folder not found: %s\n' ...
             'Open RoadRunner by hand once and confirm your actual project folder path, ' ...
             'then fix the project_folder line in this file.'], project_folder);
    end

    fprintf('[1/5] (%s) Opening RoadRunner project: %s\n', mode, project_folder);
    installFolder = resolve_install_folder();
    if isempty(installFolder)
        rrApp = roadrunner(project_folder);   % uses the folder saved by roadrunnerSetup
    else
        rrApp = roadrunner(project_folder, 'InstallationFolder', installFolder);
    end
    pause(5);

    fprintf('[2/5] Importing road from: %s\n', xodr_path);
    try
        newScene(rrApp);
        % IMPORTANT: importScene does NOT import <object> entries (which is
        % exactly how your defects -- potholes, barricades, etc. -- are
        % stored in the .xodr) unless explicitly told to. Its ImportObjects
        % option defaults to false, so without this, every defect was being
        % silently skipped on import even though the file had them.
        importOptions = openDriveImportOptions(ImportObjects=true, ImportSignals=true);
        importScene(rrApp, xodr_path, "OpenDRIVE", importOptions);
    catch importErr
        error('auto_import_roadrunner:ImportFailed', 'importScene failed: %s', importErr.message);
    end
    fprintf('[3/5] Saving scene...\n');
    saveScene(rrApp, sprintf('%s_demo_scene.rrscene', mode));

    fprintf('[4/5] Adding %s traffic...\n', mode);
    % Look for the capacity sidecar JSON next to the .xodr (same folder,
    % same base name) -- if found, real ideal-vs-reduced capacity numbers
    % drive how many vehicles get shown. Falls back to the corridor
    % capacity summary if this is a corridor file, then to a fixed
    % default if neither exists, so the demo still works either way.
    [xodrFolder, xodrBase] = fileparts(xodr_path);
    % Strip only the export SUFFIX (_roadrunner / _roadrunner_ideal), never
    % text inside the photo's own name.
    isCorridor = startsWith(xodrBase, 'roadrunner_corridor');
    if isCorridor
        capacityJsonPath = fullfile(xodrFolder, 'roadrunner_corridor_capacity.json');
    else
        stem = regexprep(xodrBase, '_roadrunner(_ideal)?$', '');
        capacityJsonPath = fullfile(xodrFolder, [stem '_roadrunner_capacity.json']);
    end

    % Real road length, read straight from the .xodr's own <road length="...">
    % values, instead of assuming a fixed 40m -- matters a lot for a
    % multi-photo corridor, which is much longer than a single segment.
    roadLength_m = 40;   % fallback if parsing fails
    try
        xodrText = fileread(xodr_path);
        % IMPORTANT: match only <road ... length="..."> tags, not every
        % length="..." attribute in the file -- geometry/lane elements
        % also carry their own length attribute with the same value,
        % which was previously causing this to be double-counted (a 40m
        % road was being read as 80m, pushing half your vehicles off
        % the actual road).
        lens = regexp(xodrText, '<road\s[^>]*\blength="([\d\.]+)"', 'tokens');
        if ~isempty(lens)
            roadLength_m = sum(cellfun(@(c) str2double(c{1}), lens));
            fprintf('      Detected real road length from file: %.1f m\n', roadLength_m);
        end
    catch
        fprintf('      Could not parse road length from file, using default %.0f m.\n', roadLength_m);
    end

    speedKmh        = [];   % empty = twin_config.m default
    defectPositions = [];   % measured lateral defect positions
    totalWidth_m    = [];   % measured carriageway width
    numLanes        = [];   % lane count of the analysed carriageway
    density         = [];   % PCU/km/lane from the Python twin (twin.ideal / twin.defect)
    avgPcu          = [];   % PCU per vehicle, to turn PCU density into vehicles
    divided         = false;% divided-road carriageway = all lanes one direction
    if isfile(capacityJsonPath)
        try
            cap = jsondecode(fileread(capacityJsonPath));
            % Vehicle count and speed come from the macroscopic twin, i.e. the
            % SAME demand on both roads. A capacity loss does not mean fewer
            % vehicles on the road: when demand exceeds the reduced capacity a
            % queue forms upstream and density goes UP, speed goes DOWN.
            if ~isfield(cap, 'twin') || isempty(cap.twin)
                error('auto_import:noTwin', ['No digital twin in the capacity data: enter the observed ' ...
                      'volume and the measured operating speed for this road, then re-run the analysis.']);
            end
            if true
                if strcmp(mode, 'ideal')
                    st = cap.twin.ideal;
                    speedKmh = st.section_speed_kmh;
                    density  = st.section_density_pcu_km_lane;
                else
                    st = cap.twin.defect;
                    if isfield(st, 'upstream_queue_density_pcu_km_lane')
                        speedKmh = st.upstream_speed_kmh;           % queued traffic
                        density  = st.upstream_queue_density_pcu_km_lane;
                    else
                        speedKmh = st.section_speed_kmh;
                        density  = st.section_density_pcu_km_lane;
                    end
                end
                fprintf('      Twin (%s): %s, %.1f km/h, %.1f PCU/km/lane at demand %.0f PCU/h\n', ...
                    mode, st.state, speedKmh, density, cap.twin.demand_pcu_h);
            end
            if isfield(cap, 'avg_pcu_per_vehicle') && ~isempty(cap.avg_pcu_per_vehicle)
                avgPcu = cap.avg_pcu_per_vehicle;
            end
            if isfield(cap, 'divided') && ~isempty(cap.divided)
                divided = logical(cap.divided);
            end
            if strcmp(mode, 'nonideal') && isfield(cap, 'defect_positions') && ~isempty(cap.defect_positions)
                defectPositions = cap.defect_positions;
            end
            if isfield(cap, 'total_width_m') && ~isempty(cap.total_width_m)
                totalWidth_m = cap.total_width_m;
            end
            if isfield(cap, 'num_lanes') && ~isempty(cap.num_lanes)
                numLanes = cap.num_lanes;
            end
        catch capErr
            rethrow(capErr);   % never fall back to default traffic
        end
    else
        error('auto_import:noData', ['No capacity data found (%s). Run an analysis with an entered ' ...
              'observed volume and a measured operating speed first.'], capacityJsonPath);
    end

    opts = struct('projectFolder', project_folder, 'numLanes', numLanes, ...
                  'totalWidth_m', totalWidth_m, 'densityPcuKmLane', density, ...
                  'avgPcu', avgPcu, 'divided', divided);

    if strcmp(mode, 'ideal')
        add_vehicles_ideal(rrApp, [], speedKmh, roadLength_m, opts);
    else
        add_vehicles_nonideal(rrApp, [], speedKmh, roadLength_m, opts);
        % Real detected defects (potholes, barricades, ...) become enlarged,
        % clearly visible marker clusters -- see add_defects_to_scene.m and
        % twin_config.m.
        add_defects_to_scene(rrApp, defectPositions, totalWidth_m, roadLength_m, opts);
    end

    fprintf('[5/5] Starting simulation...\n');
    rrSim = createSimulation(rrApp);
    set(rrSim, 'SimulationCommand', 'Start');

    fprintf('\nDONE (%s). Road and traffic are in RoadRunner and the simulation is running.\n', mode);
end


function folder = resolve_project_folder(here)
%RESOLVE_PROJECT_FOLDER  RoadRunner project folder, in this order:
%   1. environment variable RR_PROJECT_FOLDER
%   2. roadrunner_project.txt next to this script (one line: the path)
%   3. ask once with a folder picker, then save it to roadrunner_project.txt
    folder = getenv('RR_PROJECT_FOLDER');
    if ~isempty(folder) && isfolder(folder), return; end
    cfgFile = fullfile(here, 'roadrunner_project.txt');
    if isfile(cfgFile)
        folder = strtrim(fileread(cfgFile));
        if isfolder(folder), return; end
        fprintf('Saved RoadRunner project folder no longer exists: %s\n', folder);
    end
    folder = uigetdir(pwd, 'Select your RoadRunner PROJECT folder (the one with Assets and Scenes)');
    if isequal(folder, 0)
        error('auto_import_roadrunner:NoProject', 'No RoadRunner project folder selected.');
    end
    fid = fopen(cfgFile, 'w');
    if fid ~= -1, fprintf(fid, '%s', folder); fclose(fid); end
    fprintf('Saved RoadRunner project folder to %s\n', cfgFile);
end


function folder = resolve_install_folder()
%RESOLVE_INSTALL_FOLDER  RoadRunner install folder, or '' to let
%   roadrunner() use the one saved by roadrunnerSetup.
%   Order: env RR_INSTALL_FOLDER, then the newest C:\Program Files\RoadRunner R20xx*\bin\win64.
    folder = getenv('RR_INSTALL_FOLDER');
    if ~isempty(folder) && isfolder(folder), return; end
    folder = '';
    if ispc
        d = dir(fullfile(getenv('ProgramFiles'), 'RoadRunner R20*'));
        if ~isempty(d)
            names = sort({d.name});
            cand = fullfile(getenv('ProgramFiles'), names{end}, 'bin', 'win64');
            if isfolder(cand), folder = cand; end
        end
    end
end

