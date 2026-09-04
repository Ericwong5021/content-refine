'use client';

import { useEffect, useMemo, useState } from 'react';
import type { SearchEntry } from '../lib/book';

export default function SearchPanel({ entries }: { entries: SearchEntry[] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const results = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return [];
    return entries.map((entry) => {
      const title = entry.title.toLowerCase();
      const haystack = [title, entry.thesis, ...entry.topics, entry.search_text].join(' ').toLowerCase();
      return { entry, score: haystack.includes(normalized) ? (title.includes(normalized) ? 3 : 1) : 0 };
    }).filter((result) => result.score > 0).sort((a, b) => b.score - a.score || a.entry.index - b.entry.index).slice(0, 12);
  }, [entries, query]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement)?.tagName;
      if ((event.key === '/' && !['INPUT', 'TEXTAREA'].includes(tag)) || (event.key === 'Escape' && open)) {
        event.preventDefault();
        if (event.key === 'Escape') { setOpen(false); setQuery(''); } else setOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  return <div className="search-wrap"><button className="quiet-button" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="book-search">搜索全书 <kbd>/</kbd></button>{open && <div className="search-popover" id="book-search"><label htmlFor="search-input">搜索标题、观点、主题或逐字稿</label><input id="search-input" autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：阶层、销售、行动" />{query.trim() && <p className="search-count">找到 {results.length} 个结果</p>}<div className="search-results">{results.map(({ entry }) => <a key={entry.id} href={entry.href || `/read/${entry.id}`} onClick={() => setOpen(false)}><span>{String(entry.index).padStart(2, '0')}</span><strong>{entry.title}</strong></a>)}{query.trim() && !results.length && <p className="empty-state">没有匹配内容，试试更短的关键词。</p>}</div></div>}</div>;
}
