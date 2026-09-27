function add_defects_to_scene(rrApp, defectPositions, totalWidth_m, roadLength_m)
%ADD_DEFECTS_TO_SCENE  Places a VISIBLE marker for each REAL defect your
%   YOLOv8 model detected -- one marker per actual detected instance, at
%   its REAL measured position ACROSS the road (lateral position), which
%   is accurate data straight from your photo analysis.
%
%   HONEST LIMIT (same one your own roadrunner_export.py documents): a
%   single photo cannot measure how far apart defects are ALONG the
%   road's length -- that information doesn't exist in one photo. So
%   markers are evenly spread along the road for visual clarity, but
%   their LEFT-RIGHT position is real, not guessed.
%
%   WHY THIS EXISTS AT ALL (instead of the .xodr import just showing
%   them): RoadRunner does not auto-render generic OpenDRIVE <object>
%   entries without a project-specific asset-mapping file most projects
%   don't have -- so this places them directly via script instead,
%   using the same reliable technique as your vehicles.
%
%   defectPositions: struct array (from your capacity JSON's
%                    "defect_positions" field), each with fields
%                    .type, .lateral_m, .width_m -- one per REAL
%                    detected defect instance.
%   totalWidth_m:    real road width (from capacity JSON's "total_width_m")
%   roadLength_m:    real road length, so markers land within the road.

    if nargin < 2 || isempty(defectPositions)
        fprintf('      No defects to place (defect_positions was empty).\n');
        return;
    end
    if nargin < 3 || isempty(totalWidth_m)
        totalWidth_m = 7.0;
    end
    if nargin < 4 || isempty(roadLength_m)
        roadLength_m = 40;
    end

    n = numel(defectPositions);
    fprintf('      Placing %d visible defect marker(s) at REAL measured positions...\n', n);

    rrApi = roadrunnerAPI(rrApp);
    scnro = rrApi.Scenario;
    prj   = rrApi.Project;

    margin_m  = min(3, roadLength_m * 0.05);
    usable_m  = roadLength_m - 2*margin_m;
    spacing_m = usable_m / max(n, 1);

    placed = 0;
    for i = 1:n
        try
            d = defectPositions(i);

            % REAL lateral position: convert "meters from the road's left
            % edge" (what your photo analysis measured) into "meters left/
            % right of the road's centerline" (what RoadRunner positions
            % use) -- this is the exact same formula your own
            % roadrunner_export.py uses for the .xodr version, so both
            % stay consistent with each other.
            t_offset = d.lateral_m - totalWidth_m / 2;

            % Longitudinal position: cosmetic spread only (see docstring
            % above) -- a single photo has no real data for this.
            posX = margin_m + (i-1) * spacing_m + spacing_m/2;

            markerAsset = getAsset(prj, "Props/TrafficControl/TrafficCone01.fbx", "MovableObjectAsset");
            marker = addActor(scnro, markerAsset, [posX, t_offset, 0]);
            autoAnchor(marker.InitialPoint, PosePreservation="reset-pose");

            placed = placed + 1;
            fprintf('        [%d/%d] %s at %.2fm from centerline (real), %.1fm along road (spread for clarity).\n', ...
                i, n, d.type, t_offset, posX);
        catch e
            warning('add_defects_to_scene:PlacementFailed', ...
                'Could not place marker %d: %s', i, e.message);
        end
    end

    fprintf('      %d of %d defect markers placed at their real measured positions.\n', placed, n);
end
