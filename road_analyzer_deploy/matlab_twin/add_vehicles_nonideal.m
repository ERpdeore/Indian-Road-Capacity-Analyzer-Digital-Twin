function add_vehicles_nonideal(rrApp, numVehicles)
%ADD_VEHICLES_NONIDEAL  Traffic for the NON-IDEAL (defect-affected) road.
%   numVehicles: how many cars to place -- normally computed by
%   auto_import_roadrunner.m from your REAL reduced-capacity number
%   (vehicles/hr), so fewer vehicles here visually represents the actual
%   capacity loss your analysis calculated, not an arbitrary guess.
%
%   Vehicles get only a small safe sideways jitter (+/-0.3m) to suggest
%   weaving around obstructions, while staying anchored to the real lane
%   via autoAnchor -- this keeps them from overflowing the road edges,
%   which is what was happening with the larger offsets before.

    if nargin < 2 || isempty(numVehicles)
        numVehicles = 6;
    end

    fprintf('      Placing %d non-ideal vehicles...\n', numVehicles);

    newScenario(rrApp);
    rrApi = roadrunnerAPI(rrApp);
    scnro = rrApi.Scenario;
    prj   = rrApi.Project;

    roadLength_m = 40;   % matches DEFAULT_SEGMENT_LENGTH_M in roadrunner_export.py
    margin_m     = 3;
    usable_m     = roadLength_m - 2*margin_m;
    spacing_m    = usable_m / max(numVehicles, 1);
    driveDist    = min(8, spacing_m * 0.6);

    jitter = 0.3;   % small, safe sideways variation -- stays within the lane

    placed = 0;
    for i = 1:numVehicles
        try
            asset = getAsset(prj, "Vehicles/Sedan.fbx", "VehicleAsset");
            startX = margin_m + (i-1) * spacing_m;
            lane_t = jitter * (mod(i, 2) * 2 - 1);   % alternates +/-jitter

            car = addActor(scnro, asset, [startX, lane_t, 0]);
            autoAnchor(car.InitialPoint, PosePreservation="reset-pose");

            rrRoute = car.InitialPoint.Route;
            endPoint = addPoint(rrRoute, [startX + driveDist, lane_t, 0]);
            autoAnchor(endPoint, PosePreservation="reset-pose");

            placed = placed + 1;
        catch e
            warning('add_vehicles_nonideal:PlacementFailed', ...
                'Could not place/anchor vehicle %d: %s', i, e.message);
        end
    end

    saveScenario(rrApp, 'nonideal_traffic.rrscenario');
    fprintf('      %d of %d vehicles placed and anchored to the road.\n', placed, numVehicles);
end
