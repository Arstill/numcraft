"""
3D-просмотр детали для HTML-техкарты: каркас рёбер на <canvas>, без внешних библиотек (работает офлайн).

Управление: ЛКМ — вращать, ПКМ или Shift+ЛКМ — сдвигать, колесо — масштаб, двойной щелчок — сброс.
Выбор операции подсвечивает обрабатываемые рёбра; операции установа 2 показываются перевёрнутыми.
"""
from __future__ import annotations

import json

from numcraft.sketch import GEOM_RU

CSS = """
.v3d{border:1px solid var(--line);border-radius:8px;padding:8px;background:var(--bg)}
.v3d canvas{width:100%;display:block;touch-action:none;cursor:grab;border-radius:6px;background:var(--partbg)}
.v3d canvas:active{cursor:grabbing}
.v3d .bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}
.v3d button,.v3d select{font:inherit;font-size:13px;padding:3px 8px;border:1px solid var(--line);background:var(--head);
color:var(--fg);border-radius:6px;cursor:pointer}
.v3d select{max-width:100%;flex:1 1 240px}
.v3d .info{font-size:13px;min-height:1.4em}.v3d .hint{font-size:12px;color:var(--muted)}
.v3d label{font-size:13px;color:var(--muted)}
.layout{display:flex;flex-direction:column}.layout aside{order:-1;margin:8px 0 16px}
@media (min-width:1200px){.layout{display:grid;grid-template-columns:minmax(0,1fr) 540px;gap:28px;align-items:start}
.layout aside{order:0;grid-column:2;grid-row:1;position:sticky;top:12px;margin:0}.layout main{grid-column:1;grid-row:1}}
tr.oprow{cursor:pointer}tr.oprow:hover td{background:var(--head)}tr.oprow.cur td{outline:2px solid var(--hl)}
.btn3d{font:inherit;font-size:12px;padding:2px 8px;border:1px solid var(--hl);color:var(--hl);background:none;
border-radius:6px;cursor:pointer;margin:4px 0}
"""

JS = r"""
document.addEventListener("DOMContentLoaded",function(){
const M=JSON.parse(document.getElementById('nc3d-data').textContent);
const GEOM=__GEOM__;
const cv=document.getElementById('nc3d'),ctx=cv.getContext('2d');
const sel=document.getElementById('nc3d-op'),info=document.getElementById('nc3d-info');
const flip=document.getElementById('nc3d-flip'),stockCb=document.getElementById('nc3d-stock');
const [X,Y,Z]=M.size;let az=-0.62,el=0.6,zoom=1,panX=0,panY=0,cur=null;
const C=[X/2,Y/2,-Z/2];
M.edges.forEach(e=>{e.ts=new Set(e.t);let lo=1e9,hi=-1e9;e.p.forEach(p=>{lo=Math.min(lo,p[2]);hi=Math.max(hi,p[2]);});e.lo=lo;e.hi=hi;});
const fmin={};M.edges.forEach(e=>e.t.forEach(t=>{fmin[t]=Math.min(t in fmin?fmin[t]:1e9,e.lo);}));
const S=M.stock,sb=[[S[0],S[1],S[2]],[S[3],S[1],S[2]],[S[3],S[4],S[2]],[S[0],S[4],S[2]],[S[0],S[1],S[5]],[S[3],S[1],S[5]],[S[3],S[4],S[5]],[S[0],S[4],S[5]]];
const stockEdges=[[0,1],[1,2],[2,3],[3,0],[4,5],[5,6],[6,7],[7,4],[0,4],[1,5],[2,6],[3,7]].map(([a,b])=>[sb[a],sb[b]]);
function flipped(){return flip.checked&&cur&&cur.side==='bottom';}
function tf(p){let x=p[0],y=p[1],z=p[2];if(flipped()){y=Y-y;z=-Z-z;}return [x,y,z];}
function rot(x,y,z){x-=C[0];y-=C[1];z-=C[2];const ca=Math.cos(az),sa=Math.sin(az),x1=x*ca-y*sa,y1=x*sa+y*ca,
 ce=Math.cos(el),se=Math.sin(el);return [x1,y1*se+z*ce,y1*ce-z*se];}
function hl(e){if(!cur)return false;const g=cur.geom,ids=cur.ids,face=cur.side==='bottom'?'bot':'top';
 if(g==='face')return e.ts.has(face);
 if(g==='outer_rough'||g==='outer_walls')return e.ts.has('outer');
 if(g==='chamfer_outer')return e.ts.has('outer')&&e.ts.has(face);
 if(g==='chamfer_all')return e.ts.has(face);
 if(g==='chamfer_pockets')return M.pockets.some(i=>e.ts.has(i))&&e.ts.has(face);
 if(g==='chamfer_holes')return M.holes.some(i=>e.ts.has(i))&&(e.ts.has(face)||Math.abs(e.hi)<0.05);
 if(g==='pocket_floor')return ids.some(i=>e.ts.has(i)&&Math.abs(e.hi-fmin[i])<0.05);
 return ids.some(i=>e.ts.has(i));}
function color(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim()||'#888';}
function draw(){
 const dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=Math.min(Math.round(W*0.75),620);
 cv.width=W*dpr;cv.height=H*dpr;cv.style.height=H+'px';ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
 const diag=Math.hypot(X,Y,Z)||1,s=0.82*Math.min(W,H)/diag*zoom;
 const P=p=>{const r=rot(...tf(p));return [W/2+(r[0]+panX)*s,H/2-(r[1]+panY)*s,r[2]];};
 const fg=color('--fg'),hc=color('--hl'),mu=color('--muted');
 let dmin=1e9,dmax=-1e9;const items=M.edges.map(e=>{const q=e.p.map(P);let d=0;q.forEach(v=>{d+=v[2];dmin=Math.min(dmin,v[2]);dmax=Math.max(dmax,v[2]);});return {e,q,d:d/q.length,h:hl(e)};});
 items.sort((a,b)=>b.d-a.d);
 if(stockCb.checked){ctx.save();ctx.setLineDash([5,4]);ctx.strokeStyle=mu;ctx.lineWidth=1;ctx.globalAlpha=.7;
  const top=cur&&(cur.geom==='face'||cur.geom==='outer_rough');if(top){ctx.strokeStyle=hc;ctx.globalAlpha=1;}
  stockEdges.forEach(([a,b])=>{const p=P(a),q=P(b);ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.stroke();});ctx.restore();}
 const span=Math.max(dmax-dmin,1e-6);
 for(const pass of [false,true])for(const it of items){if(it.h!==pass)continue;
  ctx.beginPath();it.q.forEach((v,i)=>i?ctx.lineTo(v[0],v[1]):ctx.moveTo(v[0],v[1]));
  if(it.h){ctx.strokeStyle=hc;ctx.lineWidth=3;ctx.globalAlpha=1;}
  else{ctx.strokeStyle=fg;ctx.lineWidth=1.2;ctx.globalAlpha=cur?0.25+0.35*(1-(it.d-dmin)/span):0.35+0.65*(1-(it.d-dmin)/span);}
  ctx.stroke();}
 ctx.globalAlpha=1;
 // нуль установа
 const o=M.datum==='center'?[X/2,Y/2,0]:[0,0,0],L=diag*0.18,wcs=cur?cur.wcs:'G54';
 const R=p=>{const r=rot(p[0],p[1],p[2]);return [W/2+(r[0]+panX)*s,H/2-(r[1]+panY)*s];};
 const O=R(o);const ax=[[[o[0]+L,o[1],o[2]],'X','#e03131'],[[o[0],o[1]+L,o[2]],'Y','#2f9e44'],[[o[0],o[1],o[2]+L],'Z','#1971c2']];
 ctx.font='600 13px system-ui,sans-serif';ax.forEach(([p,t,c])=>{const q=R(p);ctx.strokeStyle=c;ctx.fillStyle=c;ctx.lineWidth=2.5;
  ctx.beginPath();ctx.moveTo(O[0],O[1]);ctx.lineTo(q[0],q[1]);ctx.stroke();ctx.fillText(t,q[0]+3,q[1]-3);});
 ctx.fillStyle=color('--datum');ctx.fillText(wcs,O[0]+4,O[1]+16);}
function view(a,e){az=a;el=e;zoom=1;panX=panY=0;draw();}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{const v=b.dataset.view;
 ({top:()=>view(0,Math.PI/2),front:()=>view(0,0),right:()=>view(-Math.PI/2,0),iso:()=>view(-0.62,0.6),bottom:()=>view(0,-Math.PI/2)})[v]();});
let drag=null;const pts=new Map();
cv.addEventListener('pointerdown',ev=>{cv.setPointerCapture(ev.pointerId);pts.set(ev.pointerId,[ev.clientX,ev.clientY]);
 drag={x:ev.clientX,y:ev.clientY,pan:ev.button===2||ev.shiftKey,d:null};});
cv.addEventListener('pointermove',ev=>{if(!drag)return;const pr=pts.get(ev.pointerId);if(pr){pts.set(ev.pointerId,[ev.clientX,ev.clientY]);}
 if(pts.size===2){const [a,b]=[...pts.values()];const d=Math.hypot(a[0]-b[0],a[1]-b[1]);if(drag.d)zoom*=d/drag.d;drag.d=d;draw();return;}
 const dx=ev.clientX-drag.x,dy=ev.clientY-drag.y;drag.x=ev.clientX;drag.y=ev.clientY;
 if(drag.pan){const W=cv.clientWidth,H=cv.clientHeight,s=0.82*Math.min(W,H)/Math.hypot(X,Y,Z)*zoom;panX+=dx/s;panY-=dy/s;}
 else{az+=dx*0.01;el=Math.max(-Math.PI/2,Math.min(Math.PI/2,el+dy*0.01));}draw();});
const up=ev=>{pts.delete(ev.pointerId);if(!pts.size)drag=null;else if(drag)drag.d=null;};
cv.addEventListener('pointerup',up);cv.addEventListener('pointercancel',up);
cv.addEventListener('contextmenu',ev=>ev.preventDefault());
cv.addEventListener('wheel',ev=>{ev.preventDefault();zoom*=Math.exp(-ev.deltaY*0.0015);draw();},{passive:false});
cv.addEventListener('dblclick',()=>view(-0.62,0.6));
let g='';M.ops.forEach(op=>{if(op.setup!==g){g=op.setup;const og=document.createElement('optgroup');og.label=g;sel.appendChild(og);}
 const o=document.createElement('option');o.value=op.n;o.textContent='Оп. '+op.n+' — '+op.title;sel.lastChild.appendChild(o);});
function setOp(n){cur=M.ops.find(o=>String(o.n)===String(n))||null;sel.value=cur?cur.n:'';
 info.textContent=cur?('Оп. '+cur.n+': '+(GEOM[cur.geom]||'')+(flipped()?' · деталь перевёрнута (установ 2)':'')):'Выберите операцию — обрабатываемые рёбра подсветятся.';
 document.querySelectorAll('tr.oprow').forEach(r=>r.classList.toggle('cur',cur&&r.dataset.op===String(cur.n)));draw();}
sel.onchange=()=>setOp(sel.value);flip.onchange=()=>setOp(sel.value);stockCb.onchange=draw;
window.nc3dShow=n=>{setOp(n);const a=document.getElementById('v3d');const r=a.getBoundingClientRect();
 if(r.top<0||r.bottom>window.innerHeight)a.scrollIntoView({behavior:'smooth',block:'start'});};
document.querySelectorAll('table').forEach(t=>{const h=t.querySelector('th');if(!h||h.textContent.trim()!=='Оп.')return;
 t.querySelectorAll('tr').forEach((r,i)=>{if(!i)return;const n=r.cells[0].textContent.trim();r.dataset.op=n;r.classList.add('oprow');
 r.title='Показать в 3D';r.onclick=()=>window.nc3dShow(n);});});
window.addEventListener('resize',draw);setOp('');
});
"""


# в 3D нет номеров обхода — пояснения в скобках убираем
GEOM_3D = {k: v.split(" (")[0] for k, v in GEOM_RU.items()}


def viewer_html(model: dict) -> str:
    data = json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    src = "по рёбрам STEP-модели" if model.get("source") == "step" else "по габариту и элементам (STEP не задан)"
    return f"""<div class="v3d" id="v3d">
<div class="bar"><b>3D-вид</b><span class="hint">{src}</span></div>
<canvas id="nc3d" aria-label="3D-вид детали"></canvas>
<div class="bar"><button data-view="iso">Изометрия</button><button data-view="top">Сверху</button>
<button data-view="front">Спереди</button><button data-view="right">Справа</button><button data-view="bottom">Снизу</button>
<label><input type="checkbox" id="nc3d-stock" checked> заготовка</label>
<label><input type="checkbox" id="nc3d-flip" checked> как в установе</label></div>
<div class="bar"><select id="nc3d-op"><option value="">— операция: без подсветки —</option></select></div>
<div class="info" id="nc3d-info"></div>
<div class="hint">ЛКМ — вращать · ПКМ или Shift — сдвиг · колесо — масштаб · двойной щелчок — сброс ·
щелчок по строке операции в таблице — показать её здесь</div>
<script type="application/json" id="nc3d-data">{data}</script>
<script>{JS.replace("__GEOM__", json.dumps(GEOM_3D, ensure_ascii=False))}</script>
</div>"""
