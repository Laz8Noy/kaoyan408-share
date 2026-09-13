/* Pure, deterministic teaching models. No network or backend required. */
'use strict';
const clone = value => JSON.parse(JSON.stringify(value));
const hex = (n, width = 4) => '0x' + n.toString(16).toUpperCase().padStart(width, '0');
const makeFrame = (title, copy, formula, data) => ({ title, copy, formula, ...clone(data) });

function memoryModel(p) {
  const vpn = Math.floor(p.address / 4096), offset = p.address % 4096;
  const resident = [3, 5, 7, null, 2, 1, 0, 4];
  const fault = p.scenario === 'fault';
  const pfn = fault ? 6 : (resident[vpn] == null ? (vpn * 3 + 2) % 8 : resident[vpn]);
  const hit = p.scenario === 'hit';
  const data = { vpn, offset, pfn, address: p.address, physical: pfn * 4096 + offset, hit, fault, phase: 0, allocated: false };
  const frames = [makeFrame('从 CPU 发出的一个地址开始', 'CPU 给出的是<strong>虚拟地址</strong>。先别急着去内存找它：虚拟页号需要翻译，页内偏移不需要。', 'VA = ' + hex(p.address) + ' · 页大小 = 4 KiB', data)];
  frames.push(makeFrame('先拆开：页号与页内偏移', '4 KiB = 2¹² B，因此低 <strong>12 位</strong>是页内偏移；这个 16 位教学地址的高 4 位是虚拟页号。', 'VPN = ' + vpn + '  |  offset = ' + hex(offset, 3), { ...data, phase: 1 }));
  frames.push(makeFrame(hit ? 'TLB 命中，找到页框号' : 'TLB 未命中，但先别说“缺页”', hit ? '快表已缓存此页的映射，直接得到页框号。<strong>不必再访问内存中的页表</strong>。' : 'TLB 中没有此映射，只表示<strong>翻译缓存未命中</strong>。还要查页表，才能判断页面是否在内存。', hit ? 'TLB[' + vpn + '] → PFN ' + pfn : 'TLB miss → 查询页表', { ...data, phase: 2 }));
  if (!hit) {
    frames.push(makeFrame(fault ? '有效位为 0，发生缺页异常' : '页表有效，页面就在内存中', fault ? '页表显示页面尚未驻留。CPU 触发<strong>缺页异常</strong>，操作系统接管处理；这不是一次普通内存读取。' : '页表项有效位 V = 1，对应页框号为 ' + pfn + '。把映射回填到 TLB，后续访问可加速。', fault ? 'PTE[' + vpn + '].V = 0 → page fault' : 'PTE[' + vpn + '] = { V:1, PFN:' + pfn + ' }', { ...data, phase: 3 }));
    if (fault) frames.push(makeFrame('操作系统调页，再重新执行', '教学模型中把页面从外存调入空闲页框 6，更新页表与 TLB，再<strong>重新执行原指令</strong>。真实系统还涉及调度、磁盘 I/O 和可能的置换。', '调入 PFN 6 → V = 1 → 重新翻译', { ...data, phase: 4, allocated: true }));
  }
  frames.push(makeFrame('拼接，而不是把两个地址相加', '用<strong>物理页框号替换虚拟页号</strong>，页内偏移原样保留。页框基址加上偏移，才是最终的物理地址。', 'PA = ' + pfn + ' × 4096 + ' + offset + ' = ' + hex(data.physical), { ...data, phase: 5, allocated: fault }));
  return frames;
}

function cacheModel(p) {
  const sets = p.mode === 'direct' ? 4 : p.mode === 'set' ? 2 : 1;
  const ways = 4 / sets, lines = Array.from({ length: 4 }, () => ({ block: null, used: -1 }));
  let hits = 0, misses = 0;
  const base = { lines, sets, ways, hits, misses, access: -1, block: null, target: -1, hit: null, evicted: null, sequence: p.sequence };
  const frames = [makeFrame('相同的容量，不同的“放法”', '这里有 <strong>4 行 Cache</strong>，初始为空。每个内存块为 16 B。点击播放，观察相同访问序列在不同映射方式下的命中情况。', sets + ' 组 × ' + ways + ' 路 = 4 行 · LRU 替换', base)];
  p.sequence.forEach((block, access) => {
    const set = block % sets, tag = Math.floor(block / sets), indexes = Array.from({ length: ways }, (_, w) => set * ways + w);
    let target = indexes.find(i => lines[i].block === block), hit = target !== undefined, evicted = null;
    if (hit) hits++;
    else {
      misses++;
      target = indexes.find(i => lines[i].block == null);
      if (target === undefined) target = indexes.reduce((a, b) => lines[a].used < lines[b].used ? a : b);
      evicted = lines[target].block;
      lines[target].block = block;
    }
    lines[target].used = access;
    frames.push(makeFrame(hit ? '命中！块 ' + block + ' 已在 Cache 中' : evicted == null ? '未命中，填入一个空闲行' : '映射冲突，需要替换旧块', hit ? '先定位到组 ' + set + '，再比较组内标记。找到块 ' + block + '，<strong>无需读取主存</strong>。同时更新最近使用顺序。' : evicted == null ? '组 ' + set + ' 内有空闲位置。将主存块 ' + block + ' 调入，并保存标记 ' + tag + '；这次访问仍计为<strong>未命中</strong>。' : '块 ' + block + ' 只能进入组 ' + set + '。' + (ways === 1 ? '直接映射没有选择，必须换出块 ' + evicted + '。' : '组内已满，按 LRU 换出最久未使用的块 ' + evicted + '。') + '<strong>容量没满也可能发生映射冲突。</strong>', '组号 = ' + block + ' mod ' + sets + ' = ' + set + '  |  tag = ' + tag, { lines, sets, ways, hits, misses, access, block, target, hit, evicted, sequence: p.sequence }));
  });
  return frames;
}

function pipelineModel(p) {
  const instructions = p.kind === 'load' ? [
    { text: 'LW R1, 0(R2)', dest: 1, src: [2], load: true },
    { text: 'ADD R3, R1, R4', dest: 3, src: [1, 4] },
    { text: 'SUB R5, R3, R6', dest: 5, src: [3, 6] },
    { text: 'OR R7, R5, R8', dest: 7, src: [5, 8] }
  ] : [
    { text: 'ADD R1, R2, R3', dest: 1, src: [2, 3] },
    { text: 'SUB R4, R1, R5', dest: 4, src: [1, 5] },
    { text: 'AND R6, R4, R7', dest: 6, src: [4, 7] },
    { text: 'OR R8, R6, R9', dest: 8, src: [6, 9] }
  ];
  const names = ['IF', 'ID', 'EX', 'MEM', 'WB'];
  let pipe = [null, null, null, null, null], next = 0, cycle = 0, stalls = 0;
  const history = instructions.map(() => []);
  const frames = [makeFrame('流水线重叠的是“阶段”', '每条指令依次经过取指、译码、执行、访存和写回。理想情况下，4 条指令不需要 20 周期，只需要 <strong>4 + 5 − 1 = 8 周期</strong>。', '理想周期 = n + k − 1 = 8', { instructions, history, cycle, stalls, pipe, stalled: false, forwarding: p.forwarding, total: 8 })];
  while (next < instructions.length || pipe.some(x => x != null)) {
    const consumer = pipe[1];
    let stalled = false, reg = null, forwarded = false;
    if (consumer != null) {
      for (const r of instructions[consumer].src) {
        const producerStage = [2, 3, 4].find(s => pipe[s] != null && instructions[pipe[s]].dest === r);
        if (producerStage !== undefined) {
          const producer = instructions[pipe[producerStage]];
          const blocked = p.forwarding ? producerStage === 2 && !!producer.load : producerStage < 4;
          if (blocked) { stalled = true; reg = r; }
          else if (p.forwarding && producerStage < 4) forwarded = true;
        }
      }
    }
    const n = [null, null, null, pipe[2], pipe[3]];
    if (stalled) { n[0] = pipe[0]; n[1] = pipe[1]; stalls++; }
    else { n[2] = pipe[1]; n[1] = pipe[0]; if (next < instructions.length) n[0] = next++; }
    pipe = n;
    if (!pipe.some(x => x != null)) break;
    cycle++;
    for (let i = 0; i < instructions.length; i++) history[i].push('');
    pipe.forEach((inst, stage) => { if (inst != null) history[inst][cycle - 1] = stalled && stage <= 1 ? 'ST' : names[stage]; });
    const copy = stalled ? '后面的指令要读 R' + reg + '，但结果还没准备好。冻结 IF / ID，向 EX 注入一个<strong>气泡</strong>；更早的指令继续前进。' : forwarded ? '结果还没写回寄存器，但已经由前面的执行阶段产生。通过<strong>前递通路</strong>把数据送到需要它的 EX 阶段，避免停顿。' : pipe[4] != null ? '指令 I' + (pipe[4] + 1) + ' 进入 WB。采用<strong>先写后读的寄存器堆</strong>：同一周期 WB 的结果可被 ID 读取。' : '不同指令正在占用不同阶段。横向追踪一条指令，纵向观察同一周期的并行工作。';
    frames.push(makeFrame(stalled ? '数据还没到，先停 ' + (p.forwarding ? '1' : '一') + ' 拍' : forwarded ? '前递：不必等到写回' : '第 ' + cycle + ' 周期，阶段继续推进', copy, 'cycle ' + cycle + '  |  累计停顿 ' + stalls + ' 周期', { instructions, history, cycle, stalls, pipe, stalled, forwarding: p.forwarding, total: 8 + stalls }));
  }
  const n = instructions.length, ideal = n + 5 - 1, serial = 5 * n;
  const speedup = serial / cycle, efficiency = n / cycle;
  frames.forEach(f => Object.assign(f, { total: cycle, ideal, serial, speedup, efficiency }));
  const last = frames[frames.length - 1];
  last.title = n + ' 条指令，在 ' + cycle + ' 个周期后完成';
  last.copy = '理想需要 ' + ideal + ' 周期，数据相关引入 ' + stalls + ' 个额外周期。' + (p.forwarding ? '<strong>前递不能消除所有相关</strong>：紧邻的 load-use 仍需停顿。' : '关闭前递时，消费者必须等待生产者写回；试试打开前递再对比。');
  last.formula = 'C = N + 4 + stall = ' + cycle + ' · S = 5N/C = ' + speedup.toFixed(2) + ' · E = N/C = ' + (efficiency * 100).toFixed(1) + '%';
  return frames;
}

function tcpModel(p) {
  const count = 8, size = 100, start = 1001;
  let base = 0, next = 0, expected = 0, dropped = false, dup = 0;
  const status = Array(count).fill('waiting'), received = Array(count).fill(false), events = [];
  const frames = [];
  function push(title, copy, formula, active = -1, direction = 'idle') {
    frames.push(makeFrame(title, copy, formula, { count, size, start, base, next, expected, status, received, dup, window: p.window, active, direction, events: events.slice(-4) }));
  }
  push('窗口，决定还能发多少数据', '这里每段固定 100 B，用分段格子展示<strong>按字节计数的 TCP 窗口</strong>。假设拥塞窗口不构成约束，接收窗口恒定为 ' + p.window * size + ' B。', '发送窗口 = ' + p.window * size + ' B · 初始 SEQ = 1001');
  let guard = 0;
  while (base < count && guard++ < 30) {
    const batch = [];
    while (next < Math.min(count, base + p.window)) {
      status[next] = 'sent'; batch.push(next); next++;
    }
    if (batch.length) push('窗口内的数据可以连续发送', '从 SND.NXT 开始发送，不必每发一段都等 ACK。<strong>窗口右边界以外的数据暂时不能发送</strong>。', 'SND.UNA = ' + (start + base * size) + ' · SND.NXT = ' + (start + next * size), batch[batch.length - 1], 'send');
    for (const i of batch) {
      if (p.loss && i === 1 && !dropped) {
        dropped = true; status[i] = 'lost'; events.push('段 2 丢失');
        push('第 2 段在途中丢失', '发送方不会凭空得知丢包。它只能根据<strong>重复 ACK 或重传计时器</strong>判断，而接收方只能确认连续收到的数据。', '丢失 SEQ 1101–1200', i, 'loss');
        continue;
      }
      received[i] = true; status[i] = 'buffered';
      while (expected < count && received[expected]) expected++;
      if (expected > base) {
        const old = base; base = expected; dup = 0;
        for (let j = 0; j < base; j++) status[j] = 'acked';
        events.push('ACK ' + (start + expected * size));
        push('累计确认，让窗口向前滑动', 'ACK = ' + (start + expected * size) + ' 表示<strong>下一个期望字节</strong>，不是“最后收到的字节”。这一次确认了 ' + (base - old) + ' 段连续数据。', 'ACK = ' + (start + expected * size) + ' → SND.UNA 更新', i, 'ack');
      } else {
        dup++; events.push('重复 ACK ' + (start + expected * size));
        push('后面的段到了，ACK 却不变', '接收方缓存乱序段，但前面还有缺口，因此继续回复 ACK ' + (start + expected * size) + '。<strong>累计确认不能越过缺口</strong>。', '重复 ACK ' + (start + expected * size) + ' · 第 ' + dup + ' 次', i, 'duplicate');
      }
    }
    if (base < next && status[base] === 'lost') {
      // Permit newly freed window space to generate further duplicate ACKs before retransmission.
      if (next < Math.min(count, base + p.window) && dup < 3) continue;
      const i = base, fast = dup >= 3;
      received[i] = true; status[i] = 'buffered';
      push(fast ? '3 个重复 ACK，触发快重传' : '重复 ACK 不足，等待超时重传', fast ? '已收到 3 个重复 ACK，发送方重传缺失段。本模型<strong>不展开拥塞控制</strong>，只聚焦窗口与累计确认。' : '当前窗口不足以产生 3 个重复 ACK，需要依靠<strong>重传超时 RTO</strong>。这里用一步表示计时器到期，不模拟真实时延。', '重传 SEQ ' + (start + i * size) + '–' + (start + (i + 1) * size - 1), i, 'retransmit');
      while (expected < count && received[expected]) expected++;
      base = expected; dup = 0;
      for (let j = 0; j < base; j++) status[j] = 'acked';
      events.push('ACK ' + (start + expected * size));
      push('缺口补上，一次确认多段数据', '缺失段到达后，之前缓存的乱序段也连成连续区间。<strong>ACK 一次向前跳过多个分段</strong>，不必重新发送已经缓存的段。', '累计 ACK = ' + (start + expected * size), i, 'ack');
    }
  }
  push('全部 800 字节，可靠送达', '发送窗口左边界推进到 1801，所有数据均被确认。这里省略连接建立、挥手和 ACK 延迟；不含 SACK，也不模拟拥塞控制。', '最终 ACK = 1001 + 800 = 1801', -1, 'done');
  return frames;
}

const graphEdges = [[0,1,4],[0,2,2],[1,2,1],[1,3,5],[2,3,8],[2,4,10],[3,4,2],[3,5,6],[4,5,3]];
const nodeNames = ['A','B','C','D','E','F'];
function dijkstraModel(p) {
  const edges = graphEdges.map((e, i) => i === 4 ? [e[0], e[1], p.weight] : [...e]);
  const dist = Array(6).fill(Infinity), prev = Array(6).fill(null), visited = Array(6).fill(false);
  dist[p.source] = 0;
  const frames = [];
  const snapshot = (title, copy, formula, current = -1, activeEdge = -1, relaxed = -1) => frames.push(makeFrame(title, copy, formula, { dist: dist.map(d => Number.isFinite(d) ? d : '∞'), prev, visited, current, activeEdge, relaxed, edges, source: p.source }));
  snapshot('先承认：其他点的距离还不知道', '起点到自身距离为 0，其余暂记为 ∞。这是一张<strong>无向、非负权图</strong>，满足 Dijkstra 的使用条件。', 'dist[' + nodeNames[p.source] + '] = 0；其余 = ∞');
  for (let step = 0; step < 6; step++) {
    let u = -1;
    for (let i = 0; i < 6; i++) if (!visited[i] && (u < 0 || dist[i] < dist[u])) u = i;
    if (u < 0 || !Number.isFinite(dist[u])) break;
    visited[u] = true;
    snapshot('选择未确定点中，距离最小的 ' + nodeNames[u], '当前最小暂定距离是 ' + dist[u] + '。因为边权非负，绕经其他未确定点不会让它更短，因此<strong>此刻才能确定最短距离</strong>。', '确定 ' + nodeNames[u] + '：dist = ' + dist[u], u);
    edges.forEach(([a,b,w], edgeIndex) => {
      const v = a === u ? b : b === u ? a : -1;
      if (v < 0 || visited[v]) return;
      const old = dist[v], candidate = dist[u] + w, better = candidate < old;
      if (better) { dist[v] = candidate; prev[v] = u; }
      snapshot(better ? '经过 ' + nodeNames[u] + '，到 ' + nodeNames[v] + ' 可以更短' : '这条路不更短，保留原距离', '比较“原来的暂定距离”和“先到 ' + nodeNames[u] + ' 再走这条边”的距离。' + (better ? '<strong>更新距离与前驱</strong>，但这还不是最终确定。' : '<strong>没有改善就不更新</strong>，也不改变前驱。'), 'min(' + (Number.isFinite(old) ? old : '∞') + ', ' + dist[u] + ' + ' + w + ') = ' + dist[v], u, edgeIndex, better ? v : -1);
    });
  }
  snapshot('所有最短距离已确定', '深绿色边组成最短路径树，不是最小生成树。试试<strong>调大 C—D 的边权</strong>或更换起点，看看路径选择如何变化。', nodeNames.map((n,i) => n + ':' + dist[i]).join('  '));
  return frames;
}

function avlModel(p) {
  const configs = {
    LL: { values: [30,20,10], rotations: ['对 30 右旋'], roots: [30,30,30,20], copy: '失衡点的左孩子仍然左重，是 LL 型。对失衡点进行一次右旋。' },
    RR: { values: [10,20,30], rotations: ['对 10 左旋'], roots: [10,10,10,20], copy: '失衡点的右孩子仍然右重，是 RR 型。对失衡点进行一次左旋。' },
    LR: { values: [30,10,20], rotations: ['先对 10 左旋','再对 30 右旋'], roots: [30,30,30,30,20], copy: '失衡点左重，但左孩子右重，是 LR 型。必须先左旋子树，再右旋失衡点。' },
    RL: { values: [10,30,20], rotations: ['先对 30 右旋','再对 10 左旋'], roots: [10,10,10,10,20], copy: '失衡点右重，但右孩子左重，是 RL 型。必须先右旋子树，再左旋失衡点。' }
  };
  const cfg = configs[p.type];
  let root = null;
  const insert = (n, value) => n == null ? { value, left: null, right: null } : (value < n.value ? n.left = insert(n.left, value) : n.right = insert(n.right, value), n);
  const height = n => n == null ? 0 : 1 + Math.max(height(n.left),height(n.right));
  const flatten = (n, x = 300, y = 78, spread = 112, parent = null, out = []) => {
    if (!n) return out;
    out.push({ value:n.value, x,y,parent,bf:height(n.left)-height(n.right),height:height(n) });
    flatten(n.left,x-spread,y+87,spread*.58,n.value,out); flatten(n.right,x+spread,y+87,spread*.58,n.value,out);
    return out;
  };
  const frames = [makeFrame('平衡不是“左右节点数相同”', 'AVL 要求每个节点的<strong>左右子树高度差不超过 1</strong>。这里约定空树高度为 0，平衡因子 BF = 左高 − 右高。', 'BF = h(left) − h(right) ∈ {−1, 0, 1}', { nodes: [], values:cfg.values, inserted:0, type:p.type, action:'ready', inorder:[] })];
  const snap = (title, copy, formula, inserted, action) => frames.push(makeFrame(title,copy,formula,{ nodes:flatten(root),values:cfg.values,inserted,type:p.type,action,inorder:cfg.values.slice(0,inserted).sort((a,b)=>a-b) }));
  cfg.values.forEach((v,i) => { root = insert(root,v); snap(i===2 ? '出现 ' + p.type + ' 型失衡' : '按二叉搜索树规则插入 ' + v, i===2 ? cfg.copy + '<strong>先找从插入点向上遇到的第一个失衡节点</strong>。' : '小值放左边，大值放右边。插入后沿祖先路径更新高度，检查平衡因子。', '插入 ' + v + ' · 根节点 BF = ' + (height(root.left)-height(root.right)), i+1, i===2?'unbalanced':'insert'); });
  const leftRotate = n => { const x=n.right; n.right=x.left; x.left=n; return x; };
  const rightRotate = n => { const x=n.left; n.left=x.right; x.right=n; return x; };
  if (p.type === 'LR') { root.left = leftRotate(root.left); snap('第一步：左旋左子树','先把折线“拉直”，把 LR 转成 LL。注意此时<strong>整棵树还没有恢复平衡</strong>。','对节点 10 左旋 → 转化为 LL',3,'first'); }
  if (p.type === 'RL') { root.right = rightRotate(root.right); snap('第一步：右旋右子树','先把 RL 转成 RR，再处理根节点。双旋的次序不能颠倒。','对节点 30 右旋 → 转化为 RR',3,'first'); }
  root = p.type === 'LL' || p.type === 'LR' ? rightRotate(root) : leftRotate(root);
  snap('旋转后，平衡恢复而顺序不变','新根为 20，左右孩子分别为 10 和 30。旋转改变结构，但<strong>中序遍历仍然是 10 → 20 → 30</strong>，搜索树性质没有改变。','所有 BF = 0 · 中序序列保持不变',3,'done');
  return frames;
}
function sortingModel(p) {
  const arr = p.sequence.slice(), n = arr.length, frames = [];
  let comparisons = 0, writes = 0;
  const codes = {
    bubble:['for (i = 0; i < n-1; i++)','  for (j = 0; j < n-1-i; j++)','    if (a[j] > a[j+1])','      swap(a[j], a[j+1]);','  // 末尾已有序'],
    insertion:['for (i = 1; i < n; i++) {','  key = a[i];  j = i-1;','  while (j >= 0 && a[j] > key) {','    a[j+1] = a[j];','    j--;','  }','  a[j+1] = key;','}'],
    selection:['for (i = 0; i < n-1; i++) {','  min = i;','  for (j = i+1; j < n; j++)','    if (a[j] < a[min]) min = j;','  swap(a[i], a[min]);','}'],
    quick:['quick(l, r):','  pivot = a[r];  i = l-1;','  for (j = l; j < r; j++)','    if (a[j] <= pivot)','      swap(a[++i], a[j]);','  swap(a[i+1], a[r]);','  quick(l, i); quick(i+2, r);'],
    merge:['mergeSort(l, r):','  mid = (l+r)/2;','  mergeSort(l, mid);','  mergeSort(mid+1, r);','  while (i<=mid && j<=r)','    temp[k++] = min(left, right);','  copy remaining items;','  copy temp back to a[l..r];'],
    heap:['for (i = n/2-1; i >= 0; i--)','  siftDown(a, i, n);','for (end = n-1; end > 0; end--) {','  swap(a[0], a[end]);','  siftDown(a, 0, end);','}']
  };
  const names={bubble:'冒泡排序',insertion:'直接插入排序',selection:'简单选择排序',quick:'快速排序',merge:'归并排序',heap:'堆排序'};
  const code=codes[p.algo];
  const push=(title,copy,line,active=[],changed=[],sorted=[],range=null,pivot=null)=>frames.push(makeFrame(title,copy,'比较 '+comparisons+' 次 · 写入/交换 '+writes+' 次',{arr,active,changed,sorted,line,code,algo:p.algo,range,pivot,comparisons,writes}));
  push('准备执行 '+names[p.algo], '每一步都与右侧高亮代码同步。橙色表示正在比较或移动，绿色表示已经确定位置。', 0);
  const swap=(i,j)=>{[arr[i],arr[j]]=[arr[j],arr[i]];writes+=2};
  if(p.algo==='bubble'){
    for(let i=0;i<n-1;i++){let moved=false;for(let j=0;j<n-1-i;j++){comparisons++;push('比较相邻元素 '+arr[j]+' 与 '+arr[j+1],arr[j]>arr[j+1]?'左边更大，需要交换，让较大值继续“冒”向右侧。':'顺序正确，不交换，继续比较下一对。',2,[j,j+1],[],Array.from({length:i},(_,k)=>n-1-k));if(arr[j]>arr[j+1]){swap(j,j+1);moved=true;push('交换相邻元素','一次交换不会直接让全局有序，但本轮结束后最大值一定到达末尾。',3,[j,j+1],[j,j+1],Array.from({length:i},(_,k)=>n-1-k));}}push('第 '+(i+1)+' 轮结束','当前未排序区间的最大元素已经固定在右端。',4,[],[],Array.from({length:i+1},(_,k)=>n-1-k));if(!moved)break;}
  } else if(p.algo==='insertion'){
    for(let i=1;i<n;i++){const key=arr[i];let j=i-1;push('取出待插入元素 '+key,'左侧区间已经有序。保存 key，避免右移时覆盖它。',1,[i],[],Array.from({length:i},(_,k)=>k),[0,i]);while(j>=0){comparisons++;push('比较 '+arr[j]+' 与 key '+key,arr[j]>key?'前者更大，需要向右移动一个位置。':'找到插入位置，停止向左扫描。',2,[j,i],[],[],[0,i],key);if(arr[j]<=key)break;arr[j+1]=arr[j];writes++;push('把 '+arr[j]+' 向右移动','这是“移动”而不是每次都交换；空位继续向左移动。',3,[j,j+1],[j+1],[],[0,i],key);j--;}arr[j+1]=key;writes++;push('把 key 放入空位','插入完成，左侧有序区间扩大一个元素。',6,[j+1],[j+1],Array.from({length:i+1},(_,k)=>k),[0,i]);}
  } else if(p.algo==='selection'){
    for(let i=0;i<n-1;i++){let m=i;push('从位置 '+i+' 开始寻找最小值','先假设未排序区间的第一个元素最小。',1,[m],[],Array.from({length:i},(_,k)=>k),[i,n-1]);for(let j=i+1;j<n;j++){comparisons++;push('比较候选最小值与 '+arr[j],arr[j]<arr[m]?'发现更小元素，更新 min。':'候选最小值保持不变。',3,[m,j],[],Array.from({length:i},(_,k)=>k),[i,n-1]);if(arr[j]<arr[m])m=j;}if(m!==i){swap(i,m);push('最小元素归位','只在每轮末尾交换一次，这也是选择排序交换次数较少的原因。',4,[i,m],[i,m],Array.from({length:i+1},(_,k)=>k));}else push('当前位置本来就是最小值','无需交换，有序前缀仍然扩大。',4,[i],[],Array.from({length:i+1},(_,k)=>k));}
  } else if(p.algo==='quick'){
    const qs=(l,r)=>{if(l>=r)return;const pivot=arr[r];let i=l-1;push('选择枢轴 '+pivot,'采用末元素作枢轴。分区目标：左边 ≤ pivot，右边 > pivot。',1,[r],[],[],[l,r],r);for(let j=l;j<r;j++){comparisons++;push('让 '+arr[j]+' 与枢轴比较',arr[j]<=pivot?'它应进入枢轴左侧区间。':'它留在右侧候选区。',3,[j,r],[],[],[l,r],r);if(arr[j]<=pivot){i++;if(i!==j){swap(i,j);push('扩展“小于等于”区间','交换后，边界 i 左侧都不大于枢轴。',4,[i,j],[i,j],[],[l,r],r);}}}swap(i+1,r);const q=i+1;push('枢轴 '+pivot+' 到达最终位置','分区完成：枢轴左侧不大于它，右侧大于它。枢轴无需再参与递归。',5,[q],[q],[q],[l,r],q);qs(l,q-1);qs(q+1,r)};qs(0,n-1);
  } else if(p.algo==='merge'){
    const ms=(l,r)=>{if(l>=r)return;const m=Math.floor((l+r)/2);push('把区间 ['+l+', '+r+'] 分成两半','归并排序先递归拆分，再把两个有序段合并。',1,[],[],[],[l,r]);ms(l,m);ms(m+1,r);const temp=[];let i=l,j=m+1;while(i<=m&&j<=r){comparisons++;push('比较两段的队首 '+arr[i]+' 与 '+arr[j],'较小者进入临时数组；原有相对次序可被保留，因此归并排序可以稳定。',4,[i,j],[],[],[l,r]);if(arr[i]<=arr[j])temp.push(arr[i++]);else temp.push(arr[j++]);writes++;push('写入临时数组','临时区当前为 ['+temp.join(', ')+']。',5,[],[],[],[l,r]);}while(i<=m){temp.push(arr[i++]);writes++;}while(j<=r){temp.push(arr[j++]);writes++;}for(let k=0;k<temp.length;k++){arr[l+k]=temp[k];writes++;push('把临时结果写回原数组','区间 ['+l+', '+r+'] 正在恢复为有序段。',7,[l+k],[l+k],[],[l,r]);}};ms(0,n-1);
  } else {
    const down=(root,size)=>{while(true){let child=root*2+1;if(child>=size)return;if(child+1<size){comparisons++;if(arr[child+1]>arr[child])child++;}comparisons++;push('比较父结点与较大的孩子','大顶堆要求父结点不小于两个孩子。',1,[root,child],[],Array.from({length:n-size},(_,k)=>n-1-k),[0,size-1]);if(arr[root]>=arr[child])return;swap(root,child);push('较大孩子上浮','交换后继续向下检查原父结点的新位置。',1,[root,child],[root,child],Array.from({length:n-size},(_,k)=>n-1-k),[0,size-1]);root=child;}};for(let i=Math.floor(n/2)-1;i>=0;i--)down(i,n);push('大顶堆建立完成','堆顶是当前最大值，但数组整体还没有有序。',1,[0],[],[],[0,n-1]);for(let end=n-1;end>0;end--){swap(0,end);push('把最大值交换到末尾','末尾元素从此退出堆，进入最终有序区。',3,[0,end],[0,end],Array.from({length:n-end},(_,k)=>end+k));down(0,end);} }
  push('排序完成','所有元素已经按非递减次序排列。试着更换算法：相同输入会走出完全不同的比较与移动轨迹。',code.length-1,[],[],Array.from({length:n},(_,i)=>i));
  return frames;
}

function schedulingModel(p) {
  const presets={mix:[['P1',0,6],['P2',1,3],['P3',2,7],['P4',4,2]],staggered:[['P1',0,5],['P2',3,2],['P3',5,4],['P4',6,1]]};
  const jobs=presets[p.load].map(([id,arrival,burst])=>({id,arrival,burst,remaining:burst,start:null,finish:null,wait:0}));
  const frames=[], timeline=[];let time=0,current=null,quantumLeft=p.quantum,done=0,ready=[];
  const snapshot=(title,copy,formula,event='tick')=>frames.push(makeFrame(title,copy,formula,{jobs,timeline,time,current,ready,quantumLeft,event,algo:p.algo,quantum:p.quantum}));
  snapshot('调度器只在若干时刻做决定','进程到达、当前进程完成或时间片耗尽时，调度器从就绪队列中选择下一个进程。等待时间只统计在就绪态停留的时间。','turnaround = finish − arrival · wait = turnaround − burst');
  const arrivals=()=>jobs.filter(j=>j.arrival===time&&j.remaining>0).forEach(j=>{if(!ready.includes(j.id)&&j.id!==current)ready.push(j.id)});
  const choose=()=>{if(!ready.length)return null;if(p.algo==='sjf'){let best=0;for(let i=1;i<ready.length;i++){const a=jobs.find(j=>j.id===ready[i]),b=jobs.find(j=>j.id===ready[best]);if(a.burst<b.burst)best=i;}return ready.splice(best,1)[0];}return ready.shift()};
  while(done<jobs.length&&time<40){arrivals();const curJob=jobs.find(j=>j.id===current);
    if(p.algo==='rr'&&curJob&&quantumLeft===0){ready.push(current);snapshot(current+' 的时间片用完','当前进程尚未结束，被放回就绪队列尾部；调度器将选择队首进程。','quantum = '+p.quantum+' · remaining = '+curJob.remaining,'preempt');current=null;}
    if(current==null){current=choose();quantumLeft=p.quantum;if(current){const j=jobs.find(x=>x.id===current);if(j.start==null)j.start=time;snapshot('调度 '+current+' 上 CPU',p.algo==='fcfs'?'FCFS 选择最早进入就绪队列的进程。':p.algo==='sjf'?'非抢占 SJF 选择本次 CPU 时间最短的已到达进程。':'RR 从队首取进程并给予固定时间片。','time = '+time+' · ready = ['+ready.join(', ')+']','dispatch');}}
    ready.forEach(id=>jobs.find(j=>j.id===id).wait++);
    if(current){const j=jobs.find(x=>x.id===current);j.remaining--;quantumLeft--;timeline.push(current);time++;snapshot(current+' 执行 1 个时间单位','时间轴新增一格；就绪队列中的其他进程各累计 1 个单位等待时间。','remaining('+current+') = '+j.remaining+' · time = '+time,'run');if(j.remaining===0){j.finish=time;done++;snapshot(current+' 执行完成','该进程离开系统。周转时间由完成时刻减到达时刻得到。','T = '+j.finish+' − '+j.arrival+' = '+(j.finish-j.arrival),'finish');current=null;}}
    else{timeline.push('IDLE');time++;snapshot('CPU 暂时空闲','当前没有已到达的就绪进程，时间轴记为空闲。','time = '+time,'idle');}}
  const avgW=jobs.reduce((a,j)=>a+j.wait,0)/jobs.length,avgT=jobs.reduce((a,j)=>a+j.finish-j.arrival,0)/jobs.length;
  snapshot('全部进程完成','不同算法改变响应顺序与平均等待时间。SJF 通常降低平均等待，但可能让长作业饥饿；RR 改善交互响应，却增加切换次数。','平均等待 '+avgW.toFixed(2)+' · 平均周转 '+avgT.toFixed(2),'done');
  return frames;
}
function replacementModel(p){
  const refs=p.refs.slice(),cap=p.frames,slots=Array(cap).fill(null),last=Array(cap).fill(-1),loaded=Array(cap).fill(-1),frames=[],history=[];let faults=0;
  const push=(title,copy,formula,index=-1,target=-1,hit=false,evicted=null)=>frames.push(makeFrame(title,copy,formula,{refs,slots,last,loaded,history,faults,index,target,hit,evicted,algo:p.algo,cap}));
  push('页框为空，引用串即将开始','每次访问先检查页面是否已经在页框中；不在则发生缺页，并按所选算法决定装入位置。','页框数 = '+cap+' · 缺页数 = 0');
  refs.forEach((page,index)=>{let target=slots.indexOf(page),hit=target>=0,evicted=null;if(hit){last[target]=index;history.push({page,hit:true,target});push('访问页面 '+page+'：命中','页面已经驻留，不需要置换。LRU 会更新最近使用时刻，FIFO 不改变装入顺序。','HIT · faults = '+faults,index,target,true);return;}faults++;target=slots.indexOf(null);if(target<0){if(p.algo==='fifo')target=loaded.indexOf(Math.min(...loaded));else if(p.algo==='lru')target=last.indexOf(Math.min(...last));else{let far=-1;target=0;for(let i=0;i<cap;i++){let next=refs.slice(index+1).indexOf(slots[i]);if(next<0){target=i;far=Infinity;break}if(next>far){far=next;target=i}}}evicted=slots[target];}slots[target]=page;last[target]=index;loaded[target]=index;history.push({page,hit:false,target,evicted});push(evicted==null?'访问页面 '+page+'：装入空页框':'访问页面 '+page+'：置换页面 '+evicted,evicted==null?'页面不在内存，且存在空页框，直接调入。':'所有页框已满。'+(p.algo==='fifo'?'FIFO 换出最早进入内存的页面。':p.algo==='lru'?'LRU 换出过去最久未被访问的页面。':'OPT 换出未来最晚才会再用、或不再使用的页面。'),(hit?'HIT':'FAULT')+' · faults = '+faults,index,target,false,evicted)});
  push('引用串处理完毕','命中率与缺页率由整个引用串统计。OPT 需要知道未来，因此只能作为理论最优基准；FIFO 还可能出现 Belady 异常。','缺页率 = '+faults+' / '+refs.length+' = '+(faults/refs.length*100).toFixed(1)+'%',refs.length-1,-1,false);
  return frames;
}
function congestionModel(p){
  const threshold=p.threshold,rounds=14,frames=[];let cwnd=1,ssthresh=threshold,dup=0;const history=[];
  const push=(title,copy,formula,phase,event='ack')=>frames.push(makeFrame(title,copy,formula,{cwnd,ssthresh,dup,history,phase,event,loss:p.loss}));
  push('拥塞窗口从 1 MSS 开始','发送方用 cwnd 限制网络中未确认的数据量。慢开始并不慢：它让窗口按 RTT 近似翻倍，快速探测可用带宽。','cwnd = 1 MSS · ssthresh = '+ssthresh,'慢开始','start');
  for(let r=1;r<=rounds;r++){
    const phase=cwnd<ssthresh?'慢开始':'拥塞避免';history.push({r,cwnd,phase,ssthresh});push('第 '+r+' 轮发送 '+cwnd+' 个报文段',phase==='慢开始'?'每收到 ACK，cwnd 增加 1 MSS；一整个 RTT 后近似翻倍。':'每个 RTT 只让 cwnd 大约增加 1 MSS，线性试探剩余带宽。','round '+r+' · cwnd = '+cwnd+' · ssthresh = '+ssthresh,phase,'send');
    if(r===p.lossRound){const old=cwnd;ssthresh=Math.max(2,Math.floor(cwnd/2));if(p.loss==='timeout'){cwnd=1;dup=0;push('发生超时：窗口骤降到 1','超时意味着拥塞较重。把 ssthresh 设为旧窗口的一半，cwnd 回到 1，重新慢开始。','ssthresh = '+ssthresh+' · cwnd = 1','超时恢复','timeout');}else{dup=3;cwnd=ssthresh+3;push('收到 3 个重复 ACK：快重传','不等超时，立即重传缺失段；进入快速恢复，暂把重复 ACK 反映为在途数据已离开网络。','ssthresh = '+ssthresh+' · cwnd = '+cwnd,'快速恢复','dupack');cwnd=ssthresh;push('新 ACK 到达，退出快速恢复','确认覆盖了重传段后，cwnd 回到 ssthresh，进入拥塞避免。','cwnd = ssthresh = '+ssthresh,'拥塞避免','recover');}continue;}
    if(cwnd<ssthresh)cwnd=Math.min(cwnd*2,ssthresh);else cwnd+=1;push(phase==='慢开始'?'ACK 推动窗口指数增长':'ACK 推动窗口线性增长',phase==='慢开始'?'只要还低于 ssthresh，下一轮窗口近似翻倍。':'每经过一个 RTT，拥塞窗口约增加 1 MSS。','next cwnd = '+cwnd,cwnd<ssthresh?'慢开始':'拥塞避免');}
  push('窗口形成典型的锯齿轨迹','拥塞控制调节的是发送速率，不等于接收方流量控制。真实 TCP 版本在细节上有所差异，本实验采用经典 Reno 教学口径。','send window = min(cwnd, rwnd)','完成','done');return frames;
}

function semaphoreModel(p) {
  const cap = p.capacity, items = [], waitP = [], waitC = [];
  let empty = cap, full = 0, mutex = 1;
  const frames = [];
  const snap = (title, copy, formula, actor = '', action = '', token = '') => frames.push(makeFrame(title, copy, formula, { cap, items, waitP, waitC, empty, full, mutex, actor, action, token }));
  snap('三个信号量，守住三件不同的事', '<strong>empty</strong> 表示空槽数量，<strong>full</strong> 表示已有产品数量，mutex 只保护缓冲区这段临界区。P 可能阻塞，V 可能唤醒。', 'empty = ' + cap + ' · full = 0 · mutex = 1');
  const put = (actor, token) => {
    empty--; snap(actor + ' 执行 P(empty)', '先预订一个空槽。若 empty 原本为 0，生产者应在这里睡眠，而不是进入缓冲区。', 'P(empty): ' + (empty + 1) + ' → ' + empty, actor, 'P(empty)', token);
    mutex--; snap(actor + ' 进入临界区', 'P(mutex) 成功后，当前生产者独占缓冲区结构。<strong>互斥锁应该尽量晚拿、尽量早放</strong>。', 'P(mutex): 1 → 0', actor, 'lock', token);
    items.push(token); snap('把产品 ' + token + ' 放入缓冲区', '修改共享缓冲区必须发生在 mutex 保护之内。此时 full 尚未增加，消费者仍不能把它当成可用产品。', 'buffer.push(' + token + ')', actor, 'put', token);
    mutex++; full++; snap('离开临界区，并发布一个产品', '先 V(mutex)，再 V(full)。full 增加后，若有消费者在等待，就会唤醒其中一个。', 'V(mutex); V(full) → full = ' + full, actor, 'signal', token);
  };
  const take = actor => {
    full--; snap(actor + ' 执行 P(full)', '先确认缓冲区里确实有产品。若 full 为 0，消费者会阻塞，不能继续取空槽。', 'P(full): ' + (full + 1) + ' → ' + full, actor, 'P(full)');
    mutex--; snap(actor + ' 进入临界区', '消费者获得 mutex，其他生产者和消费者暂时不能修改缓冲区。', 'P(mutex): 1 → 0', actor, 'lock');
    const token = items.shift(); snap('取出最早进入的产品 ' + token, '有界缓冲区按 FIFO 展示。取出操作结束后要先释放互斥，再告诉生产者多了一个空槽。', 'buffer.shift() → ' + token, actor, 'take', token);
    mutex++; empty++; snap('离开临界区，并归还一个空槽', 'V(empty) 让等待空槽的生产者有机会继续。资源计数与互斥是两类职责，不能只用一个信号量代替。', 'V(mutex); V(empty) → empty = ' + empty, actor, 'signal', token);
  };
  if (p.scenario === 'consumer') {
    waitC.push('C1'); snap('缓冲区为空，消费者 C1 阻塞', 'C1 执行 P(full)，发现 full = 0，于是进入 full 的等待队列。<strong>阻塞不是忙等</strong>，它不继续占用 CPU 循环检查。', 'P(full) when full = 0 → block C1', 'C1', 'block');
    put('P1', 'A'); waitC.shift(); snap('V(full) 唤醒等待的 C1', 'P1 发布产品后，C1 从等待队列转为就绪；调度后重新完成 P(full)，再进入临界区。', 'wake(C1) · full 保持可消费', 'C1', 'wake', 'A'); take('C1');
  } else if (p.scenario === 'producer') {
    for (let i = 0; i < cap; i++) put('P1', String.fromCharCode(65 + i));
    waitP.push('P2'); snap('缓冲区已满，生产者 P2 阻塞', 'P2 执行 P(empty)，发现 empty = 0，进入 empty 的等待队列。注意它<strong>尚未获得 mutex</strong>，因此不会抱锁睡眠。', 'P(empty) when empty = 0 → block P2', 'P2', 'block', 'D');
    take('C1'); waitP.shift(); snap('V(empty) 唤醒 P2', '消费者释放空槽后，P2 可以继续完成 P(empty)，随后再竞争 mutex。正确顺序避免“拿着 mutex 等 empty”的死锁。', 'wake(P2) · empty 可被预订', 'P2', 'wake', 'D');
  } else { put('P1', 'A'); put('P2', 'B'); take('C1'); put('P1', 'C'); take('C2'); }
  snap('计数与缓冲区重新一致', '任何时刻都应满足 <strong>empty + full = N</strong>，mutex 只取 0 或 1。用这两个不变量检查 PV 操作是否漏写或次序错误。', 'empty + full = ' + empty + ' + ' + full + ' = ' + cap, '', 'done');
  return frames;
}

function bankerModel(p) {
  const available = [3,3,2];
  const alloc = [[0,1,0],[2,0,0],[3,0,2],[2,1,1],[0,0,2]].map(r=>r.slice());
  const max = [[7,5,3],[3,2,2],[9,0,2],[2,2,2],[4,3,3]].map(r=>r.slice());
  const need = max.map((r,i)=>r.map((v,j)=>v-alloc[i][j]));
  const requests = p.request === 'safe' ? {pid:1,vec:[1,0,2]} : {pid:4,vec:[3,3,0]};
  let work = available.slice(), finish = Array(5).fill(false), sequence = [];
  const frames=[];
  const push=(title,copy,formula,current=-1,status='scan',request=null)=>frames.push(makeFrame(title,copy,formula,{available,alloc,max,need,work,finish,sequence,current,status,request,requestType:p.request}));
  push('安全，不等于“现在每个人都能满足”','银行家算法寻找的是一种<strong>完成顺序</strong>：沿这个顺序，每个进程都能拿到剩余资源、完成并归还占有量。','Need = Max − Allocation');
  const {pid,vec}=requests;
  push('进程 P'+pid+' 提出请求 ['+vec.join(', ')+']','先检查 Request ≤ Need，再检查 Request ≤ Available。只有两关都过，才做一次“假分配”并运行安全性算法。','Request ≤ Need 且 Request ≤ Available',pid,'request',vec);
  const allowed=vec.every((v,j)=>v<=need[pid][j]&&v<=work[j]);
  if(!allowed){push('请求超过当前可用量，暂不分配','这不是说系统已经死锁，而是当前请求不能立即满足。进程进入等待，不改变系统资源状态。','Request ≰ Available → wait',pid,'denied',vec);return frames;}
  vec.forEach((v,j)=>{work[j]-=v;alloc[pid][j]+=v;need[pid][j]-=v});
  push('先假装把资源分给 P'+pid,'银行家算法不立刻承诺，而是在副本上扣减 Available、增加 Allocation、减少 Need，然后测试是否仍存在安全序列。','Work = ['+work.join(', ')+']',pid,'grant',vec);
  let progressed=true;
  while(sequence.length<5&&progressed){progressed=false;for(let i=0;i<5;i++){if(finish[i])continue;const can=need[i].every((v,j)=>v<=work[j]);push(can?'P'+i+' 的剩余需求可以满足':'P'+i+' 暂时不能完成',can?'Need[P'+i+'] ≤ Work。假设它获得资源并运行结束，随后归还当前占有的全部资源。':'至少一种资源的 Need 大于 Work；先跳过它，继续寻找其他可完成进程。','Need ['+need[i].join(', ')+'] '+(can?'≤':'≰')+' Work ['+work.join(', ')+']',i,can?'can':'skip');if(can){finish[i]=true;sequence.push(i);work=work.map((v,j)=>v+alloc[i][j]);push('P'+i+' 完成并归还资源','Work 加上 P'+i+' 的 Allocation。资源变多后，之前不能满足的进程也可能变得可行。','Work ← Work + Allocation[P'+i+'] = ['+work.join(', ')+']',i,'finish');progressed=true;break;}}}
  const safe=finish.every(Boolean);
  push(safe?'找到安全序列，假分配可以提交':'找不到安全序列，必须撤销假分配',safe?'序列 <strong>&lt;'+sequence.map(i=>'P'+i).join(', ')+'&gt;</strong> 证明所有进程都可以依次完成。安全状态不保证调度一定按它执行，只证明至少存在一条路。':'已经找不到 Need ≤ Work 的未完成进程。系统进入不安全状态；不安全不等于已经死锁，但存在走向死锁的风险。',safe?'Safe sequence = '+sequence.map(i=>'P'+i).join(' → '):'rollback tentative allocation',-1,safe?'safe':'unsafe');
  return frames;
}

function interruptModel(p) {
  const external=p.kind==='external';
  const frames=[], base={kind:p.kind,phase:0,pc:'0x1040',sp:'0x7FF0',vector:external?'0x0020':'0x000C',source:external?'I/O 设备完成':'DIV 指令除数为 0',stack:[]};
  frames.push(makeFrame('CPU 正在顺序执行程序','中断响应发生在指令边界附近；异常则由当前指令执行触发。两者都要暂时离开用户程序，转入操作系统的处理例程。','PC = 0x1040 · PSW = USER',base));
  frames.push(makeFrame(external?'设备发出中断请求':'当前指令触发同步异常',external?'I/O 控制器置位中断请求。CPU 先完成当前指令，再检查<strong>中断允许位与优先级</strong>。':'除零异常与当前指令同步发生。处理后是否重试、终止或跳过，要由异常类型与操作系统决定。',external?'INTR = 1 · IF = 1':'trap(divide_error)',{...base,phase:1}));
  frames.push(makeFrame('硬件自动保存最小现场','CPU 切换到内核态，把返回所需的 PC、PSW 等压入内核栈。通用寄存器通常由软件入口继续保存。','push(PC, PSW) · mode → KERNEL',{...base,phase:2,stack:['PSW: USER','PC: 0x1040']}));
  frames.push(makeFrame('根据中断向量找到入口','中断类型号不是处理代码本身。CPU 用它索引<strong>中断向量表</strong>，读取对应服务程序入口地址。','IVT['+(external?'0x20':'0x0C')+'] → '+(external?'0xF120':'0xE840'),{...base,phase:3,stack:['PSW: USER','PC: 0x1040']}));
  frames.push(makeFrame('服务程序处理中断原因',external?'驱动读取设备状态、搬走数据并清除中断请求。若使用 DMA，大块数据搬运可由控制器完成，CPU 只处理开始与结束。':'异常处理程序记录错误并根据策略处理当前进程。异常来自当前指令，返回地址语义可能与外部中断不同。','ISR: save regs → handle → restore regs',{...base,phase:4,stack:['R0…Rn','PSW: USER','PC: 0x1040']}));
  frames.push(makeFrame('中断返回，恢复原来的控制流','执行专用中断返回指令，恢复 PSW 与 PC。若期间唤醒了更高优先级进程，调度器也可能选择先运行别的进程。','iret → PC = 0x1040 · mode → USER',{...base,phase:5,stack:[]}));
  return frames;
}

function cidrModel(p) {
  const ip=p.dest;
  const routes=[
    {prefix:'0.0.0.0/0',mask:0,base:0,next:'R0 · 默认出口'},
    {prefix:'10.0.0.0/8',mask:8,base:10<<24,next:'R1 · 校园网'},
    {prefix:'10.16.0.0/12',mask:12,base:(10<<24)|(16<<16),next:'R2 · 实验网'},
    {prefix:'10.18.32.0/20',mask:20,base:(10<<24)|(18<<16)|(32<<8),next:'R3 · 机房'}
  ];
  const toInt=s=>s.split('.').reduce((a,v)=>(a*256+(+v))>>>0,0)>>>0, n=toInt(ip);
  const matches=r=>r.mask===0||((n>>>(32-r.mask))===(r.base>>>(32-r.mask)));
  const frames=[], matched=[];
  const push=(title,copy,formula,current=-1,chosen=-1)=>frames.push(makeFrame(title,copy,formula,{ip,routes,matched,current,chosen,bits:n.toString(2).padStart(32,'0')}));
  push('路由器只看目标地址','同一个目标可能同时匹配多条路由。转发表查找不是“先遇到谁选谁”，而是选择<strong>前缀最长</strong>、范围最具体的一条。','destination = '+ip);
  routes.forEach((r,i)=>{const ok=matches(r);if(ok)matched.push(i);push(ok?ip+' 匹配 '+r.prefix:ip+' 不属于 '+r.prefix,ok?'目标地址的前 '+r.mask+' 位与网络前缀相同，把它加入候选集合。':'掩码后的网络号不同，这条路由不能使用。','('+ip+' AND /'+r.mask+') '+(ok?'=':'≠')+' '+r.prefix.split('/')[0],i);});
  const chosen=matched.reduce((a,b)=>routes[a].mask>routes[b].mask?a:b);
  push('选择前缀最长的 '+routes[chosen].prefix,'它覆盖的地址范围最小，因此比更短的前缀更具体。默认路由 /0 只在没有更具体匹配时兜底。','max prefix length = /'+routes[chosen].mask+' → '+routes[chosen].next,-1,chosen);
  return frames;
}
const Models = { memory:memoryModel, cache:cacheModel, pipeline:pipelineModel, tcp:tcpModel, dijkstra:dijkstraModel, avl:avlModel, sorting:sortingModel, scheduling:schedulingModel, replacement:replacementModel, congestion:congestionModel, semaphore:semaphoreModel, banker:bankerModel, interrupt:interruptModel, cidr:cidrModel };
if (typeof module !== 'undefined') module.exports = { Models, hex };
