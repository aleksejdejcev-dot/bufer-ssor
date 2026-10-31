import React from 'react';
import { Sparkles, ArrowLeft, Check, Shield } from 'lucide-react';
import WebApp from '@twa-dev/sdk';

export default function PaywallStub({ onBack }) {
  const handleBack = () => {
    try {
      WebApp.HapticFeedback?.impactOccurred('light');
    } catch {}
    onBack();
  };

  return (
    <div className="min-h-screen flex flex-col justify-between p-5 max-w-md mx-auto animate-fade-in bg-slate-50/50 dark:bg-zinc-950">
      <div>
        {/* Кнопка назад */}
        <button
          onClick={handleBack}
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100 mb-6 py-1 px-2 -ml-2 rounded-lg transition-colors"
        >
          <ArrowLeft size={16} />
          <span>Назад на главную</span>
        </button>

        {/* Иконка и заголовки */}
        <div className="text-center pt-2 pb-6">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 flex items-center justify-center border border-indigo-100 dark:border-indigo-900/40 shadow-sm mb-4">
            <Sparkles size={28} />
          </div>
          <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 tracking-tight">
            Бесплатные разборы закончились
          </h2>
          <p className="mt-2 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed max-w-xs mx-auto">
            Вы использовали 2 стартовых разбора медиатора для вашей пары.
          </p>
        </div>

        {/* Карточка преимуществ */}
        <div className="bg-white dark:bg-zinc-900 rounded-2xl p-5 border border-slate-200/70 dark:border-zinc-800 shadow-sm space-y-3.5">
          <div className="font-semibold text-xs text-slate-400 uppercase tracking-wider">
            Скоро в подписке:
          </div>

          <div className="flex items-start gap-3">
            <div className="w-5 h-5 rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0 mt-0.5">
              <Check size={13} />
            </div>
            <div className="text-xs text-slate-600 dark:text-slate-300">
              <span className="font-medium text-slate-900 dark:text-slate-100">Безлимитные медиации ссор</span> — бережный разбор любых разногласий 24/7.
            </div>
          </div>

          <div className="flex items-start gap-3">
            <div className="w-5 h-5 rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0 mt-0.5">
              <Check size={13} />
            </div>
            <div className="text-xs text-slate-600 dark:text-slate-300">
              <span className="font-medium text-slate-900 dark:text-slate-100">Голосовые сообщения</span> — рассказывайте ситуацию голосом без ограничений.
            </div>
          </div>

          <div className="flex items-start gap-3">
            <div className="w-5 h-5 rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0 mt-0.5">
              <Check size={13} />
            </div>
            <div className="text-xs text-slate-600 dark:text-slate-300">
              <span className="font-medium text-slate-900 dark:text-slate-100">Полная тайна исповеди</span> — неизменный строгий информационный барьер.
            </div>
          </div>
        </div>

        {/* Информационный бэйдж */}
        <div className="mt-4 flex items-center justify-center gap-2 text-xs text-slate-400">
          <Shield size={14} />
          <span>Платежи подключаются на следующем этапе</span>
        </div>
      </div>

      {/* Кнопка возврата */}
      <div className="pt-6">
        <button
          onClick={handleBack}
          className="w-full py-3 px-4 bg-slate-900 dark:bg-slate-100 hover:bg-slate-800 dark:hover:bg-white text-white dark:text-slate-900 text-sm font-semibold rounded-xl transition-all shadow-sm"
        >
          Вернуться на главную
        </button>
      </div>
    </div>
  );
}
