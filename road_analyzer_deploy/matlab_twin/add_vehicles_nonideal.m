function add_vehicles_nonideal(rrApp, numVehicles, speedKmh, roadLength_m, opts)
%ADD_VEHICLES_NONIDEAL  Dense, moving traffic for the DEFECT-AFFECTED road.
%   Thin wrapper kept so existing callers still work; the real work is in
%   build_traffic.m and every setting lives in twin_config.m.
%
%   numVehicles  : optional EXACT count. Leave empty (recommended): the count
%                  is the ideal-road traffic scaled by opts.keepFraction
%                  (= real reduced / original capacity), so fewer vehicles
%                  and a lower speed show the REAL capacity loss.
%   speedKmh     : real congested speed (empty = 30 km/h).
%   roadLength_m : real road length (empty = 40 m).
%   opts         : optional struct, see build_traffic.m (keepFraction,
%                  projectFolder, numLanes, totalWidth_m, ...).

    if nargin < 2, numVehicles = []; end
    if nargin < 3, speedKmh = []; end
    if nargin < 4, roadLength_m = []; end
    if nargin < 5 || isempty(opts), opts = struct(); end
    if ~isempty(numVehicles), opts.targetCount = numVehicles; end
    opts.scenarioFile = 'nonideal_traffic.rrscenario';

    build_traffic(rrApp, 'nonideal', speedKmh, roadLength_m, opts);
end
