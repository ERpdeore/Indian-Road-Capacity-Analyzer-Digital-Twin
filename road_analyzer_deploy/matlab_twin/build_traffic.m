function planned = build_traffic(rrApp, mode, speedKmh, roadLength_m, opts)
%BUILD_TRAFFIC  Dense, mixed, MOVING traffic for the ideal or defect road.
%
%   Replaces the old "6 sedans that barely move". Vehicles are
%     * a mix of cars, two-wheelers, trucks, buses and vans (twin_config.m)
%     * packed lane by lane with a real gap, so they never overlap
%     * given a speed and a route, so they actually drive when you press Play
%     * fewer on the defect road, in proportion to the REAL capacity loss
%
%   mode          : 'ideal' or 'nonideal'
%   speedKmh      : real free-flow (ideal) or congested (nonideal) speed
%   roadLength_m  : real road length
%   opts (optional struct, every field optional):
%     .projectFolder  RoadRunner project folder (lets twin_assets list your real assets)
%     .numLanes       lanes on the road (default 2)
%     .totalWidth_m   road width in metres (default 7)
%     .keepFraction   nonideal only: reduced/original capacity, 0..1 (default 1)
%     .targetCount    force an exact vehicle count instead
%     .scenarioFile   file name to save the scenario to
%
%   Returns the number of vehicles planned.

    cfg = twin_config();  tc = cfg.traffic;
    if nargin < 5 || isempty(opts), opts = struct(); end
    mode = lower(char(mode));
    if nargin < 3 || isempty(speedKmh),     speedKmh = tc.defaultSpeedKmh.(mode); end
    if nargin < 4 || isempty(roadLength_m), roadLength_m = 40; end

    nLanes       = max(1, round(getOpt(opts, 'numLanes', 2)));
    totalWidth   = getOpt(opts, 'totalWidth_m', 7.0);
    laneW        = totalWidth / nLanes;
    keepFraction = getOpt(opts, 'keepFraction', 1);
    target       = getOpt(opts, 'targetCount', []);
    scenarioFile = char(getOpt(opts, 'scenarioFile', [mode '_traffic.rrscenario']));

    %% ---- lane table: lateral centre t, travel direction, rank (1 = inner)
    nLeft  = ceil(nLanes/2);               % same split as roadrunner_export.py
    nRight = nLanes - nLeft;
    plusDir = 1;  if ~tc.rightLanesTravelPlusX, plusDir = -1; end
    lanes = struct('t',{},'dir',{},'rank',{});
    for i = 1:nRight, lanes(end+1) = struct('t', -(i-0.5)*laneW, 'dir',  plusDir, 'rank', i); end %#ok<AGROW>
    for i = 1:nLeft,  lanes(end+1) = struct('t',  (i-0.5)*laneW, 'dir', -plusDir, 'rank', i); end %#ok<AGROW>

    %% ---- plan the vehicle slots lane by lane (no overlaps, fixed seed)
    rng(tc.seed);
    cats   = fieldnames(tc.mix);
    wts    = cellfun(@(c) tc.mix.(c), cats);
    cumw   = cumsum(wts) / sum(wts);
    usable = max(roadLength_m - 2*tc.margin_m, 1);
    packLen = (1 - tc.travelReserve) * usable;     % traffic starts in this part,
    reserve = tc.travelReserve * usable;           % and drives into the rest
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
            x = far + dirn*tc.gap_m;
        end
    end
    if isempty(slots)
        slots = [1, roadLength_m/2, 1];
        warning('build_traffic:RoadTooShort', 'Road is very short -- placing a single vehicle.');
    end

    %% ---- how many to show
    n      = size(slots,1);
    nIdeal = min(n, tc.maxVehicles);
    if ~isempty(target)
        nKeep = min(target, n);
    elseif strcmp(mode, 'nonideal')
        nKeep = max(min(tc.minVehicles, nIdeal), round(nIdeal * min(max(keepFraction,0),1)));
    else
        nKeep = nIdeal;
    end
    nKeep = max(1, min(nKeep, tc.maxVehicles));
    if nKeep < n
        slots = slots(unique(round(linspace(1, n, nKeep))), :);   % thin evenly: gaps only grow
    end
    planned = size(slots,1);
    fprintf('      Traffic plan (%s): %d vehicles on %d lane(s), %.0f km/h, %.0f m road.\n', ...
        mode, planned, numel(lanes), speedKmh, roadLength_m);

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

            kmh = speedKmh * (1 - tc.laneSpeedStep * (lane.rank - 1));
            mps = kmh / 3.6;
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
