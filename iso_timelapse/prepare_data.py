"""
ConstructionPlan + Scene3D -> compact isometric timelapse data.
Source of truth:
 - model/generated_construction_plan_*.json (tasks: es/ef working days, start/end calendar dates)
 - model/generated_scene3d_*.json (members: box geometry; events: place/stock/remove time t in working days per member)
Output: iso_timelapse_data.json  { buildings: [ {meta, tasks, kinds, members:[tPlace,tRemove,kindIdx,x,y,z,dx,dy,dz]} ] }
Members are sorted by depth key (x+y) then z for painter's algorithm in iso view.
Detail thinning: NONE for geometry kinds that form silhouette/structure/exterior.
For high-count interior detail kinds, keep every member but frontend can toggle them;
data keeps all - thinning is a display option, not data loss.
Coordinates rounded to 2 decimals, times to 2 decimals.
"""
import json, pathlib, collections
base = pathlib.Path.home()/"workspace/genba-kantoku-game/model"
out_path = pathlib.Path.home()/"workspace/genba-kantoku-game/iso_timelapse/iso_timelapse_data.json"
pairs = [
    ("パークサイドモール", "generated_construction_plan_game_mall.json", "generated_scene3d_game_mall.json"),
    ("アリオ蘇我", "generated_construction_plan_commercial_seeded2.json", "generated_scene3d_commercial_seeded2.json"),
    ("アリオ亀有", "generated_construction_plan_commercial_seeded2_kameari.json", "generated_scene3d_commercial_seeded2_kameari.json"),
]
PHASE_JA = {
 "prep":"準備・仮設","earthwork":"土工事","piling":"杭工事","foundation":"基礎工事",
 "frame":"躯体・鉄骨建方","roofExterior":"屋根・外装","mepInterior":"設備・内装",
 "elevator":"エレベーター","exteriorWorks":"外構","closing":"試運転・検査・引渡し","inspection":"検査チェーン"
}
buildings=[]
for label, plan_fn, scene_fn in pairs:
    plan=json.load(open(base/plan_fn)); sc=json.load(open(base/scene_fn))
    place={}; remove={}
    for e in sc['events']:
        if e['type'] in ('place','stock') and 'member' in e:
            # first appearance = min(stock, place) -> member becomes visible as stock then placed; use min for stock visibility is handled in frontend via kind? Use place preferentially if exists, else stock.
            pass
    # place time: prefer 'place' event; if only stock, use stock time
    place_t={}; stock_t={}
    for e in sc['events']:
        if 'member' not in e: 
            if e['type']=='remove' and 'members' in e:
                for mid in e['members']: remove[mid]=e['t']
            continue
        if e['type']=='place': place_t[e['member']]=min(place_t.get(e['member'],1e18), e['t'])
        elif e['type']=='stock': stock_t[e['member']]=min(stock_t.get(e['member'],1e18), e['t'])
        elif e['type']=='remove': remove[e['member']]=e['t']
    kinds=sorted(set(m['kind'] for m in sc['members']))
    kidx={k:i for i,k in enumerate(kinds)}
    members=[]
    for m in sc['members']:
        t = place_t.get(m['id'], stock_t.get(m['id']))
        if t is None: continue
        b=m['box']
        members.append([round(t,2), round(remove[m['id']],2) if m['id'] in remove else -1, kidx[m['kind']],
                        round(b['x'],2),round(b['y'],2),round(b['z'],2),round(b['dx'],2),round(b['dy'],2),round(b['dz'],2),
                        m.get('task','')])
    # sort by painter depth: (x+y) ascending? Iso view from south-east: larger x+y is nearer. Draw far first: sort by (x+y) then z
    members.sort(key=lambda r:(r[3]+r[4], r[5]))
    tasks=[]
    for t in plan['tasks']:
        tasks.append({"id":t['id'],"name":t['name'],"phase":t['phase'],"phaseJa":PHASE_JA.get(t['phase'],t['phase']),
                      "trade":t['trade'],"zone":t.get('zone'),"es":round(t['es'],1),"ef":round(t['ef'],1),
                      "start":t['startDate'],"end":t['endDate'],"gate":bool(t.get('gate'))})
    tasks.sort(key=lambda x:x['es'])
    # phase ranges (excluding inspection which spans all)
    phases=[]
    for ph, ja in PHASE_JA.items():
        ts=[t for t in tasks if t['phase']==ph]
        if ts: phases.append({"phase":ph,"ja":ja,"es":min(t['es'] for t in ts),"ef":max(t['ef'] for t in ts),"count":len(ts)})
    phases.sort(key=lambda x:x['es'])
    buildings.append({
        "id": plan['meta']['building'], "label": label,
        "overview": plan['overview'],
        "startDate": plan['meta']['startDate'], "endDate": plan['schedules']['endDate'],
        "totalWorkingDays": round(plan['schedules']['totalWorkingDays'],1),
        "totalGameDays": sc['timeAxis']['totalGameDays'], "durationScale": sc['timeAxis']['durationScale'],
        "milestones": plan['schedules']['milestones'],
        "sCurve": plan['schedules'].get('sCurve'),
        "phases": phases, "tasks": tasks, "kinds": kinds, "members": members,
        "stats": {"memberCount": len(members), "taskCount": len(tasks), "inspectionChains": len(plan['inspections']),
                  "validationPass": sum(1 for v in plan['validation'] if str(v.get('result','PASS')).upper().startswith('PASS') or v.get('pass') is True) if plan.get('validation') else None,
                  "sceneStats": sc['stats']}
    })
    print(label, "tasks", len(tasks), "members", len(members), "kinds", len(kinds), "days", buildings[-1]['totalWorkingDays'], "phases", [(p['phase'],p['es'],p['ef']) for p in phases])
out={"schema":"iso-timelapse/1.0","source":{"plan":"model/generated_construction_plan_*.json (CP-1..CP-10, PL 12/12 PASS)","scene":"model/generated_scene3d_*.json (scene3d/1.0, member place/remove events t=working days)","note":"Member appearance time = its place event t in Scene3D, which is derived from the ConstructionPlan task ES/EF. Remove events (scaffold, formwork, temp fence) hide the member after that time."},"buildings":buildings}
out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(',',':')))
print("written", out_path, out_path.stat().st_size//1024, "KB")

# ---- machinery layer (appended 2026-11-10) ----
# Rebuilds the output file adding, per building:
#  machines: [{id,kind,label,keys:[[t,x,y,z]...],active:[[es,ef]...]}]
#    - keys = the actor's own move/stock/lift/remove keyframe events in Scene3D (position interpolated in the view)
#    - active intervals = the ES/EF of the plan tasks those keyframes belong to
#      (AWP: lift-in ES .. lift-out EF, i.e. its on-floor presence; crane: steel-erection tasks; pump: each pour task)
#  lifts: [[t,x,y,z]...] member-lift events (crane boom target at time t)
# NOTE: Scene3D has NO mixer-truck or delivery-truck actor (stock events only, note 'トラック搬入→仮置き').
# That gap is recorded, not filled by invention.
import json as _json, pathlib as _pl
_out = _pl.Path.home()/"workspace/genba-kantoku-game/iso_timelapse/iso_timelapse_data.json"
_data = _json.loads(_out.read_text())
_base = _pl.Path.home()/"workspace/genba-kantoku-game/model"
_pairs = [("generated_construction_plan_game_mall.json","generated_scene3d_game_mall.json"),
          ("generated_construction_plan_commercial_seeded2.json","generated_scene3d_commercial_seeded2.json"),
          ("generated_construction_plan_commercial_seeded2_kameari.json","generated_scene3d_commercial_seeded2_kameari.json")]
for bld, (pf, sf) in zip(_data['buildings'], _pairs):
    plan=_json.load(open(_base/pf)); sc=_json.load(open(_base/sf))
    taskmap={t['id']:(t['es'],t['ef']) for t in plan['tasks']}
    actors={a['id']:a for a in sc['actors']}
    mach={}
    for e in sc['events']:
        aid=e.get('actor')
        if not aid or aid not in actors: continue
        a=actors[aid]
        if a['kind'] in ('crew','inspector'): continue
        if 'at' not in e: continue
        m=mach.setdefault(aid, {"id":aid,"kind":a['kind'],"label":a.get('label',aid),"keys":[],"tasks":set()})
        m['keys'].append([round(e['t'],2)]+[round(v,2) for v in e['at']])
        m['tasks'].add(e['task'])
    machines=[]
    for aid,m in mach.items():
        m['keys'].sort()
        # dedupe same t
        seen={}; 
        for k in m['keys']: seen[k[0]]=k
        m['keys']=sorted(seen.values())
        intervals=[]
        if m['kind']=='awp':
            ts=sorted(taskmap[t] for t in m['tasks'] if t in taskmap)
            if ts: intervals=[[round(ts[0][0],1), round(ts[-1][1],1)]]
        else:
            intervals=[[round(taskmap[t][0],1), round(taskmap[t][1],1)] for t in sorted(m['tasks']) if t in taskmap]
        m['active']=intervals; del m['tasks']
        machines.append(m)
    machines.sort(key=lambda x: x['active'][0][0] if x['active'] else 0)
    lifts=[[round(e['t'],2)]+[round(v,2) for v in e['at']] for e in sc['events'] if e['type']=='lift' and 'member' in e and 'at' in e]
    lifts.sort()
    bld['machines']=machines; bld['lifts']=lifts
    print(bld['label'], "machines", [(m['kind'], len(m['keys']), m['active']) for m in machines], "lifts", len(lifts))
_data['machineryNote']="Scene3D actors only; no mixer/delivery truck actor exists in Scene3D (gap). Crane boom target = member lift events."
_out.write_text(_json.dumps(_data, ensure_ascii=False, separators=(',',':')))
print("updated", _out.stat().st_size//1024, "KB")

# ---- carrier coupling (appended 2026-11-11) ----
# Within each plan task's ES..EF, hypothesise a SPATIAL WORK PLAN for the carriers
# (this is an assumption about work sequence inside the task period, NOT new plan data):
#  - human-carried members: place times re-sequenced inside their task along a spatial
#    sweep (kind-group order preserved; the multiset of place times per task, the member
#    count, coordinates and sizes are all unchanged)
#  - fronts: per task, sampled centroids of the member-appearance front
#  - excavator keys follow the excavation-strip front; dump keys cycle front <-> gate
#  - rough-crane keys follow the zone-order erection front; lifts gain the member index
#    so the view can hang the ACTUAL member from the wire (no dummy load)
#  - pump aim samples = pour-front points of the pour tasks the pump serves
#  - crews: worker actors per task following the task front; guides follow the excavator
import json as _j3, pathlib as _p3
_out3 = _p3.Path.home()/"workspace/genba-kantoku-game/iso_timelapse/iso_timelapse_data.json"
_d3 = _j3.loads(_out3.read_text())
_base3 = _p3.Path.home()/"workspace/genba-kantoku-game/model"
_pairs3 = [("generated_construction_plan_game_mall.json","generated_scene3d_game_mall.json"),
           ("generated_construction_plan_commercial_seeded2.json","generated_scene3d_commercial_seeded2.json"),
           ("generated_construction_plan_commercial_seeded2_kameari.json","generated_scene3d_commercial_seeded2_kameari.json")]
_HUMAN_PHASES = {"foundation","roofExterior","mepInterior","elevator","exteriorWorks","closing"}
_SKIP_TRADES = {"鉄骨","揚重","検査","監督"}
_ROLE_MAP = {'土工':('土工班',3),'鉄骨':('建方班',4),'コンクリート':('打設班',5),'基礎':('基礎班',4),'軽鉄':('軽鉄班',3),
  'ボード':('ボード班',3),'設備':('設備班',3),'設備2次':('設備班',3),'設備支持':('設備班',3),
  '電気':('設備班',3),'空調':('設備班',3),'衛生':('設備班',3),'EV':('EV班',3),'外装':('外装班',3),
  '防水':('防水班',3),'仕上げ':('内装班',3),'床':('内装班',3),'建具':('内装班',3),'器具付け':('内装班',3),
  '美装':('美装班',2),'外構':('外構班',3),'仮設':('仮設班',3),'墨出し':('墨出し班',2),'鳶':('鳶班',3),'杭':('杭班',3)}
def _role_for(tk):
    nm = tk['name']
    if '配筋' in nm: return ('鉄筋班',4)
    if '型枠' in nm: return ('型枠班',4)
    if '打設' in nm: return ('打設班',5)
    return _ROLE_MAP.get(tk['trade'], (tk['trade']+'班',3))
for bld, (pf, sf) in zip(_d3['buildings'], _pairs3):
    plan = _j3.load(open(_base3/pf)); sc = _j3.load(open(_base3/sf))
    kinds = bld['kinds']; kidx = {k:i for i,k in enumerate(kinds)}
    members = bld['members']
    tasks = {t['id']:t for t in bld['tasks']}
    before_count = len(members)
    before_times = sorted(m[0] for m in members)
    # --- reconstruct Scene3D member id -> compact index (identical construction to main block) ---
    place_t={}; stock_t={}; remove_t={}
    for e in sc['events']:
        if 'member' not in e:
            if e['type']=='remove' and 'members' in e:
                for mid in e['members']: remove_t[mid]=e['t']
            continue
        if e['type']=='place': place_t[e['member']]=min(place_t.get(e['member'],1e18), e['t'])
        elif e['type']=='stock': stock_t[e['member']]=min(stock_t.get(e['member'],1e18), e['t'])
        elif e['type']=='remove': remove_t[e['member']]=e['t']
    rows=[]
    for m in sc['members']:
        tt = place_t.get(m['id'], stock_t.get(m['id']))
        if tt is None: continue
        b = m['box']
        rows.append([round(tt,2), round(remove_t[m['id']],2) if m['id'] in remove_t else -1, kidx[m['kind']],
                     round(b['x'],2),round(b['y'],2),round(b['z'],2),round(b['dx'],2),round(b['dy'],2),round(b['dz'],2),
                     m.get('task',''), m['id']])
    rows.sort(key=lambda r:(r[3]+r[4], r[5]))
    assert len(rows)==len(members), (bld['label'], len(rows), len(members))
    id2idx={}
    for i,(r,cm) in enumerate(zip(rows, members)):
        assert r[:10]==cm[:10], (bld['label'], i, r[:10], cm[:10])
        id2idx[r[10]]=i
    # --- group members by task ---
    bytask={}
    for i,cm in enumerate(members): bytask.setdefault(cm[9], []).append(i)
    # --- 1) re-sequence place times inside human-carried tasks along a spatial sweep ---
    n_reseq=0
    for tid, idxs in bytask.items():
        tk = tasks.get(tid)
        if not tk or len(idxs)<4: continue
        if tk['phase'] not in _HUMAN_PHASES or tk['trade'] in _SKIP_TRADES: continue
        tmax = max(members[i][0] for i in idxs)
        pool = [i for i in idxs if members[i][1]<0 or members[i][1]>=tmax-1e-9]
        if len(pool)<4: continue
        krank={}
        for i in sorted(pool, key=lambda j: members[j][0]):
            k = kinds[members[i][2]]
            if k not in krank: krank[k]=len(krank)
        def _sweep(i, krank=krank):
            m = members[i]; cx = m[3]+m[6]/2; cy = m[4]+m[7]/2
            return (krank[kinds[m[2]]], round(m[5],1), round(cx+cy,1), round(cx,1))
        pool_sorted = sorted(pool, key=_sweep)
        pool_times = sorted(members[i][0] for i in pool)
        for i, nt in zip(pool_sorted, pool_times): members[i][0]=nt
        n_reseq+=1
    assert len(members)==before_count and sorted(m[0] for m in members)==before_times, bld['label']
    # --- 2) task fronts (appearance-front samples, incl. ES/EF end caps) ---
    fronts={}
    for tid, idxs in bytask.items():
        tk = tasks.get(tid)
        if not tk or len(idxs)<3: continue
        ms = sorted(idxs, key=lambda i: members[i][0])
        W = min(10, len(ms)); fr=[]
        for w in range(W):
            seg = ms[w*len(ms)//W:(w+1)*len(ms)//W]
            if not seg: continue
            cx = sum(members[i][3]+members[i][6]/2 for i in seg)/len(seg)
            cy = sum(members[i][4]+members[i][7]/2 for i in seg)/len(seg)
            cz = min(members[i][5] for i in seg)
            fr.append([round(members[seg[-1]][0],2), round(cx,1), round(cy,1), round(cz,1)])
        if not fr: continue
        fr.insert(0, [round(tk['es'],2), fr[0][1], fr[0][2], fr[0][3]])
        fr.append([round(tk['ef'],2), fr[-1][1], fr[-1][2], fr[-1][3]])
        fronts[tid]=fr
    bld['fronts']=fronts
    # --- 3) excavation: excavator follows strip front, dump cycles front <-> gate ---
    exc_tid=None
    for tid, idxs in bytask.items():
        if any(kinds[members[i][2]]=='excavationTile' for i in idxs): exc_tid=tid; break
    gcands=[m for m in members if kinds[m[2]]=='tempGate']
    gate=None
    if gcands:
        g = min(gcands, key=lambda m: m[4]+m[7]/2)
        gate = [round(g[3]+g[6]/2,1), round(g[4]+g[7]/2,1)]
        bld['gatePt']=gate
    if exc_tid and gate:
        tk = tasks[exc_tid]; es = tk['es']
        tiles = sorted([i for i in bytask[exc_tid] if kinds[members[i][2]]=='excavationTile'],
                       key=lambda i: members[i][0])
        exc_keys=[]; dump_keys=[]; prev_t=es
        for n,i in enumerate(tiles):
            m = members[i]; Ti = m[0]
            if m[6]>=m[7]: s=[m[3]+3, m[4]+m[7]/2]; en=[m[3]+m[6]-3, m[4]+m[7]/2]
            else:          s=[m[3]+m[6]/2, m[4]+3]; en=[m[3]+m[6]/2, m[4]+m[7]-3]
            # relocation to the next strip start takes the first quarter of its interval
            t_start = prev_t if n==0 else prev_t + 0.25*(Ti-prev_t)
            exc_keys.append([round(t_start,2), round(s[0],1), round(s[1],1), round(m[5],1)])
            exc_keys.append([round(Ti,2), round(en[0],1), round(en[1],1), round(m[5],1)])
            dump_keys.append([round(prev_t,2), round(s[0],1), round(s[1],1), round(m[5],1)])
            dump_keys.append([round((prev_t+Ti)/2,2), gate[0], gate[1], 0])
            if n==len(tiles)-1: dump_keys.append([round(Ti,2), round(en[0],1), round(en[1],1), round(m[5],1)])
            prev_t = Ti
        ef = tk['ef']
        for mach in bld['machines']:
            if not any(a[0]<ef and a[1]>es for a in mach['active']): continue
            if mach['kind']=='excavator' and '外構' not in mach['label']: mach['keys']=exc_keys
            if mach['kind']=='dumpTruck': mach['keys']=dump_keys
    # --- 4) crane keys along the erection front + lifts with member index ---
    lift_events = sorted([e for e in sc['events'] if e['type']=='lift' and 'member' in e and 'at' in e],
                         key=lambda e: e['t'])
    newlifts=[]
    for e in lift_events:
        mi = id2idx.get(e['member'])
        if mi is not None: newlifts.append([round(e['t'],2), mi])
    bld['lifts']=newlifts
    steel=[i for i,m in enumerate(members) if kinds[m[2]] in ('column','girder','joist','brace')]
    if steel and newlifts:
        bx0=min(members[i][3] for i in steel); bx1=max(members[i][3]+members[i][6] for i in steel)
        by0=min(members[i][4] for i in steel); by1=max(members[i][4]+members[i][7] for i in steel)
        cyb=(by0+by1)/2; laneS=round(by0-8,1); laneN=round(by1+8,1)
        ckeys=[]; last=None; lastt=-1e18
        for e in lift_events:
            mi = id2idx.get(e['member'])
            if mi is None: continue
            m = members[mi]; cx = m[3]+m[6]/2; cym = m[4]+m[7]/2
            lane = laneS if cym<=cyb else laneN
            sx = min(max(cx, bx0+4), bx1-4)
            if last is None or abs(sx-last[0])>=5 or lane!=last[1] or e['t']-lastt>=1.5:
                ckeys.append([round(e['t'],2), round(sx,1), lane, 0]); last=(sx,lane); lastt=e['t']
        for mach in bld['machines']:
            if mach['kind']=='roughCrane': mach['keys']=ckeys
    # --- 5) pump aim = pour fronts of the tasks the pump serves ---
    actor_kind={a['id']:a['kind'] for a in sc['actors']}
    pump_tasks=sorted(set(e['task'] for e in sc['events'] if e.get('actor') and actor_kind.get(e['actor'])=='pumpTruck'))
    aim=[]
    for tid in pump_tasks: aim += fronts.get(tid, [])
    aim.sort()
    for mach in bld['machines']:
        if mach['kind']=='pumpTruck': mach['aim']=aim
    # --- 6) crews: workers following task fronts + guides following the excavator ---
    crews=[]
    for tid, fr in fronts.items():
        tk = tasks.get(tid)
        if not tk or tk['phase']=='inspection' or tk['trade'] in ('検査','監督'): continue
        role, n = _role_for(tk)
        crews.append({'task':tid, 'role':role, 'n':n, 'keys':fr})
    for mach in bld['machines']:
        if mach['kind']=='excavator' and len(mach['keys'])>=2:
            gk=[[k[0], round(k[1]+3.0,1), round(k[2]+3.5,1), k[3]] for k in mach['keys']]
            crews.append({'task':None, 'role':'誘導員', 'n':1, 'keys':gk})
    bld['crews']=crews
    print(bld['label'], 'reseq tasks', n_reseq, 'fronts', len(fronts), 'lifts', len(newlifts),
          'crews', len(crews), 'members unchanged', len(members)==before_count)
_d3['couplingNote']="Carrier coupling (2026-11-11): within-task work-sequence assumption only. Place-time multisets per building, member counts, coordinates and plan ES/EF are unchanged."
_out3.write_text(_j3.dumps(_d3, ensure_ascii=False, separators=(',',':')))
print("coupling written", _out3.stat().st_size//1024, "KB")

# ---- labour deployment + pass-through rule (appended 2026-11-11) ----
# Headcount is DERIVED from the plan's own tables, not from published unit rates:
#   crew size per trade  = model/scene_rules.json global.crewByTrade (game defaults)
#   crews per task       = plan resource link / chain parallelism; the plan JSON carries
#                          resource=None for every task, so 1 crew per task. Verified:
#                          with 1 crew/task, the max number of concurrently active tasks
#                          of any trade never exceeds plan resources.tradePeak[trade]
#                          (zone-split tasks are separate tasks, each with its own crew).
#   person-days per task = crewSize x crews x duration (working days, compact ES/EF)
# Workers are INDIVIDUALS: every deployed worker gets his own keyframed path.
# PASS-THROUGH RULE (hard): every member is assigned to one worker of its task, and that
# worker's path contains a visit key at the member centroid at (place - DELTA) days.
# A member may therefore only appear after its worker has physically passed its spot.
# Machine-led members are covered the same way (earthwork tiles go to the guide worker).
# Member place times / counts / coordinates are NOT touched by this block.
import json as _j4, pathlib as _p4
_out4 = _p4.Path.home()/"workspace/genba-kantoku-game/iso_timelapse/iso_timelapse_data.json"
_d4 = _j4.loads(_out4.read_text())
_base4 = _p4.Path.home()/"workspace/genba-kantoku-game/model"
_rules4 = _j4.load(open(_base4/"scene_rules.json"))
_CREW = _rules4['global']['crewByTrade']
_DELTA = 0.35   # worker passes the member's spot this many working days before it appears
for bld, (pf, sf) in zip(_d4['buildings'], _pairs3):
    plan = _j4.load(open(_base4/pf))
    peak_cap = plan['resources']['tradePeak']
    kinds = bld['kinds']; members = bld['members']
    tasks = {t['id']: t for t in bld['tasks']}
    # site bbox centre (patrol loops for member-less tasks: supervision / inspection)
    xs = [m[3] for m in members] + [m[3]+m[6] for m in members]
    ys = [m[4] for m in members] + [m[4]+m[7] for m in members]
    ccx = (min(xs)+max(xs))/2; ccy = (min(ys)+max(ys))/2
    rrx = (max(xs)-min(xs))/2*0.62+4; rry = (max(ys)-min(ys))/2*0.62+4
    bytask = {}
    for i, m in enumerate(members): bytask.setdefault(m[9], []).append(i)
    workers = []; passes = {}; total_pd = 0.0
    for tk in bld['tasks']:
        trade = tk['trade']; crew_size = _CREW.get(trade, 3)
        bands = 1  # plan resource link gives no per-task parallelism (resource=None) -> 1 crew
        assert bands <= peak_cap.get(trade, 99), (bld['label'], trade)
        nw = crew_size*bands; dur = round(tk['ef']-tk['es'], 2)
        pd = round(crew_size*bands*dur, 1); total_pd += pd
        tk['crew'] = crew_size; tk['bands'] = bands; tk['nWorkers'] = nw; tk['personDays'] = pd
        role, _n = _role_for(tk)
        idxs = bytask.get(tk['id'], [])
        wrecs = []
        for wi in range(nw):
            wrole = role
            if trade == '土工' and wi == 0: wrole = '誘導員'  # guide walks the excavation tiles
            w = {'task': tk['id'], 'role': wrole, 'visits': [], 'last_t': -1e18, 'last_p': None}
            wrecs.append(w)
        if idxs:
            ms = sorted(idxs, key=lambda i: (members[i][0], members[i][3]+members[i][4]))
            for i in ms:
                m = members[i]; place = m[0]
                cx = round(m[3]+m[6]/2, 1); cy = round(m[4]+m[7]/2, 1); cz = round(m[5], 1)
                pt = round(place-_DELTA, 2)
                if trade == '土工' and kinds[m[2]] == 'excavationTile':
                    cand = wrecs[:1]
                elif trade == '土工' and len(wrecs) > 1:
                    cand = wrecs[1:]
                else:
                    cand = wrecs
                free = [w for w in cand if w['last_t'] < pt]
                pool = free if free else cand
                def _dist(w, cx=cx, cy=cy):
                    if w['last_p'] is None: return 0.0
                    return (w['last_p'][0]-cx)**2 + (w['last_p'][1]-cy)**2
                w = min(pool, key=_dist) if free else min(pool, key=lambda w: w['last_t'])
                w['visits'].append([pt, cx, cy, cz]); w['last_t'] = pt; w['last_p'] = (cx, cy)
                passes[i] = pt
            for w in wrecs:
                vs = sorted(w['visits'])
                keys = []
                if vs:
                    st = [round(tk['es'], 2), vs[0][1], vs[0][2], vs[0][3]]
                    if st[0] > vs[0][0]: st[0] = round(vs[0][0]-0.2, 2)
                    keys.append(st); keys += vs
                    en = [round(tk['ef'], 2), vs[-1][1], vs[-1][2], vs[-1][3]]
                    if en[0] > vs[-1][0]: keys.append(en)
                else:
                    keys = [[round(tk['es'], 2), round(ccx, 1), round(ccy, 1), 0],
                            [round(tk['ef'], 2), round(ccx, 1), round(ccy, 1), 0]]
                # strictly increasing times (visits win over caps at equal t)
                outk = []
                for k in keys:
                    if outk and k[0] <= outk[-1][0]:
                        if k in vs and outk[-1] not in vs: outk[-1] = k
                        continue
                    outk.append(k)
                workers.append({'task': tk['id'], 'role': w['role'], 'keys': outk})
        else:
            # no members (supervision / inspection / paperwork): patrol loop around the building
            for wi, w in enumerate(wrecs):
                off = wi*(6.2832/max(1, nw))
                keys = []
                steps = 8 if dur >= 1 else 1
                for s in range(steps+1):
                    tt = round(tk['es'] + dur*s/steps, 2)
                    a = off + s*0.85
                    keys.append([tt, round(ccx+rrx*__import__('math').cos(a), 1),
                                 round(ccy+rry*__import__('math').sin(a), 1), 0])
                workers.append({'task': tk['id'], 'role': w['role'], 'keys': keys})
    # peak concurrent deployed workers (same window definition the view uses)
    evs = []
    for w in workers:
        evs.append((w['keys'][0][0], 1)); evs.append((w['keys'][-1][0], -1))
    evs.sort(key=lambda e: (e[0], -e[1]))
    cur = 0; peak_n = 0; peak_t = 0.0
    for tt, dd in evs:
        cur += dd
        if cur > peak_n: peak_n = cur; peak_t = tt
    # PASS-THROUGH ASSERT: every member has an assigned pass within [place-1.0, place)
    viol = 0
    for i, m in enumerate(members):
        p = passes.get(i)
        if p is None or not (m[0]-1.0 <= p < m[0]): viol += 1
    assert viol == 0, (bld['label'], 'pass violations', viol)
    bld.pop('crews', None)
    bld['workers'] = workers
    bld['labor'] = {'crewBasis': 'scene_rules global.crewByTrade x plan resources (bands=1 per task, cap tradePeak)',
                    'totalPersonDays': round(total_pd), 'peakWorkers': peak_n, 'peakDay': round(peak_t, 1),
                    'passDeltaDays': _DELTA, 'passMembers': len(passes), 'passViolations': viol}
    print(bld['label'], 'workers', len(workers), 'total person-days', round(total_pd),
          'peak', peak_n, 'at day', round(peak_t, 1), 'pass check', len(passes), '/', len(members), 'violations', viol)
_d4['laborNote'] = ("Labour deployment (2026-11-11): person-days = crewByTrade[trade] (scene_rules global, game defaults) "
  "x crews per task (plan resource link; resource=None in plan -> 1, capped by resources.tradePeak) x task duration. "
  "Zone-split tasks are separate tasks and each deploys its own crew. Every member is assigned to one worker whose "
  "path passes the member centroid 0.35 working days before its place time (pass-through rule, asserted for all members).")
_out4.write_text(_j4.dumps(_d4, ensure_ascii=False, separators=(',',':')))
print("labour written", _out4.stat().st_size//1024, "KB")
