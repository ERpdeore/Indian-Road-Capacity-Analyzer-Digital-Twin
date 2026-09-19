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

    fprintf('[1/5] (%s) Opening RoadRunner project: %s\n', mode, project_folder);
    rrApp = roadrunner(project_folder);
    pause(5);

    fprintf('[2/5] Importing road from: %s\n', xodr_path);
    try
        importScene(rrApp, xodr_path);
    catch importErr
        error('auto_import_roadrunner:ImportFailed', 'importScene failed: %s', importErr.message);
    end
    fprintf('[3/5] Saving scene...\n');
    saveScene(rrApp);

    fprintf('[4/5] Adding %s traffic...\n', mode);
    if strcmp(mode, 'ideal')
        add_vehicles_ideal(rrApp);
    else
        add_vehicles_nonideal(rrApp);
    end

    fprintf('[5/5] Building and running simulation...\n');
    sim = createSimulation(rrApp);
    run(sim);

    fprintf('\nDONE (%s). Road and traffic are in RoadRunner and the simulation is running.\n', mode);
end
