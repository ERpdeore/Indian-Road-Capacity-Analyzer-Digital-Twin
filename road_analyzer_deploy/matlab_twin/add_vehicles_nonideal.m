function add_vehicles_nonideal(rrApp, numVehicles, speedKmh, roadLength_m)
%ADD_VEHICLES_NONIDEAL  Traffic for the NON-IDEAL (defect-affected) road.
%   numVehicles : how many cars to place -- normally computed by
%   auto_import_roadrunner.m from your REAL reduced-capacity number
%   (vehicles/hr), so fewer vehicles here visually represents the actual
%   capacity loss your analysis calculated, not an arbitrary guess.
%   speedKmh    : real congested speed from the capacity JSON (defaults
%                 to 30 km/h if not supplied).
%   roadLength_m: REAL road length parsed from the .xodr by
%                 auto_import_roadrunner.m (defaults to 40 if not
%                 supplied). Previously hardcoded here.
%
%   Vehicles get only a small safe sideways jitter (+/-0.3m) to suggest
%   weaving around obstructions, while staying anchored to the real lane
%   via autoAnchor -- this keeps them from overflowing the road edges,
%   which is what was happening with the larger offsets before.

    if nargin < 2 || isempty(numVehicles)
        numVehicles = 6;
    end
    if nargin < 3 || isempty(speedKmh)
        speedKmh = 30;   % non-ideal-road default congested speed
    end
    if nargin < 4 || isempty(roadLength_m)
        roadLength_m = 40;   % fallback only -- real value now comes from the caller
    end

    fprintf('      Placing %d non-ideal vehicles on a %.1fm road at %.0f km/h...\n', ...
        numVehicles, roadLength_m, speedKmh);

    newScenario(rrApp);
    rrApi = roadrunnerAPI(rrApp);
    scnro = rrApi.Scenario;
    prj   = rrApi.Project;

    margin_m     = 3;
    usable_m     = max(roadLength_m - 2*margin_m, 1);
    spacing_m    = usable_m / max(numVehicles, 1);

    driveDist = min(spacing_m * 0.6, max(speedKmh / 50 * 8, 2));

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
