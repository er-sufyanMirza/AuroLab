"""
dashboard/pages/10_digital_twin.py - AuroLab OT-2 Digital Twin
Full 3D robot simulation. No GPU required. Three.js r128.
"""
import json
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).parent.parent.parent))
sys.path.insert(0, str(_Path(__file__).parent.parent.parent / 'dashboard'))
import streamlit as st
import httpx
from shared import inject_css, render_nav, api_get as _api_get

st.set_page_config(page_title="Digital Twin - AuroLab", page_icon="⚗", layout="wide", initial_sidebar_state="collapsed")
inject_css()
render_nav("twin")

API_BASE = "http://localhost:8080"

def api_get(path):
    try:
        r = httpx.get(f"{API_BASE}{path}", timeout=4.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

history    = st.session_state.get("protocol_history", [])
live_steps = history[0].get("steps", []) if history else []
lab_state  = api_get("/api/v1/vision/current") or {}
labware    = lab_state.get("labware_map", {}) or {
    "1":"96_well_plate","2":"96_well_plate","3":"plate_reader_slot",
    "5":"tube_rack","7":"incubator_slot","11":"tip_rack_300ul","12":"waste_container",
}

SLOT_XZ = {
    "1":[14.4,10.0],"2":[132.5,10.0],"3":[250.6,10.0],
    "4":[14.4,75.1],"5":[132.5,75.1],"6":[250.6,75.1],
    "7":[14.4,140.2],"8":[132.5,140.2],"9":[250.6,140.2],
    "10":[14.4,205.3],"11":[132.5,205.3],"12":[250.6,205.3],
}
LH = {"96_well_plate":14.5,"384_well_plate":14.5,"tip_rack_300ul":65.0,
      "tip_rack_200ul":65.0,"tip_rack_10ul":60.0,"tip_rack_1000ul":95.0,
      "tube_rack":45.0,"tube_rack_1.5ml":45.0,"waste_container":50.0,
      "plate_reader_slot":80.0,"incubator_slot":100.0,"generic":30.0}
LC = {"96_well_plate":"#1a5fb4","384_well_plate":"#1a5fb4","tip_rack_300ul":"#e5a50a",
      "tip_rack_200ul":"#e5a50a","tube_rack":"#9141ac","tube_rack_1.5ml":"#9141ac",
      "waste_container":"#5c5c5c","plate_reader_slot":"#26a269","incubator_slot":"#c64600","generic":"#7c7c7c"}

lw_js = []
for slot, ltype in labware.items():
    pos = SLOT_XZ.get(str(slot))
    if not pos: continue
    lw_js.append({"slot":str(slot),"type":ltype,"x":pos[0]+58.5,"z":pos[1]+58.5,
                  "h":LH.get(ltype,30.0),"color":LC.get(ltype,"#7c7c7c")})

DEMO = [
    {"type":"home","label":"Home - initialise","slot":None},
    {"type":"pick_up_tip","label":"Pick up tip - slot 11","slot":11},
    {"type":"aspirate","label":"Aspirate 50 uL from slot 1","slot":1,"vol":50},
    {"type":"dispense","label":"Dispense 50 uL to slot 2","slot":2,"vol":50},
    {"type":"mix","label":"Mix 5x in slot 2","slot":2},
    {"type":"drop_tip","label":"Eject tip to slot 12","slot":12},
    {"type":"pick_up_tip","label":"Pick up tip - slot 11","slot":11},
    {"type":"aspirate","label":"Aspirate 25 uL from slot 1","slot":1,"vol":25},
    {"type":"dispense","label":"Dispense 25 uL to slot 2","slot":2,"vol":25},
    {"type":"drop_tip","label":"Eject tip to slot 12","slot":12},
    {"type":"centrifuge","label":"Centrifuge 3000 rpm 5 min","slot":None},
    {"type":"incubate","label":"Incubate 37C 30 min slot 7","slot":7},
    {"type":"read_absorbance","label":"Read absorbance 562nm slot 3","slot":3},
    {"type":"home","label":"Home - protocol complete","slot":None},
]

if live_steps:
    import re
    def _s(inst, d=None):
        m = re.search(r"slot\s*(\d+)", inst, re.I)
        return int(m.group(1)) if m else d
    cmds = [{"type":"home","label":"Home - start","slot":None}]
    for s in live_steps:
        inst = s.get("instruction","").lower()
        lbl  = s["instruction"][:55]
        if any(k in inst for k in ["pipette","aspirate","transfer","add","aliquot"]):
            cmds.append({"type":"aspirate","label":lbl,"slot":_s(inst,1),"vol":50})
        elif "dispense" in inst:
            cmds.append({"type":"dispense","label":lbl,"slot":_s(inst,2),"vol":50})
        elif "centrifuge" in inst or "spin" in inst:
            cmds.append({"type":"centrifuge","label":lbl,"slot":None})
        elif "incubate" in inst or "warm" in inst:
            cmds.append({"type":"incubate","label":lbl,"slot":_s(inst,7)})
        elif "read" in inst or "absorbance" in inst:
            cmds.append({"type":"read_absorbance","label":lbl,"slot":_s(inst,3)})
        elif "mix" in inst or "vortex" in inst:
            cmds.append({"type":"mix","label":lbl,"slot":_s(inst,2)})
        elif "shake" in inst:
            cmds.append({"type":"shake","label":lbl,"slot":_s(inst,5)})
        else:
            cmds.append({"type":"pause","label":lbl,"slot":None})
    cmds.append({"type":"home","label":"Home - complete","slot":None})
    sim_cmds = cmds if len(cmds) > 2 else DEMO
else:
    sim_cmds = DEMO

cmds_j = json.dumps(sim_cmds)
lw_j   = json.dumps(lw_js)
sp_j   = json.dumps({k:[v[0]+58.5,v[1]+58.5] for k,v in SLOT_XZ.items()})

st.markdown("## Digital Twin - OT-2 Live Simulation")
st.markdown("3D robot simulation - **Drag** to orbit - **Scroll** to zoom - **Click log entries** to jump to step")

# Inject the data into the HTML template
HTML = open(__file__).read()
# We build the HTML as a string below

_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
html,body{margin:0;padding:0;width:100%;height:100%;background:#0c0c10;overflow:hidden;font-family:'IBM Plex Mono',monospace}
#wrap{display:flex;width:100%;height:720px}
#sidebar{width:260px;flex-shrink:0;background:#0f0f14;border-right:1px solid #1e1e28;display:flex;flex-direction:column;height:720px}
#hdr{padding:10px 12px;border-bottom:1px solid #1e1e28}
#hdr h1{font-size:11px;font-weight:500;color:#a78bfa}
#hdr p{font-size:9px;color:#444458;margin-top:1px}
#spanel{padding:8px 12px;border-bottom:1px solid #1e1e28}
#slabel{font-size:10px;color:#c8c8d0;min-height:28px;line-height:1.5}
#stype{font-size:8px;color:#7c6af7;letter-spacing:.08em;margin-top:2px;text-transform:uppercase}
#pbar{height:2px;background:#1e1e28;margin-top:5px;border-radius:1px}
#pfill{height:100%;background:#7c6af7;width:0%;border-radius:1px;transition:width .4s}
#ctl{padding:7px 12px;border-bottom:1px solid #1e1e28;display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.btn{background:#1a1a24;border:1px solid #2a2a38;color:#c8c8d0;font-size:10px;padding:4px 8px;border-radius:3px;cursor:pointer;transition:all .15s;font-family:inherit}
.btn:hover{background:#252533;border-color:#7c6af7;color:#a78bfa}
.btn.on{background:#2a1f4a;border-color:#7c6af7;color:#a78bfa}
#spv{font-size:9px;color:#a78bfa;min-width:24px}
#log{flex:1;overflow-y:auto;padding:4px 0;height:1px}
#log::-webkit-scrollbar{width:2px}
#log::-webkit-scrollbar-thumb{background:#222230}
.le{padding:3px 12px;font-size:9px;border-left:2px solid #111118;cursor:pointer;line-height:1.5}
.le:hover{background:#141420}
.le.on{background:#1a1428;border-left-color:#7c6af7;color:#d0d0dc}
.le.done{color:#2a2a3a;border-left-color:#1a1a24}
.le.pend{color:#1e1e2e}
.sn{color:#2a2a38;margin-right:4px}
.lt{font-size:7px;display:inline-block;padding:1px 3px;border-radius:2px;margin-right:3px;vertical-align:middle}
.t-home{background:#1a1a24;color:#444458}
.t-pick_up_tip{background:#172208;color:#6a9e1a}
.t-drop_tip{background:#221708;color:#cc8800}
.t-aspirate{background:#081522;color:#3a9dbf}
.t-dispense{background:#08221a;color:#3a9d8f}
.t-mix{background:#181222;color:#9070c0}
.t-centrifuge{background:#220812;color:#c05050}
.t-incubate{background:#172208;color:#80a830}
.t-read_absorbance{background:#081222;color:#50b0c0}
.t-shake{background:#221808;color:#c09020}
.t-pause{background:#181818;color:#505060}
#cv_wrap{flex:1;position:relative}
#cv{display:block}
#flash{position:absolute;inset:0;background:rgba(220,50,50,0);pointer-events:none;transition:background .3s}
#hint{position:absolute;top:8px;right:8px;font-size:8px;color:#1e1e2e;text-align:right;line-height:2;pointer-events:none}
#statbox{position:absolute;bottom:8px;right:8px;font-size:9px;color:#2a2a3a;text-align:right;line-height:1.9}
</style>
</head>
<body>
<div id="wrap">
  <div id="sidebar">
    <div id="hdr"><h1>AuroLab Digital Twin</h1><p>OT-2 Three.js r128</p></div>
    <div id="spanel">
      <div id="slabel">Ready - press Play</div>
      <div id="stype">-</div>
      <div id="pbar"><div id="pfill"></div></div>
    </div>
    <div id="ctl">
      <button class="btn" id="btnPrev" onclick="doPrev()">&#9664;</button>
      <button class="btn on" id="btnPlay" onclick="doPlay()">&#9654; Play</button>
      <button class="btn" id="btnNext" onclick="doNext()">&#9654;</button>
      <button class="btn" onclick="doReset()">&#10227;</button>
      <input type="range" min="1" max="8" value="3" id="spRange" style="width:45px" oninput="doSpd(this.value)">
      <span id="spv">1x</span>
    </div>
    <div id="log"></div>
  </div>
  <div id="cv_wrap">
    <canvas id="cv"></canvas>
    <div id="flash"></div>
    <div id="hint"><span>Drag: orbit</span><span>Scroll: zoom</span></div>
    <div id="statbox">
      <span id="sc">Steps: 0/0</span>
      <span id="sv2">Vol: 0 uL</span>
      <span id="st2">Tips: 0</span>
    </div>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const CMDS=CMDS_DATA;
const LW=LW_DATA;
const SP=SP_DATA;

// ---- sizes ----
const SIDEBAR=260;
function CW(){return Math.max(400,window.innerWidth-SIDEBAR-4);}
function CH(){return 720;}

// ---- renderer ----
const cvEl=document.getElementById('cv');
cvEl.width=CW(); cvEl.height=CH();
cvEl.style.width=CW()+'px'; cvEl.style.height=CH()+'px';

const renderer=new THREE.WebGLRenderer({canvas:cvEl,antialias:true});
renderer.setPixelRatio(window.devicePixelRatio||1);
renderer.setSize(CW(),CH());
renderer.shadowMap.enabled=true;
renderer.setClearColor(0x0c0c10,1);

const scene=new THREE.Scene();
scene.fog=new THREE.Fog(0x0c0c10,700,1500);
const camera=new THREE.PerspectiveCamera(42,CW()/CH(),1,2000);

// ---- lights ----
scene.add(new THREE.AmbientLight(0x304050,0.8));
const sun=new THREE.DirectionalLight(0xffffff,1.0);
sun.position.set(300,500,200);
sun.castShadow=true;
sun.shadow.mapSize.width=sun.shadow.mapSize.height=1024;
sun.shadow.camera.left=-450;sun.shadow.camera.right=450;
sun.shadow.camera.top=450;sun.shadow.camera.bottom=-450;
sun.shadow.camera.far=1400;
scene.add(sun);
const fill=new THREE.DirectionalLight(0x4466aa,0.3);
fill.position.set(-200,200,-300);scene.add(fill);
const rim=new THREE.DirectionalLight(0x7c6af7,0.18);
rim.position.set(0,50,400);scene.add(rim);

// ---- helpers ----
function mkBox(w,h,d,col,shininess,alpha){
  const mat=new THREE.MeshPhongMaterial({color:col,shininess:shininess||30});
  if(alpha!==undefined&&alpha<1){mat.transparent=true;mat.opacity=alpha;}
  const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat);
  m.castShadow=true;m.receiveShadow=true;return m;
}
function mkCyl(rt,rb,h,seg,col,sh){
  const m=new THREE.Mesh(new THREE.CylinderGeometry(rt,rb,h,seg||12),
    new THREE.MeshPhongMaterial({color:col,shininess:sh||60}));
  m.castShadow=true;return m;
}
function edgeLines(mesh,col){
  const l=new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({color:col||0x223344,transparent:true,opacity:0.3}));
  l.position.copy(mesh.position);l.rotation.copy(mesh.rotation);return l;
}

// ---- deck ----
const deck=mkBox(400,10,300,0x1a1a2a,5);
deck.position.set(196,-5,140);scene.add(deck);

const railMat=new THREE.MeshPhongMaterial({color:0x252535,shininess:20});
[[400,7,7,196,0,-3],[400,7,7,196,0,283],[7,7,300,-3,0,140],[7,7,300,395,0,140]].forEach(([w,h,d,x,y,z])=>{
  const r=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),railMat);
  r.position.set(x,y,z);r.receiveShadow=true;scene.add(r);
});
const divMat=new THREE.MeshPhongMaterial({color:0x1e1e2e});
for(let c=1;c<=3;c++){
  const div=new THREE.Mesh(new THREE.BoxGeometry(2,16,290),divMat);
  div.position.set(c*118-5,8,140);scene.add(div);
}
for(let r=1;r<=3;r++){
  const div=new THREE.Mesh(new THREE.BoxGeometry(390,16,2),divMat);
  div.position.set(196,8,r*65.1);scene.add(div);
}

// slot labels
function makeLabel(txt,x,z){
  const c2=document.createElement('canvas');c2.width=80;c2.height=40;
  const ctx=c2.getContext('2d');
  ctx.fillStyle='#1a2a3a';ctx.font='bold 20px monospace';
  ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(txt,40,20);
  const plane=new THREE.Mesh(new THREE.PlaneGeometry(32,16),
    new THREE.MeshBasicMaterial({map:new THREE.CanvasTexture(c2),transparent:true,opacity:0.5}));
  plane.rotation.x=-Math.PI/2;plane.position.set(x,0.8,z);scene.add(plane);
}
[[1,14.4,10],[2,132.5,10],[3,250.6,10],[4,14.4,75.1],[5,132.5,75.1],[6,250.6,75.1],
 [7,14.4,140.2],[8,132.5,140.2],[9,250.6,140.2],[10,14.4,205.3],[11,132.5,205.3],[12,250.6,205.3]]
  .forEach(([n,sx,sz])=>makeLabel(String(n),sx+58.5,sz+58.5));

// ---- labware ----
const lwMeshes={};
LW.forEach(item=>{
  const col=parseInt(item.color.replace('#',''),16);
  const b=mkBox(114,item.h,114,col,60,0.88);
  b.position.set(item.x,item.h/2,item.z);scene.add(b);
  const wf=edgeLines(b,col);scene.add(wf);
  lwMeshes[item.slot]={mesh:b,origCol:col,ox:item.x,oy:item.h/2};
});

// ---- gantry ----
// X-rail (horizontal beam)
const xRail=mkBox(420,12,12,0x888898,90);
xRail.position.set(196,228,140);scene.add(xRail);
// Upright posts
const postMat=new THREE.MeshPhongMaterial({color:0x666680,shininess:70});
[-10,290].forEach(z=>{
  const post=new THREE.Mesh(new THREE.BoxGeometry(12,248,12),postMat);
  post.position.set(196,112,z);post.castShadow=true;scene.add(post);
  const foot=new THREE.Mesh(new THREE.BoxGeometry(26,12,26),postMat);
  foot.position.set(196,-6,z);scene.add(foot);
});

// ---- arm ----
const armGroup=new THREE.Group();
// Z-carriage block
const carriage=mkBox(32,24,32,0x555568,80);
carriage.position.set(0,0,0);armGroup.add(carriage);
// Pipette body
const pipBody=mkCyl(5,5,78,12,0x444458,60);
pipBody.position.set(0,-45,0);armGroup.add(pipBody);
// Nozzle
const nozzle=mkCyl(3,1.5,20,10,0x333345,40);
nozzle.position.set(0,-91,0);armGroup.add(nozzle);
// Tip (hidden until pick_up_tip)
const tipMesh=mkCyl(2.5,0.8,32,8,0xd4a000,100);
tipMesh.position.set(0,-111,0);tipMesh.visible=false;armGroup.add(tipMesh);
// Plunger rod
const plungerMesh=mkCyl(1.5,1.5,58,8,0x7c6af7,80);
plungerMesh.position.set(0,-10,0);armGroup.add(plungerMesh);

armGroup.position.set(196,224,140);scene.add(armGroup);

// ---- scan beam ----
let scanBeam=null;
function showScanBeam(x,z){
  if(scanBeam){scene.remove(scanBeam);scanBeam=null;}
  scanBeam=new THREE.Mesh(
    new THREE.BoxGeometry(3,80,3),
    new THREE.MeshPhongMaterial({color:0x80deea,transparent:true,opacity:0.75,
      emissive:0x006070,emissiveIntensity:0.6}));
  scanBeam.position.set(x,40,z);scene.add(scanBeam);
  setTimeout(()=>{if(scanBeam){scene.remove(scanBeam);scanBeam=null;}},
    1200/SPDS[spdIdx]);
}

// ---- particles ----
const particles=[];
const pGeo=new THREE.SphereGeometry(1.8,6,6);
const pMats={
  a:new THREE.MeshPhongMaterial({color:0x4fc3f7,transparent:true,opacity:0.88}),
  d:new THREE.MeshPhongMaterial({color:0x4db6ac,transparent:true,opacity:0.88}),
  m:new THREE.MeshPhongMaterial({color:0xb39ddb,transparent:true,opacity:0.82}),
};
function spawnParticles(x,z,t,n){
  n=n||12;
  for(let i=0;i<n;i++){
    const p=new THREE.Mesh(pGeo,pMats[t]||pMats.d);
    const angle=Math.random()*Math.PI*2;
    const speed=0.5+Math.random()*0.9;
    p.position.set(x,62,z);
    p._vx=Math.sin(angle)*speed*0.35;
    p._vy=1.6+Math.random()*2.2;
    p._vz=Math.cos(angle)*speed*0.35;
    p._life=1.0;
    scene.add(p);particles.push(p);
  }
}
function tickParticles(){
  for(let i=particles.length-1;i>=0;i--){
    const p=particles[i];
    p._vy-=0.14;
    p.position.x+=p._vx;p.position.y+=p._vy;p.position.z+=p._vz;
    p._life-=0.028;
    p.material.opacity=Math.max(0,p._life*0.88);
    p.scale.setScalar(Math.max(0.05,p._life));
    if(p._life<=0||p.position.y<0){scene.remove(p);particles.splice(i,1);}
  }
}

// ---- state ----
const SPDS=[0.25,0.5,1,2,3,4,6,8];
let spdIdx=2,vol=0,tipCount=0,frame=0;
let playing=false,cmdIdx=-1,animTimer=null;
let armTx=196,armTy=224,armTz=140;
let armCx=196,armCy=224,armCz=140;
let plungerTarget=-10,plungerCurrent=-10;
let spinning=false,spinAngle=0;
let glowSlot=null,glowVal=0,glowDir=1;
const L=(a,b,t)=>a+(b-a)*t;

function slotCenter(slot){
  const p=SP[String(slot)];
  return p?{x:p[0],z:p[1]}:{x:196,z:140};
}

const CMD_DUR={
  home:1100,pick_up_tip:1300,drop_tip:950,aspirate:1500,dispense:1300,
  mix:1800,centrifuge:2800,incubate:2400,shake:1900,read_absorbance:1700,pause:750
};

function execCmd(i){
  if(i<0||i>=CMDS.length)return;
  const cmd=CMDS[i];
  cmdIdx=i;
  updateLog(i);updateProgress(i);
  document.getElementById('slabel').textContent=cmd.label||cmd.type;
  document.getElementById('stype').textContent=cmd.type.replace(/_/g,' ').toUpperCase();
  document.getElementById('sc').textContent='Steps:'+(i+1)+'/'+CMDS.length;

  const sp=SPDS[spdIdx];
  const slc=cmd.slot?slotCenter(cmd.slot):{x:196,z:140};

  // Move arm
  if(cmd.type==='home'){armTx=196;armTz=140;}
  else if(cmd.slot){armTx=slc.x;armTz=slc.z;}
  armTy=224;

  // Command-specific effects
  if(cmd.type==='pick_up_tip'){
    tipMesh.visible=true;
    tipMesh.material.color.setHex(0xd4a000);
    tipCount++;
    document.getElementById('st2').textContent='Tips:'+tipCount;
  }
  if(cmd.type==='drop_tip'){
    setTimeout(()=>{tipMesh.visible=false;},380/sp);
    spawnParticles(slc.x,slc.z,'d',7);
  }
  if(cmd.type==='aspirate'){
    plungerTarget=-32;
    setTimeout(()=>{plungerTarget=-10;},580/sp);
    spawnParticles(slc.x,slc.z,'a',16);
    vol+=(cmd.vol||50);
    document.getElementById('sv2').textContent='Vol:'+vol.toFixed(0)+'uL';
  }
  if(cmd.type==='dispense'){
    plungerTarget=12;
    setTimeout(()=>{plungerTarget=-10;},580/sp);
    spawnParticles(slc.x,slc.z,'d',16);
  }
  if(cmd.type==='mix'){
    [0,280,560,840].forEach(t=>setTimeout(()=>spawnParticles(slc.x,slc.z,'m',9),t/sp));
  }
  if(cmd.type==='centrifuge'){
    spinning=true;
    setTimeout(()=>{spinning=false;},2800/sp);
  }
  if(cmd.type==='incubate'&&cmd.slot){
    glowSlot=String(cmd.slot);glowVal=0;glowDir=1;
    setTimeout(()=>{
      glowSlot=null;
      const lw=lwMeshes[String(cmd.slot)];
      if(lw)lw.mesh.material.color.setHex(lw.origCol);
    },2400/sp);
  }
  if(cmd.type==='read_absorbance'||cmd.type==='read_fluorescence'){
    setTimeout(()=>showScanBeam(slc.x,slc.z),480/sp);
  }
  if(cmd.type==='shake'&&cmd.slot){
    const lw=lwMeshes[String(cmd.slot)];
    if(lw){
      let t=0;
      const iv=setInterval(()=>{
        lw.mesh.position.x=lw.ox+(Math.random()-0.5)*4;
        if(++t>22){clearInterval(iv);lw.mesh.position.x=lw.ox;}
      },65);
    }
  }

  const dur=(CMD_DUR[cmd.type]||1100)/sp;
  if(playing){
    animTimer=setTimeout(()=>{
      if(i+1<CMDS.length){execCmd(i+1);}
      else{playing=false;setPlayBtn(false);}
    },dur);
  }
}

function setPlayBtn(on){
  const b=document.getElementById('btnPlay');
  b.textContent=on?'|| Pause':'\u25BA Play';
  b.className='btn '+(on?'on':'');
}
function doPlay(){
  playing=!playing;setPlayBtn(playing);
  if(playing){
    if(animTimer)clearTimeout(animTimer);
    if(cmdIdx>=CMDS.length-1)cmdIdx=-1;
    execCmd(cmdIdx+1);
  }else{if(animTimer)clearTimeout(animTimer);}
}
function doNext(){
  if(animTimer)clearTimeout(animTimer);
  playing=false;setPlayBtn(false);
  execCmd(Math.min(cmdIdx+1,CMDS.length-1));
}
function doPrev(){
  if(animTimer)clearTimeout(animTimer);
  playing=false;setPlayBtn(false);
  execCmd(Math.max(cmdIdx-1,0));
}
function doReset(){
  if(animTimer)clearTimeout(animTimer);
  playing=false;cmdIdx=-1;vol=0;tipCount=0;
  armTx=196;armTy=224;armTz=140;
  tipMesh.visible=false;
  setPlayBtn(false);
  document.getElementById('slabel').textContent='Ready - press Play';
  document.getElementById('stype').textContent='-';
  document.getElementById('pfill').style.width='0%';
  document.getElementById('sc').textContent='Steps:0/'+CMDS.length;
  document.getElementById('sv2').textContent='Vol:0uL';
  document.getElementById('st2').textContent='Tips:0';
  buildLog();
}
function doSpd(v){
  spdIdx=parseInt(v)-1;
  document.getElementById('spv').textContent=SPDS[spdIdx]+'x';
}

function buildLog(){
  const log=document.getElementById('log');log.innerHTML='';
  CMDS.forEach((cmd,i)=>{
    const d=document.createElement('div');
    d.className='le pend';d.id='logItem'+i;
    d.onclick=()=>{
      if(animTimer)clearTimeout(animTimer);
      playing=false;setPlayBtn(false);execCmd(i);
    };
    d.innerHTML=
      '<span class="sn">'+String(i+1).padStart(2,'0')+'</span>'+
      '<span class="lt t-'+cmd.type+'">'+cmd.type+'</span>'+
      (cmd.label||cmd.type);
    log.appendChild(d);
  });
}
function updateLog(active){
  CMDS.forEach((_,i)=>{
    const el=document.getElementById('logItem'+i);
    if(!el)return;
    el.className='le '+(i<active?'done':i===active?'on':'pend');
  });
  const el=document.getElementById('logItem'+active);
  if(el)el.scrollIntoView({behavior:'smooth',block:'nearest'});
}
function updateProgress(i){
  const pct=CMDS.length>1?(i/(CMDS.length-1)*100):0;
  document.getElementById('pfill').style.width=pct.toFixed(1)+'%';
}

// ---- camera orbit ----
let camTheta=0.42,camPhi=0.78,camRadius=510;
const camTarget=new THREE.Vector3(196,58,140);
let isDragging=false,prevX=0,prevY=0;

function applyCamera(){
  camera.position.set(
    camTarget.x+camRadius*Math.sin(camPhi)*Math.sin(camTheta),
    camTarget.y+camRadius*Math.cos(camPhi),
    camTarget.z+camRadius*Math.sin(camPhi)*Math.cos(camTheta)
  );
  camera.lookAt(camTarget);
}
applyCamera();

cvEl.addEventListener('mousedown',e=>{isDragging=true;prevX=e.clientX;prevY=e.clientY;});
window.addEventListener('mouseup',()=>{isDragging=false;});
window.addEventListener('mousemove',e=>{
  if(!isDragging)return;
  camTheta-=(e.clientX-prevX)*0.006;
  camPhi=Math.max(0.06,Math.min(1.42,camPhi-(e.clientY-prevY)*0.005));
  prevX=e.clientX;prevY=e.clientY;applyCamera();
});
cvEl.addEventListener('wheel',e=>{
  camRadius=Math.max(150,Math.min(900,camRadius+e.deltaY*0.38));
  applyCamera();e.preventDefault();
},{passive:false});

// ---- render loop ----
function animate(){
  requestAnimationFrame(animate);frame++;
  const sp=SPDS[spdIdx];

  // Smooth arm movement
  armCx=L(armCx,armTx,0.065);
  armCy=L(armCy,armTy,0.065);
  armCz=L(armCz,armTz,0.065);
  armGroup.position.set(armCx,armCy,armCz);

  // Plunger animation
  plungerCurrent=L(plungerCurrent,plungerTarget,0.11);
  plungerMesh.position.y=L(plungerMesh.position.y,plungerCurrent,0.13);

  // X-rail follows arm
  xRail.position.x=L(xRail.position.x,armCx,0.045);

  // Centrifuge spin
  if(spinning){
    spinAngle+=0.18*sp;
    const lw=lwMeshes['5']||lwMeshes['1'];
    if(lw)lw.mesh.rotation.y=spinAngle;
  }

  // Incubate glow
  if(glowSlot){
    glowVal+=0.045*glowDir*sp;
    if(glowVal>1){glowVal=1;glowDir=-1;}
    if(glowVal<0){glowVal=0;glowDir=1;}
    const lw=lwMeshes[glowSlot];
    if(lw)lw.mesh.material.color.setRGB(0.28+glowVal*0.72,0.08+glowVal*0.12,0.04);
  }

  // Scan beam sway
  if(scanBeam)scanBeam.rotation.z=Math.sin(frame*0.22)*0.06;

  // Particles
  tickParticles();

  // Idle bob when stationary
  if(Math.abs(armCx-armTx)<2&&Math.abs(armCz-armTz)<2){
    armGroup.position.y=armCy+Math.sin(frame*0.016)*0.6;
  }

  renderer.render(scene,camera);
}

buildLog();
animate();
</script>
</body>
</html>"""

_HTML = (
    _HTML
    .replace("CMDS_DATA", cmds_j)
    .replace("LW_DATA",   lw_j)
    .replace("SP_DATA",   sp_j)
)

st.components.v1.html(_HTML, height=740, scrolling=False)