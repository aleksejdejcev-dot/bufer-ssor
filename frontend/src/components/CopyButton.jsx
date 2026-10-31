import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import WebApp from '@twa-dev/sdk';

export default function CopyButton({ text, label = 'Скопировать', className = '' }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e) => {
    e.stopPropagation();
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback для старых WebView
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.opacity = '0';
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }

      setCopied(true);
      try {
        WebApp.HapticFeedback?.notificationOccurred('success');
      } catch {}

      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.warn('Failed to copy text:', err);
    }
  };

  return (
    <button
      onClick={handleCopy}
      type="button"
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
        copied
          ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
          : 'bg-slate-100 hover:bg-slate-200/80 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-slate-300 border border-slate-200/70 dark:border-zinc-700'
      } ${className}`}
    >
      {copied ? (
        <>
          <Check size={13} className="text-emerald-600 dark:text-emerald-400" />
          <span>Скопировано!</span>
        </>
      ) : (
        <>
          <Copy size={13} className="opacity-70" />
          <span>{label}</span>
        </>
      )}
    </button>
  );
}
