import React, { useState } from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';
import WebApp from '@twa-dev/sdk';

export default function ConfirmModal({ isOpen, onClose, onConfirm, isDeleting }) {
  const [step, setStep] = useState(1);

  if (!isOpen) return null;

  const handleNext = () => {
    try {
      WebApp.HapticFeedback?.impactOccurred('medium');
    } catch {}
    if (step === 1) {
      setStep(2);
    } else {
      onConfirm();
    }
  };

  const handleClose = () => {
    setStep(1);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={handleClose}
    >
      <div
        className="w-full max-w-sm bg-white dark:bg-zinc-900 rounded-2xl p-5 shadow-2xl border border-rose-100 dark:border-rose-950/60 animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div className="w-10 h-10 rounded-xl bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 flex items-center justify-center border border-rose-100 dark:border-rose-900/50">
            <AlertTriangle size={20} />
          </div>
          <button
            onClick={handleClose}
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="mt-3.5">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-base">
            {step === 1 ? 'Удалить все данные пары?' : 'Точно удалить все данные?'}
          </h3>
          <p className="mt-2 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
            {step === 1 ? (
              'Это приведет к удалению связки с партнером, завершению всех текущих сессий и стиранию истории разборов.'
            ) : (
              <span className="text-rose-600 dark:text-rose-400 font-medium">
                Внимание! Это действие необратимо. Восстановить доступ к паре и материалам будет невозможно.
              </span>
            )}
          </p>
        </div>

        <div className="mt-5 space-y-2">
          <button
            disabled={isDeleting}
            onClick={handleNext}
            className="w-full py-2.5 px-4 bg-rose-600 hover:bg-rose-700 text-white font-medium text-xs sm:text-sm rounded-xl transition-colors flex items-center justify-center gap-2 shadow-sm disabled:opacity-50"
          >
            <Trash2 size={16} />
            <span>
              {isDeleting
                ? 'Удаление...'
                : step === 1
                ? 'Да, я хочу удалить (1/2)'
                : 'Подтверждаю безвозвратное удаление (2/2)'}
            </span>
          </button>

          <button
            disabled={isDeleting}
            onClick={handleClose}
            className="w-full py-2 px-4 bg-slate-100 hover:bg-slate-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-700 dark:text-slate-300 font-medium text-xs sm:text-sm rounded-xl transition-colors"
          >
            Отмена
          </button>
        </div>
      </div>
    </div>
  );
}
