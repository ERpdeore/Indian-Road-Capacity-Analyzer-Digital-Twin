function add_vehicles_ideal(rrApp, numVehicles, speedKmh, roadLength_m)
%ADD_VEHICLES_IDEAL  Orderly, evenly-spaced traffic for the IDEAL road.
%   numVehicles : how many cars to place (defaults to 6).
%   speedKmh    : free-flow speed for this road, from the real capacity
%                 JSON (defaults to 50 km/h if not supplied). Used to
%                 scale how far each vehicle's initial route point sits
%                 ahead of it, so a faster road visibly shows vehicles
%                 further along their lane, not just more of them.
%   roadLength_m: REAL road length parsed from the .xodr by
%                 auto_import_roadrunner.m (defaults to 40 if not
%                 supplied). Previously this was hardcoded here, which
%                 silently ignored the actual road length and could
%                 place vehicles past the end of shorter/longer roads.
%
%   Vehicles are placed centered in the lane (no manual sideways offset)
%   and snapped onto the road via autoAnchor -- this keeps them from
%   ever overflowing the road edges, regardless of the road's real width.

    if nargin < 2 || isempty(numVehicles)
        numVehicles = 6;
    end
    if nargin < 3 || isempty(speedKmh)
        speedKmh = 50;   % ideal-road default free-flow speed
    end
    if nargin < 4 || isempty(roadLength_m)
        roadLength_m = 40;   % fallback only -- real value now comes from the caller
    end

    fprintf('      Placing %d ideal (orderly) vehicles on a %.1fm road at %.0f km/h...\n', ...
        numVehicles, roadLength_m, speedKmh);

    newScenario(rrApp);
    rrApi = roadrunnerAPI(rrApp);
    scnro = rrApi.Scenario;
    prj   = rrApi.Project;

    margin_m     = 3;    % keep clear of the very start/end of the road
    usable_m     = max(roadLength_m - 2*margin_m, 1);
    spacing_m    = usable_m / max(numVehicles, 1);

    % Faster roads => each vehicle's initial route point sits further
    % ahead, visually implying more forward motion; capped so it never
    % overlaps the next vehicle's start position.
    driveDist = min(spacing_m * 0.6, max(speedKmh / 50 * 10, 3));

    placed = 0;
    for i = 1:numVehicles
        try
            asset = getAsset(prj, "Vehicles/Sedan.fbx", "VehicleAsset");
            startX = margin_m + (i-1) * spacing_m;
            car = addActor(scnro, asset, [startX, 0, 0]);   % lane_t = 0: centered in lane

            autoAnchor(car.InitialPoint, PosePreservation="reset-pose");

            rrRoute = car.InitialPoint.Route;
            endPoint = addPoint(rrRoute, [startX + driveDist, 0, 0]);
            autoAnchor(endPoint, PosePreservation="reset-pose");

            placed = placed + 1;
        catch e
            warning('add_vehicles_ideal:PlacementFailed', ...
                'Could not place/anchor vehicle %d: %s', i, e.message);
        end
    end

    saveScenario(rrApp, 'ideal_traffic.rrscenario');
    fprintf('      %d of %d vehicles placed and anchored to the road.\n', placed, numVehicles);
end
