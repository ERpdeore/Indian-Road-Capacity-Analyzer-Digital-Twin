function add_vehicles_ideal(rrApp, numVehicles)
%ADD_VEHICLES_IDEAL  Orderly, evenly-spaced traffic for the IDEAL road.
%   numVehicles: how many cars to place (defaults to 6).
%
%   Vehicles are placed centered in the lane (no manual sideways offset)
%   and snapped onto the road via autoAnchor -- this keeps them from
%   ever overflowing the road edges, regardless of the road's real width.

    if nargin < 2 || isempty(numVehicles)
        numVehicles = 6;
    end

    fprintf('      Placing %d ideal (orderly) vehicles...\n', numVehicles);

    newScenario(rrApp);
    rrApi = roadrunnerAPI(rrApp);
    scnro = rrApi.Scenario;
    prj   = rrApi.Project;

    roadLength_m = 40;   % matches DEFAULT_SEGMENT_LENGTH_M in roadrunner_export.py
    margin_m     = 3;    % keep clear of the very start/end of the road
    usable_m     = roadLength_m - 2*margin_m;
    spacing_m    = usable_m / max(numVehicles, 1);
    driveDist    = min(10, spacing_m * 0.6);  % how far each vehicle drives forward

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
