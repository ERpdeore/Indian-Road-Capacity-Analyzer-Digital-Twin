function add_vehicles_nonideal(rrApp, numVehicles, speedKmh, roadLength_m, opts)
%ADD_VEHICLES_NONIDEAL  Dense, moving traffic for the DEFECT-AFFECTED road.
%   Thin wrapper kept so existing callers still work; the real work is in
%   build_traffic.m and every setting lives in twin_config.m.
%
%   numVehicles  : optional EXACT count. Leave empty (recommended): vehicles
%                  are spaced at the twin's density for the defect road --
%                  the upstream queue density when demand exceeds the
%                  reduced capacity -- so the defect road shows MORE, slower
%                  vehicles, which is what a bottleneck actually does.
%   speedKmh     : twin speed for the defect road (empty = 30 km/h).
%   roadLength_m : real road length (empty = 40 m).
%   opts         : optional struct, see build_traffic.m (densityPcuKmLane,
%                  avgPcu, divided, projectFolder, numLanes, totalWidth_m, ...).

    if nargin < 2, numVehicles = []; end
    if nargin < 3, speedKmh = []; end
    if nargin < 4, roadLength_m = []; end
    if nargin < 5 || isempty(opts), opts = struct(); end
    if ~isempty(numVehicles), opts.targetCount = numVehicles; end
    opts.scenarioFile = 'nonideal_traffic.rrscenario';

    build_traffic(rrApp, 'nonideal', speedKmh, roadLength_m, opts);
end
