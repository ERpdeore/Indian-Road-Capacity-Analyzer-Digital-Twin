%% ================================================================
%% INDIAN ROAD CAPACITY DIGITAL TWIN
%% roadtwin.m
%%
%% USAGE (in MATLAB Command Window):
%%   >> roadtwin
%%
%% This script animates two roads side by side:
%%   TOP    - Ideal road: full capacity, vehicles at 50 km/h
%%   BOTTOM - Defect road: reduced capacity, vehicles slow near obstacle
%%
%% HOW TO USE WITH YOUR REAL DATA:
%%   1. Run analysis on your dashboard
%%   2. Click "Download MATLAB Script" button
%%   3. Rename downloaded file to roadtwin.m
%%   4. Run: >> roadtwin
%%
%% ================================================================

function roadtwin()

%% ---- PARAMETERS (auto-filled by dashboard, or edit manually) ----
base_dsv        = 1500;       %% PCU/hr  IRC:106 Table 2
reduced_cap     = 1050;       %% PCU/hr  after defects
cap_loss_pct    = 30.0;       %% % capacity lost
total_width_m   = 7.0;        %% metres
blocked_m       = 2.1;        %% metres blocked (overlap-aware)
width_factor    = 0.700;      %% effective/total width
pothole_penalty = 0.85;       %% 0.95 shallow / 0.85 moderate / 0.70 deep
num_lanes       = 2;
image_name      = 'demo_road.jpg';
defects_found   = 'pothole + street vendor';
has_pothole     = true;
has_vendor      = true;
has_parking     = false;
has_barricade   = false;

%% ---- DERIVED ----
FREE_SPD   = 50;
vc         = reduced_cap / base_dsv;
cong_spd   = FREE_SPD * (1 - (1 - vc) * 0.5);
h_i        = 3600 / max(base_dsv,  1);
h_d        = 3600 / max(reduced_cap, 1);
spc_i      = max((FREE_SPD/3.6)*h_i,  6);
spc_d      = max((cong_spd/3.6)*h_d,  4);

%% ---- LAYOUT ----
RL  = 100;  LH = 8;
TI  = 5;    TD = 50;
VL  = 4;    VH = 3;
OX  = 55;   NV = 12;
BPX = (blocked_m/total_width_m)*RL*0.35;

ly_i = arrayfun(@(l) TI + (l-0.5)*LH, 1:num_lanes);
ly_d = arrayfun(@(l) TD + (l-0.5)*LH, 1:num_lanes);

vx_i = linspace(-spc_i*(NV-1), 0, NV)';
vx_d = linspace(-spc_d*(NV-1), 0, NV)';
vs_i = FREE_SPD/3.6*0.1;
vs_d = cong_spd/3.6*0.1;

%% ---- COLOURS ----
CI = [0.11 0.62 0.46];
CD = [0.89 0.29 0.28];
RI = [0.55 0.58 0.62];
RD = [0.50 0.52 0.55];

%% ---- FIGURE ----
fig = figure('Name','Road Digital Twin','Color',[0.09 0.11 0.14],...
    'Position',[60 60 1200 680],'NumberTitle','off',...
    'MenuBar','none','ToolBar','none');
ax = axes('Parent',fig,'Position',[0.01 0.22 0.97 0.74],...
    'XLim',[0 RL],'YLim',[0 70],...
    'Color',[0.09 0.11 0.14],'XColor',[0.09 0.11 0.14],'YColor',[0.09 0.11 0.14]);
hold(ax,'on');

%% ---- DRAW ROADS ----
rectangle('Position',[0 TI RL LH*num_lanes],'FaceColor',RI,'EdgeColor','none');
rectangle('Position',[0 TD RL LH*num_lanes],'FaceColor',RD,'EdgeColor','none');

for ln = 1:num_lanes-1
    yd_i = TI+ln*LH; yd_d = TD+ln*LH;
    for x = 0:8:RL
        line([x x+4],[yd_i yd_i],'Color',[1 1 1 0.25],'LineWidth',1);
        line([x x+4],[yd_d yd_d],'Color',[1 1 1 0.25],'LineWidth',1);
    end
end
line([0 RL],[TI TI],'Color',[1 1 1],'LineWidth',2);
line([0 RL],[TI+LH*num_lanes TI+LH*num_lanes],'Color',[1 1 1],'LineWidth',2);
line([0 RL],[TD TD],'Color',[1 1 1],'LineWidth',2);
line([0 RL],[TD+LH*num_lanes TD+LH*num_lanes],'Color',[1 1 1],'LineWidth',2);

%% ---- BLOCKED ZONE ----
rectangle('Position',[OX TD BPX LH*num_lanes],...
    'FaceColor',[0.89 0.29 0.28 0.2],'EdgeColor',[0.89 0.29 0.28 0.5],'LineWidth',1);
text(OX+BPX/2, TD+LH*num_lanes+1.5, sprintf('%.1fm blocked',blocked_m),...
    'Color',[0.89 0.29 0.28],'FontSize',8,'HorizontalAlignment','center');

%% ---- DRAW DEFECTS ----
if has_pothole
    th = linspace(0,2*pi,40);
    fill(OX+2+1.8*cos(th), TD+LH*0.4+0.9*sin(th),...
        [0.25 0.18 0.18],'EdgeColor',[0.7 0.2 0.2],'LineWidth',1.5);
    text(OX+2, TD+LH*0.4+2.8,'Pothole',...
        'Color',[1 0.7 0.7],'FontSize',7,'HorizontalAlignment','center');
end
if has_vendor
    rectangle('Position',[OX+BPX*0.5-1.5 TD+LH*0.55 3 2.5],...
        'FaceColor',[0.95 0.68 0.10],'EdgeColor',[0.75 0.50 0],'Curvature',0.1);
    text(OX+BPX*0.5, TD+LH*0.55+3.8,'Vendor',...
        'Color',[0.95 0.82 0.20],'FontSize',7,'HorizontalAlignment','center');
end
if has_parking
    rectangle('Position',[OX+BPX*0.4-2 TD+LH*0.8 4 2],...
        'FaceColor',[0.89 0.29 0.28],'EdgeColor',[0.7 0.1 0.1],'Curvature',0.25);
    text(OX+BPX*0.4, TD+LH*0.8-1.5,'Illegal Parking',...
        'Color',[1 0.6 0.6],'FontSize',7,'HorizontalAlignment','center');
end
if has_barricade
    for bi = 0:2
        rectangle('Position',[OX+bi*1.8-0.3 TD 0.6 LH*num_lanes],...
            'FaceColor',[0.95 0.50 0.10],'EdgeColor',[0.75 0.30 0]);
    end
end

%% ---- LABELS ----
text(RL*0.5, TI-2.5,'IDEAL ROAD - NO DEFECTS',...
    'Color',CI,'FontSize',12,'FontWeight','bold','HorizontalAlignment','center');
text(RL*0.5, TD-2.5,['DEFECT ROAD - ' upper(defects_found)],...
    'Color',CD,'FontSize',12,'FontWeight','bold','HorizontalAlignment','center');

%% ---- CAPACITY BARS ----
BAX=88; BAW=4; BAH=16;
rectangle('Position',[BAX TI+1 BAW BAH],'FaceColor',[0.10 0.28 0.16],'EdgeColor',CI);
rectangle('Position',[BAX TI+1 BAW BAH],'FaceColor',CI,'EdgeColor','none');
text(BAX+BAW/2, TI+BAH+2.5,sprintf('%d PCU/hr',round(base_dsv)),...
    'Color',CI,'FontSize',8,'HorizontalAlignment','center');

rectangle('Position',[BAX TD+1 BAW BAH],'FaceColor',[0.24 0.08 0.08],'EdgeColor',CD);
dh = BAH*(reduced_cap/base_dsv);
fd = rectangle('Position',[BAX TD+1 BAW dh],'FaceColor',CD,'EdgeColor','none');
text(BAX+BAW/2, TD+BAH+2.5,sprintf('%d PCU/hr',round(reduced_cap)),...
    'Color',CD,'FontSize',8,'HorizontalAlignment','center');

%% ---- STATS PANEL ----
NL = newline;
annotation('rectangle',[0.01 0.01 0.47 0.18],'Color',CI,'LineWidth',1.5,'FaceColor',[0.04 0.14 0.09]);
annotation('rectangle',[0.52 0.01 0.47 0.18],'Color',CD,'LineWidth',1.5,'FaceColor',[0.16 0.05 0.05]);

s1 = ['IDEAL ROAD' NL ...
      sprintf('DSV : %d PCU/hr', round(base_dsv)) NL ...
      sprintf('Speed : %d km/h  |  Lanes : %d', round(FREE_SPD), num_lanes) NL ...
      sprintf('Carriageway : %s', strrep(image_name,'.jpg',''))];
annotation('textbox',[0.01 0.01 0.47 0.18],'String',s1,...
    'Color',[0.80 0.96 0.88],'FontSize',10,'FontName','Courier New',...
    'EdgeColor','none','VerticalAlignment','middle','HorizontalAlignment','center');

s2 = ['DEFECT ROAD' NL ...
      sprintf('Capacity : %d PCU/hr  (-%.1f%%)', round(reduced_cap), cap_loss_pct) NL ...
      sprintf('Speed : %.1f km/h  |  Width factor : %.3f', cong_spd, width_factor) NL ...
      sprintf('Pothole penalty : %.2f  |  Blocked : %.1f m', pothole_penalty, blocked_m)];
annotation('textbox',[0.52 0.01 0.47 0.18],'String',s2,...
    'Color',[0.98 0.78 0.78],'FontSize',10,'FontName','Courier New',...
    'EdgeColor','none','VerticalAlignment','middle','HorizontalAlignment','center');

ttl = sprintf('Indian Road Digital Twin  |  %s  |  Loss: %.1f%%', image_name, cap_loss_pct);
annotation('textbox',[0.01 0.94 0.98 0.05],'String',ttl,...
    'Color',[0.95 0.95 0.95],'FontSize',12,'FontWeight','bold',...
    'EdgeColor','none','HorizontalAlignment','center','FaceColor','none');

%% ---- VEHICLE PATCHES ----
vpi = gobjects(NV,1);
vpd = gobjects(NV,1);
for v = 1:NV
    ln = mod(v-1,num_lanes)+1;
    vpi(v) = rectangle('Position',[vx_i(v) ly_i(ln)-VH/2 VL VH],...
        'FaceColor',CI,'EdgeColor',[1 1 1 0.2],'Curvature',[0.3 0.4]);
    vpd(v) = rectangle('Position',[vx_d(v) ly_d(ln)-VH/2 VL VH],...
        'FaceColor',CD,'EdgeColor',[1 1 1 0.2],'Curvature',[0.3 0.4]);
end

%% ---- ANIMATION ----
fprintf('\nDigital Twin running. Close figure to stop.\n');
fprintf('Base DSV  : %d PCU/hr\n', round(base_dsv));
fprintf('Reduced   : %d PCU/hr  (-%.1f%%)\n', round(reduced_cap), cap_loss_pct);
fprintf('Defects   : %s\n\n', defects_found);

st = 0;
while isvalid(fig)
    st = st + 0.05;

    %% Ideal — constant speed
    vx_i = vx_i + vs_i;
    wr = vx_i > RL+VL;
    if any(wr)
        vx_i(wr) = min(vx_i(~wr)) - spc_i*(1:sum(wr))';
    end

    %% Defect — slow near obstacle
    for v = 1:NV
        x = vx_d(v);
        d = OX - x;
        if d > 0 && d < spc_d*3
            sp = vs_d*(0.25 + 0.75*min(1, d/(spc_d*2)));
        elseif x >= OX && x <= OX+BPX
            sp = vs_d*0.25;
        elseif x > OX+BPX
            sp = vs_d*(0.25 + 0.75*min(1,(x-OX-BPX)/20));
        else
            sp = vs_d;
        end
        vx_d(v) = vx_d(v) + sp;
    end
    wr2 = vx_d > RL+VL;
    if any(wr2)
        vx_d(wr2) = min(vx_d(~wr2)) - spc_d*(1:sum(wr2))';
    end

    %% Update patches
    for v = 1:NV
        ln = mod(v-1,num_lanes)+1;
        x  = vx_d(v);
        d  = OX - x;
        if x >= OX && x <= OX+BPX
            col = [0.95 0.50 0.10];
        elseif d > 0 && d < spc_d*3
            a = 1 - d/(spc_d*3);
            col = CD*(1-a) + [0.95 0.50 0.10]*a;
        else
            col = CD;
        end
        set(vpi(v),'Position',[vx_i(v) ly_i(ln)-VH/2 VL VH]);
        set(vpd(v),'Position',[vx_d(v) ly_d(ln)-VH/2 VL VH],'FaceColor',col);
    end

    %% Pulse defect bar
    ph = dh*(0.88 + 0.12*sin(st*2.5));
    set(fd,'Position',[BAX TD+1 BAW min(ph,BAH)]);

    drawnow limitrate;
    pause(0.012);
end
fprintf('Stopped.\n');
end
