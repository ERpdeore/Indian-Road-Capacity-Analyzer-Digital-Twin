function add_vehicles_ideal(rrApp)
%ADD_VEHICLES_IDEAL  Orderly traffic for the IDEAL (unobstructed) road.
%   Same vehicle type, even lane-center spacing, steady flow -- this is
%   what capacity looks like with no obstructions.

    fprintf('      Placing ideal (orderly) traffic...\n');

    scenario = newScenario(rrApp);

    numVehicles = 4;
    spacing_m   = 15;     % even spacing = free-flowing traffic
    lane_t      = 0;      % centered in lane -- adjust to your lane_width/2 if needed

    for i = 1:numVehicles
        veh = createActor(scenario, 'Vehicle', ActorModel = 'Sedan');
        setPosition(veh, [(i-1) * spacing_m, lane_t, 0]);
    end

    saveScenario(rrApp);
    fprintf('      %d vehicles placed (uniform spacing).\n', numVehicles);
end
