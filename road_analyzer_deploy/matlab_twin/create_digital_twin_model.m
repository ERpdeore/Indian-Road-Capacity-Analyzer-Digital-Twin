%% ================================================================
%% Indian Road Capacity Analyzer — Simulink queue model
%% create_digital_twin_model.m
%%
%% Run ONCE to generate road_digital_twin.slx; run_digital_twin.m then
%% simulates it for each analysis.
%%
%% Model (deterministic point queue, same as the Python twin):
%%     dQ/dt = (q - C) / 3600     [PCU/s],  Q >= 0
%% for two capacities fed with the SAME demand q:
%%     ideal road  : C = C0 (Indo-HCM base capacity)
%%     current road: C = reduced capacity from the obstructions
%% Q is the number of PCU stored upstream of the section. When q <= C the
%% integrator sits at its lower limit 0 (no queue).
%%
%% Inputs come from the struct simIn in the base workspace
%% (simIn.demand_pcu_h, simIn.ideal_cap, simIn.defect_cap).
%%
%% Replaces a model that passed capacity through first-order lags
%% (tau = 5 s / 30 s) — capacity does not "ramp up" from zero, so those
%% curves had no physical meaning — and that mapped capacity-loss % to an
%% LOS letter, which needs a V/C ratio.
%% ================================================================

clc; clear; close all;
MODEL_NAME = 'road_digital_twin';
fprintf('Building %s.slx ...\n', MODEL_NAME);

if bdIsLoaded(MODEL_NAME), close_system(MODEL_NAME, 0); end
new_system(MODEL_NAME);
open_system(MODEL_NAME);
POS = @(x,y,w,h) [x, y, x+w, y+h];

%% ---- sources ----
add_block('simulink/Sources/Constant', [MODEL_NAME '/Demand_pcu_h'], ...
    'Value', 'simIn.demand_pcu_h', 'Position', POS(30, 60, 110, 30));
add_block('simulink/Sources/Constant', [MODEL_NAME '/IdealCap_pcu_h'], ...
    'Value', 'simIn.ideal_cap', 'Position', POS(30, 140, 110, 30));
add_block('simulink/Sources/Constant', [MODEL_NAME '/DefectCap_pcu_h'], ...
    'Value', 'simIn.defect_cap', 'Position', POS(30, 260, 110, 30));

%% ---- ideal road queue ----
add_block('simulink/Math Operations/Sum', [MODEL_NAME '/Excess_ideal'], ...
    'Inputs', '+-', 'Position', POS(200, 90, 30, 40));
add_block('simulink/Math Operations/Gain', [MODEL_NAME '/PerSecond_ideal'], ...
    'Gain', '1/3600', 'Position', POS(270, 95, 60, 30));
add_block('simulink/Continuous/Integrator', [MODEL_NAME '/Queue_ideal'], ...
    'InitialCondition', '0', 'LimitOutput', 'on', ...
    'LowerSaturationLimit', '0', 'UpperSaturationLimit', 'inf', ...
    'Position', POS(370, 95, 40, 30));

%% ---- current (defect) road queue ----
add_block('simulink/Math Operations/Sum', [MODEL_NAME '/Excess_defect'], ...
    'Inputs', '+-', 'Position', POS(200, 210, 30, 40));
add_block('simulink/Math Operations/Gain', [MODEL_NAME '/PerSecond_defect'], ...
    'Gain', '1/3600', 'Position', POS(270, 215, 60, 30));
add_block('simulink/Continuous/Integrator', [MODEL_NAME '/Queue_defect'], ...
    'InitialCondition', '0', 'LimitOutput', 'on', ...
    'LowerSaturationLimit', '0', 'UpperSaturationLimit', 'inf', ...
    'Position', POS(370, 215, 40, 30));

%% ---- outputs ----
add_block('simulink/Signal Routing/Mux', [MODEL_NAME '/OutputMux'], ...
    'Inputs', '2', 'Position', POS(470, 100, 10, 140));
add_block('simulink/Sinks/To Workspace', [MODEL_NAME '/SimOut'], ...
    'VariableName', 'dt_simout', 'SampleTime', '60', ...
    'SaveFormat', 'Structure With Time', 'Position', POS(540, 155, 100, 30));
add_block('simulink/Sinks/Scope', [MODEL_NAME '/Scope_Queue'], ...
    'Position', POS(540, 60, 40, 40));

%% ---- wiring ----
add_line(MODEL_NAME, 'Demand_pcu_h/1',    'Excess_ideal/1',  'autorouting', 'on');
add_line(MODEL_NAME, 'IdealCap_pcu_h/1',  'Excess_ideal/2',  'autorouting', 'on');
add_line(MODEL_NAME, 'Demand_pcu_h/1',    'Excess_defect/1', 'autorouting', 'on');
add_line(MODEL_NAME, 'DefectCap_pcu_h/1', 'Excess_defect/2', 'autorouting', 'on');
add_line(MODEL_NAME, 'Excess_ideal/1',     'PerSecond_ideal/1');
add_line(MODEL_NAME, 'PerSecond_ideal/1',  'Queue_ideal/1');
add_line(MODEL_NAME, 'Excess_defect/1',    'PerSecond_defect/1');
add_line(MODEL_NAME, 'PerSecond_defect/1', 'Queue_defect/1');
add_line(MODEL_NAME, 'Queue_ideal/1',  'OutputMux/1', 'autorouting', 'on');
add_line(MODEL_NAME, 'Queue_defect/1', 'OutputMux/2', 'autorouting', 'on');
add_line(MODEL_NAME, 'OutputMux/1', 'SimOut/1',      'autorouting', 'on');
add_line(MODEL_NAME, 'OutputMux/1', 'Scope_Queue/1', 'autorouting', 'on');

%% ---- settings: one-hour horizon ----
set_param(MODEL_NAME, 'StopTime', '3600', 'Solver', 'ode45', 'MaxStep', '10');

save_system(MODEL_NAME, [MODEL_NAME '.slx']);
fprintf('Model saved as %s.slx. Next: run_digital_twin(<capacity json>)\n', MODEL_NAME);
