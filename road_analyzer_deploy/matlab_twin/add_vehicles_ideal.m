function add_vehicles_ideal(rrApp, numVehicles, speedKmh, roadLength_m, opts)
%ADD_VEHICLES_IDEAL  Orderly, dense, moving traffic for the IDEAL road.
%   Thin wrapper kept so existing callers still work; the real work is in
%   build_traffic.m and every setting lives in twin_config.m.
%
%   numVehicles  : optional EXACT count. Leave empty (recommended) to fill the
%                  lanes automatically from the road length and lane count.
%   speedKmh     : real free-flow speed (empty = 50 km/h).
%   roadLength_m : real road length (empty = 40 m).
%   opts         : optional struct, see build_traffic.m (projectFolder, numLanes,
%                  totalWidth_m, ...).

    if nargin < 2, numVehicles = []; end
    if nargin < 3, speedKmh = []; end
    if nargin < 4, roadLength_m = []; end
    if nargin < 5 || isempty(opts), opts = struct(); end
    if ~isempty(numVehicles), opts.targetCount = numVehicles; end
    opts.scenarioFile = 'ideal_traffic.rrscenario';

    build_traffic(rrApp, 'ideal', speedKmh, roadLength_m, opts);
end
