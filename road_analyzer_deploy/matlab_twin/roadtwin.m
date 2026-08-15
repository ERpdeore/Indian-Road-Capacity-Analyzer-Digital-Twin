function roadtwin()
%% ================================================================
%% INDIAN ROAD CAPACITY DIGITAL TWIN
%% File: roadtwin.m
%%
%% USAGE:
%%   1. Open MATLAB
%%   2. cd to folder containing this file
%%   3. Type: roadtwin
%%   4. Press Enter
%%
%% WHAT YOU SEE:
%%   TOP    = Ideal road  : vehicles flow at 50 km/h, full capacity
%%   BOTTOM = Defect road : vehicles slow at obstacle, queue builds
%%
%% VIDEO: roadtwin_video.avi saved in same folder after animation
%% ================================================================

clc;
fprintf('Road Digital Twin starting...\n');

%% ============================================================
%% PARAMETERS  (edit to match your analysis output)
%% ============================================================
BASE_DSV        = 1500;
REDUCED_CAP     = 1050;
CAP_LOSS_PCT    = 30.0;
TOTAL_WIDTH_M   = 7.0;
BLOCKED_M       = 2.1;
WIDTH_FACTOR    = 0.700;
POTHOLE_PENALTY = 0.85;
NUM_LANES       = 2;
DEFECTS         = 'pothole + street vendor';

%% IRC Design Speed (km/h) — based on carriageway type and fringe condition
%% IRC:106-1990 / IRC:64-1990 design speed guidance:
%%   2-lane twoway arterial    = 50 km/h
%%   4-lane divided arterial   = 80 km/h
%%   6-lane divided arterial   = 100 km/h
%%   any collector             = 30 km/h
%%   any sub-arterial 2-lane   = 40 km/h
%% When downloaded from dashboard, this is auto-filled correctly.
FREE_FLOW_SPEED = 50;   %% <-- CHANGE THIS to match your road type

HAS_POTHOLE   = true;
HAS_VENDOR    = true;
HAS_PARKING   = false;
HAS_BARRICADE = false;
HAS_GARBAGE   = false;

SAVE_VIDEO    = true;
VIDEO_SEC     = 8;
VIDEO_FPS     = 20;

%% ============================================================
%% DERIVED
%% ============================================================
FREE_SPD = FREE_FLOW_SPEED;
CONG_SPD = FREE_SPD * (1 - (1 - REDUCED_CAP/BASE_DSV) * 0.5);

fprintf('Base DSV      : %d PCU/hr\n', round(BASE_DSV));
fprintf('Reduced cap   : %d PCU/hr  (%.1f%% loss)\n', round(REDUCED_CAP), CAP_LOSS_PCT);
fprintf('Ideal speed   : %d km/h\n', round(FREE_SPD));
fprintf('Congested spd : %.1f km/h\n', CONG_SPD);
fprintf('Defects       : %s\n\n', DEFECTS);

%% ============================================================
%% LAYOUT
%% ============================================================
RL    = 120;
LH    = 10;
TI    = 8;
TD    = 55;
VW    = 5;
VH    = 6;
NV    = 10;
OX    = 68;
RDH   = LH * NUM_LANES;
BLKW  = max((BLOCKED_M/TOTAL_WIDTH_M)*RL*0.28, 3);

LYI = arrayfun(@(l) TI + (l-0.5)*LH, 1:NUM_LANES);
LYD = arrayfun(@(l) TD + (l-0.5)*LH, 1:NUM_LANES);

SI   = FREE_SPD/3.6*0.18;
SD   = CONG_SPD/3.6*0.18;
SPCI = max(SI*(3600/max(BASE_DSV,1)),    VW+6);
SPCD = max(SD*(3600/max(REDUCED_CAP,1)), VW+3);

VXI = (-SPCI*(NV-1) : SPCI : 0)';
VXD = (-SPCD*(NV-1) : SPCD : 0)';
if length(VXI) > NV, VXI = VXI(1:NV); end
if length(VXD) > NV, VXD = VXD(1:NV); end
NVI = length(VXI);
NVD = length(VXD);
CURD = ones(NVD,1)*SD;

%% ============================================================
%% COLOURS
%% ============================================================
CBG  = [0.08 0.10 0.14];
CRI  = [0.30 0.33 0.38];
CRD  = [0.28 0.30 0.35];
CGI  = [0.13 0.74 0.55];
CGD  = [0.88 0.28 0.28];
CSLO = [0.95 0.52 0.10];
CTGI = [0.20 0.90 0.65];
CTGD = [0.95 0.40 0.40];
CW   = [1.00 1.00 1.00];
CPH  = [0.20 0.14 0.14];
CVN  = [0.95 0.70 0.10];
CPK  = [0.80 0.20 0.20];
CBR  = [0.95 0.50 0.10];

%% ============================================================
%% FIGURE
%% ============================================================
fig = figure('Name','Road Digital Twin','NumberTitle','off',...
    'Color',CBG,'Position',[40 40 1280 700],...
    'MenuBar','none','ToolBar','none','Resize','on');

ax = axes('Parent',fig,'Position',[0.01 0.20 0.97 0.76],...
    'XLim',[0 RL],'YLim',[0 100],...
    'Color',CBG,'XColor',CBG,'YColor',CBG,...
    'XTick',[],'YTick',[]);
hold(ax,'on');

%% ============================================================
%% STATIC ELEMENTS
%% ============================================================

%% Ideal road surface
patch([0 RL RL 0],[TI TI TI+RDH TI+RDH],CRI,'EdgeColor','none','Parent',ax);

%% Defect road surface
patch([0 RL RL 0],[TD TD TD+RDH TD+RDH],CRD,'EdgeColor','none','Parent',ax);

%% Lane dividers
for ln = 1:NUM_LANES-1
    ydi = TI+ln*LH; ydd = TD+ln*LH;
    for xs = 0:10:RL
        xe = min(xs+5,RL);
        line([xs xe],[ydi ydi],'Color',[1 1 1 0.28],'LineWidth',1.2,'Parent',ax);
        line([xs xe],[ydd ydd],'Color',[1 1 1 0.22],'LineWidth',1.2,'Parent',ax);
    end
end

%% Road edges
line([0 RL],[TI TI],     'Color',CW,'LineWidth',2,'Parent',ax);
line([0 RL],[TI+RDH TI+RDH],'Color',CW,'LineWidth',2,'Parent',ax);
line([0 RL],[TD TD],     'Color',CW,'LineWidth',2,'Parent',ax);
line([0 RL],[TD+RDH TD+RDH],'Color',CW,'LineWidth',2,'Parent',ax);

%% Blocked zone
patch([OX OX+BLKW OX+BLKW OX],[TD TD TD+RDH TD+RDH],...
    [0.8 0.15 0.15],'FaceAlpha',0.18,'EdgeColor',[0.9 0.2 0.2],...
    'LineWidth',1.5,'Parent',ax);
text(OX+BLKW/2,TD+RDH+2,sprintf('%.1f m blocked',BLOCKED_M),...
    'Color',CTGD,'FontSize',8,'HorizontalAlignment','center','Parent',ax);

%% Defects
draw_defects_fn(ax,OX,BLKW,TD,LH,NUM_LANES,...
    HAS_POTHOLE,HAS_VENDOR,HAS_PARKING,HAS_BARRICADE,HAS_GARBAGE,...
    CPH,CVN,CPK,CBR);

%% Road labels
text(RL*0.5,TI-3.5,'IDEAL ROAD  -  NO DEFECTS',...
    'Color',CTGI,'FontSize',13,'FontWeight','bold',...
    'HorizontalAlignment','center','Parent',ax);
text(RL*0.5,TD-3.5,['DEFECT ROAD  -  ' upper(DEFECTS)],...
    'Color',CTGD,'FontSize',13,'FontWeight','bold',...
    'HorizontalAlignment','center','Parent',ax);

%% Speed display
spd_i_txt = text(4,TI+RDH/2,sprintf('%d km/h',round(FREE_SPD)),...
    'Color',CTGI,'FontSize',10,'FontWeight','bold','Parent',ax);
spd_d_txt = text(4,TD+RDH/2,sprintf('%.1f km/h',CONG_SPD),...
    'Color',CTGD,'FontSize',10,'FontWeight','bold','Parent',ax);

%% Capacity bars
BX=110; BW=5; BH=RDH*0.85;
patch([BX BX+BW BX+BW BX],[TI+1 TI+1 TI+1+BH TI+1+BH],...
    [0.12 0.30 0.20],'EdgeColor',CTGI,'LineWidth',1,'Parent',ax);
patch([BX BX+BW BX+BW BX],[TI+1 TI+1 TI+1+BH TI+1+BH],...
    CGI,'EdgeColor','none','Parent',ax);
text(BX+BW/2,TI+BH+3,sprintf('%d PCU/hr',round(BASE_DSV)),...
    'Color',CTGI,'FontSize',8,'HorizontalAlignment','center','Parent',ax);

patch([BX BX+BW BX+BW BX],[TD+1 TD+1 TD+1+BH TD+1+BH],...
    [0.28 0.08 0.08],'EdgeColor',CTGD,'LineWidth',1,'Parent',ax);
DBH  = BH*(REDUCED_CAP/BASE_DSV);
fd   = patch([BX BX+BW BX+BW BX],[TD+1 TD+1 TD+1+DBH TD+1+DBH],...
    CGD,'EdgeColor','none','Parent',ax);
text(BX+BW/2,TD+BH+3,sprintf('%d PCU/hr',round(REDUCED_CAP)),...
    'Color',CTGD,'FontSize',8,'HorizontalAlignment','center','Parent',ax);

%% Stats panels
NL = newline;
annotation(fig,'rectangle',[0.01 0.01 0.48 0.17],...
    'Color',CTGI,'LineWidth',1.5,'FaceColor',[0.04 0.14 0.09]);
annotation(fig,'rectangle',[0.51 0.01 0.48 0.17],...
    'Color',CTGD,'LineWidth',1.5,'FaceColor',[0.16 0.05 0.05]);

s1 = ['IDEAL ROAD (IRC:106-1990)' NL ...
      sprintf('Design Service Volume : %d PCU/hr',round(BASE_DSV)) NL ...
      sprintf('Free-flow speed       : %d km/h',round(FREE_SPD)) NL ...
      sprintf('Lanes : %d  |  Full capacity : 100%%',NUM_LANES)];
annotation(fig,'textbox',[0.01 0.01 0.48 0.17],'String',s1,...
    'Color',[0.78 0.95 0.86],'FontSize',10,'FontName','Courier New',...
    'EdgeColor','none','VerticalAlignment','middle','HorizontalAlignment','center');

s2 = ['DEFECT ROAD (Current State)' NL ...
      sprintf('Reduced Capacity : %d PCU/hr  (-%.1f%%)',round(REDUCED_CAP),CAP_LOSS_PCT) NL ...
      sprintf('Congested speed  : %.1f km/h  (was %d km/h)',CONG_SPD,round(FREE_SPD)) NL ...
      sprintf('Width factor : %.3f  |  Pothole penalty : %.2f',WIDTH_FACTOR,POTHOLE_PENALTY)];
annotation(fig,'textbox',[0.51 0.01 0.48 0.17],'String',s2,...
    'Color',[0.98 0.78 0.78],'FontSize',10,'FontName','Courier New',...
    'EdgeColor','none','VerticalAlignment','middle','HorizontalAlignment','center');

annotation(fig,'textbox',[0.01 0.94 0.98 0.05],...
    'String',sprintf('Indian Road Digital Twin  |  Loss: %.1f%%  |  %s',CAP_LOSS_PCT,DEFECTS),...
    'Color',[0.95 0.95 0.95],'FontSize',11,'FontWeight','bold',...
    'EdgeColor','none','HorizontalAlignment','center','FaceColor','none');

%% ============================================================
%% VEHICLE PATCHES
%% ============================================================
vi = gobjects(NVI,1);
vd = gobjects(NVD,1);
sl = gobjects(NVD,1);

for v = 1:NVI
    ln = mod(v-1,NUM_LANES)+1;
    yi = LYI(ln)-VH/2;
    vi(v) = patch(VXI(v)+[0 VW VW 0],yi+[0 0 VH VH],...
        CGI,'EdgeColor',[1 1 1 0.2],'LineWidth',0.5,'Parent',ax);
end
for v = 1:NVD
    ln = mod(v-1,NUM_LANES)+1;
    yd = LYD(ln)-VH/2;
    vd(v) = patch(VXD(v)+[0 VW VW 0],yd+[0 0 VH VH],...
        CGD,'EdgeColor',[1 1 1 0.2],'LineWidth',0.5,'Parent',ax);
    sl(v) = text(VXD(v)+VW/2,yd+VH+1.8,'',...
        'Color',[1.0 0.85 0.40],'FontSize',7,...
        'HorizontalAlignment','center','Parent',ax);
end

%% ============================================================
%% VIDEO WRITER
%% ============================================================
vw = [];
if SAVE_VIDEO
    try
        vw = VideoWriter('roadtwin_video.avi','Motion JPEG AVI');
        vw.FrameRate = VIDEO_FPS;
        vw.Quality   = 90;
        open(vw);
        fprintf('Recording %d sec video at %d fps...\n',VIDEO_SEC,VIDEO_FPS);
    catch me
        fprintf('Video writer error: %s\n',me.message);
        vw = [];
    end
end
total_frames = VIDEO_SEC * VIDEO_FPS;
fc   = 0;
simt = 0;
DT   = 0.05;

%% ============================================================
%% ANIMATION LOOP
%% ============================================================
fprintf('Running. Close figure to stop.\n\n');

while isvalid(fig)
    simt = simt + DT;
    fc   = fc   + 1;

    %% Ideal vehicles - constant speed
    VXI = VXI + SI;
    wi  = VXI > RL+VW;
    if any(wi)
        mn = min(VXI(~wi));
        c  = sum(wi);
        VXI(wi) = mn - SPCI*(1:c)';
    end

    %% Defect vehicles - physics speed
    for v = 1:NVD
        x  = VXD(v);
        d  = OX - x;
        if d > SPCD*4
            tsp = SD;
        elseif d > 0
            tsp = SD*(0.20 + 0.80*d/(SPCD*4));
        elseif x >= OX && x <= OX+BLKW
            tsp = SD*0.15;
        else
            rec = min(1,(x-OX-BLKW)/(SPCD*6));
            tsp = SD*(0.20 + 0.80*rec);
        end
        CURD(v) = CURD(v) + (tsp-CURD(v))*0.15;
        VXD(v)  = VXD(v)  + CURD(v);
    end
    wd = VXD > RL+VW;
    if any(wd)
        mn = min(VXD(~wd));
        c  = sum(wd);
        VXD(wd)  = mn - SPCD*(1:c)';
        CURD(wd) = SD*0.5;
    end

    %% Update ideal patches
    for v = 1:NVI
        set(vi(v),'XData',VXI(v)+[0 VW VW 0]);
    end

    %% Update defect patches + speed labels
    avg_kmh = 0; vis_cnt = 0;
    for v = 1:NVD
        ln = mod(v-1,NUM_LANES)+1;
        yd = LYD(ln)-VH/2;
        x  = VXD(v);
        sr = CURD(v)/SD;
        if sr > 0.75
            col = CGD;
        elseif sr > 0.35
            a   = (0.75-sr)/0.40;
            col = CGD*(1-a)+CSLO*a;
        else
            col = CSLO;
        end
        set(vd(v),'XData',x+[0 VW VW 0],...
                  'YData',yd+[0 0 VH VH],...
                  'FaceColor',col);
        kmh = sr*CONG_SPD;
        if x > -VW && x < RL
            set(sl(v),'Position',[x+VW/2 yd+VH+1.8 0],...
                      'String',sprintf('%.0f',kmh));
            avg_kmh = avg_kmh + kmh;
            vis_cnt = vis_cnt + 1;
        else
            set(sl(v),'String','');
        end
    end

    if vis_cnt > 0
        set(spd_d_txt,'String',sprintf('avg %.1f km/h',avg_kmh/vis_cnt));
    end

    %% Pulse capacity bar
    ph = DBH*(0.88+0.12*sin(simt*2.8));
    set(fd,'YData',[TD+1 TD+1 TD+1+ph TD+1+ph]);

    drawnow limitrate;

    %% Write video frame
    if ~isempty(vw) && fc <= total_frames
        try
            writeVideo(vw,getframe(fig));
        catch
        end
        if fc == total_frames
            close(vw);
            vw = [];
            fprintf('Video saved: roadtwin_video.avi\n');
        end
    end

    pause(0.01);
end

if ~isempty(vw)
    try, close(vw); catch, end
    fprintf('Video saved: roadtwin_video.avi\n');
end
fprintf('Done.\n');

end %% function roadtwin


%% ============================================================
%% DRAW DEFECT OBJECTS
%% ============================================================
function draw_defects_fn(ax,OX,BLKW,RDT,LH,NL,...
        has_ph,has_vn,has_pk,has_br,has_gb,...
        CPH,CVN,CPK,CBR)

RDH  = LH*NL;
midy = RDT + RDH*0.35;

if has_ph
    th   = linspace(0,2*pi,60);
    prx  = min(BLKW*0.28,3.5);
    pry  = min(LH*0.28,2.0);
    pcx  = OX+BLKW*0.25;
    pcy  = midy;
    fill(pcx+prx*cos(th),pcy+pry*sin(th),...
        CPH,'EdgeColor',[0.65 0.18 0.18],'LineWidth',2,'Parent',ax);
    for ang = 0:60:300
        r1=prx*0.7; r2=prx*1.35; ar=deg2rad(ang);
        line([pcx+r1*cos(ar) pcx+r2*cos(ar)],...
             [pcy+r1*sin(ar) pcy+r2*sin(ar)],...
             'Color',[0.55 0.18 0.18],'LineWidth',1,'Parent',ax);
    end
    text(pcx,pcy-pry-1.5,'Pothole',...
        'Color',[1 0.70 0.70],'FontSize',8,'FontWeight','bold',...
        'HorizontalAlignment','center','Parent',ax);
end

if has_vn
    vx=OX+BLKW*0.55; vy=RDT+RDH*0.55;
    vw2=min(BLKW*0.35,5); vh2=LH*0.40;
    patch(vx+[0 vw2 vw2 0],vy+[0 0 vh2 vh2],...
        CVN,'EdgeColor',[0.75 0.50 0],'LineWidth',1.5,'Parent',ax);
    patch(vx-0.5+[0 vw2+1 vw2+1 0],vy+vh2+[0 0 1.2 1.2],...
        [0.95 0.40 0.10],'EdgeColor',[0.75 0.30 0],'Parent',ax);
    text(vx+vw2/2,vy+vh2+2.8,'Street Vendor',...
        'Color',[0.95 0.82 0.20],'FontSize',8,'FontWeight','bold',...
        'HorizontalAlignment','center','Parent',ax);
end

if has_pk
    px=OX+BLKW*0.45; py=RDT+RDH*0.72;
    pw=min(BLKW*0.45,6.5); phh=LH*0.36;
    patch(px+[0 pw pw 0],py+[0 0 phh phh],...
        CPK,'EdgeColor',[0.70 0.10 0.10],'LineWidth',1.5,'Parent',ax);
    patch(px+pw*0.55+[0 pw*0.30 pw*0.30 0],...
          py+[phh*0.15 phh*0.15 phh*0.85 phh*0.85],...
          [0.30 0.55 0.80],'EdgeColor','none','Parent',ax);
    text(px+pw/2,py-1.8,'Illegal Parking',...
        'Color',[1 0.60 0.60],'FontSize',8,'FontWeight','bold',...
        'HorizontalAlignment','center','Parent',ax);
end

if has_br
    for bi=0:2
        bx=OX+bi*(BLKW/3.5);
        patch(bx+[0 1.2 1.2 0],RDT+[0 0 RDH RDH],...
            CBR,'EdgeColor',[0.75 0.30 0],'LineWidth',1,'Parent',ax);
    end
    text(OX+BLKW*0.5,RDT+RDH+2.5,'Barricade',...
        'Color',[1.0 0.75 0.40],'FontSize',8,'FontWeight','bold',...
        'HorizontalAlignment','center','Parent',ax);
end

if has_gb
    gx=OX+BLKW*0.68; gy=RDT+RDH*0.45;
    patch(gx+[0 3.5 4 0.5],gy+[0 0 2.5 2.5],...
        [0.42 0.55 0.28],'EdgeColor',[0.30 0.42 0.18],'Parent',ax);
    text(gx+2,gy-1.5,'Garbage',...
        'Color',[0.78 0.92 0.50],'FontSize',8,...
        'HorizontalAlignment','center','Parent',ax);
end

end %% function draw_defects_fn
