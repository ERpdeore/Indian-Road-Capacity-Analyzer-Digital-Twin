function cfg = twin_config()
%TWIN_CONFIG  Every look-and-feel setting of the RoadRunner twin in ONE place.
%   Edit the numbers below -- no other file needs to change.
%
%   Used by: build_traffic.m, add_defects_to_scene.m, twin_assets.m

%% ===================== TRAFFIC =====================
% Vehicle COUNT and SPEED are not set here: they come from the Python
% digital twin (capacity JSON -> twin.ideal / twin.defect), so both roads
% carry the SAME demand and differ only by what the obstructions do to it.
cfg.traffic.minGap_m       = 1.5;    % bumper-to-bumper gap at jam (queued traffic)
cfg.traffic.margin_m       = 3.0;    % keep clear of the road start / end
cfg.traffic.maxVehicles    = 120;    % rendering cap for very long corridors
cfg.traffic.simSeconds     = 40;     % how long vehicles drive (distance = speed * this)
cfg.traffic.travelReserve  = 0.40;   % share of the road kept free ahead of the traffic
cfg.traffic.weave_m        = 0.25;   % sideways weave on the defect road
cfg.traffic.seed           = 7;      % fixed seed -> identical traffic every run
cfg.traffic.rightLanesTravelPlusX = true;   % OpenDRIVE default: lanes with t<0 drive +x
% Fallbacks used only when no capacity JSON is found
cfg.traffic.defaultDensityPcuKmLane = 30;   % ~ LOS-C density on a 50 km/h urban arterial
cfg.traffic.defaultAvgPcu           = 0.75; % extensions.ASSUMED_COMPOSITION x Indo-HCM Table 5.3, four-lane divided
% Assumed Indian urban mix (same shares as road_analyzer/extensions.py
% ASSUMED_COMPOSITION; autos and LCVs are drawn as vans, two-wheelers as
% two-wheelers). Replace with your classified count.
cfg.traffic.mix      = struct('twoWheeler',0.55,'car',0.25,'van',0.14,'bus',0.03,'truck',0.03);
% Typical lengths (m), used to space vehicles so they never overlap
cfg.traffic.length_m = struct('car',4.0,'twoWheeler',2.0,'truck',8.5,'bus',11.0,'van',3.5);
cfg.traffic.defaultSpeedKmh = struct('ideal',50,'nonideal',30);

%% ===================== DEFECT VISIBILITY =====================
% A real pothole (~0.4 m) or barricade is far too small to see on a road
% model in RoadRunner. Each defect is therefore drawn as a CLUSTER of markers
% over an ENLARGED footprint:
%   footprint = max(measured size * scale, minimum size)
%   kind      : 'ring' (markers around the edge), 'row' (a line across the
%               road), 'fill' (a grid), 'single', 'vehicle' (a parked vehicle)
%   prop      : 'cone', 'barrier' or 'barrel' (falls back to cone if the
%               project has no such prop)
mk = @(kind,L,W,sc,sp,prop,maxN,veh) struct('kind',kind,'minLength_m',L,'minWidth_m',W, ...
        'scale',sc,'spacing_m',sp,'prop',prop,'maxMarkers',maxN,'vehicle',veh);
cfg.defect.default         = mk('fill',   1.0, 1.0, 1.5, 0.40, 'cone',    16, '');
cfg.defect.pothole         = mk('ring',   1.4, 1.4, 1.5, 0.35, 'cone',    24, '');
cfg.defect.barricade       = mk('row',    0.5, 3.0, 1.5, 0.80, 'barrier', 12, '');
cfg.defect.illegal_parking = mk('vehicle',0,   0,   1.0, 0,    'cone',     1, 'car');
cfg.defect.street_vendor   = mk('ring',   1.8, 1.8, 1.2, 0.50, 'cone',    16, '');
cfg.defect.garbage         = mk('fill',   1.2, 1.2, 1.5, 0.40, 'barrel',  16, '');
cfg.defect.tree            = mk('single', 0.5, 0.5, 1.0, 0.50, 'cone',     1, '');
end
