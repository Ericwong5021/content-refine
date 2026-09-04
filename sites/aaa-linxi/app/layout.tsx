import type { Metadata } from 'next';
import './globals.css';
import siteConfig from './lib/config';

export const metadata: Metadata = {
  title: `${siteConfig.title} · ${siteConfig.author}`,
  description: siteConfig.description,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <head>
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
      </head>
      <body>{children}</body>
    </html>
  );
}
