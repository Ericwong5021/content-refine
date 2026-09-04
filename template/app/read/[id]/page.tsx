import { redirect } from 'next/navigation';
import { articles, book } from '../../lib/book';

export function generateStaticParams() {
  return book.entries.map((entry) => ({ id: entry.id }));
}

export default async function ReadRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const matched = articles.find((a) => a.source_entry_ids.includes(id));
  if (matched) {
    redirect(`/article/${matched.id}`);
  }
  redirect('/');
}
