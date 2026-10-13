function add_defects_to_scene(rrApp, defectPositions, totalWidth_m, roadLength_m, opts)
%ADD_DEFECTS_TO_SCENE  Draws every detected defect so it is CLEARLY VISIBLE.
%
%   WHY THE OLD VERSION WAS HARD TO SEE: each defect was a single traffic
%   cone, whatever its type or size. A 0.4 m pothole or a 1 m barricade is a
%   speck on a road model, so nothing stood out.
%
%   NOW: each defect becomes a cluster of markers over an ENLARGED footprint
%     pothole          ring of cones around the hole
%     barricade        a row of barrier pieces across the blocked width
%     illegal_parking  a parked vehicle at the real lateral position
%     street_vendor    ring of cones
%     garbage          grid of barrels
%   Footprint = max(measured size * scale, minimum size) -- all tunable in
%   twin_config.m. The console prints measured size vs. drawn size, so the
%   enlargement is never hidden.
%
%   HONEST LIMIT (same as roadrunner_export.py): one photo cannot give the
%   distance between defects ALONG the road, so they are spread evenly along
%   it. Their LEFT-RIGHT position is real.
%
%   defectPositions: struct array from the capacity JSON ("defect_positions"):
%                    .type, .lateral_m, .width_m -- one per detected defect.
%   totalWidth_m   : real road width (JSON "total_width_m").
%   roadLength_m   : real road length.
%   opts (optional): .projectFolder, .numLanes, .scenarioFile

    if nargin < 2 || isempty(defectPositions)
        fprintf('      No defects to place (defect_positions was empty).\n');
        return;
    end
    if nargin < 3 || isempty(totalWidth_m), totalWidth_m = 7.0; end
    if nargin < 4 || isempty(roadLength_m), roadLength_m = 40;  end
    if nargin < 5 || isempty(opts),         opts = struct();    end
    if iscell(defectPositions), defectPositions = [defectPositions{:}]; end   % jsondecode quirk

    cfg   = twin_config();  dc = cfg.defect;
    nLanes = max(1, round(getOpt(opts, 'numLanes', 2)));
    laneW  = totalWidth_m / nLanes;
    nLeft  = ceil(nLanes/2);  nRight = nLanes - nLeft;
    tLeft  =  nLeft  * laneW;                 % road edges in the .xodr (t, metres)
    tRight = -nRight * laneW;
    tMid   = (tLeft + tRight) / 2;            % equals 0 for an even lane count
    scenarioFile = char(getOpt(opts, 'scenarioFile', 'nonideal_traffic.rrscenario'));

    n = numel(defectPositions);
    fprintf('      Placing %d defect(s) as enlarged, clearly visible markers...\n', n);

    rrApi = roadrunnerAPI(rrApp);
    scnro = rrApi.Scenario;
    prj   = rrApi.Project;
    A = twin_assets(prj, getOpt(opts, 'projectFolder', ''));

    margin_m  = min(3, roadLength_m * 0.05);
    usable_m  = roadLength_m - 2*margin_m;
    spacing_m = usable_m / max(n, 1);
    maxLen_m  = max(0.3, 0.85 * spacing_m);   % neighbouring defects must not merge

    placedDefects = 0;  placedMarkers = 0;  carCount = 0;
    for i = 1:n
        try
            d    = defectPositions(i);
            type = char(d.type);
            key  = matlab.lang.makeValidName(type);
            if isfield(dc, key), p = dc.(key); else, p = dc.default; end

            measuredW = 0.3;
            if isfield(d, 'width_m') && ~isempty(d.width_m), measuredW = max(double(d.width_m), 0.05); end

            W  = min(max(measuredW * p.scale, p.minWidth_m),  0.9 * totalWidth_m);
            Lg = min(max(measuredW * p.scale, p.minLength_m), maxLen_m);

            % Lateral position: REAL measurement (same formula as
            % roadrunner_export.py), shifted so it stays on the real road for
            % odd lane counts too, and clamped so the footprint stays on the road.
            tCenter = tMid + (d.lateral_m - totalWidth_m / 2);
            tCenter = min(max(tCenter, tRight + W/2), tLeft - W/2);

            posX = margin_m + (i - 0.5) * spacing_m;       % cosmetic spread along the road

            if strcmp(p.kind, 'vehicle')
                carCount = carCount + 1;
                pool = A.vehicles.car;
                if carCount > 1 && ~isempty(A.vehicles.van), pool = A.vehicles.van; end
                if isempty(pool), pool = A.vehicles.car; end
                actor = addActor(scnro, pool{1}, [posX, tCenter, 0]);
                autoAnchor(actor.InitialPoint, PosePreservation="reset-pose");
                try, actor.InitialPoint.Speed = 0; catch, end      % parked: stays put
                nMark = 1;
            else
                P = footprintPoints(p.kind, Lg, W, p.spacing_m, p.maxMarkers);
                prop = A.props.(p.prop);
                nMark = size(P, 1);
                for m = 1:nMark
                    mx = posX + P(m,1);
                    my = min(max(tCenter + P(m,2), tRight + 0.1), tLeft - 0.1);
                    marker = addActor(scnro, prop, [mx, my, 0]);
                    autoAnchor(marker.InitialPoint, PosePreservation="reset-pose");
                end
            end

            placedDefects = placedDefects + 1;
            placedMarkers = placedMarkers + nMark;
            fprintf('        [%d/%d] %-15s measured %.2f m wide -> shown %.1f x %.1f m (%d marker(s)), t=%.2f m, %.1f m along road.\n', ...
                i, n, type, measuredW, Lg, W, nMark, tCenter, posX);
        catch e
            warning('add_defects_to_scene:PlacementFailed', ...
                'Could not place defect %d: %s', i, e.message);
        end
    end

    saveScenario(rrApp, scenarioFile);
    fprintf('      %d of %d defects drawn with %d markers in total; saved to %s.\n', ...
        placedDefects, n, placedMarkers, scenarioFile);
end

%% ---------------------------------------------------------------- helpers
function v = getOpt(opts, name, default)
    if isfield(opts, name) && ~isempty(opts.(name)), v = opts.(name); else, v = default; end
end

function P = footprintPoints(kind, Lg, W, sp, maxN)
% Marker offsets [along, across] (m) around the defect centre.
    sp = max(sp, 0.1);
    switch kind
        case 'ring'
            n = max(6, round(pi * (Lg + W) / 2 / sp));
            a = linspace(0, 2*pi, n + 1)';  a(end) = [];
            P = [Lg/2 * cos(a), W/2 * sin(a)];
        case 'row'
            n = max(2, round(W / sp) + 1);
            P = [zeros(n,1), linspace(-W/2, W/2, n)'];
        case 'single'
            P = [0 0];
        otherwise                                  % 'fill'
            nx = max(1, round(Lg / sp) + 1);
            ny = max(1, round(W  / sp) + 1);
            [X, Y] = meshgrid(spread(Lg, nx), spread(W, ny));
            P = [X(:), Y(:)];
    end
    if size(P,1) > maxN
        P = P(unique(round(linspace(1, size(P,1), maxN))), :);
    end
end

function v = spread(len, n)
    if n == 1, v = 0; else, v = linspace(-len/2, len/2, n); end
end
