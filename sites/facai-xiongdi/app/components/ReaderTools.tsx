'use client';

export default function ReaderTools() {
  return <button className="quiet-button print-button" type="button" onClick={() => window.print()}>打印 / 保存 PDF</button>;
}
