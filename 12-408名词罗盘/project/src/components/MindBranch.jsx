import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { gsap } from 'gsap';
import './MindBranch.css';

/**
 * MindBranch —— 层级直列视图：
 * 不做扇形弧线，纯垂直列表；焦点行 = 无框的巨型标题（纯字重对比），
 * 相邻行自动让位（指数扩张间距，避免与大字号重叠）；
 * 层级 = 缩进 + 虚线引导线 + 圆点按级分尺寸；
 * 平滑移动/距离淡出/渐进模糊沿用轮盘的 rAF 机制。
 */
const SPAN = 8; // 只渲染焦点上下各 8 行

const CJK = /[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]/;
const effLen = s => {
  let e = 0;
  for (const c of s) e += CJK.test(c) ? 1 : 0.56;
  return e || 1;
};
const viewFactor = () =>
  typeof window === 'undefined' ? 1 : Math.max(1, Math.min(1.4, window.innerWidth / 1280));

const KIND_CN = { part: '科', chapter: '章', section: '节', bullet: '点' };

export default function MindBranch({ subject }) {
  const items = subject.items;
  const [focus, setFocusState] = useState(0);
  const focusRef = useRef(0);
  const posRef = useRef(0);
  const targetRef = useRef(0);
  const rafRef = useRef(0);
  const lastRef = useRef(0);
  const stageRef = useRef(null);
  const rowEls = useRef(new Map());
  const [boxW, setBoxW] = useState(1000);
  const [vf, setVf] = useState(viewFactor);

  /* —— 几何参数 —— */
  const step = Math.max(30, 40 * vf); // 基准槽距
  const PUSH = 2.8; // 焦点让位强度（指数扩张）
  const fade = 0.1;
  const smoothing = 170;

  const setF = useCallback(i => {
    const v = Math.max(0, i);
    focusRef.current = v;
    setFocusState(v);
  }, []);

  useEffect(() => {
    setF(0);
    posRef.current = 0;
    targetRef.current = 0;
  }, [subject, setF]);

  /* 逐帧布局：连续 pos → 直列让位排布（无旋转、无弧线） */
  const layout = useCallback(() => {
    const pos = posRef.current;
    rowEls.current.forEach((el, idx) => {
      if (!el) return;
      const d = idx - pos;
      const ad = Math.abs(d);
      const sgn = d >= 0 ? 1 : -1;
      const y = step * (d + PUSH * sgn * (1 - Math.exp(-ad / 2.2)));
      el.style.transform = `translate3d(0, calc(${y.toFixed(1)}px - 50%), 0)`;
      el.style.opacity = String(Math.max(0.08, 1 - ad * fade));
      el.style.filter = ad > 2 ? `blur(${Math.min(2.6, (ad - 2) * 0.55).toFixed(2)}px)` : 'none';
      el.style.zIndex = String(100 - Math.round(ad * 5));
    });
  }, [step, PUSH, fade]);

  const runFrame = useCallback(
    now => {
      const dt = Math.min((now - lastRef.current) / 1000, 0.05);
      lastRef.current = now;
      const k = 1 - Math.exp(-dt / (smoothing / 1000));
      let next = posRef.current + (targetRef.current - posRef.current) * k;
      const settled = Math.abs(targetRef.current - next) < 0.001;
      if (settled) next = targetRef.current;
      posRef.current = next;
      layout();
      rafRef.current = settled ? 0 : requestAnimationFrame(runFrame);
    },
    [layout]
  );

  /* 目标变了就启动/校正 rAF 循环（含 resize 重排） */
  useEffect(() => {
    targetRef.current = focus;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    lastRef.current = performance.now();
    rafRef.current = requestAnimationFrame(runFrame);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [focus, vf, boxW, runFrame]);

  /* 容器宽度监听 */
  useEffect(() => {
    const el = stageRef.current;
    const measure = () => {
      setVf(viewFactor());
      if (el) setBoxW(el.clientWidth);
    };
    measure();
    let ro;
    if (el && window.ResizeObserver) {
      ro = new ResizeObserver(measure);
      ro.observe(el);
    }
    addEventListener('resize', measure);
    return () => {
      ro?.disconnect();
      removeEventListener('resize', measure);
    };
  }, []);

  /* 滚轮：一格一行 */
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    let acc = 0;
    const onWheel = e => {
      e.preventDefault();
      acc += e.deltaY;
      while (Math.abs(acc) >= 52) {
        const v = focusRef.current + Math.sign(acc);
        acc -= Math.sign(acc) * 52;
        if (v >= 0 && v < items.length) setF(v);
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [setF, items.length]);

  /* 键盘 */
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onKey = e => {
      const map = { ArrowDown: 1, ArrowUp: -1, PageDown: 6, PageUp: -6 };
      if (e.key in map) {
        e.preventDefault();
        const v = focusRef.current + map[e.key];
        if (v >= 0 && v < items.length) setF(v);
      } else if (e.key === 'Home') setF(0);
      else if (e.key === 'End') setF(items.length - 1);
    };
    el.addEventListener('keydown', onKey);
    return () => el.removeEventListener('keydown', onKey);
  }, [setF, items.length]);

  /* 拖拽：每 step 一行，移动超阈值才 capture */
  const drag = useRef(null);
  const suppressClick = useRef(false);
  const onPointerDown = e => {
    if (e.button !== 0) return;
    suppressClick.current = false;
    drag.current = { y: e.clientY, from: focusRef.current, moved: false, id: e.pointerId };
  };
  const onPointerMove = e => {
    const d = drag.current;
    if (!d) return;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.abs(dy) <= 4) return;
    if (!d.moved) {
      d.moved = true;
      suppressClick.current = true;
      try {
        e.currentTarget.setPointerCapture(d.id);
      } catch {
        /* noop */
      }
    }
    const units = Math.round(-dy / step);
    if (units !== d.shown) {
      d.shown = units;
      const v = Math.min(Math.max(d.from + units, 0), items.length - 1);
      setF(v);
    }
  };
  const onPointerUp = () => {
    drag.current = null;
  };

  /* 祖先链（含索引）：作为"悬挂层级"渲染在舞台顶部 */
  const chain = useMemo(() => {
    const out = [];
    let depth = items[focus].d;
    for (let i = focus - 1; i >= 0 && depth > 0; i--) {
      if (items[i].d < depth) {
        out.unshift({ idx: i, ...items[i] });
        depth = items[i].d;
      }
    }
    return out;
  }, [focus, items]);

  /* 只渲染窗口内行 */
  const lo = Math.max(0, focus - SPAN);
  const hi = Math.min(items.length - 1, focus + SPAN);
  const rows = [];
  for (let i = lo; i <= hi; i++) rows.push(i);

  return (
    <div className="mind-wrap glass" style={{ '--sc': subject.color }}>
      <header className="mb-head">
        <p className="mb-crumb" aria-label="当前科目">
          <span className="mb-subject">{subject.name}</span>
        </p>
        <p className="mb-progress mono">
          {focus + 1} / {items.length} · 滚轮/拖拽/方向键播放 · 点击直达
        </p>
      </header>

      <div
        className="mw-stage"
        ref={stageRef}
        tabIndex={0}
        role="listbox"
        aria-label="思维导图轮盘"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {rows.map(i => {
          const it = items[i];
          const isFocus = i === focus;
          const depth = Math.min(it.d, 5);
          const indent = isFocus ? 20 : 28 + depth * 20;
          const avail = Math.max(240, boxW - indent - 60);
          /* 焦点行：整句撑满可用宽度的无框大标题 */
          const fs = isFocus
            ? Math.max(30, Math.min(76, (avail / effLen(it.t)) * 0.95))
            : SMALL_BASE[it.k] * vf;
          return (
            <div
              key={i}
              ref={el => {
                if (el) rowEls.current.set(i, el);
                else rowEls.current.delete(i);
              }}
              className={`mw-row is-${it.k}${isFocus ? ' is-focus' : ''}`}
              style={{
                paddingLeft: indent,
                '--gx': !isFocus && it.d > 0 ? `${28 + (depth - 1) * 20 + 4}px` : undefined,
                fontSize: `${fs.toFixed(1)}px`,
                maxWidth: `${boxW}px`
              }}
              onClick={() => {
                if (suppressClick.current) return;
                setF(i);
              }}
              role="option"
              aria-selected={isFocus}
            >
              {isFocus ? (
                <span className="focus-col">
                  {chain.length > 0 && (
                    <button
                      type="button"
                      className="focus-parent mono"
                      onClick={e => {
                        e.stopPropagation();
                        if (!suppressClick.current) setF(chain[chain.length - 1].idx);
                      }}
                    >
                      └ {chain[chain.length - 1].t}
                    </button>
                  )}
                  <span className="mb-text">{it.t}</span>
                </span>
              ) : (
                <>
                  <span className="mb-dot" aria-hidden="true" />
                  <span className="mb-text">{it.t}</span>
                  {it.d <= 2 && <span className="mb-kind">{KIND_CN[it.k]}</span>}
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const SMALL_BASE = { part: 26, chapter: 23, section: 21, bullet: 19 };
