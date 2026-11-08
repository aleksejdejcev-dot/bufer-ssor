import React, { useState, useEffect } from 'react';
import { Shield, MessageCircleHeart, Trash2, UserPlus, ArrowRight, Check } from 'lucide-react';
import WebApp from '@twa-dev/sdk';
import { api } from '../api/client';
import LegalModal from '../components/LegalModal';

export default function Onboarding({ onAccepted, initialCouple }) {
  const [is18Plus, setIs18Plus] = useState(false);
  const [activeModalDoc, setActiveModalDoc] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isInviting, setIsInviting] = useState(false);
  const [inviteLink, setInviteLink] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);

  // Интеграция с нативной MainButton Telegram
  useEffect(() => {
    try {
      if (WebApp && WebApp.MainButton) {
        WebApp.MainButton.setText('Продолжить');
        if (is18Plus && !isSubmitting) {
          WebApp.MainButton.enable();
          WebApp.MainButton.show();
        } else {
          WebApp.MainButton.disable();
          WebApp.MainButton.hide();
        }

        const handleMainButtonClick = () => {
          handleAccept();
        };

        WebApp.MainButton.onClick(handleMainButtonClick);
        return () => {
          WebApp.MainButton.offClick(handleMainButtonClick);
          WebApp.MainButton.hide();
        };
      }
    } catch (e) {
      console.warn('MainButton integration error:', e);
    }
  }, [is18Plus, isSubmitting]);

  const handleCheckboxChange = (e) => {
    const checked = e.target.checked;
    setIs18Plus(checked);
    try {
      WebApp.HapticFeedback?.selectionChanged();
    } catch {}
  };

  const handleAccept = async () => {
    if (!is18Plus || isSubmitting) return;

    setIsSubmitting(true);
    setErrorMsg(null);

    try {
      WebApp.HapticFeedback?.impactOccurred('medium');
      const res = await api.acceptLegal(true, true);

      WebApp.HapticFeedback?.notificationOccurred('success');

      // 2. Передаем управление родительскому роутеру для перехода на следующий шаг
      if (typeof onAccepted === 'function') {
        await onAccepted(res);
      }
    } catch (err) {
      console.error('Legal accept failed:', err);
      setErrorMsg(err.message || 'Не удалось сохранить согласие');
      WebApp.HapticFeedback?.notificationOccurred('error');
    } finally {
      // 3. Гарантированно снимаем флаг загрузки, чтобы кнопка никогда не зависала намертво
      setIsSubmitting(false);
    }
  };

  const handleInvite = async () => {
    setIsInviting(true);
    setErrorMsg(null);

    try {
      WebApp.HapticFeedback?.impactOccurred('light');
      let link = inviteLink;
      if (!link) {
        const res = await api.createInvite();
        link = res.invite_link;
        setInviteLink(link);
      }

      // Нативный шаринг ссылки через Telegram
      const shareText = 'Давай подключимся к «Буферу Ссор» — здесь можно безопасно и бережно разбирать наши разногласия с помощью ИИ.';
      const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(shareText)}`;

      try {
        if (WebApp.openTelegramLink) {
          WebApp.openTelegramLink(shareUrl);
        } else {
          window.open(shareUrl, '_blank');
        }
      } catch {
        window.open(shareUrl, '_blank');
      }
    } catch (err) {
      console.error('Invite generation failed:', err);
      // Если нельзя создать инвайт до согласия, предлагаем сначала подтвердить 18+
      if (err.status === 403) {
        setErrorMsg('Сначала подтвердите возраст 18+ и нажмите «Продолжить»');
      } else {
        setErrorMsg(err.message || 'Не удалось сформировать ссылку-приглашение');
      }
    } finally {
      setIsInviting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-between p-5 max-w-md mx-auto animate-fade-in bg-slate-50/50 dark:bg-zinc-950/55">
      <div>
        {/* Шапка и название */}
        <div className="text-center pt-2 pb-5">
          <div className="flex justify-center mb-3">
            <div className="relative group">
              <div className="absolute -inset-1 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-3xl blur-md opacity-30"></div>
              <img
                src="/logo.png"
                alt="Буфер Ссор"
                className="relative w-20 h-20 rounded-2xl shadow-lg object-cover ring-1 ring-black/5 dark:ring-white/20"
              />
            </div>
          </div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-900/40 text-xs font-medium mb-2.5">
            <span>🤍 Безопасное пространство</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
            Буфер Ссор
          </h1>
          <p className="mt-1.5 text-xs sm:text-sm text-slate-500 dark:text-slate-400 max-w-xs mx-auto leading-relaxed">
            ИИ-медиатор для пар в ссоре: бережно выслушает каждого наедине и поможет услышать друг друга
          </p>
        </div>

        {/* 3 главных тезиса безопасности */}
        <div className="space-y-3 my-4">
          <div className="bg-white dark:bg-zinc-900 rounded-2xl p-4 border border-slate-200/70 dark:border-zinc-800 shadow-sm flex items-start gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400 flex items-center justify-center shrink-0 border border-indigo-100 dark:border-indigo-900/40">
              <Shield size={20} />
            </div>
            <div>
              <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                Анонимно
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-relaxed">
                Ваши имена и личные данные не передаются во внешние системы и не разглашаются.
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-zinc-900 rounded-2xl p-4 border border-slate-200/70 dark:border-zinc-800 shadow-sm flex items-start gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 flex items-center justify-center shrink-0 border border-rose-100 dark:border-rose-900/40">
              <MessageCircleHeart size={20} />
            </div>
            <div>
              <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                ИИ выслушает каждого наедине
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-relaxed">
                Партнёр никогда не увидит ваши исходные слова и формулировки.
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-zinc-900 rounded-2xl p-4 border border-slate-200/70 dark:border-zinc-800 shadow-sm flex items-start gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0 border border-emerald-100 dark:border-emerald-900/40">
              <Trash2 size={20} />
            </div>
            <div>
              <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                Исходники удаляются
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-relaxed">
                Все исходные сообщения безвозвратно стираются сразу после анализа.
              </div>
            </div>
          </div>
        </div>

        {errorMsg && (
          <div className="my-3 p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 text-xs border border-rose-200 dark:border-rose-900">
            {errorMsg}
          </div>
        )}
      </div>

      {/* Нижняя часть: чекбокс 18+ и кнопки */}
      <div className="pt-4 pb-2 space-y-4">
        {/* Обязательный чекбокс (по умолчанию НЕ отмечен) */}
        <label className="flex items-start gap-3 p-3.5 rounded-xl bg-white dark:bg-zinc-900 border border-slate-200/70 dark:border-zinc-800 shadow-sm cursor-pointer select-none">
          <input
            type="checkbox"
            checked={is18Plus}
            onChange={handleCheckboxChange}
            className="w-5 h-5 rounded border-slate-300 dark:border-zinc-700 text-indigo-600 focus:ring-indigo-500 shrink-0 mt-0.5 cursor-pointer accent-indigo-600"
          />
          <span className="text-xs text-slate-600 dark:text-slate-300 leading-snug">
            Мне исполнилось 18 лет, я принимаю{' '}
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                setActiveModalDoc('terms');
              }}
              className="text-indigo-600 dark:text-indigo-400 underline underline-offset-2 hover:opacity-80"
            >
              Пользовательское соглашение (оферту)
            </button>
            ,{' '}
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                setActiveModalDoc('privacy');
              }}
              className="text-indigo-600 dark:text-indigo-400 underline underline-offset-2 hover:opacity-80"
            >
              Политику конфиденциальности
            </button>{' '}
            и{' '}
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                setActiveModalDoc('nda');
              }}
              className="text-indigo-600 dark:text-indigo-400 underline underline-offset-2 hover:opacity-80"
            >
              Режим неразглашения
            </button>
            .
          </span>
        </label>

        {/* Кнопки действий */}
        <div className="space-y-2.5">
          <button
            type="button"
            disabled={!is18Plus || isSubmitting}
            onClick={handleAccept}
            className={`w-full py-3.5 px-4 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all shadow-sm ${
              is18Plus && !isSubmitting
                ? 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-indigo-600/20 active:scale-[0.99]'
                : 'bg-slate-200 dark:bg-zinc-800 text-slate-400 dark:text-zinc-500 cursor-not-allowed'
            }`}
          >
            <span>{isSubmitting ? 'Сохранение...' : 'Продолжить'}</span>
            <ArrowRight size={16} />
          </button>

          <button
            type="button"
            onClick={handleInvite}
            disabled={isInviting}
            className="w-full py-2.5 px-4 rounded-xl text-xs sm:text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-zinc-800/80 border border-slate-200/80 dark:border-zinc-800 flex items-center justify-center gap-2 transition-colors"
          >
            <UserPlus size={16} />
            <span>{isInviting ? 'Генерация ссылки...' : 'Пригласить партнёра'}</span>
          </button>
        </div>
      </div>

      {/* Модальное окно с документами */}
      <LegalModal
        docKey={activeModalDoc}
        onClose={() => setActiveModalDoc(null)}
      />
    </div>
  );
}
