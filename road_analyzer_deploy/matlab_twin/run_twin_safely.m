function run_twin_safely(mode)
%RUN_TWIN_SAFELY  Entry point used by the .bat launchers.
%   mode: 'ideal' | 'nonideal'  -> RoadRunner 3D twin (auto_import_roadrunner)
%         '2d'                  -> MATLAB-only 2D twin (roadtwin), no RoadRunner needed
%
%   Everything printed is also written to twin_log.txt in this folder, and
%   any error is shown in a popup, so a failed run is never "silent".

    here = fileparts(mfilename('fullpath'));
    cd(here);
    logFile = fullfile(here, 'twin_log.txt');
    if isfile(logFile), delete(logFile); end
    diary(logFile);
    cleanup = onCleanup(@() diary('off'));
    fprintf('=== Digital twin run: %s  (%s) ===\n', mode, datestr(now));
    fprintf('MATLAB %s | folder %s\n', version, here);

    try
        switch lower(mode)
            case {'ideal', 'nonideal'}
                auto_import_roadrunner(lower(mode));
            case '2d'
                files = dir(fullfile(here, '*_roadrunner_capacity.json'));
                corridor = fullfile(here, 'roadrunner_corridor_capacity.json');
                if ~isempty(files)
                    [~, i] = max([files.datenum]);
                    jsonPath = fullfile(files(i).folder, files(i).name);
                elseif isfile(corridor)
                    jsonPath = corridor;
                else
                    jsonPath = '';
                    fprintf(['No *_roadrunner_capacity.json here - showing DEMO numbers.\n' ...
                             'Extract the Digital Twin Bundle into this folder for real data.\n']);
                end
                roadtwin(jsonPath);
            otherwise
                error('run_twin_safely:mode', 'Unknown mode "%s".', mode);
        end
        fprintf('=== Finished OK ===\n');
    catch e
        fprintf(2, '\n=== FAILED ===\n%s\n', getReport(e, 'extended', 'hyperlinks', 'off'));
        errordlg(sprintf('%s\n\nFull details: %s', e.message, logFile), 'Digital twin failed');
    end
end
