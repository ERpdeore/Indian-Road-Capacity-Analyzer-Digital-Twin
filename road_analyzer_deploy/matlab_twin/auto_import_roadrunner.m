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
        project_folder = 'C:\Users\Admin\OneDrive\Desktop\New RoadRunner Project';  % <-- CONFIRM this is your real RoadRunner project folder
    end
    % --------------------------------------------------------------------

    if strcmp(mode, 'ideal')
        filePattern = '*_roadrunner_ideal.xodr';
    else
        filePattern = '*_roadrunner.xodr';
    end

    if nargin < 2 || isempty(xodr_path)
        fprintf('No file given -- looking for the most recent "%s" export in:\n  %s\n', mode, RESULTS_DIR);
        matches = dir(fullfile(RESULTS_DIR, filePattern));   % non-recursive: Downloads is flat
        if strcmp(mode, 'nonideal')
            matches = matches(~contains({matches.name}, '_ideal.xodr'));
        end
        if isempty(matches)
            error('auto_import_roadrunner:NoneFound', ...
                ['No %s files found in %s.\n' ...
                 'Did you click "Download .xodr" on the website for this job yet? ' ...
                 'That has to happen before this script can find anything.'], ...
                filePattern, RESULTS_DIR);
        end
        [~, idx] = max([matches.datenum]);
        xodr_path = fullfile(matches(idx).folder, matches(idx).name);
        fprintf('Using most recent file: %s\n', xodr_path);
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
        importScene(rrApp, xodr_path, "OpenDRIVE");
    catch importErr
        error('auto_import_roadrunner:ImportFailed', 'importScene failed: %s', importErr.message);
    end
    fprintf('[3/5] Saving scene...\n');
    saveScene(rrApp, sprintf('%s_demo_scene.rrscene', mode));

    fprintf('[4/5] Adding %s traffic...\n', mode);
    % Look for the capacity sidecar JSON next to the .xodr (same folder,
    % same base name) -- if found, real ideal-vs-reduced capacity numbers
    % drive how many vehicles get shown. If not found, falls back to a
    % fixed default count so the demo still works either way.
    [xodrFolder, xodrBase] = fileparts(xodr_path);
    xodrBase = erase(xodrBase, '_ideal');
    xodrBase = erase(xodrBase, '_roadrunner');
    capacityJsonPath = fullfile(xodrFolder, [xodrBase '_roadrunner_capacity.json']);

    baselineVehicles = 6;   % vehicle count shown for the ideal case
    numVehicles = baselineVehicles;
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
        catch
            fprintf('      Could not read capacity data, using default vehicle count.\n');
        end
    else
        fprintf('      No capacity data found (%s) -- using default vehicle count.\n', capacityJsonPath);
    end

    if strcmp(mode, 'ideal')
        add_vehicles_ideal(rrApp, baselineVehicles);
    else
        add_vehicles_nonideal(rrApp, numVehicles);
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
