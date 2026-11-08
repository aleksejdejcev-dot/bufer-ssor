import React, { useState } from 'react';
import { Sparkles, ArrowLeft, Check, Shield, AlertCircle } from 'lucide-react';
import WebApp from '@twa-dev/sdk';
import { api } from '../api/client';

export default function PaywallStub({ onBack }) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleBack = () => {
    try {
      WebApp.HapticFeedback?.impactOccurred('light');
    } catch {}
    onBack();
  };

  const handleSubscribe = async () => {
    setIsLoading(true);
    setError(null);
    try {
      WebApp.HapticFeedback?.impactOccurred('medium');
      const res = await api.createPayment('month_sub');
      if (res && res.confirmation_url) {
        if (WebApp?.openLink) {
          WebApp.openLink(res.confirmation_url);
        } else if (window.Telegram?.WebApp?.openLink) {
          window.Telegram.WebApp.openLink(res.confirmation_url);
        } else {
          window.open(res.confirmation_url, '_blank');
        }
      } else {
        throw new Error('Не удалось получить ссылку для оплаты');
      }
    } catch (err) {
      console.error('Payment error:', err);
      setError(err.message || 'Ошибка создания платежа. Попробуйте позже.');
      WebApp.HapticFeedback?.notificationOccurred('error');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-between p-5 max-w-md mx-auto animate-fade-in bg-slate-50/50 dark:bg-zinc-950/55">
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
            Оформите подписку для пары
          </h2>
          <p className="mt-2 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed max-w-xs mx-auto">
            Один тариф на двоих: безлимитные медиации, персональный ИИ-анализ и забота о ваших отношениях.
          </p>
        </div>

        {/* Карточка преимуществ */}
        <div className="bg-white dark:bg-zinc-900 rounded-2xl p-5 border border-slate-200/70 dark:border-zinc-800 shadow-sm space-y-3.5">
          <div className="font-semibold text-xs text-slate-400 uppercase tracking-wider">
            Что входит в подписку:
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
              <span className="font-medium text-slate-900 dark:text-slate-100">Персональные шаги примирения</span> — конкретные фразы и действия для спокойного выхода из конфликта.
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

        {error && (
          <div className="mt-4 p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200/60 dark:border-rose-900/40 flex items-center gap-2.5 text-xs text-rose-600 dark:text-rose-400">
            <AlertCircle size={15} className="shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Информационный бэйдж */}
        <div className="mt-4 flex items-center justify-center gap-1.5 text-xs text-slate-400">
          <Shield size={14} className="text-emerald-500" />
          <span>Безопасная оплата через ЮKassa</span>
        </div>
      </div>

      {/* Кнопки действий */}
      <div className="pt-6 space-y-2.5">
        <button
          onClick={handleSubscribe}
          disabled={isLoading}
          className="w-full py-3.5 px-4 bg-indigo-600 hover:bg-indigo-700 active:scale-[0.99] text-white font-semibold rounded-xl text-sm transition-all shadow-md shadow-indigo-500/20 flex items-center justify-center gap-2 disabled:opacity-50"
        >
          <Sparkles size={16} />
          <span>{isLoading ? 'Подключение к ЮKassa...' : 'Оформить подписку за 199 ₽ / мес'}</span>
        </button>

        <button
          onClick={handleBack}
          className="w-full py-2.5 px-4 bg-transparent hover:bg-slate-100 dark:hover:bg-zinc-800 text-slate-500 dark:text-slate-400 text-xs font-medium rounded-xl transition-all"
        >
          Вернуться на главную
        </button>
      </div>
    </div>
  );
}
