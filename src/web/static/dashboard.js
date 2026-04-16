/* ── 仪表盘图表渲染与实时数据推送 ── */

const PLT_CFG = {responsive:true, displayModeBar:false};
const DARK = {
  paper_bgcolor:'rgba(0,0,0,0)',
  plot_bgcolor:'rgba(0,0,0,0)',
  font:{color:'#8899a8',size:11,family:'Plus Jakarta Sans, Noto Sans SC, sans-serif'},
  xaxis:{gridcolor:'rgba(255,255,255,.06)',zerolinecolor:'rgba(255,255,255,.1)',tickfont:{color:'#8899a8'}},
  yaxis:{gridcolor:'rgba(255,255,255,.06)',zerolinecolor:'rgba(255,255,255,.1)',tickfont:{color:'#8899a8'}},
  margin:{l:48,r:14,t:10,b:42},
  legend:{
    bgcolor:'rgba(21,27,36,.88)',font:{size:10,color:'#c5d0da'},
    bordercolor:'rgba(255,255,255,.08)',borderwidth:1,
  },
};

// 皮带颜色方案
const BELT_COLORS = {
  main: {line:'#f59e0b', fill:'rgba(245,158,11,0.18)'},
  incline: {line:'#5eb0ff', fill:'rgba(94,176,255,0.18)'},
  panel101: {line:'#a78bfa', fill:'rgba(167,139,250,0.18)'},
};

function beltYMaxPerCell(bid){
  const maxDensity = bid==='main' ? 0.125 : bid==='incline' ? 0.111 : 0.123;
  return maxDensity * 1.2;
}

function mkBelt(id, color){
  const c = BELT_COLORS[color] || BELT_COLORS.main;
  Plotly.newPlot(id,[{name:'智能调速', x:[],y:[],mode:'lines',
    line:{color:c.line,width:1.5},
    fill:'tozeroy',fillcolor:c.fill,
    hovertemplate:'里程 %{x} m<br>载荷 %{y:.4f} t/m<extra></extra>'}],
  {...DARK, xaxis:{...DARK.xaxis,title:'沿程 (m)'},
   yaxis:{...DARK.yaxis,title:'线载荷 (t/m)'}},PLT_CFG);
}

function mkLane(id){
  Plotly.newPlot(id,[
    {name:'实测流量', x:[],y:[],mode:'lines',line:{color:'#4ade80',width:1.5}},
    {name:'历史预测', x:[],y:[],mode:'lines',connectgaps:false,
     line:{color:'#fbbf24',width:1.5,dash:'dot'}},
    {name:'上界', x:[],y:[],mode:'lines',line:{color:'rgba(0,0,0,0)',width:0},showlegend:false},
    {name:'80% 区间', x:[],y:[],fill:'tonexty',fillcolor:'rgba(94,176,255,0.14)',
     mode:'lines',line:{color:'rgba(0,0,0,0)',width:0}},
    {name:'超前预测', x:[],y:[],mode:'lines',
     line:{color:'#60a5fa',width:2,dash:'dash'}},
  ],{...DARK, xaxis:{...DARK.xaxis,title:'时间 (s)'},
     yaxis:{...DARK.yaxis,title:'瞬时流量 (t/s)',range:[0,window.LANE_FLOW_YMAX]}},PLT_CFG);
}

function mkSpeed(){
  Plotly.newPlot('ch-speed',[
    {name:'智能调速',x:[],y:[],mode:'lines',line:{color:'#c4b5fd',width:2}},
  ],{...DARK, xaxis:{...DARK.xaxis,title:'时间 (s)'},
     yaxis:{...DARK.yaxis,title:'带速 (m/s)',range:[0.5,5.2]}},PLT_CFG);
}

function mkEnergy(){
  Plotly.newPlot('ch-energy',[
    {name:'AI 智能调速',x:[],y:[],mode:'lines',line:{color:'#c4b5fd',width:2}},
  ],{...DARK, xaxis:{...DARK.xaxis,title:'时间 (s)'},
     yaxis:{...DARK.yaxis,title:'累计能耗 (kWh)'}},PLT_CFG);
}

// ── 初始化所有图表 ──
mkBelt('ch-belt-main', 'main');
mkBelt('ch-belt-incline', 'incline');
mkBelt('ch-belt-panel101', 'panel101');
mkLane('ch-lane0');
mkLane('ch-lane1');
mkSpeed();
mkEnergy();

// ── UI 辅助 ──
function setCard(id, val, suffix=''){
  document.getElementById(id).textContent = val + suffix;
}

let _paused = false, _auto = true;
let _controlBusy = false;
let _lastPred = [null, null];

function applyHeaderButtons(paused, autoSpeed){
  _auto = !!autoSpeed;
  const bv = document.getElementById('btn-vfd');
  bv.textContent = _auto ? '智能调速 ON' : '智能调速 OFF';
  bv.setAttribute('aria-pressed', _auto ? 'true' : 'false');
  bv.classList.toggle('active', _auto);
}

async function postControl(payload){
  const bv = document.getElementById('btn-vfd');
  if(_controlBusy) return;
  _controlBusy = true;
  bv.disabled = true;
  try{
    const r = await fetch('/api/control',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload),
    });
    const j = await r.json().catch(()=>({}));
    if(!r.ok || !j.ok){ console.warn('control failed', r.status, j); return; }
    applyHeaderButtons(j.paused, j.auto_speed);
  }catch(e){ console.warn('control error', e); }
  finally{ _controlBusy = false; bv.disabled = false; }
}

async function poll(){
  try{
    const r = await fetch('/api/state');
    const d = await r.json();
    if(d.booting) return;
    renderState(d);
  }catch(e){console.warn('poll error',e);}
}

function renderState(d){
  try{
    if(!_controlBusy) applyHeaderButtons(d.paused, d.auto_speed);

    const mBadge = document.getElementById('badge-model');
    if(d.model_ready){
      mBadge.textContent='预测模型就绪';
      mBadge.classList.remove('loading','pulse');
    }

    // KPI
    setCard('cv-save', d.saving_pct, '%');
    const sk = document.getElementById('cv-save-detail');
    if(sk){
      const fk = (v)=> (typeof v === 'number' && !Number.isNaN(v)) ? v.toFixed(4) : '—';
      sk.textContent =
        '节电 ' + fk(d.saving_kwh) + ' kWh · 对照累计 ' + fk(d.total_energy_baseline_kwh)
        + ' kWh · 智能累计 ' + fk(d.total_energy_kwh) + ' kWh';
    }
    setCard('cv-power-ai', d.total_power_kw, ' kW');
    setCard('cv-power', d.total_power_const_kw);
    setCard('cv-time', d.sim_time, ' s');

    // 三条皮带载荷图 + 指标
    const beltIds = ['main','incline','panel101'];
    const belts = d.belts || {};
    for(const bid of beltIds){
      const b = belts[bid];
      if(!b) continue;
      setCard('bm-'+bid+'-spd', b.speed);
      setCard('bm-'+bid+'-pwr', b.power_kw);
      setCard('bm-'+bid+'-inv', b.inventory_t);
      setCard('bm-'+bid+'-fill', b.fill_ratio);

      const bc = BELT_COLORS[bid];
      const BELT_YMAX = beltYMaxPerCell(bid);
      Plotly.react('ch-belt-'+bid, [{
        name:'智能调速', x:b.pos, y:b.load, mode:'lines',
        line:{color:bc.line,width:1.5},
        fill:'tozeroy',fillcolor:bc.fill,
        hovertemplate:'里程 %{x} m<br>载荷 %{y:.4f} t/m<extra></extra>'
      }],{...DARK,
        xaxis:{...DARK.xaxis,title:'沿程 (m)'},
        yaxis:{...DARK.yaxis,title:'线载荷 (t/m)',range:[0,BELT_YMAX]},
        showlegend:false
      },PLT_CFG);
    }

    // 双路流量图
    const laneYMax = (typeof d.lane_flow_ymax === 'number' && d.lane_flow_ymax > 0)
      ? d.lane_flow_ymax : window.LANE_FLOW_YMAX;
    for(let li=0; li<2; li++){
      const lane = d.lanes[li];
      const pid = li===0 ? 'ch-lane0':'ch-lane1';
      const col = li===0 ? '#f85149':'#58a6ff';
      const ci  = li===0 ? 'rgba(248,81,73,0.15)':'rgba(88,166,255,0.15)';
      if(lane.pred_med && lane.pred_med.length > 0){
        _lastPred[li] = {t:lane.pred_t, low:lane.pred_low, med:lane.pred_med, high:lane.pred_high};
      }
      const pred = _lastPred[li] || {t:[],low:[],med:[],high:[]};
      Plotly.react(pid,[
        {name:'实测流量', x:lane.hist_t, y:lane.hist_flow,
         mode:'lines',line:{color:'#4ade80',width:1.5}},
        {name:'历史预测', x:lane.hist_t, y:lane.hist_pred,
         mode:'lines', connectgaps:false,
         line:{color:'#fbbf24',width:1.5,dash:'dot'}},
        {name:'上界', x:pred.t, y:pred.high,
         mode:'lines',line:{color:'rgba(0,0,0,0)',width:0},showlegend:false},
        {name:'80% 区间', x:pred.t, y:pred.low,
         fill:'tonexty',fillcolor:ci,mode:'lines',
         line:{color:'rgba(0,0,0,0)',width:0}},
        {name:'超前预测', x:pred.t, y:pred.med,
         mode:'lines',line:{color:col,width:2,dash:'dash'}},
      ],{...DARK, xaxis:{...DARK.xaxis,title:'时间 (s)'},
         yaxis:{...DARK.yaxis,title:'瞬时流量 (t/s)',range:[0,laneYMax]},
         annotations: (()=>{
           const ann = [];
           if(lane.now_pred !== null){
             let mae = null;
             if(lane.hist_pred && lane.hist_flow){
               let sum=0, cnt=0;
               for(let k=0;k<lane.hist_pred.length;k++){
                 if(lane.hist_pred[k]!==null && lane.hist_flow[k]!==null){
                   sum += Math.abs(lane.hist_pred[k]-lane.hist_flow[k]); cnt++;
                 }
               }
               if(cnt>0) mae = (sum/cnt).toFixed(4);
             }
             ann.push({
               x:1,y:1,xref:'paper',yref:'paper',xanchor:'right',yanchor:'top',
               text: `实测 ${lane.now_actual} t/s<br>预测 ${lane.now_pred} t/s`
                     + (mae!==null ? `<br>平均误差 ${mae} t/s` : ''),
               showarrow:false, bgcolor:'rgba(21,27,36,0.94)',
               bordercolor:col, borderwidth:1, font:{size:10,color:'#f0f3f6'}
             });
           }
           return ann;
         })()},PLT_CFG);
    }

    // 带速图
    Plotly.react('ch-speed',[
      {name:'智能调速', x:d.spd_t, y:d.spd_v,
       mode:'lines',line:{color:'#c4b5fd',width:2}},
    ],{...DARK, xaxis:{...DARK.xaxis,title:'时间 (s)'},
       yaxis:{...DARK.yaxis,title:'带速 (m/s)',range:[0.5,5.2]}},PLT_CFG);

    // 能耗累积图
    Plotly.react('ch-energy',[
      {name:'AI 智能调速', x:d.spd_t, y:d.energy_ai||[],
       mode:'lines',line:{color:'#c4b5fd',width:2}},
    ],{...DARK, xaxis:{...DARK.xaxis,title:'时间 (s)'},
       yaxis:{...DARK.yaxis,title:'累计能耗 (kWh)'}},PLT_CFG);

  }catch(e){console.warn('render error',e);}
}

// ── 按钮事件 ──
document.getElementById('btn-vfd').addEventListener('click', ()=>{
  postControl({action: 'toggle_vfd'});
});

// ── SSE 实时推送 + 轮询回退 ──
let _pollTimer = null;
function startPollingFallback(){
  if(!_pollTimer){
    _pollTimer = setInterval(poll, 1000);
    poll();
  }
}
function stopPollingFallback(){
  if(_pollTimer){ clearInterval(_pollTimer); _pollTimer = null; }
}
try{
  const _es = new EventSource('/api/stream');
  _es.onmessage = function(ev){
    try{
      const d = JSON.parse(ev.data);
      if(!d.booting) renderState(d);
    }catch(e){}
  };
  _es.onerror = function(){
    _es.close();
    startPollingFallback();
  };
}catch(e){
  startPollingFallback();
}
