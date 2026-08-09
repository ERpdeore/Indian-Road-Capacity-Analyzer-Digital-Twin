%% ================================================================
%% ROAD DIGITAL TWIN — STANDALONE TEST
%% road_twin_test.m
%%
%% Run this file in MATLAB to see the animation immediately.
%% No dashboard or JSON file needed — uses demo values.
%%
%% Usage:
%%   >> road_twin_test
%% ================================================================

function road_twin_test()

%% --- Demo parameters (replace with your real values) ---
base_dsv         = 1500;      % PCU/hr — IRC:106 Table 2 (2-lane twoway, arterial)
reduced_cap      = 1050;      % PCU/hr — after defects
cap_loss_pct     = 30.0;      % % capacity lost
total_width_m    = 7.0;       % metres
blocked_width_m  = 2.1;       % metres (overlap-aware)
eff_width_m      = 4.9;       % metres
width_factor     = 0.700;     % eff / total
pothole_penalty  = 0.85;      % moderate pothole
worst_depth      = 'moderate';
num_lanes        = 2;
carriageway_key  = '2lane_twoway';
fringe_condition = 'arterial';
traffic_regime   = 'low';
base_veh_hr      = 1500;
reduced_veh_hr   = 1050;
image_name       = 'demo_road.jpg';
defects_found    = 'pothole + street_vendor';

has_pothole   = true;
has_vendor    = true;
has_parking   = false;
has_barricade = false;
has_garbage   = false;
has_tree      = false;
has_cart      = false;

%% --- Derived values ---
FREE_FLOW_SPEED = 50;
vc_ratio        = reduced_cap / base_dsv;
congested_speed = FREE_FLOW_SPEED * (1 - (1 - vc_ratio) * 0.5);

%% --- Layout constants ---
ROAD_LEN  = 100;
LANE_H    = 8;
ROAD_TOP_I = 5;
ROAD_TOP_D = 50;
VEH_LEN   = 4;
VEH_H     = 3;
OBS_X     = 55;
N_VEH     = 12;

headway_i = 3600 / max(base_dsv, 1);
headway_d = 3600 / max(reduced_cap, 1);
spc_i     = max((FREE_FLOW_SPEED/3.6) * headway_i,  6);
spc_d     = max((congested_speed/3.6) * headway_d,  4);

vx_i = linspace(-spc_i*(N_VEH-1), 0, N_VEH)';
vx_d = linspace(-spc_d*(N_VEH-1), 0, N_VEH)';
vs_i = FREE_FLOW_SPEED  / 3.6 * 0.1;
vs_d = congested_speed  / 3.6 * 0.1;

lane_y_i = arrayfun(@(l) ROAD_TOP_I + (l-0.5)*LANE_H, 1:num_lanes);
lane_y_d = arrayfun(@(l) ROAD_TOP_D + (l-0.5)*LANE_H, 1:num_lanes);

%% --- Colours ---
C_GI = [0.11 0.62 0.46];   % green (ideal)
C_GD = [0.89 0.29 0.28];   % red   (defect)
C_RI = [0.55 0.58 0.62];   % road surface ideal
C_RD = [0.50 0.52 0.55];   % road surface defect

%% --- Figure ---
fig = figure('Name', 'Indian Road Capacity Digital Twin', ...
             'Color', [0.09 0.11 0.14], ...
             'Position', [60 60 1200 680], ...
             'NumberTitle', 'off', ...
             'MenuBar', 'none', 'ToolBar', 'none');

ax = axes('Parent', fig, ...
          'Position', [0.01 0.20 0.97 0.76], ...
          'XLim', [0 ROAD_LEN], 'YLim', [0 70], ...
          'Color', [0.09 0.11 0.14], ...
          'XColor', [0.09 0.11 0.14], ...
          'YColor', [0.09 0.11 0.14]);
hold(ax, 'on');

%% --- Draw road surfaces ---
rectangle('Position', [0 ROAD_TOP_I ROAD_LEN LANE_H*num_lanes], ...
          'FaceColor', C_RI, 'EdgeColor', 'none');
rectangle('Position', [0 ROAD_TOP_D ROAD_LEN LANE_H*num_lanes], ...
          'FaceColor', C_RD, 'EdgeColor', 'none');

%% Lane dividers
for ln = 1:num_lanes-1
    for x = 0:8:ROAD_LEN
        line([x x+4], [ROAD_TOP_I+ln*LANE_H ROAD_TOP_I+ln*LANE_H], ...
             'Color', [1 1 1 0.3], 'LineWidth', 1, 'Parent', ax);
        line([x x+4], [ROAD_TOP_D+ln*LANE_H ROAD_TOP_D+ln*LANE_H], ...
             'Color', [1 1 1 0.3], 'LineWidth', 1, 'Parent', ax);
    end
end

%% Road edges
line([0 ROAD_LEN], [ROAD_TOP_I ROAD_TOP_I], 'Color', [1 1 1], 'LineWidth', 2, 'Parent', ax);
line([0 ROAD_LEN], [ROAD_TOP_I+LANE_H*num_lanes ROAD_TOP_I+LANE_H*num_lanes], ...
     'Color', [1 1 1], 'LineWidth', 2, 'Parent', ax);
line([0 ROAD_LEN], [ROAD_TOP_D ROAD_TOP_D], 'Color', [1 1 1], 'LineWidth', 2, 'Parent', ax);
line([0 ROAD_LEN], [ROAD_TOP_D+LANE_H*num_lanes ROAD_TOP_D+LANE_H*num_lanes], ...
     'Color', [1 1 1], 'LineWidth', 2, 'Parent', ax);

%% --- Draw defects ---
blk_px = (blocked_width_m / total_width_m) * ROAD_LEN * 0.35;
rectangle('Position', [OBS_X ROAD_TOP_D blk_px LANE_H*num_lanes], ...
          'FaceColor', [0.89 0.29 0.28 0.2], ...
          'EdgeColor', [0.89 0.29 0.28 0.6], 'LineWidth', 1);

if has_pothole
    theta = linspace(0, 2*pi, 40);
    fill(OBS_X + 1.5 + 1.8*cos(theta), ...
         ROAD_TOP_D + LANE_H*0.4 + 0.9*sin(theta), ...
         [0.25 0.18 0.18], 'EdgeColor', [0.7 0.2 0.2], 'LineWidth', 1.5);
    text(OBS_X + 1.5, ROAD_TOP_D + LANE_H*0.4 + 2.8, ...
         ['Pothole (' worst_depth ')'], ...
         'Color', [1 0.7 0.7], 'FontSize', 7, 'HorizontalAlignment', 'center');
end

if has_vendor
    rectangle('Position', [OBS_X+blk_px*0.5-1.5  ROAD_TOP_D+LANE_H*0.55  3  2.5], ...
              'FaceColor', [0.95 0.68 0.10], 'EdgeColor', [0.75 0.50 0], 'Curvature', 0.1);
    text(OBS_X + blk_px*0.5, ROAD_TOP_D + LANE_H*0.55 + 3.8, 'Vendor', ...
         'Color', [0.95 0.82 0.20], 'FontSize', 7, 'HorizontalAlignment', 'center');
end

if has_parking
    rectangle('Position', [OBS_X+blk_px*0.4-2  ROAD_TOP_D+LANE_H*0.8  4  2], ...
              'FaceColor', [0.89 0.29 0.28], 'EdgeColor', [0.7 0.1 0.1], 'Curvature', 0.25);
    text(OBS_X + blk_px*0.4, ROAD_TOP_D + LANE_H*0.8 - 1.5, 'Illegal Parking', ...
         'Color', [1 0.6 0.6], 'FontSize', 7, 'HorizontalAlignment', 'center');
end

if has_barricade
    for bi = 0:2
        rectangle('Position', [OBS_X+bi*1.8-0.3  ROAD_TOP_D  0.6  LANE_H*num_lanes], ...
                  'FaceColor', [0.95 0.50 0.10], 'EdgeColor', [0.75 0.30 0]);
    end
    text(OBS_X + 1.8, ROAD_TOP_D + LANE_H*num_lanes + 1.5, 'Barricade', ...
         'Color', [1 0.75 0.4], 'FontSize', 7, 'HorizontalAlignment', 'center');
end

%% Blocked zone label
text(OBS_X + blk_px/2, ROAD_TOP_D + LANE_H*num_lanes + 1.2, ...
     sprintf('%.1fm blocked', blocked_width_m), ...
     'Color', [0.89 0.29 0.28], 'FontSize', 8, 'HorizontalAlignment', 'center');

%% --- Road labels ---
text(ROAD_LEN*0.5, ROAD_TOP_I - 2.5, 'IDEAL ROAD - NO DEFECTS', ...
     'Color', C_GI, 'FontSize', 12, 'FontWeight', 'bold', ...
     'HorizontalAlignment', 'center');
text(ROAD_LEN*0.5, ROAD_TOP_D - 2.5, ...
     ['DEFECT ROAD - ' upper(defects_found)], ...
     'Color', C_GD, 'FontSize', 12, 'FontWeight', 'bold', ...
     'HorizontalAlignment', 'center');

%% --- Stats annotations ---
NL = newline;
annotation('rectangle', [0.01 0.01 0.47 0.17], ...
           'Color', C_GI, 'LineWidth', 1.5, 'FaceColor', [0.04 0.14 0.09]);
annotation('rectangle', [0.52 0.01 0.47 0.17], ...
           'Color', C_GD, 'LineWidth', 1.5, 'FaceColor', [0.16 0.05 0.05]);

ideal_str = ['IDEAL ROAD' NL ...
    sprintf('Design Service Volume : %d PCU/hr  |  %d vehicles/hr', ...
            round(base_dsv), round(base_veh_hr)) NL ...
    sprintf('Free-flow speed       : %d km/h  |  Lanes: %d', ...
            round(FREE_FLOW_SPEED), num_lanes) NL ...
    sprintf('Carriageway: %s  |  Fringe: %s  |  Regime: %s', ...
            carriageway_key, fringe_condition, traffic_regime)];

annotation('textbox', [0.01 0.01 0.47 0.17], 'String', ideal_str, ...
           'Color', [0.80 0.96 0.88], 'FontSize', 10, ...
           'FontName', 'Courier New', 'EdgeColor', 'none', ...
           'VerticalAlignment', 'middle', 'HorizontalAlignment', 'center');

defect_str = ['DEFECT ROAD' NL ...
    sprintf('Reduced Capacity : %d PCU/hr  |  %d veh/hr  (-%.1f%%)', ...
            round(reduced_cap), round(reduced_veh_hr), cap_loss_pct) NL ...
    sprintf('Congested speed  : %.1f km/h  |  Width factor: %.3f', ...
            congested_speed, width_factor) NL ...
    sprintf('Pothole penalty  : %.2f  |  Blocked width: %.1f m', ...
            pothole_penalty, blocked_width_m)];

annotation('textbox', [0.52 0.01 0.47 0.17], 'String', defect_str, ...
           'Color', [0.98 0.78 0.78], 'FontSize', 10, ...
           'FontName', 'Courier New', 'EdgeColor', 'none', ...
           'VerticalAlignment', 'middle', 'HorizontalAlignment', 'center');

%% --- Title ---
title_str = sprintf('Indian Road Capacity Digital Twin  |  %s  |  Loss: %.1f%%', ...
                    image_name, cap_loss_pct);
annotation('textbox', [0.01 0.94 0.98 0.05], 'String', title_str, ...
           'Color', [0.95 0.95 0.95], 'FontSize', 12, 'FontWeight', 'bold', ...
           'EdgeColor', 'none', 'HorizontalAlignment', 'center', 'FaceColor', 'none');

%% --- Capacity bars (right side) ---
BAR_X = 88; BAR_W = 4; BAR_H = 16;

rectangle('Position', [BAR_X ROAD_TOP_I+1 BAR_W BAR_H], ...
          'FaceColor', [0.12 0.30 0.18], 'EdgeColor', C_GI);
rectangle('Position', [BAR_X ROAD_TOP_I+1 BAR_W BAR_H], ...
          'FaceColor', C_GI, 'EdgeColor', 'none');
text(BAR_X+BAR_W/2, ROAD_TOP_I+BAR_H+2, ...
     sprintf('%d\nPCU/hr', round(base_dsv)), ...
     'Color', C_GI, 'FontSize', 8, 'HorizontalAlignment', 'center');

rectangle('Position', [BAR_X ROAD_TOP_D+1 BAR_W BAR_H], ...
          'FaceColor', [0.25 0.08 0.08], 'EdgeColor', C_GD);
defect_h = BAR_H * (reduced_cap / base_dsv);
fill_d = rectangle('Position', [BAR_X ROAD_TOP_D+1 BAR_W defect_h], ...
                    'FaceColor', C_GD, 'EdgeColor', 'none');
text(BAR_X+BAR_W/2, ROAD_TOP_D+BAR_H+2, ...
     sprintf('%d\nPCU/hr', round(reduced_cap)), ...
     'Color', C_GD, 'FontSize', 8, 'HorizontalAlignment', 'center');

%% --- Vehicle patches ---
vp_i = gobjects(N_VEH, 1);
vp_d = gobjects(N_VEH, 1);

for v = 1:N_VEH
    ln = mod(v-1, num_lanes) + 1;
    vp_i(v) = rectangle('Position', [vx_i(v) lane_y_i(ln)-VEH_H/2 VEH_LEN VEH_H], ...
                         'FaceColor', C_GI, 'EdgeColor', [1 1 1 0.25], 'Curvature', [0.3 0.4]);
    vp_d(v) = rectangle('Position', [vx_d(v) lane_y_d(ln)-VEH_H/2 VEH_LEN VEH_H], ...
                         'FaceColor', C_GD, 'EdgeColor', [1 1 1 0.25], 'Curvature', [0.3 0.4]);
end

%% --- Animation loop ---
fprintf('\n==========================================\n');
fprintf('  Digital Twin Animation Running\n');
fprintf('  Base DSV    : %d PCU/hr\n', round(base_dsv));
fprintf('  Reduced cap : %d PCU/hr\n', round(reduced_cap));
fprintf('  Loss        : %.1f%%\n', cap_loss_pct);
fprintf('  Defects     : %s\n', defects_found);
fprintf('  Close the figure window to stop.\n');
fprintf('==========================================\n\n');

sim_t = 0;

while isvalid(fig)
    sim_t = sim_t + 0.05;

    %% Move ideal vehicles at constant speed
    vx_i = vx_i + vs_i;
    wrap_i = vx_i > ROAD_LEN + VEH_LEN;
    if any(wrap_i)
        vx_i(wrap_i) = min(vx_i(~wrap_i)) - spc_i * (1:sum(wrap_i))';
    end

    %% Move defect vehicles — slow near obstacle
    for v = 1:N_VEH
        x      = vx_d(v);
        d2obs  = OBS_X - x;

        if d2obs > 0 && d2obs < spc_d * 3
            slow   = min(1, d2obs / (spc_d * 2));
            spd_v  = vs_d * (0.25 + 0.75 * slow);
        elseif x >= OBS_X && x <= OBS_X + blk_px
            spd_v  = vs_d * 0.25;
        elseif x > OBS_X + blk_px
            recovery = min(1, (x - OBS_X - blk_px) / 20);
            spd_v    = vs_d * (0.25 + 0.75 * recovery);
        else
            spd_v  = vs_d;
        end
        vx_d(v) = vx_d(v) + spd_v;
    end

    wrap_d = vx_d > ROAD_LEN + VEH_LEN;
    if any(wrap_d)
        vx_d(wrap_d) = min(vx_d(~wrap_d)) - spc_d * (1:sum(wrap_d))';
    end

    %% Update patch positions and colours
    for v = 1:N_VEH
        ln = mod(v-1, num_lanes) + 1;
        x  = vx_d(v);
        d2obs = OBS_X - x;

        %% Ideal vehicles — always green
        set(vp_i(v), 'Position', [vx_i(v) lane_y_i(ln)-VEH_H/2 VEH_LEN VEH_H]);

        %% Defect vehicles — colour shifts green→orange→red based on zone
        if x >= OBS_X && x <= OBS_X + blk_px
            col = [0.95 0.50 0.10];     % orange = in defect zone
        elseif d2obs > 0 && d2obs < spc_d * 3
            alpha = 1 - d2obs / (spc_d * 3);
            col   = C_GD * (1-alpha) + [0.95 0.50 0.10] * alpha;
        else
            col = C_GD;                 % red = free on defect road
        end

        set(vp_d(v), 'Position', [vx_d(v) lane_y_d(ln)-VEH_H/2 VEH_LEN VEH_H], ...
            'FaceColor', col);
    end

    %% Pulsing capacity bar
    pulse_h = defect_h * (0.88 + 0.12 * sin(sim_t * 2.5));
    set(fill_d, 'Position', [BAR_X ROAD_TOP_D+1 BAR_W min(pulse_h, BAR_H)]);

    drawnow limitrate;
    pause(0.012);
end

fprintf('Animation stopped.\n');
end
