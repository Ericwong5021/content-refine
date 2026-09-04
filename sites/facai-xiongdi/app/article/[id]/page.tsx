import { notFound } from 'next/navigation';
import SearchPanel from '../../components/SearchPanel';
import { articles, articlesById, articlesByChapter, book, chaptersById, entriesById, searchIndex, type Article } from '../../lib/book';
import siteConfig from '../../lib/config';

export function generateStaticParams() { return articles.map((a) => ({ id: a.id })); }

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const article = articlesById.get(id);
  const siteTitle = siteConfig.title || book.title;
  return { 
    title: article ? `${article.title} · ${siteTitle}` : siteTitle, 
    description: article?.subtitle || book.subtitle 
  };
}

function renderMarkdown(md: string, article: Article) {
  const lines = md.split('\n');
  const elements: React.ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith('# ') || line === '---' || line.startsWith('**来源') || line.startsWith('### 来源') || line.startsWith('- [')) {
      i++;
      continue;
    }
    if (line.startsWith('> ') && !/\[\d+\]/.test(line) && elements.length === 0) {
      i++;
      continue;
    }

    if (line.startsWith('### ')) {
      elements.push(<h2 key={key++} className="article-section-heading">{line.slice(4)}</h2>);
      i++;
      continue;
    }

    if (line.startsWith('> ')) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].startsWith('> ')) {
        quoteLines.push(lines[i].slice(2));
        i++;
      }
      const quoteText = quoteLines.join('\n');
      const citationMatch = quoteText.match(/\[(\d+)\]\s*$/);
      const citationIndex = citationMatch ? parseInt(citationMatch[1]) : null;
      const cleanText = citationMatch ? quoteText.replace(/\[\d+\]\s*$/, '').trim() : quoteText;
      const citation = citationIndex ? article.source_citations.find(c => c.index === citationIndex) : null;
      const entry = citation ? entriesById.get(citation.entry_id) : null;

      elements.push(
        <blockquote key={key++} className="naval-quote">
          <p>{cleanText}</p>
          {citation && entry && entry.video_url && (
            <cite><a href={entry.video_url} target="_blank" rel="noreferrer">{citation.index}</a></cite>
          )}
        </blockquote>
      );
      continue;
    }

    if (line.trim() === '') {
      i++;
      continue;
    }

    const paraLines: string[] = [];
    while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('#') && !lines[i].startsWith('>') && lines[i] !== '---' && !lines[i].startsWith('**来源') && !lines[i].startsWith('- [')) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      const paraText = paraLines.join('\n');
      const parts = paraText.split(/(\[\d+\])/g);
      const rendered = parts.map((part, pIdx) => {
        const m = part.match(/^\[(\d+)\]$/);
        if (m) {
          const cIdx = parseInt(m[1]);
          const citation = article.source_citations.find(c => c.index === cIdx);
          const entry = citation ? entriesById.get(citation.entry_id) : null;
          if (citation && entry && entry.video_url) {
            return <a key={pIdx} className="inline-citation" href={entry.video_url} target="_blank" rel="noreferrer">{cIdx}</a>;
          }
          return <span key={pIdx} className="inline-citation">{cIdx}</span>;
        }
        return <span key={pIdx}>{part}</span>;
      });
      elements.push(<p key={key++} className="article-paragraph">{rendered}</p>);
    }
  }
  return elements;
}

export default async function ArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const article = articlesById.get(id);
  if (!article) notFound();
  const chapter = chaptersById.get(article.chapter_id);
  if (!chapter) notFound();
  const allArticlesSorted = book.chapters.flatMap(ch => articlesByChapter.get(ch.id) || []);
  const globalPos = allArticlesSorted.findIndex(a => a.id === article.id);
  const previous = globalPos > 0 ? allArticlesSorted[globalPos - 1] : null;
  const next = globalPos < allArticlesSorted.length - 1 ? allArticlesSorted[globalPos + 1] : null;

  const displayTitle = siteConfig.title || book.title;
  const displayAuthor = siteConfig.author || book.author;
  const brandMark = siteConfig.brandMark || displayAuthor.slice(0, 1);

  return <main className="site-shell reader-page" id="top">
    <header className="topbar">
      <a className="brand" href="/" aria-label="首页">
        <span className="brand-mark">{brandMark}</span>
        <span><strong>{displayTitle}</strong><small>{displayAuthor}</small></span>
      </a>
      <div className="top-actions"><SearchPanel entries={searchIndex} /></div>
    </header>
    <div className="reader-grid">
      <aside className="book-nav" aria-label="目录">
        <a className="back-link" href="/">← 目录</a>
        {book.chapters.map((ch) => {
          const ca = articlesByChapter.get(ch.id) || [];
          if (!ca.length) return null;
          return <div key={ch.id} className="nav-chapter-group">
            <p className="nav-chapter-title">{ch.title.replace(/^第[一二三四五六七八九十]+部\s*/, '')}</p>
            <ol>{ca.map((a) => <li key={a.id} className={a.id === article.id ? 'active' : ''}><a href={`/article/${a.id}`}>{a.title}</a></li>)}</ol>
          </div>;
        })}
      </aside>
      <article className="book-page article-page naval-article">
        <div className="article-kicker">{chapter.title.replace(/^第[一二三四五六七八九十]+部\s*/, '')}</div>
        <h1>{article.title}</h1>
        {article.subtitle && <p className="article-subtitle">{article.subtitle}</p>}
        <div className="naval-body">
          {renderMarkdown(article.body_md, article)}
        </div>
        <nav className="article-pagination" aria-label="翻页">
          {previous ? <a href={`/article/${previous.id}`} className="prev"><small>上一篇</small><span>← {previous.title}</span></a> : <span />}
          {next ? <a href={`/article/${next.id}`} className="next"><small>下一篇</small><span>{next.title} →</span></a> : <span />}
        </nav>
      </article>
      <aside className="source-rail" aria-label="来源">
        <p className="eyebrow">内容溯源</p>
        <div className="source-note">
          <strong>第一人称精炼</strong>
          <p>本文由流水线基于博主原声观点进行主题重组与第一人称提炼。方括号数字为原话出处。</p>
        </div>
        <div className="source-citations-list">
          <p className="eyebrow">引用的公开视频</p>
          {article.source_citations.map((c) => {
            const entry = entriesById.get(c.entry_id);
            return <div key={c.index} className="citation-entry-card">
              <span className="citation-badge">[{c.index}]</span>
              <div>
                <a href={entry?.video_url || '#'} target="_blank" rel="noreferrer" className="citation-title">
                  {c.label} ↗
                </a>
                {entry && <p className="citation-thesis">{entry.thesis}</p>}
              </div>
            </div>;
          })}
        </div>
      </aside>
    </div>
  </main>;
}
