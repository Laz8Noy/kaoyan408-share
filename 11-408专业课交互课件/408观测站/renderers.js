/* SVG renderers for every deterministic frame produced by models.js. */
'use strict';
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtHex = (n,w=4) => '0x' + Number(n).toString(16).toUpperCase().padStart(w,'0');
const arrow = (id='arrow-orange', color='#e66b46') => `<marker id="${id}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8Z" fill="${color}"/></marker>`;
const txt = (x,y,text,cls='',size=11,anchor='start',extra='') => `<text x="${x}" y="${y}" class="${cls}" font-size="${size}" text-anchor="${anchor}" ${extra}>${esc(text)}</text>`;
const pill = (x,y,w,h,label,active=false,sub='') => `<g class="diagram-enter"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="${active?'#fff0e6':'#f3f5ed'}" stroke="${active?'#e79e7b':'#e0e5d8'}"/>${txt(x+w/2,y+h/2+(sub?-3:4),label,active?'orange':'',11,'middle','font-weight="600"')}${sub?txt(x+w/2,y+h/2+12,sub,'muted mono',8,'middle'):''}</g>`;
const baseSvg = (content, defs='') => `<svg viewBox="0 0 680 350" aria-hidden="true"><defs>${defs}</defs>${content}</svg>`;

function renderMemory(f){
  const pageY=69, tlbHit=f.phase>=2&&f.hit, tableOn=f.phase>=3&&!f.hit, frameOn=f.phase>=4||f.hit||(!f.fault&&f.phase>=3), final=f.phase>=5;
  const vpnBits=f.vpn.toString(2).padStart(4,'0'), offBits=f.offset.toString(2).padStart(12,'0');
  let s=`${txt(31,30,'16 位虚拟地址','muted',9)}${txt(650,30,fmtHex(f.address),'mono',12,'end','font-weight="600"')}
  <rect x="30" y="42" width="132" height="50" rx="7" fill="${f.phase>=1?'#fff0e6':'#f3f5ed'}" stroke="${f.phase>=1?'#e79e7b':'#dfe4d7'}"/><rect x="162" y="42" width="258" height="50" rx="7" fill="#eef2e8" stroke="#dbe2d5"/>
  ${txt(96,62,'虚拟页号 VPN','muted',8,'middle')}${txt(96,80,vpnBits+'  ('+f.vpn+')','mono orange',12,'middle')}${txt(291,62,'页内偏移 OFFSET','muted',8,'middle')}${txt(291,80,offBits+'  ('+fmtHex(f.offset,3)+')','mono green',12,'middle')}
  ${txt(96,111,'高 4 位','subtle',8,'middle')}${txt(291,111,'低 12 位 · 全程不变','subtle',8,'middle')}`;
  s+=`<path d="M96 93V130H120" class="${f.phase>=2?'active-line':'thin-line'}" marker-end="url(#arrow-orange)"/>
  <g><rect x="120" y="117" width="160" height="80" rx="9" fill="${tlbHit?'#eaf1e8':'#fffefa'}" stroke="${tlbHit?'#7ca48b':'#dce2d6'}"/>${txt(140,140,'TLB · 快表','',11,'start','font-weight="600"')}${txt(260,140,tlbHit?'HIT':f.phase>=2?'MISS':'WAIT',tlbHit?'green':f.phase>=2?'orange':'muted','8','end','font-weight="600"')}${txt(140,163,'VPN '+f.vpn,'mono muted',9)}${txt(260,163,tlbHit?'PFN '+f.pfn:'—','mono',10,'end')}${txt(140,183,tlbHit?'命中后跳过页表':'翻译的高速缓存','muted',8)}</g>`;
  s+=`<path d="M280 157H330V198" class="${tableOn?'active-line':'thin-line'}" opacity="${f.hit?.28:1}" marker-end="url(#arrow-orange)"/>
  <g><rect x="330" y="117" width="150" height="145" rx="9" fill="${tableOn?'#fff0e6':'#fffefa'}" stroke="${tableOn?'#e79e7b':'#dce2d6'}"/>${txt(349,139,'页表（内存中）','',10,'start','font-weight="600"')}${txt(461,139,'PTE','muted',8,'end')}`;
  const rows=[Math.max(0,f.vpn-1),f.vpn,Math.min(15,f.vpn+1)]; rows.forEach((v,i)=>{const y=150+i*31, chosen=v===f.vpn; let val='V 1 · PFN '+([3,5,7,null,2,1,0,4][v]??'—'); if(chosen&&f.fault&&!f.allocated)val='V 0 · 不在内存'; if(chosen&&!f.fault)val='V 1 · PFN '+f.pfn; if(chosen&&f.allocated)val='V 1 · PFN 6'; s+=`<rect x="342" y="${y}" width="126" height="25" rx="4" fill="${chosen&&tableOn?'#fff7f1':'#f3f5ed'}"/>${txt(351,y+16,'VPN '+v,'mono '+(chosen?'orange':'muted'),8)}${txt(460,y+16,val,'mono',7,'end')}`}); s+='</g>';
  s+=`<path d="M280 157H510V194" class="${tlbHit?'settled-line':'thin-line'}" opacity="${tlbHit?1:.2}"/><path d="M480 215H510" class="${frameOn&&!f.hit?'active-line':'thin-line'}" opacity="${f.hit?.2:1}" marker-end="url(#arrow-orange)"/>
  <g><rect x="510" y="116" width="139" height="176" rx="9" fill="#fffefa" stroke="#dce2d6"/>${txt(527,138,'物理内存','',10,'start','font-weight="600"')}`;
  for(let i=0;i<8;i++){const y=148+i*16,active=frameOn&&i===f.pfn;s+=`<rect x="525" y="${y}" width="108" height="13" rx="3" fill="${active?'#eaf1e8':i%2?'#f7f8f2':'#f1f3eb'}" stroke="${active?'#7ca48b':'transparent'}"/>${txt(531,y+9,'页框 '+i,'mono '+(active?'green':'muted'),7)}${active?txt(625,y+9,'+ '+fmtHex(f.offset,3),'mono green',7,'end'):''}`};s+='</g>';
  if(final)s+=`<g class="diagram-enter"><rect x="30" y="292" width="450" height="39" rx="7" fill="#243632"/>${txt(48,316,'物理地址 = PFN '+f.pfn+' × 4096 + '+f.offset,'white mono',10)}${txt(462,316,fmtHex(f.physical),'white mono',12,'end','font-weight="600"')}</g>`;
  else s+=`${txt(30,315,f.phase<2?'点击播放，跟随地址开始翻译':'橙色虚线表示当前正在进行的查找','muted',9)}`;
  return baseSvg(s,arrow());
}

function renderCache(f){
  const seq=f.sequence||[], x0=26, max=Math.min(seq.length,16), cw=(405-8)/Math.max(max,1);
  let s=`${txt(26,28,'内存块访问序列','muted',9)}${txt(650,28,'命中率 '+(f.hits+f.misses?Math.round(f.hits/(f.hits+f.misses)*100):0)+'%','mono',10,'end','font-weight="600"')}`;
  seq.slice(0,max).forEach((b,i)=>{let fill=i<f.access?'#eaf1e8':i===f.access?(f.hit?'#dceee1':'#fff0e6'):'#f3f5ed';s+=`<rect x="${x0+i*cw}" y="41" width="${Math.max(18,cw-4)}" height="28" rx="5" fill="${fill}" stroke="${i===f.access?(f.hit?'#7ca48b':'#e79e7b'):'#e0e5d8'}"/>${txt(x0+i*cw+Math.max(18,cw-4)/2,59,b,'mono '+(i===f.access?(f.hit?'green':'orange'):'muted'),9,'middle')}`});
  s+=`${txt(26,98,'CACHE · 4 LINES','muted mono',8)}${txt(26,113,f.sets+' 组 × '+f.ways+' 路','',12,'start','font-weight="600"')}`;
  const lx=26,ly=128,lw=420,lh=41,gap=7;
  for(let i=0;i<4;i++){const line=f.lines[i],active=i===f.target&&f.access>=0,set=Math.floor(i/f.ways);s+=`<g><rect x="${lx}" y="${ly+i*(lh+gap)}" width="${lw}" height="${lh}" rx="7" fill="${active?(f.hit?'#eaf1e8':'#fff0e6'):'#fffefa'}" stroke="${active?(f.hit?'#76a187':'#e79e7b'):'#dce2d6'}"/>${txt(lx+14,ly+25+i*(lh+gap),'行 '+i,'mono muted',8)}${txt(lx+77,ly+25+i*(lh+gap),'组 '+set,'mono',9)}<line x1="${lx+118}" x2="${lx+118}" y1="${ly+8+i*(lh+gap)}" y2="${ly+lh-8+i*(lh+gap)}" stroke="#e1e5da"/>${txt(lx+138,ly+25+i*(lh+gap),line.block==null?'— 空闲 —':'主存块 '+line.block,'mono '+(active?(f.hit?'green':'orange'):''),11)}${line.block!=null?txt(lx+315,ly+25+i*(lh+gap),'TAG '+Math.floor(line.block/f.sets),'mono muted',8):''}${active?txt(lx+402,ly+25+i*(lh+gap),f.hit?'HIT':f.evicted==null?'FILL':'EVICT','mono '+(f.hit?'green':'orange'),7,'end'):''}</g>`}
  const accesses=f.hits+f.misses;s+=`<g><rect x="478" y="91" width="172" height="228" rx="10" fill="#eef1e8" stroke="#dfe5d5"/>${txt(497,116,'本轮统计','muted',8)}${txt(497,155,'命中','',10)}${txt(626,155,f.hits,'mono green',28,'end')}${txt(497,190,'未命中','',10)}${txt(626,190,f.misses,'mono orange',28,'end')}<line x1="497" x2="631" y1="208" y2="208" stroke="#d6dfcf"/>${txt(497,232,'总访问','muted',9)}${txt(630,232,accesses,'mono',11,'end')}${txt(497,255,'当前块','muted',9)}${txt(630,255,f.block==null?'—':f.block,'mono',11,'end')}${txt(497,278,'映射到','muted',9)}${txt(630,278,f.block==null?'—':'组 '+(f.block%f.sets),'mono',11,'end')}${txt(497,302,f.evicted!=null?'换出块 '+f.evicted:f.hit?'数据已在缓存中':'等待下一次访问',f.evicted!=null?'orange':'muted',8)}</g>`;
  return baseSvg(s);
}

function renderPipeline(f){
  const total=Math.max(8,f.total||8), left=188, right=655, top=84, rh=47, col=(right-left)/total;
  const colors={IF:'#dfe9e1',ID:'#e7eadc',EX:'#fff0e6',MEM:'#e7edf0',WB:'#dfece4',ST:'#f3dfd2'};
  let s=`${txt(27,28,'五级流水线时空图','muted',9)}${txt(27,47,'当前周期 '+f.cycle+' / '+total,'mono',12,'start','font-weight="600"')}${txt(485,28,'S '+(f.speedup||2.5).toFixed(2),'mono green',8,'end')}${txt(565,28,'E '+((f.efficiency||.5)*100).toFixed(1)+'%','mono green',8,'end')}${txt(653,46,'STALL '+f.stalls,'mono '+(f.stalls?'orange':'muted'),10,'end')}`;
  for(let c=1;c<=total;c++){const x=left+(c-1)*col;s+=`<rect x="${x}" y="65" width="${col}" height="${rh*4+18}" fill="${c===f.cycle?'#fff9f2':'transparent'}"/>${txt(x+col/2,74,c,'mono '+(c===f.cycle?'orange':'muted'),8,'middle')}`}
  f.instructions.forEach((inst,r)=>{const y=top+r*rh;s+=`${txt(27,y+16,'I'+(r+1),'mono',8)}${txt(49,y+16,inst.text,'mono',9)}<line x1="${left}" x2="${right}" y1="${y+30}" y2="${y+30}" stroke="#e5e8df"/>`;for(let c=0;c<total;c++){const stage=(f.history[r]||[])[c]||''; if(stage)s+=`<rect x="${left+c*col+2}" y="${y}" width="${Math.max(18,col-4)}" height="26" rx="5" fill="${colors[stage]}" stroke="${stage==='ST'?'#dea486':'#d7dfd3'}"/>${txt(left+c*col+col/2,y+17,stage,'mono '+(stage==='ST'?'orange':''),Math.min(8,col/5),'middle','font-weight="600"')}`}})
  s+=`<g transform="translate(27 298)">${['IF 取指','ID 译码','EX 执行','MEM 访存','WB 写回','ST 停顿'].map((a,i)=>`<rect x="${i*103}" y="0" width="12" height="12" rx="3" fill="${colors[a.slice(0,2)]}" stroke="#d5ddd1"/>${txt(i*103+18,10,a,'muted',8)}`).join('')}</g>`;
  if(f.forwarding&&f.cycle>0)s+=`${txt(653,329,'前递 ON','green mono',8,'end')}`;else s+=`${txt(653,329,'前递 OFF','orange mono',8,'end')}`;
  return baseSvg(s);
}

function renderTcp(f){
  const left=57,w=568,cw=w/8, sendY=88, recvY=230;
  const stColor={waiting:'#f1f3eb',sent:'#fff0e6',lost:'#f4d8cc',buffered:'#e5ecea',acked:'#dfeee0'};
  let s=`${txt(left,28,'发送方 · 按字节编号','muted',9)}${txt(625,28,'rwnd = '+f.window*100+' B','mono',9,'end')}`;
  const wb=Math.min(8-f.base,f.window), wx=left+f.base*cw;
  if(wb>0)s+=`<rect x="${wx-4}" y="57" width="${wb*cw+8}" height="82" rx="9" fill="none" stroke="#e66b46" stroke-width="1.5" stroke-dasharray="5 4"/>${txt(wx,52,'SND.WND','orange mono',8)}`;
  for(let i=0;i<8;i++){const x=left+i*cw,active=i===f.active;s+=`<rect x="${x+2}" y="${sendY}" width="${cw-5}" height="43" rx="6" fill="${stColor[f.status[i]]}" stroke="${active?'#e66b46':'#dae1d5'}" stroke-width="${active?1.8:1}"/>${txt(x+cw/2,sendY+17,'#'+(i+1),'mono '+(active?'orange':''),8,'middle')}${txt(x+cw/2,sendY+32,(f.start+i*100)+'–'+(f.start+(i+1)*100-1),'mono muted',6.5,'middle')}`}
  s+=`${txt(left,157,'SND.UNA '+(f.start+f.base*100),'mono green',8)}${txt(625,157,'SND.NXT '+(f.start+f.next*100),'mono',8,'end')}<path d="M57 175H625" stroke="#dbe1d5"/>${txt(left,204,'接收方 · 乱序缓存','muted',9)}${txt(625,204,'期望 '+(f.start+f.expected*100),'mono',9,'end')}`;
  for(let i=0;i<8;i++){const x=left+i*cw,rec=f.received[i],acked=i<f.expected;s+=`<rect x="${x+2}" y="${recvY}" width="${cw-5}" height="36" rx="6" fill="${acked?'#dfeee0':rec?'#e7edf0':'#f3f5ed'}" stroke="${acked?'#84aa91':'#dce2d7'}"/>${txt(x+cw/2,recvY+22,acked?'连续':rec?'缓存':'—',''+(acked?'green':'muted'),8,'middle')}`}
  const dir=f.direction; if(dir!=='idle'&&dir!=='done'){const y=182,label=dir==='ack'||dir==='duplicate'?'ACK '+(f.start+f.expected*100):dir==='retransmit'?'RETRANSMIT':'SEGMENT';s+=`<g class="tcp-packet"><path d="M${dir==='ack'||dir==='duplicate'?580:100} ${y}H${dir==='ack'||dir==='duplicate'?100:580}" stroke="${dir==='loss'?'#c98d75':'#e66b46'}" stroke-width="2" stroke-dasharray="5 4" marker-end="url(#arrow-orange)"/>${txt(340,y-8,label,'orange mono',8,'middle')}${dir==='loss'?`<path d="M330 171l18 20m0-20l-18 20" stroke="#e66b46" stroke-width="2"/>`:''}</g>`}
  s+=`<g transform="translate(57 294)">${Object.entries(stColor).map(([k,v],i)=>`<rect x="${i*96}" y="0" width="9" height="9" rx="2" fill="${v}" stroke="#d7dfd2"/>${txt(i*96+14,8,({waiting:'未发送',sent:'在途',lost:'丢失',buffered:'乱序缓存',acked:'已确认'})[k],'muted',7)}`).join('')}</g>`;
  if(f.events.length)s+=`${txt(625,329,f.events[f.events.length-1],'mono '+(dir==='duplicate'||dir==='loss'?'orange':'green'),8,'end')}`;
  return baseSvg(s,arrow());
}

function renderDijkstra(f){
  const pos=[[92,167],[219,78],[239,258],[398,87],[423,259],[590,171]], edges=f.edges;
  let s=`${txt(26,27,'从节点出发，逐步确定最短距离','muted',9)}${txt(652,27,'非负权无向图','mono',8,'end')}`;
  edges.forEach(([a,b,w],i)=>{const [x1,y1]=pos[a],[x2,y2]=pos[b],tree=f.prev[b]===a||f.prev[a]===b,active=i===f.activeEdge; const mx=(x1+x2)/2,my=(y1+y2)/2;s+=`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${active?'#e66b46':tree?'#3c7771':'#d8dfd4'}" stroke-width="${active||tree?2.3:1.4}" ${active?'stroke-dasharray="5 4"':''}/><circle cx="${mx}" cy="${my}" r="11" fill="#fffefa" stroke="${active?'#e6a285':'#e2e6dc'}"/>${txt(mx,my+3,w,'mono '+(active?'orange':'muted'),8,'middle')}`});
  pos.forEach(([x,y],i)=>{const source=i===f.source,current=i===f.current,done=f.visited[i],relaxed=i===f.relaxed,fill=source?'#243632':current||relaxed?'#fff0e6':done?'#eaf1e8':'#fffefa',stroke=current||relaxed?'#e66b46':done?'#6d9a7b':'#d8dfd4';s+=`<g class="clickable" data-source="${i}" role="button" tabindex="0" aria-label="以 ${nodeNames[i]} 为起点"><circle cx="${x}" cy="${y}" r="26" fill="${fill}" stroke="${stroke}" stroke-width="${current?3:1.5}"/>${txt(x,y+4,nodeNames[i],source?'white':current?'orange':done?'green':'',14,'middle','font-weight="600"')}${source?txt(x,y+43,'SOURCE','mono muted',6,'middle'):''}${txt(x,y-35,f.dist[i]===undefined?'∞':f.dist[i],'mono '+(current?'orange':done?'green':'muted'),9,'middle','font-weight="600"')}</g>`});
  s+=`<g transform="translate(26 309)">${f.dist.map((d,i)=>`<rect x="${i*104}" y="0" width="94" height="26" rx="5" fill="${f.visited[i]?'#eaf1e8':'#f3f5ed'}" stroke="#dce2d7"/>${txt(i*104+10,17,nodeNames[i],'mono '+(f.visited[i]?'green':'muted'),8)}${txt(i*104+82,17,d,'mono',9,'end')}`).join('')}</g>`;
  return baseSvg(s);
}

function renderAvl(f){
  let s=`${txt(28,28,'插入序列','muted',9)}`;
  f.values.forEach((v,i)=>s+=pill(28+i*64,39,52,34,String(v),i<f.inserted));
  s+=`${txt(652,29,f.type+' 型','mono orange',10,'end')}`;
  const byVal=new Map(f.nodes.map(n=>[n.value,n]));
  f.nodes.forEach(n=>{if(n.parent!=null){const p=byVal.get(n.parent); if(p)s+=`<line x1="${p.x+40}" y1="${p.y+17}" x2="${n.x+40}" y2="${n.y+17}" stroke="#b9c7b8" stroke-width="2"/>`}});
  f.nodes.forEach(n=>{const x=n.x+40,y=n.y+17,unbalanced=Math.abs(n.bf)>1;s+=`<g class="tree-node diagram-enter"><circle cx="${x}" cy="${y}" r="27" fill="${unbalanced?'#fff0e6':f.action==='done'?'#eaf1e8':'#fffefa'}" stroke="${unbalanced?'#e66b46':f.action==='done'?'#79a087':'#d7ded3'}" stroke-width="${unbalanced?2.5:1.5}"/>${txt(x,y+5,n.value,'mono '+(unbalanced?'orange':f.action==='done'?'green':''),14,'middle','font-weight="600"')}<rect x="${x+20}" y="${y-31}" width="35" height="17" rx="7" fill="${unbalanced?'#e66b46':'#eef1e8'}"/>${txt(x+37.5,y-20,'BF '+n.bf,'mono '+(unbalanced?'white':'muted'),6.5,'middle')}</g>`});
  if(!f.nodes.length)s+=`<circle cx="340" cy="191" r="70" fill="#f1f3eb" stroke="#dfe4d9" stroke-dasharray="5 5"/>${txt(340,185,'树从一次插入开始','muted',12,'middle')}${txt(340,205,'点击播放，观察高度变化','subtle',8,'middle')}`;
  if(f.action==='unbalanced')s+=`<path d="M130 293c70 32 350 32 420 0" stroke="#e66b46" fill="none" stroke-dasharray="6 5"/>${txt(340,322,'从插入点向上，找到第一个 |BF| > 1 的祖先','orange',9,'middle')}`;
  else s+=`${txt(28,326,'中序遍历','muted',8)}${txt(104,326,f.inorder.length?f.inorder.join('  →  '):'—','mono green',9)}`;
  return baseSvg(s);
}

function renderSorting(f){
  const n=f.arr.length,left=24,chartW=397,gap=7,bw=(chartW-gap*(n-1))/n,max=Math.max(...f.arr,1),base=270;
  let s=`${txt(24,27,'数组变化','muted',9)}${txt(421,27,'比较 '+f.comparisons+' · 写入/交换 '+f.writes,'mono',8,'end')}`;
  f.arr.forEach((v,i)=>{const h=38+v/max*146,x=left+i*(bw+gap),y=base-h,active=f.active.includes(i),changed=f.changed.includes(i),sorted=f.sorted.includes(i);s+=`<rect x="${x}" y="${y}" width="${bw}" height="${h}" rx="${Math.min(7,bw/4)}" fill="${active?'#fff0e6':sorted?'#eaf1e8':'#edf0e8'}" stroke="${active?'#e66b46':sorted?'#69a07c':'#d9e0d5'}" stroke-width="${changed?2.5:1}"/>${txt(x+bw/2,y-7,v,'mono '+(active?'orange':sorted?'green':'muted'),9,'middle','font-weight="600"')}${txt(x+bw/2,base+17,i,'mono subtle',7,'middle')}`});
  if(f.range)s+=`<path d="M${left+f.range[0]*(bw+gap)} 295V286H${left+(f.range[1]+1)*(bw+gap)-gap}V295" stroke="#899b8a" fill="none"/>${txt((left+f.range[0]*(bw+gap)+left+(f.range[1]+1)*(bw+gap)-gap)/2,311,'当前区间','muted',7,'middle')}`;
  s+=`<rect x="449" y="42" width="207" height="278" rx="9" fill="#eef1e8" stroke="#dfe5d5"/>${txt(466,65,'伪代码同步','muted',8)}`;f.code.forEach((line,i)=>{const y=88+i*27,active=i===f.line;s+=`<rect x="461" y="${y-17}" width="182" height="23" rx="4" fill="${active?'#fff0e6':'transparent'}"/>${txt(470,y,String(i+1).padStart(2,'0'),'mono '+(active?'orange':'subtle'),7)}${txt(493,y,line,'mono '+(active?'orange':'muted'),7.2,'start',active?'font-weight="600"':'')}`});return baseSvg(s);
}
function renderScheduling(f){
  const palette={P1:'#e66b46',P2:'#3c7771',P3:'#72899f',P4:'#b49265',IDLE:'#e6e8df'},left=28,width=624,cell=Math.min(34,width/Math.max(f.timeline.length,1));let s=`${txt(28,27,'CPU 执行时间轴','muted',9)}${txt(652,27,f.algo.toUpperCase()+(f.algo==='rr'?' · q='+f.quantum:''),'mono orange',9,'end')}`;
  f.timeline.forEach((id,i)=>{const x=left+i*cell;s+=`<rect x="${x}" y="48" width="${cell-2}" height="40" rx="4" fill="${palette[id]}" opacity="${i===f.timeline.length-1?.95:.72}"/>${txt(x+(cell-2)/2,73,id,'white mono',Math.min(8,cell/4),'middle')}${txt(x,102,i,'mono subtle',6,'middle')}`});s+=txt(left+f.timeline.length*cell,102,f.timeline.length,'mono subtle',6,'middle');
  const heads=['进程','到达','服务','剩余','等待','完成'];heads.forEach((h,i)=>s+=txt([30,111,191,280,375,468][i],137,h,'muted',8));f.jobs.forEach((j,i)=>{const y=149+i*38,active=f.current===j.id,done=j.finish!=null;s+=`<rect x="24" y="${y}" width="500" height="31" rx="5" fill="${active?'#fff0e6':done?'#eaf1e8':'#fffefa'}" stroke="#dce2d7"/>${txt(38,y+20,j.id,'mono '+(active?'orange':done?'green':''),9)}${txt(126,y+20,j.arrival,'mono',9,'middle')}${txt(206,y+20,j.burst,'mono',9,'middle')}${txt(297,y+20,j.remaining,'mono',9,'middle')}${txt(394,y+20,j.wait,'mono',9,'middle')}${txt(489,y+20,j.finish==null?'—':j.finish,'mono',9,'middle')}`});
  s+=`<rect x="548" y="127" width="108" height="174" rx="9" fill="#eef1e8" stroke="#dfe5d5"/>${txt(564,151,'就绪队列','muted',8)}${(f.ready.length?f.ready:['—']).map((id,i)=>`<rect x="563" y="${165+i*30}" width="78" height="23" rx="5" fill="#fffefa" stroke="#dce2d7"/>${txt(602,181+i*30,id,'mono',8,'middle')}`).join('')}${txt(564,287,'time '+f.time,'mono green',8)}`;return baseSvg(s);
}
function renderReplacement(f){
  let s=`${txt(25,27,'页面引用串','muted',8)}${txt(655,27,f.algo.toUpperCase()+' · '+f.cap+' FRAMES','mono orange',9,'end')}`;const cw=Math.min(38,600/f.refs.length);f.refs.forEach((v,i)=>{const x=25+i*cw,cur=i===f.index;s+=`<rect x="${x}" y="42" width="${cw-3}" height="27" rx="4" fill="${cur?'#fff0e6':i<f.index?'#eaf1e8':'#f3f5ed'}" stroke="${cur?'#e66b46':'#dce2d7'}"/>${txt(x+(cw-3)/2,59,v,'mono '+(cur?'orange':'muted'),8,'middle')}`});
  for(let i=0;i<f.cap;i++){const y=104+i*58,active=i===f.target;s+=`<rect x="25" y="${y}" width="320" height="45" rx="7" fill="${active?'#fff0e6':'#fffefa'}" stroke="${active?'#e66b46':'#dce2d7'}"/>${txt(42,y+18,'页框 '+i,'mono muted',8)}${txt(318,y+30,f.slots[i]==null?'EMPTY':'PAGE '+f.slots[i],'mono '+(active?'orange':''),13,'end','font-weight="600"')}`};
  s+=`<rect x="378" y="99" width="278" height="${Math.max(116,f.cap*58+10)}" rx="9" fill="#eef1e8" stroke="#dfe5d5"/>${txt(396,124,'最近访问','muted',8)}`;f.slots.forEach((v,i)=>s+=`${txt(396,151+i*36,v==null?'—':'PAGE '+v,'mono',8)}${txt(632,151+i*36,v==null?'—':f.algo==='fifo'?'装入 @ '+f.loaded[i]:'访问 @ '+f.last[i],'mono muted',8,'end')}`);s+=`${txt(396,293,'累计缺页','muted',8)}${txt(632,298,f.faults,'mono orange',24,'end')}`;return baseSvg(s);
}
function renderCongestion(f){
  const hist=f.history,max=Math.max(16,...hist.map(x=>x.cwnd),f.cwnd),left=36,base=284,w=606,h=220;let s=`${txt(28,27,'拥塞窗口 cwnd / MSS','muted',9)}${txt(652,27,'ssthresh '+f.ssthresh,'mono orange',9,'end')}`;
  [0,4,8,12,16,20].forEach(v=>{const y=base-v/max*h;s+=`<line x1="${left}" x2="${left+w}" y1="${y}" y2="${y}" stroke="#e2e6dc"/>${txt(left-7,y+3,v,'mono subtle',7,'end')}`});const pts=hist.map((d,i)=>(left+i*(w/13))+','+(base-d.cwnd/max*h)).join(' ');if(pts)s+=`<polyline points="${pts}" fill="none" stroke="#3c7771" stroke-width="2.5"/>`;hist.forEach((d,i)=>{const x=left+i*(w/13),y=base-d.cwnd/max*h;s+=`<circle cx="${x}" cy="${y}" r="${i===hist.length-1?5:3}" fill="${i===hist.length-1?'#e66b46':'#3c7771'}"/>${txt(x,base+17,d.r,'mono subtle',7,'middle')}`});
  const thresholdY=base-f.ssthresh/max*h;s+=`<line x1="${left}" x2="${left+w}" y1="${thresholdY}" y2="${thresholdY}" stroke="#e66b46" stroke-dasharray="6 5"/>${txt(left+w,thresholdY-6,'ssthresh','orange mono',7,'end')}<rect x="36" y="311" width="606" height="25" rx="5" fill="#eef1e8"/>${txt(50,327,'当前阶段','muted',8)}${txt(131,327,f.phase,'mono green',8)}${txt(371,327,'当前 cwnd','muted',8)}${txt(625,327,f.cwnd+' MSS','mono orange',9,'end')}`;return baseSvg(s);
}
function renderSemaphore(f){
  const colors={empty:'#eaf1e8',full:'#fff0e6'};let s=`${txt(28,28,'生产者—消费者 · 有界缓冲区','muted',9)}${txt(652,28,'N = '+f.cap,'mono',9,'end')}`;
  [['empty',f.empty,colors.empty],['full',f.full,colors.full],['mutex',f.mutex,'#e7edf0']].forEach(([name,v,c],i)=>{const x=28+i*115;s+=`<rect x="${x}" y="43" width="104" height="46" rx="7" fill="${c}" stroke="#d7e0d4"/>${txt(x+12,62,name,'mono muted',8)}${txt(x+88,76,v,'mono '+(name==='full'?'orange':'green'),18,'end','font-weight="600"')}`});
  s+=`${txt(28,121,'BUFFER','muted mono',8)}`;for(let i=0;i<f.cap;i++){const x=28+i*92,token=f.items[i],active=token&&token===f.token;s+=`<rect x="${x}" y="136" width="78" height="64" rx="9" fill="${token?'#fff0e6':'#f3f5ed'}" stroke="${active?'#e66b46':'#dce2d6'}" stroke-width="${active?2:1}"/>${txt(x+39,164,'槽 '+i,'muted',8,'middle')}${txt(x+39,187,token||'EMPTY','mono '+(token?'orange':'subtle'),11,'middle','font-weight="600"')}`}
  const px=515;s+=`<rect x="${px}" y="43" width="137" height="157" rx="10" fill="#eef1e8" stroke="#dfe5d5"/>${txt(px+17,67,'当前动作','muted',8)}${txt(px+17,95,f.actor||'—','mono orange',15)}${txt(px+17,119,f.action||'等待','',10)}${txt(px+17,151,'等待队列','muted',8)}${txt(px+17,172,'生产者 '+(f.waitP.join(', ')||'—'),'mono',8)}${txt(px+17,188,'消费者 '+(f.waitC.join(', ')||'—'),'mono',8)}`;
  s+=`<path d="M68 251H612" stroke="#dbe1d5"/><g transform="translate(28 274)">${['P(empty)','P(mutex)','修改 buffer','V(mutex)','V(full/empty)'].map((a,i)=>`<rect x="${i*124}" y="0" width="110" height="34" rx="6" fill="${f.action&&a.toLowerCase().includes(f.action.split('(')[0].toLowerCase())?'#fff0e6':'#f3f5ed'}" stroke="#dce2d7"/>${txt(i*124+55,21,a,'mono muted',7.5,'middle')}`).join('')}</g>${txt(652,330,'empty + full = '+(f.empty+f.full),'mono green',8,'end')}`;return baseSvg(s);
}
function renderBanker(f){
  let s=`${txt(25,27,'银行家算法 · 三类资源 A / B / C','muted',9)}${txt(654,27,'Work ['+f.work.join('  ')+']','mono green',10,'end')}`;
  const headers=['进程','Allocation','Max','Need','Finish'];headers.forEach((h,i)=>s+=txt([28,113,245,367,516][i],58,h,'muted',8));
  for(let i=0;i<5;i++){const y=70+i*44,active=i===f.current,done=f.finish[i];s+=`<rect x="24" y="${y}" width="632" height="36" rx="6" fill="${active?'#fff0e6':done?'#eaf1e8':i%2?'#f7f8f2':'#fffefa'}" stroke="${active?'#e79e7b':'#e0e5d8'}"/>${txt(40,y+23,'P'+i,'mono '+(active?'orange':''),9)}${txt(112,y+23,'['+f.alloc[i].join('  ')+']','mono',9)}${txt(244,y+23,'['+f.max[i].join('  ')+']','mono muted',9)}${txt(366,y+23,'['+f.need[i].join('  ')+']','mono '+(active?'orange':''),9)}${txt(538,y+23,done?'✓':'—',done?'green':'muted',11)}`}
  s+=`<rect x="24" y="305" width="632" height="30" rx="6" fill="#243632"/>${txt(40,325,'安全序列','white',8)}${txt(128,325,f.sequence.length?f.sequence.map(i=>'P'+i).join(' → '):'尚未确定','white mono',9)}${f.request?txt(640,325,'请求 ['+f.request.join(', ')+']','white mono',8,'end'):''}`;return baseSvg(s);
}
function renderInterrupt(f){
  const steps=[['USER 程序','顺序执行'],[f.kind==='external'?'中断请求':'同步异常',f.source],['硬件保护','PC / PSW'],['向量表','索引 '+f.vector],['ISR','内核处理'],['IRET','恢复现场']];let s=`${txt(28,28,'控制流切换','muted',9)}${txt(651,28,f.kind==='external'?'外部中断 · 异步':'内部异常 · 同步','mono orange',9,'end')}`;
  steps.forEach(([a,b],i)=>{const x=23+i*109,active=i===f.phase,done=i<f.phase;s+=`<rect x="${x}" y="72" width="94" height="67" rx="8" fill="${active?'#fff0e6':done?'#eaf1e8':'#f3f5ed'}" stroke="${active?'#e66b46':done?'#7da38a':'#dce2d7'}"/>${txt(x+47,98,a,active?'orange':done?'green':'',9,'middle','font-weight="600"')}${txt(x+47,117,b,'muted',7,'middle')}${i<5?`<path d="M${x+95} 105H${x+106}" stroke="${done?'#3c7771':'#cfd8cc'}" marker-end="url(#arrow-green)"/>`:''}`});
  s+=`<rect x="34" y="182" width="285" height="126" rx="10" fill="#fffefa" stroke="#dce2d7"/>${txt(52,207,'CPU 状态','muted',8)}${txt(52,237,'PC','mono muted',8)}${txt(294,237,f.phase>=3?(f.kind==='external'?'0xF120':'0xE840'):f.pc,'mono',11,'end')}${txt(52,264,'MODE','mono muted',8)}${txt(294,264,f.phase>=2&&f.phase<5?'KERNEL':'USER','mono '+(f.phase>=2&&f.phase<5?'orange':'green'),10,'end')}${txt(52,291,'SOURCE','mono muted',8)}${txt(294,291,f.source,'',8,'end')}`;
  s+=`<rect x="355" y="182" width="291" height="126" rx="10" fill="#eef1e8" stroke="#dfe5d5"/>${txt(374,207,'内核栈 · 后进先出','muted',8)}`;if(f.stack.length)f.stack.forEach((a,i)=>s+=`<rect x="374" y="${224+i*26}" width="252" height="21" rx="4" fill="#fffefa" stroke="#dbe2d5"/>${txt(386,239+i*26,a,'mono',8)}`);else s+=txt(500,263,'现场已恢复','muted',10,'middle');return baseSvg(s,arrow('arrow-green','#3c7771'));
}
function renderCidr(f){
  let s=`${txt(26,26,'目标 IPv4 地址','muted',8)}${txt(26,48,f.ip,'mono',18,'start','font-weight="600"')}`;
  const bits=f.bits.match(/.{8}/g);bits.forEach((b,i)=>s+=pill(315+i*82,25,72,34,b,i===0||f.matched.length>0));
  s+=`${txt(26,88,'路由表匹配','muted',8)}`;f.routes.forEach((r,i)=>{const y=101+i*49,match=f.matched.includes(i),current=f.current===i,chosen=f.chosen===i;s+=`<rect x="24" y="${y}" width="632" height="39" rx="7" fill="${chosen?'#eaf1e8':current?'#fff0e6':'#fffefa'}" stroke="${chosen?'#6f9d80':current?'#e66b46':'#dce2d7'}"/>${txt(42,y+24,r.prefix,'mono '+(chosen?'green':current?'orange':''),10)}${txt(244,y+24,'前缀 /'+r.mask,'mono muted',8)}${txt(374,y+24,r.next,'',9)}${txt(634,y+24,chosen?'SELECT':match?'MATCH':current?'MISS':'—','mono '+(chosen?'green':current?'orange':'muted'),7,'end')}`});
  s+=`<g transform="translate(24 310)">${f.routes.map((r,i)=>`<rect x="${i*155}" y="0" width="143" height="25" rx="5" fill="${f.matched.includes(i)?'#eaf1e8':'#f3f5ed'}" stroke="#dce2d7"/>${txt(i*155+71,16,r.mask===0?'任意地址':Math.pow(2,32-r.mask).toLocaleString()+' 个地址','mono muted',7,'middle')}`).join('')}</g>`;return baseSvg(s);
}
function renderVisualization(id,frame){
  const renderers={memory:renderMemory,cache:renderCache,pipeline:renderPipeline,tcp:renderTcp,dijkstra:renderDijkstra,avl:renderAvl,sorting:renderSorting,scheduling:renderScheduling,replacement:renderReplacement,congestion:renderCongestion,semaphore:renderSemaphore,banker:renderBanker,interrupt:renderInterrupt,cidr:renderCidr};
  return renderers[id](frame);
}
