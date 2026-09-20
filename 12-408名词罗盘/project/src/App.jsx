import { useState } from 'react';
import ClickSpark from './components/ClickSpark.jsx';
import ScrollVelocity from './components/ScrollVelocity.jsx';
import BlurText from './components/BlurText.jsx';
import Magnet from './components/Magnet.jsx';
import SpotlightCard from './components/SpotlightCard.jsx';
import WheelWell from './components/WheelWell.jsx';
import MindBranch from './components/MindBranch.jsx';
import TextType from './components/TextType.jsx';
import books from './data/books.json';
import mindData from './data/mindmap.json';

const MIND = Object.fromEntries(mindData.map(s => [s.name, s]));

const countTerms = b =>
  b.chapters.reduce((x, c) => x + c.sections.reduce((y, z) => y + z.terms.length, 0), 0);
const TAGLINES = books.map(b => `${b.name}｜${b.tagline} · 收录 ${countTerms(b)} 条`);
const TAG_COLORS = books.map(b => b.color);
const SV_TEXTS = books.map(b => `${b.name} · ${b.en} ✦`);
const MINDMAP = encodeURI(`${import.meta.env.BASE_URL}sources/408四科融合思维导图 1.pdf`);

export default function App() {
  const [act, setAct] = useState('hero');
  const [bookIdx, setBookIdx] = useState(0);
  const [chapIdx, setChapIdx] = useState(0);
  const [secIdx, setSecIdx] = useState(0);
  const [termOpen, setTermOpen] = useState(0);
  const [view, setView] = useState('terms');

  const openBook = i => {
    setBookIdx(i);
    setChapIdx(0);
    setSecIdx(0);
    setTermOpen(0);
    setAct('browse');
  };

  const book = books[bookIdx];
  const chapter = book.chapters[chapIdx];
  const section = chapter.sections[secIdx];

  let scene;
  if (act === 'hero') {
    scene = (
      <main className="scene scene--hero" key="hero">
        <ScrollVelocity texts={SV_TEXTS} velocity={26} numCopies={4} className="sv-line" />
        <section className="hero">
          <BlurText
            text="名詞羅盤 TERMINOLOGY COMPASS"
            animateBy="characters"
            direction="top"
            delay={48}
            stepDuration={0.42}
            className="hero-title"
          />
          <p className="hero-desc">408 统考四科专业名词手册 · 轮盘索引 · 章 → 节 → 词条</p>
          <TextType
            text={TAGLINES}
            as="p"
            className="hero-typing"
            typingSpeed={38}
            deletingSpeed={14}
            pauseDuration={2200}
            initialDelay={1200}
            textColors={TAG_COLORS}
            variableSpeed={{ min: 22, max: 60 }}
            cursorCharacter="▌"
          />
          <Magnet padding={110} magnetStrength={3}>
            <button type="button" className="cta" onClick={() => setAct('shelf')}>
              推门见书 →
            </button>
          </Magnet>
        </section>
        <ScrollVelocity texts={[...SV_TEXTS].reverse()} velocity={20} numCopies={4} className="sv-line sv-line--dim" />
      </main>
    );
  } else if (act === 'shelf') {
    scene = (
      <main className="scene scene--shelf" key="shelf">
        <header className="bar">
          <button type="button" className="link-back" onClick={() => setAct('hero')}>
            ← 首页
          </button>
          <h2 className="bar-title">选择一册</h2>
          <a className="link-src" href={MINDMAP} target="_blank" rel="noreferrer">
            四科融合思维导图 ↗
          </a>
        </header>
        <div className="shelf-grid">
          {books.map((b, i) => (
            <SpotlightCard key={b.id} className="book-card" spotlightColor={`${b.color}4d`}>
              <span className="book-abbr" style={{ '--ac': b.color }}>
                {b.abbr}
              </span>
              <h3 className="book-name">{b.name}</h3>
              <p className="book-en">{b.en}</p>
              <p className="book-tag">{b.tagline}</p>
              <div className="book-foot">
                <span className="book-meta">
                  {b.chapters.length} 章 · {countTerms(b)} 词
                </span>
                <button
                  type="button"
                  className="book-go"
                  style={{ '--ac': b.color }}
                  onClick={() => openBook(i)}
                >
                  开始拨轮 →
                </button>
              </div>
            </SpotlightCard>
          ))}
        </div>
      </main>
    );
  } else {
    scene = (
      <main className="scene scene--browse" key={`browse-${bookIdx}`}>
        <header className="bar">
          <button type="button" className="link-back" onClick={() => setAct('shelf')}>
            ← 书架
          </button>
          <h2 className="bar-title">
            <span style={{ color: book.color }}>{book.abbr}</span> {book.name} · 第
            {chapter.num}章 {chapter.title}
          </h2>
          <div className="seg" role="tablist" aria-label="视图切换">
            <button
              type="button"
              role="tab"
              aria-selected={view === 'terms'}
              className={view === 'terms' ? 'seg-btn is-on' : 'seg-btn'}
              style={{ '--ac': book.color }}
              onClick={() => setView('terms')}
            >
              词条
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'mind'}
              className={view === 'mind' ? 'seg-btn is-on' : 'seg-btn'}
              style={{ '--ac': book.color }}
              onClick={() => setView('mind')}
            >
              思维导图
            </button>
          </div>
          <a
            className="link-src"
            href={encodeURI(`${import.meta.env.BASE_URL}sources/${book.file}`)}
            target="_blank"
            rel="noreferrer"
          >
            《{book.name}》原典 ↗
          </a>
        </header>

        {view === 'terms' ? (
          <div className="browse-grid">
            <aside className="wheels">
              <WheelWell
                key={`ch-${bookIdx}`}
                label="章 · Chapter · 悬停展开"
                items={book.chapters.map(c => `${c.num} ${c.title}`)}
                defaultSelected={0}
                fontSize={1.55}
                inset={24}
                onChange={i => {
                  setChapIdx(i);
                  setSecIdx(0);
                  setTermOpen(0);
                }}
              />
              <WheelWell
                key={`sec-${bookIdx}-${chapIdx}`}
                label="节 · Section · 悬停展开"
                items={chapter.sections.map(s => `${s.num} ${s.title}`)}
                defaultSelected={0}
                fontSize={1.28}
                inset={22}
                onChange={i => {
                  setSecIdx(i);
                  setTermOpen(0);
                }}
              />
              <p className="well-hint" style={{ '--ac': book.color }}>
                当前：{section.num} {section.title} · {section.terms.length} 词
              </p>
            </aside>

            <SpotlightCard className="terms-card glass" spotlightColor={`${book.color}33`}>
              <div className="terms-list">
                {section.terms.map((t, i) => (
                  <article
                    key={`${bookIdx}-${chapIdx}-${secIdx}-${i}`}
                    className={i === termOpen ? 'term is-open' : 'term'}
                    style={{ '--ac': book.color }}
                    onClick={() => setTermOpen(i === termOpen ? -1 : i)}
                  >
                    <div className="term-head">
                      <h4>{t.t}</h4>
                      {t.e ? <code>{t.e}</code> : null}
                      <span className="term-no">{String(i + 1).padStart(2, '0')}</span>
                    </div>
                    <p className="term-body">{t.d}</p>
                  </article>
                ))}
              </div>
            </SpotlightCard>
          </div>
        ) : (
          <div className="browse-grid browse-grid--full">
            <MindBranch key={`mind-${bookIdx}`} subject={MIND[book.name]} />
          </div>
        )}
      </main>
    );
  }

  return (
    <ClickSpark sparkColor="#8f4fff" sparkSize={12} sparkRadius={22} sparkCount={8} duration={480}>
      {scene}
    </ClickSpark>
  );
}
