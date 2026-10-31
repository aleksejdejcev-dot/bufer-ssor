import React, { useState } from 'react';
import { X, Heart, Moon, Coffee, HandHeart, CheckCircle2 } from 'lucide-react';
import WebApp from '@twa-dev/sdk';
import { api } from '../api/client';

const HINTS = [
  {
    type: 'hug',
    title: 'Мне нужны объятия',
    desc: 'Бот мягко подскажет, что тепло и объятия сейчас важнее любых споров',
    icon: Heart,
    color: 'text-rose-500 bg-rose-50 dark:bg-rose-950/40 border-rose-100 dark:border-rose-900/40',
  },
  {
    type: 'silence',
    title: 'Хочу побыть в тишине',
    desc: 'Бот деликатно передаст просьбу о короткой паузе для отдыха',
    icon: Moon,
    color: 'text-indigo-500 bg-indigo-50 dark:bg-indigo-950/40 border-indigo-100 dark:border-indigo-900/40',
  },
  {
    type: 'talk_evening',
    title: 'Давай поговорим вечером',
    desc: 'Бот напомнит партнеру, что вечером вас ждет бережный спокойный диалог',
    icon: Coffee,
    color: 'text-amber-500 bg-amber-50 dark:bg-amber-950/40 border-amber-100 dark:border-amber-900/40',
  },
  {
    type: 'support',
    title: 'Мне нужна поддержка',
    desc: 'Бот подскажет партнеру проявить сочувствие и побыть на твоей стороне',
    icon: HandHeart,
    color: 'text-emerald-500 bg-emerald-50 dark:bg-emerald-950/40 border-emerald-100 dark:border-emerald-900/40',
  },
];

export default function HintModal({ isOpen, onClose }) {
  const [loadingType, setLoadingType] = useState(null);
  const [successType, setSuccessType] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);

  if (!isOpen) return null;

  const handleSelectHint = async (type) => {
    setLoadingType(type);
    setErrorMsg(null);
    try {
      WebApp.HapticFeedback?.impactOccurred('medium');
      await api.sendHint(type);
      setSuccessType(type);
      WebApp.HapticFeedback?.notificationOccurred('success');
      setTimeout(() => {
        setSuccessType(null);
        setLoadingType(null);
        onClose();
      }, 1500);
    } catch (err) {
      setLoadingType(null);
      setErrorMsg(err.message || 'Не удалось отправить намек');
      WebApp.HapticFeedback?.notificationOccurred('error');
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 bg-black/50 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full sm:max-w-md bg-white dark:bg-zinc-900 rounded-t-2xl sm:rounded-2xl flex flex-col shadow-xl animate-slide-up border border-slate-200/60 dark:border-zinc-800"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-4 border-b border-slate-100 dark:border-zinc-800/80">
          <div>
            <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
              💡 Тонкий намёк
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Бот подскажет от своего имени, не выдавая отправителя
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {errorMsg && (
          <div className="mx-4 mt-3 p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 text-xs border border-rose-200 dark:border-rose-900">
            {errorMsg}
          </div>
        )}

        <div className="p-4 space-y-2.5">
          {HINTS.map((h) => {
            const Icon = h.icon;
            const isSelected = successType === h.type;
            const isLoading = loadingType === h.type;

            return (
              <button
                key={h.type}
                disabled={Boolean(loadingType)}
                onClick={() => handleSelectHint(h.type)}
                className={`w-full text-left p-3.5 rounded-xl border transition-all flex items-start gap-3 ${
                  isSelected
                    ? 'border-emerald-500 bg-emerald-50/70 dark:bg-emerald-950/40'
                    : 'border-slate-200/70 dark:border-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-800/60'
                } ${isLoading ? 'opacity-60 cursor-wait' : ''}`}
              >
                <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 border ${h.color}`}>
                  {isSelected ? (
                    <CheckCircle2 size={18} className="text-emerald-600 dark:text-emerald-400" />
                  ) : (
                    <Icon size={18} />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-slate-900 dark:text-slate-100 text-sm">
                      {h.title}
                    </div>
                    {isSelected && (
                      <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                        Отправлено!
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">
                    {h.desc}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
