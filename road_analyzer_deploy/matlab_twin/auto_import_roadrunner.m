function auto_import_roadrunner(mode, xodr_path, project_folder)
%AUTO_IMPORT_ROADRUNNER  One-call RoadRunner import + vehicles + simulation.
%
%   mode: 'ideal' or 'nonideal'
%     'ideal'    -> imports the clean, defect-free version of the road,
%                   with orderly evenly-spaced traffic
%     'nonideal' -> imports the real scanned road with defects, with
%                   mixed/congested traffic
%
%   If xodr_path is left empty, this automatically finds the MOST
%   RECENT matching file inside RESULTS_DIR below (matching
%   *_roadrunner_ideal.xodr for 'ideal', *_roadrunner.xodr for 'nonideal')
%   -- so you don't have to type a path every time.
%
%   REQUIREMENTS: Automated Driving Toolbox, RoadRunner installed & licensed,
%   a RoadRunner project folder already created once.

    if nargin < 1 || isempty(mode)
        error('auto_import_roadrunner:MissingMode', ...
            "Specify mode as 'ideal' or 'nonideal', e.g. auto_import_roadrunner('ideal')");
    end
    mode = lower(mode);
    if ~ismember(mode, {'ideal', 'nonideal'})
        error('auto_import_roadrunner:BadMode', "mode must be 'ideal' or 'nonideal', got '%s'.", mode);
    end

    % ---- EDIT THESE TWO LINES ONCE ----
    RESULTS_DIR = 'C:\path\to\road_analyzer_deploy\road_analyzer\results';  % your backend's job-results folder
    if nargin < 3 || isempty(project_folder)
        project_folder = 'C:\RR\IndianRoadProject';   % your RoadRunner project folder
    end
    % ------------------------------------

    if strcmp(mode, 'ideal')
        filePattern = '*_roadrunner_ideal.xodr';
    else
        filePattern = '*_roadrunner.xodr';   % NOTE: does not match *_ideal.xodr (different suffix)
    end

    if nargin < 2 || isempty(xodr_path)
        fprintf('No file given -- looking for the most recent "%s" export in:\n  %s\n', mode, RESULTS_DIR);
        matches = dir(fullfile(RESULTS_DIR, '**', filePattern));
        if strcmp(mode, 'nonideal')
            % Exclude any *_ideal.xodr that a loose pattern might catch
            matches = matches(~contains({matches.name}, '_ideal.xodr'));
        end
        if isempty(matches)
            error('auto_import_roadrunner:NoneFound', ...
                'No %s files found under %s.\nRun an analysis on the website first so one gets generated.', ...
                filePattern, RESULTS_DIR);
        end
        [~, idx] = max([matches.datenum]);
        xodr_path = fullfile(matches(idx).folder, matches(idx).name);
        fprintf('Using most recent file: %s\n', xodr_path);
    end

    % ---- Safety checks ----
    if ~isfile(xodr_path)
        error('auto_import_roadrunner:FileNotFound', 'XODR file not found: %s', xodr_path);
    end
    if ~isfolder(project_folder)
        error('auto_import_roadrunner:ProjectNotFound', ...
            'RoadRunner project folder not found: %s\nCreate the project once inside RoadRunner first.', ...
            project_folder);
    end

    % ---- 1. Open RoadRunner ----
    fprintf('[1/5] (%s) Opening RoadRunner project: %s\n', mode, project_folder);
    rrApp = roadrunner(project_folder);
    pause(5);

    % ---- 2/3. Import scene ----
    fprintf('[2/5] Importing road from: %s\n', xodr_path);
    try
        importScene(rrApp, xodr_path);
    catch importErr
        error('auto_import_roadrunner:ImportFailed', 'importScene failed: %s', importErr.message);
    end
    fprintf('[3/5] Saving scene...\n');
    saveScene(rrApp);

    % ---- 4. Vehicles (different style per mode) ----
    fprintf('[4/5] Adding %s traffic...\n', mode);
    if strcmp(mode, 'ideal')
        add_vehicles_ideal(rrApp);
    else
        add_vehicles_nonideal(rrApp);
    end

    % ---- 5. Simulate ----
    fprintf('[5/5] Building and running simulation...\n');
    sim = createSimulation(rrApp);
    run(sim);

    fprintf('\nDONE (%s). Road and traffic are in RoadRunner and the simulation is running.\n', mode);
end
