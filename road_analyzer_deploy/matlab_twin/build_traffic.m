function planned = build_traffic(rrApp, mode, speedKmh, roadLength_m, opts)
%BUILD_TRAFFIC  Mixed, moving traffic at the density and speed of the Python twin.
%
%   mode          : 'ideal' or 'nonideal'
%   speedKmh      : stream speed for this road from the twin (ideal: speed at
%                   demand; nonideal: speed in the upstream queue when demand
%                   exceeds the reduced capacity, else speed at demand)
%   roadLength_m  : road length
%   opts (optional struct, every field optional):
%     .projectFolder     RoadRunner project folder
%     .numLanes          lanes on the carriageway (default 2)
%     .totalWidth_m      carriageway width (default 7)
%     .divided           true = one-direction carriageway (all lanes same way)
%     .densityPcuKmLane  density from the twin, PCU/km/lane
%     .avgPcu            PCU per vehicle, converts PCU density to vehicles
%     .targetCount       force an exact vehicle count instead
%     .scenarioFile      file name to save the scenario to
%
%   Spacing follows from density: front-to-front spacing (m) =
%   1000 / (k_PCU / avgPcu), never less than vehicle length + minGap.
%   Returns the number of vehicles planned.

    cfg = twin_config();  tc = cfg.traffic;
    if nargin < 5 || isempty(opts), opts = struct(); end
    mode = lower(char(mode));
    if nargin < 3 || isempty(speedKmh),     speedKmh = tc.defaultSpeedKmh.(mode); end
    if nargin < 4 || isempty(roadLength_m), roadLength_m = 40; end

    nLanes       = max(1, round(getOpt(opts, 'numLanes', 2)));
    totalWidth   = getOpt(opts, 'totalWidth_m', 7.0);
    laneW        = totalWidth / nLanes;
    divided      = logical(getOpt(opts, 'divided', false));
    kPcu         = getOpt(opts, 'densityPcuKmLane', tc.defaultDensityPcuKmLane);
    avgPcu       = getOpt(opts, 'avgPcu', tc.defaultAvgPcu);
    target       = getOpt(opts, 'targetCount', []);
    scenarioFile = char(getOpt(opts, 'scenarioFile', [mode '_traffic.rrscenario']));
    kVeh         = max(kPcu / max(avgPcu, 0.1), 1e-3);     % vehicles/km/lane
    spacing_m    = 1000 / kVeh;                            % front-to-front

    %% ---- lane table: lateral centre t, travel direction
    % Same split as roadrunner_export.py: a divided carriageway has every
    % lane on the right (t < 0, one direction); an undivided road is split.
    if divided, nLeft = 0; else, nLeft = ceil(nLanes/2); end
    nRight = nLanes - nLeft;
    plusDir = 1;  if ~tc.rightLanesTravelPlusX, plusDir = -1; end
    lanes = struct('t',{},'dir',{});
    for i = 1:nRight, lanes(end+1) = struct('t', -(i-0.5)*laneW, 'dir',  plusDir); end %#ok<AGROW>
    for i = 1:nLeft,  lanes(end+1) = struct('t',  (i-0.5)*laneW, 'dir', -plusDir); end %#ok<AGROW>

    %% ---- plan vehicle slots lane by lane at the twin density
    rng(tc.seed);
    cats   = fieldnames(tc.mix);
    wts    = cellfun(@(c) tc.mix.(c), cats);
    cumw   = cumsum(wts) / sum(wts);
    usable = max(roadLength_m - 2*tc.margin_m, 1);
    packLen = (1 - tc.travelReserve) * usable;
    reserve = tc.travelReserve * usable;
    slots = zeros(0,3);                            % [lane index, x centre, category index]
    for li = 1:numel(lanes)
        dirn = lanes(li).dir;
        if dirn > 0
            x = tc.margin_m;                 limit = x + packLen;
        else
            x = roadLength_m - tc.margin_m;  limit = x - packLen;
        end
        while true
            ci  = find(rand <= cumw, 1);
            len = tc.length_m.(cats{ci});
            xc  = x + dirn*len/2;
            far = xc + dirn*len/2;
            if (dirn > 0 && far > limit) || (dirn < 0 && far < limit), break; end
            slots(end+1,:) = [li, xc, ci]; %#ok<AGROW>
            x = far + dirn*max(spacing_m - len, tc.minGap_m);
        end
    end
    if isempty(slots)
        slots = [1, roadLength_m/2, 1];
        warning('build_traffic:RoadTooShort', 'Road is very short -- placing a single vehicle.');
    end

    n = size(slots,1);
    if ~isempty(target), nKeep = min(target, n); else, nKeep = n; end
    nKeep = max(1, min(nKeep, tc.maxVehicles));
    if nKeep < n
        slots = slots(unique(round(linspace(1, n, nKeep))), :);
    end
    planned = size(slots,1);
    fprintf('      Traffic plan (%s): %d vehicles on %d lane(s), %.1f PCU/km/lane (%.0f m spacing), %.1f km/h, %.0f m road.\n', ...
        mode, planned, numel(lanes), kPcu, spacing_m, speedKmh, roadLength_m);

    %% ---- place them
    newScenario(rrApp);
    rrApi = roadrunnerAPI(rrApp);
    scnro = rrApi.Scenario;
    prj   = rrApi.Project;
    A = twin_assets(prj, getOpt(opts, 'projectFolder', ''));

    used  = struct();  for c = 1:numel(cats), used.(cats{c}) = 0; end
    placed = 0;  speedFailed = 0;
    for k = 1:planned
        try
            lane   = lanes(slots(k,1));
            cat    = cats{slots(k,3)};
            startX = slots(k,2);
            used.(cat) = used.(cat) + 1;
            asset  = pickAsset(A, cat, used.(cat));

            side = mod(k,2)*2 - 1;                       % alternates -1 / +1
            lat  = lane.t;
            if strcmp(cat, 'twoWheeler')
                lat = lat + side * min(max(laneW/2 - 0.6, 0), 1.2);   % hug the lane edge
            elseif strcmp(mode, 'nonideal')
                lat = lat + side * tc.weave_m;                        % weave round obstructions
            end

            mps = max(speedKmh, 1) / 3.6;
            % Everyone in a lane drives the SAME distance, so gaps never close.
            dist = min(mps * tc.simSeconds, reserve);
            endX = startX + lane.dir * max(dist, 1);

            car = addActor(scnro, asset, [startX, lat, 0]);
            autoAnchor(car.InitialPoint, PosePreservation="reset-pose");
            if ~setPointSpeed(car.InitialPoint, mps), speedFailed = speedFailed + 1; end

            rrRoute  = car.InitialPoint.Route;
            endPoint = addPoint(rrRoute, [endX, lat, 0]);
            autoAnchor(endPoint, PosePreservation="reset-pose");
            setPointSpeed(endPoint, mps);

            placed = placed + 1;
        catch e
            warning('build_traffic:PlacementFailed', 'Could not place vehicle %d: %s', k, e.message);
        end
    end

    if speedFailed > 0
        warning('build_traffic:SpeedNotSet', ...
            ['Could not set vehicle speeds through the API on this RoadRunner release.\n' ...
             'In RoadRunner Scenario, select the vehicles and set their Initial Speed there.']);
    end
    saveScenario(rrApp, scenarioFile);
    fprintf('      %d of %d vehicles placed, anchored and saved to %s.\n', placed, planned, scenarioFile);
end

%% ---------------------------------------------------------------- helpers
function v = getOpt(opts, name, default)
    if isfield(opts, name) && ~isempty(opts.(name)), v = opts.(name); else, v = default; end
end

function a = pickAsset(A, cat, n)
    pool = A.vehicles.(cat);
    if isempty(pool), pool = A.vehicles.car; end
    if isempty(pool), pool = struct2cell(A.vehicles); pool = [pool{:}]; end
    a = pool{mod(n-1, numel(pool)) + 1};
end

function ok = setPointSpeed(pt, mps)
% Speed (m/s) on a route point -- the Point object has a Speed property.
    ok = true;
    try
        pt.Speed = mps;
    catch
        ok = false;
    end
end
