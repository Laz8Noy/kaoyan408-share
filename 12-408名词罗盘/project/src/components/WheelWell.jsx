import { useCallback, useRef, useState } from 'react';
import { gsap } from 'gsap';
import OptionWheel from './OptionWheel.jsx';

/**
 * WheelWell —— 收纳态 = 一叠牌只露中间一条；指向 = 平滑扇形展开。
 * 不动 OptionWheel 本体，把它支持的 spacing/tilt/curve/blur/fade 参数
 * 用 gsap 补间逐帧喂进去（原版每帧从 props 重排，天然支持动态参数）。
 */
const OPEN = { spacing: 1.45, blur: 2, fade: 0.22, tilt: 7, curve: 1.1, hMul: 8.1 };
const SHUT = { spacing: 0.5, blur: 2.6, fade: 0.95, tilt: 2.5, curve: 0.55, hMul: 2.3 };

export default function WheelWell({
  label,
  items,
  fontSize = 1.28,
  defaultSelected = 0,
  onChange,
  soundUrl,
  soundVolume = 0.5,
  inset = 24,
  textColor = '#7d89a6',
  activeColor = '#121a2b'
}) {
  const canHover =
    typeof window !== 'undefined' && window.matchMedia('(hover: hover)').matches;
  const [open, setOpen] = useState(!canHover);
  const st = useRef({ ...(canHover ? SHUT : OPEN) }).current;
  const [, force] = useState(0);

  const toggle = useCallback(
    next => {
      setOpen(next);
      gsap.to(st, {
        ...(next ? OPEN : SHUT),
        duration: 0.6,
        ease: 'power3.out',
        overwrite: true,
        onUpdate: () => force(v => v + 1)
      });
    },
    [st]
  );

  const h = fontSize * 16 * st.hMul;

  return (
    <div
      className={`fanwell glass${open ? ' is-open' : ''}`}
      onMouseEnter={() => canHover && toggle(true)}
      onMouseLeave={() => canHover && toggle(false)}
      onFocus={() => canHover && toggle(true)}
      onBlur={e => {
        if (canHover && !e.currentTarget.contains(e.relatedTarget)) toggle(false);
      }}
    >
      <p className="well-label">{label}</p>
      <div className="wheel-box" style={{ height: h }}>
        <OptionWheel
          items={items}
          defaultSelected={defaultSelected}
          textColor={textColor}
          activeColor={activeColor}
          side="left"
          fontSize={fontSize}
          spacing={st.spacing}
          curve={st.curve}
          tilt={st.tilt}
          blur={st.blur}
          fade={st.fade}
          smoothing={190}
          inset={inset}
          draggable
          soundUrl={soundUrl}
          soundVolume={soundVolume}
          onChange={onChange}
        />
      </div>
    </div>
  );
}
