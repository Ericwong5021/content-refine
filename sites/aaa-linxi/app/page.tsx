import SearchPanel from './components/SearchPanel';
import { book, chapterNumber, searchIndex, articles, articlesByChapter } from './lib/book';
import siteConfig from './lib/config';

export default function Home() {
  const displayTitle = siteConfig.title || book.title;
  const displayAuthor = siteConfig.author || book.author;
  const brandMark = siteConfig.brandMark || displayAuthor.slice(0, 1);
  const dek = siteConfig.dek || book.subtitle;

  return <main className="site-shell" id="top">
    <header className="topbar">
      <a className="brand" href="/" aria-label="首页">
        <span className="brand-mark">{brandMark}</span>
        <span><strong>{displayTitle}</strong><small>{displayAuthor}</small></span>
      </a>
      <div className="top-actions"><SearchPanel entries={searchIndex} /></div>
    </header>
    <div className="home-grid">
      <aside className="book-nav" aria-label="目录">
        <p className="eyebrow">目录</p>
        <ol>{book.chapters.map((chapter) => <li key={chapter.id}><span>{chapterNumber(chapter.id)}</span><a href={`#${chapter.id}`}>{chapter.title.replace(/^第[一二三四五六七八九十]+部\s*/, '')}</a></li>)}</ol>
      </aside>
      <article className="book-page">
        <section className="cover">
          <h1><em>{displayTitle}</em></h1>
          <p className="cover-author">{displayAuthor}</p>
          <p className="dek">{dek}</p>
          <div className="cover-stats">
            <span><strong>{book.chapters.length}</strong> 章</span>
            {articles.length > 0 && <span><strong>{articles.length}</strong> 篇精炼文章</span>}
            <span>源自 <strong>{book.stats.entry_count}</strong> 个视频</span>
          </div>
          <div className="cover-actions"><a className="primary-button" href="#contents">开始阅读</a></div>
        </section>
        <section className="preface-section">
          <p>这不是一本按学科编排的教材，而是一条清晰的思考线。</p>
          <p>{displayAuthor} 在视频中分享了 {book.stats.entry_count} 个关于商业、心理与财富的深度内容。这些内容表面上在讨论不同话题，底层都在追问同一件事：普通人怎样建立属于自己的价值系统与商业闭环。</p>
          <p>本书从这些视频中提炼核心观点，按主题重新组织成 {articles.length} 篇第一人称精炼文章。引用块保留博主原话，点击引用编号可跳转到公开视频核验。</p>
        </section>
        <section className="contents-section" id="contents">
          <div className="chapter-list">{book.chapters.map((chapter) => { 
            const ca = articlesByChapter.get(chapter.id); 
            if (!ca || ca.length === 0) return null;
            return <section className="chapter-index" id={chapter.id} key={chapter.id}>
              <div className="chapter-index-number">{chapterNumber(chapter.id)}</div>
              <div className="chapter-index-body">
                <h3>{chapter.title.replace(/^第[一二三四五六七八九十]+部\s*/, '')}</h3>
                <div className="entry-links">{ca.map((a) => <a href={`/article/${a.id}`} key={a.id}>{a.title}</a>)}</div>
              </div>
            </section>; 
          })}</div>
        </section>
      </article>
    </div>
  </main>;
}
