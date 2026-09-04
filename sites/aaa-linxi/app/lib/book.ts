import rawBook from '../../data/book.json';
import rawArticles from '../../data/articles.json';

export type Citation = {
  paragraph_id: string | null;
  score: number;
  match: 'strong' | 'related' | 'video';
};

export type TranscriptParagraph = { id: string; index: number; text: string };
export type SourceItem = { text: string; citation: Citation };
export type Argument = { claim: string; support: string; source: string; citation: Citation };
export type Term = { term: string; contextual_meaning: string; citation: Citation };

export type Entry = {
  id: string; index: number; chapter_id: string; title: string; description: string | null;
  published_at: string | null; published_timestamp: number | null; video_url: string | null;
  duration_seconds: number | null; hashtags: string[]; engagement: Record<string, number | string>;
  thesis: string; thesis_citation: Citation; viewpoints: SourceItem[]; arguments: Argument[];
  examples: SourceItem[]; references: SourceItem[]; terms: Term[]; topics: string[];
  sections: { heading: string; summary: string }[];
  corrections: { asr_text: string; corrected_text: string; basis: string; confidence: string }[];
  uncertainties: { asr_text: string; issue: string; possible_reading: string | null }[];
  transcript: TranscriptParagraph[]; transcript_sha256: string; source_asr_sha256: string | null;
  prompt_sha256: string | null; source_record_sha256: string; refinement_record_sha256: string;
};

export type Chapter = { id: string; title: string; description: string; entry_ids: string[] };
export type SearchEntry = { id: string; index: number; title: string; thesis: string; topics: string[]; search_text: string; href?: string };
export type Book = {
  schema_version: number; title: string; subtitle: string; author: string; generated_at: string; method: string;
  stats: { input_count: number; entry_count: number; unavailable_count: number; audio_hours: number; correction_count: number; uncertainty_count: number; citation_count: number; citation_matches: Record<string, number> };
  frequent_hashtags: { name: string; count: number }[]; chapters: Chapter[]; entries: Entry[];
  unavailable: { id: string; video_url: string | null; reason: string }[];
};

export const book = rawBook as Book;
export const entriesById = new Map(book.entries.map((entry) => [entry.id, entry]));
export const chaptersById = new Map(book.chapters.map((chapter) => [chapter.id, chapter]));

export type ArticleCitation = { index: number; entry_id: string; label: string };
export type Article = {
  id: string; chapter_id: string; index: number; title: string; subtitle: string;
  body_md: string; source_entry_ids: string[]; source_citations: ArticleCitation[];
};
export const articles = rawArticles as Article[];
export const articlesById = new Map(articles.map((a) => [a.id, a]));
export const articlesByChapter = new Map<string, Article[]>();
for (const a of articles) {
  const list = articlesByChapter.get(a.chapter_id) || [];
  list.push(a);
  articlesByChapter.set(a.chapter_id, list);
}

export const searchIndex: SearchEntry[] = articles.map((article, index) => ({
  id: article.id,
  index: index + 1,
  title: article.title,
  thesis: article.subtitle,
  topics: [],
  search_text: article.body_md,
  href: `/article/${article.id}`,
}));

export function formatDate(value: string | null) {
  if (!value) return '发布时间未提供';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value));
}

export function formatDuration(value: number | null) {
  if (!value) return '时长未提供';
  const seconds = Math.round(value);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function formatCount(value: number | string | undefined) {
  const number = Number(value || 0);
  if (number >= 10000) return `${(number / 10000).toFixed(number >= 100000 ? 0 : 1)}万`;
  return number.toLocaleString('zh-CN');
}

export function shortHash(value: string | null) { return value ? `${value.slice(0, 12)}…` : '未提供'; }
export function citationLabel(citation: Citation) { return citation.match === 'strong' ? '原文' : citation.match === 'related' ? '相关原文' : '查看逐字稿'; }
export function citationHref(entryId: string, citation: Citation) { return citation.paragraph_id ? `/read/${entryId}#${citation.paragraph_id}` : `/read/${entryId}#transcript`; }
export function chapterNumber(chapterId: string) { return String(book.chapters.findIndex((chapter) => chapter.id === chapterId) + 1).padStart(2, '0'); }
