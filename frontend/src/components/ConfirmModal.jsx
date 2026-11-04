import React, { useState } from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';
import WebApp from '@twa-dev/sdk';

export default function ConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  isDeleting,
  title = null,
  description = null,
  confirmText = null,
  isSingleStep = false,
}) {
  const [step, setStep] = useState(1);

  if (!isOpen) return null;

  const handleNext = () => {
    try {
      WebApp.HapticFeedback?.impactOccurred('medium');
    } catch {}
    if (!isSingleStep && step === 1) {
      setStep(2);
    } else {
      onConfirm();
    }
  };

  const handleClose = () => {
    setStep(1);
    onClose();
  };

  const modalTitle = title || (step === 1 ? 'Удалить пару и данные пары?' : 'Точно удалить пару?');
  const modalDescription = description || (step === 1 ? (
    'Будут удалены связка, профили участников в рабочей базе, сессии, исходные сообщения и результаты разборов. Telegram ID может снова сохраниться при следующем входе. Активная подписка плательщика останется до конца оплаченного срока. Платёжные записи, журнал удаления и резервные копии обрабатываются отдельно — подробности указаны в Политике конфиденциальности.'
  ) : (
    <span className="text-rose-600 dark:text-rose-400 font-medium">
      Это действие необратимо: восстановить пару, переписку и результаты разборов будет невозможно. Подписка плательщика останется активна до конца оплаченного срока.
    </span>
  ));
  const buttonLabel = isDeleting
    ? 'Удаление...'
    : confirmText || (step === 1 ? 'Да, я хочу удалить (1/2)' : 'Подтверждаю безвозвратное удаление (2/2)');

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
            {modalTitle}
          </h3>
          <p className="mt-2 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
            {modalDescription}
          </p>
        </div>

        <div className="mt-5 space-y-2">
          <button
            disabled={isDeleting}
            onClick={handleNext}
            className="w-full py-2.5 px-4 bg-rose-600 hover:bg-rose-700 text-white font-medium text-xs sm:text-sm rounded-xl transition-colors flex items-center justify-center gap-2 shadow-sm disabled:opacity-50"
          >
            <Trash2 size={16} />
            <span>{buttonLabel}</span>
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
