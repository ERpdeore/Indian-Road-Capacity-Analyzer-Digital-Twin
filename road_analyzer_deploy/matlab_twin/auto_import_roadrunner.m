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

    % ---- FILLED IN based on your screenshots -- double check these two! ----
    RESULTS_DIR = 'C:\Users\Admin\Downloads';   % where your browser downloads land
    if nargin < 3 || isempty(project_folder)
        project_folder = 'C:\Users\Admin\OneDrive\Documents\final year\matlab roadrunner\New RoadRunner Project';
    end
    % --------------------------------------------------------------------

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

    % If roadrunnerSetup() has been run once, this line is all you need.
    % If you still get "Unable to open RoadRunner application from
    % installation folder" after running roadrunnerSetup, uncomment the
    % line below and fill in your real RoadRunner install folder (find it
    % via: right-click your RoadRunner shortcut -> Open file location).
    INSTALLATION_FOLDER = 'C:\Program Files\RoadRunner R2026a\bin\win64';

    fprintf('[1/5] (%s) Opening RoadRunner project: %s\n', mode, project_folder);
    if isempty(INSTALLATION_FOLDER)
        rrApp = roadrunner(project_folder);
    else
        rrApp = roadrunner(project_folder, 'InstallationFolder', INSTALLATION_FOLDER);
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
    isCorridor = contains(xodrBase, 'corridor');
    if isCorridor
        capacityJsonPath = fullfile(xodrFolder, 'roadrunner_corridor_capacity.json');
    else
        xodrBase = erase(xodrBase, '_ideal');
        xodrBase = erase(xodrBase, '_roadrunner');
        capacityJsonPath = fullfile(xodrFolder, [xodrBase '_roadrunner_capacity.json']);
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

    baselineVehicles = 6;   % vehicle count shown for the ideal case
    numVehicles = baselineVehicles;
    speedKmh = [];   % empty = let the vehicle script use its own default
    if isfile(capacityJsonPath)
        try
            cap = jsondecode(fileread(capacityJsonPath));
            if strcmp(mode, 'nonideal') && ~isempty(cap.original_capacity_vehicles_hr) ...
                    && cap.original_capacity_vehicles_hr > 0
                ratio = cap.reduced_capacity_vehicles_hr / cap.original_capacity_vehicles_hr;
                numVehicles = max(1, round(baselineVehicles * ratio));
                fprintf('      Using real capacity data: %.0f -> %.0f veh/hr (%.0f%% loss) -> %d vehicles shown\n', ...
                    cap.original_capacity_vehicles_hr, cap.reduced_capacity_vehicles_hr, ...
                    cap.capacity_loss_pct, numVehicles);
            end
            if strcmp(mode, 'ideal') && isfield(cap, 'free_flow_speed_kmh') && ~isempty(cap.free_flow_speed_kmh)
                speedKmh = cap.free_flow_speed_kmh;
                fprintf('      Using real free-flow speed: %.1f km/h\n', speedKmh);
            elseif strcmp(mode, 'nonideal') && isfield(cap, 'congested_speed_kmh') && ~isempty(cap.congested_speed_kmh)
                speedKmh = cap.congested_speed_kmh;
                fprintf('      Using real congested speed: %.1f km/h\n', speedKmh);
            end
        catch
            fprintf('      Could not read capacity data, using default vehicle count/speed.\n');
        end
    else
        fprintf('      No capacity data found (%s) -- using default vehicle count/speed.\n', capacityJsonPath);
    end

    if strcmp(mode, 'ideal')
        add_vehicles_ideal(rrApp, baselineVehicles, speedKmh, roadLength_m);
    else
        add_vehicles_nonideal(rrApp, numVehicles, speedKmh, roadLength_m);
    end

    fprintf('[5/5] Starting simulation...\n');
    rrSim = createSimulation(rrApp);
    set(rrSim, 'SimulationCommand', 'Start');

    fprintf('\nDONE (%s). Road and traffic are in RoadRunner and the simulation is running.\n', mode);
    fprintf('Keeping this window open so the simulation keeps running for your demo.\n');
    fprintf('When you''re done, just close this window (or press Ctrl+C here).\n\n');

    % IMPORTANT: MATLAB -batch closes everything the instant the script
    % ends, which disconnects and STOPS the simulation. This loop keeps
    % MATLAB alive on purpose so your demo keeps playing until you're
    % ready to close it yourself.
    while true
        pause(1);
    end
end
