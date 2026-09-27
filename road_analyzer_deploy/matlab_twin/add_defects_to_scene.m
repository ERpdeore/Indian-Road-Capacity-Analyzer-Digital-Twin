function add_defects_to_scene(rrApp, defectsFound, roadLength_m)
%ADD_DEFECTS_TO_SCENE  Places a VISIBLE marker on the road for each real
%   defect type your YOLOv8 model detected in the analyzed photo.
%
%   WHY THIS EXISTS: RoadRunner does NOT automatically draw a 3D shape for
%   generic OpenDRIVE <object> entries (which is how potholes/barricades
%   were stored in the .xodr) unless your specific project already has a
%   custom asset-mapping file configured -- most projects don't. So
%   instead of relying on that import step (which was silently rendering
%   nothing), this places a real, always-available RoadRunner prop
%   (TrafficCone01, bundled in every default project) directly at each
%   defect's approximate position, anchored onto the actual road lane.
%
%   defectsFound: cell array of defect type strings, e.g.
%                 {'pothole','street_vendor'} -- comes straight from
%                 your capacity JSON's "defects_found" field (real YOLOv8
%                 detections, not made up).
%   roadLength_m: real road length, so markers land within the road.

    if nargin < 2 || isempty(defectsFound)
        fprintf('      No defects to place (defects_found was empty).\n');
        return;
    end
    if nargin < 3 || isempty(roadLength_m)
        roadLength_m = 40;
    end

    fprintf('      Placing %d visible defect marker(s) on the road...\n', numel(defectsFound));

    rrApi = roadrunnerAPI(rrApp);
    scnro = rrApi.Scenario;
    prj   = rrApi.Project;

    margin_m  = min(3, roadLength_m * 0.05);
    usable_m  = roadLength_m - 2*margin_m;
    n = numel(defectsFound);
    spacing_m = usable_m / max(n, 1);

    % One consistent, always-available prop for every defect type. A
    % future improvement could map specific defect types to different
    % prop assets (e.g. a barrier mesh for 'barricade'), but that requires
    % knowing which extra props exist in YOUR specific project's library
    % -- TrafficCone01 is guaranteed present in every default project, so
    % it's used here to guarantee something always renders.
    placed = 0;
    for i = 1:n
        try
            markerAsset = getAsset(prj, "Props/TrafficControl/TrafficCone01.fbx", "MovableObjectAsset");
            posX = margin_m + (i-1) * spacing_m + spacing_m/2;
            marker = addActor(scnro, markerAsset, [posX, 0, 0]);
            autoAnchor(marker.InitialPoint, PosePreservation="reset-pose");
            placed = placed + 1;
            fprintf('        [%d/%d] %s marked at %.1fm along the road.\n', i, n, defectsFound{i}, posX);
        catch e
            warning('add_defects_to_scene:PlacementFailed', ...
                'Could not place marker for "%s": %s', defectsFound{i}, e.message);
        end
    end

    fprintf('      %d of %d defect markers placed.\n', placed, n);
end
