function add_vehicles_nonideal(rrApp)
%ADD_VEHICLES_NONIDEAL  Mixed, congested traffic for the NON-IDEAL road.
%   Different vehicle types, uneven/tighter spacing, vehicles pulled
%   toward the shoulder (as if squeezing past obstructions) -- this is
%   what capacity looks like once the road has real obstructions on it.
%
%   NOTE: model names below (Sedan, SUV, Hatchback, Truck) are RoadRunner's
%   common default library assets. If your RoadRunner installation uses
%   different/renamed vehicle assets, open RoadRunner's Asset Library
%   panel, find the exact names there, and swap them into the `models`
%   list below.

    fprintf('      Placing non-ideal (mixed/congested) traffic...\n');

    scenario = newScenario(rrApp);

    % Mixed vehicle types, representative of Indian mixed traffic
    models   = {'Sedan', 'SUV', 'Hatchback', 'Truck', 'Sedan', 'Hatchback'};
    startX   = [3, 9, 14, 22, 27, 33];      % tighter/uneven spacing = congestion
    lane_t   = [0, -1.2, 0.8, -0.5, 1.5, -1.8];  % irregular lateral offsets =
                                                   % vehicles weaving/squeezing
                                                   % around obstructions

    for i = 1:numel(models)
        veh = createActor(scenario, 'Vehicle', ActorModel = models{i});
        setPosition(veh, [startX(i), lane_t(i), 0]);
    end

    saveScenario(rrApp);
    fprintf('      %d mixed vehicles placed (congested spacing).\n', numel(models));
end
