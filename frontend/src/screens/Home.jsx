import React, { useState, useEffect, useRef } from 'react';
import { 
  Heart, 
  Flag, 
  Lightbulb, 
  ShieldCheck, 
  Users, 
  UserPlus, 
  Sun, 
  CloudSun, 
  Cloud, 
  CloudRain, 
  CloudLightning,
  Sparkles,
  CheckCircle2,
  Trash2,
  Lock,
  ArrowRight,
  History
} from 'lucide-react';
import WebApp from '@twa-dev/sdk';
import { api } from '../api/client';
import HintModal from '../components/HintModal';
import ConfirmModal from '../components/ConfirmModal';
import LegalModal from '../components/LegalModal';

export default function Home({ meData, onStartSession, onOpenActiveSession, onRefreshProfile, onPaywallRequired }) {
  const user = meData?.user || {};
  const couple = meData?.couple || null;
  const activeSession = meData?.active_session || null;

  // Настроение (1-10)
  const initialMood = couple?.my_mood || 5;
  const [mood, setMood] = useState(initialMood);
  const [isSavingMood, setIsSavingMood] = useState(false);
  const moodDebounceTimer = useRef(null);

  // Модальные окна и индикаторы
  const [isHintOpen, setIsHintOpen] = useState(false);
  const [isConfirmDeleteOpen, setIsConfirmDeleteOpen] = useState(false);
  const [isDeletingCouple, setIsDeletingCouple] = useState(false);
  const [isConfirmHistoryOpen, setIsConfirmHistoryOpen] = useState(false);
  const [isDeletingHistory, setIsDeletingHistory] = useState(false);
  const [activeLegalDoc, setActiveLegalDoc] = useState(null);
  const [whiteFlagSuccess, setWhiteFlagSuccess] = useState(false);
  const [isSendingWhiteFlag, setIsSendingWhiteFlag] = useState(false);
  const [isStartingConflict, setIsStartingConflict] = useState(false);
  const [globalError, setGlobalError] = useState(null);

  // Синхронизация локального настроения при обновлении профиля
  useEffect(() => {
    if (couple?.my_mood) {
      setMood(couple.my_mood);
    }
  }, [couple?.my_mood]);

  // Обработка слайдера настроения с задержкой отправки после отпускания
  const handleMoodChange = (e) => {
    const newMood = Number(e.target.value);
    setMood(newMood);

    try {
      WebApp.HapticFeedback?.selectionChanged();
    } catch {}

    if (moodDebounceTimer.current) {
      clearTimeout(moodDebounceTimer.current);
    }

    moodDebounceTimer.current = setTimeout(async () => {
      setIsSavingMood(true);
      try {
        await api.updateMood(newMood);
        try {
          WebApp.HapticFeedback?.notificationOccurred('success');
        } catch {}
      } catch (err) {
        console.warn('Failed to update mood:', err);
      } finally {
        setIsSavingMood(false);
      }
    }, 600);
  };

  // Хелпер для отображения погоды в отношениях
  const getMoodDescriptor = (val) => {
    if (val <= 2) return { text: 'Грозовое напряжение', icon: CloudLightning, color: 'text-amber-600 dark:text-amber-400' };
    if (val <= 4) return { text: 'Дождливо и тяжело', icon: CloudRain, color: 'text-blue-500' };
    if (val <= 6) return { text: 'Облачно, есть вопросы', icon: Cloud, color: 'text-slate-500' };
    if (val <= 8) return { text: 'Прояснения, тепло', icon: CloudSun, color: 'text-amber-500' };
    return { text: 'Солнечно и спокойно', icon: Sun, color: 'text-emerald-500' };
  };

  const moodDesc = getMoodDescriptor(mood);
  const MoodIcon = moodDesc.icon;

  // Запуск разбора конфликта
  const handleStartConflict = async () => {
    // Если уже есть активная сессия — сразу переходим в неё
    if (activeSession && activeSession.id) {
      onOpenActiveSession(activeSession.id);
      return;
    }

    if (!couple || !couple.has_partner) {
      setGlobalError('Для разбора конфликта сначала пригласите партнера в пару');
      return;
    }

    setIsStartingConflict(true);
    setGlobalError(null);

    try {
      WebApp.HapticFeedback?.impactOccurred('heavy');
      const res = await api.startConflict();
      onStartSession(res.session_id);
    } catch (err) {
      console.error('Start conflict failed:', err);
      setIsStartingConflict(false);

      if (err.status === 403 && err.message?.includes('Бесплатные разборы закончились')) {
        onPaywallRequired();
      } else {
        setGlobalError(err.message || 'Не удалось запустить сессию');
        WebApp.HapticFeedback?.notificationOccurred('error');
      }
    }
  };

  // Отправка белого флага
  const handleWhiteFlag = async () => {
    if (!couple || !couple.has_partner) {
      setGlobalError('Белый флаг можно поднять только когда к паре подключен партнер');
      return;
    }

    setIsSendingWhiteFlag(true);
    setGlobalError(null);

    try {
      WebApp.HapticFeedback?.impactOccurred('medium');
      await api.sendWhiteFlag();
      setWhiteFlagSuccess(true);
      WebApp.HapticFeedback?.notificationOccurred('success');
      setTimeout(() => setWhiteFlagSuccess(false), 3000);
    } catch (err) {
      setGlobalError(err.message || 'Не удалось отправить сигнал');
      WebApp.HapticFeedback?.notificationOccurred('error');
    } finally {
      setIsSendingWhiteFlag(false);
    }
  };

  // Приглашение партнера (инвайт-ссылка)
  const handleInvitePartner = async () => {
    try {
      WebApp.HapticFeedback?.impactOccurred('light');
      const res = await api.createInvite();
      const link = res.invite_link;
      const shareText = 'Давай подключимся к «Буферу Ссор» — здесь можно безопасно и бережно разбирать наши разногласия.';
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
      setGlobalError(err.message || 'Ошибка генерации инвайта');
    }
  };

  // Удаление пары
  const handleConfirmDelete = async () => {
    setIsDeletingCouple(true);
    try {
      WebApp.HapticFeedback?.notificationOccurred('warning');
      await api.deleteCouple();
      setIsConfirmDeleteOpen(false);
      await onRefreshProfile();
    } catch (err) {
      setGlobalError(err.message || 'Ошибка удаления пары');
      setIsDeletingCouple(false);
    }
  };

  // Очистка истории сессий пары
  const handleConfirmDeleteHistory = async () => {
    setIsDeletingHistory(true);
    try {
      WebApp.HapticFeedback?.notificationOccurred('warning');
      await api.deleteHistory();
      setIsConfirmHistoryOpen(false);
      await onRefreshProfile();
    } catch (err) {
      setGlobalError(err.message || 'Ошибка очистки истории');
      setIsDeletingHistory(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-between p-4 sm:p-5 max-w-md mx-auto animate-fade-in bg-slate-50/50 dark:bg-zinc-950">
      <div className="space-y-4">
        {/* Шапка: логотип и остаток бесплатных сессий */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex items-center gap-2.5">
            <img
              src="/logo.png"
              alt="Буфер Ссор"
              className="w-9 h-9 rounded-xl shadow-sm object-cover ring-1 ring-slate-200/80 dark:ring-zinc-700"
            />
            <div>
              <h1 className="font-extrabold text-base text-slate-900 dark:text-slate-100 tracking-tight leading-none">
                Буфер Ссор
              </h1>
              <span className="text-[10px] text-slate-400 font-medium tracking-wide uppercase">
                ИИ-медиатор отношений
              </span>
            </div>
          </div>

          {couple && (
            <button
              onClick={() => onPaywallRequired && onPaywallRequired()}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-100 hover:bg-slate-200/70 dark:bg-zinc-800/80 dark:hover:bg-zinc-700/80 text-xs text-slate-600 dark:text-slate-300 font-medium border border-slate-200/60 dark:border-zinc-700/60 transition-colors cursor-pointer"
            >
              <Sparkles size={12} className="text-amber-500" />
              <span>
                {couple.subscription_until && new Date(couple.subscription_until) > new Date()
                  ? 'Подписка активна'
                  : couple.free_sessions_left > 0
                  ? `Разборов: ${couple.free_sessions_left}`
                  : 'Оформить подписку'}
              </span>
            </button>
          )}
        </div>

        {globalError && (
          <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 text-xs border border-rose-200 dark:border-rose-900 flex items-center justify-between animate-fade-in">
            <span>{globalError}</span>
            <button
              onClick={() => setGlobalError(null)}
              className="text-rose-400 hover:text-rose-600 text-sm ml-2 font-bold"
            >
              ×
            </button>
          </div>
        )}

        {/* =================================================================== */}
        {/* ЭЛЕМЕНТ 1: Статус-бар пары + Погода в отношениях (Слайдер 1-10)     */}
        {/* =================================================================== */}
        <div className="bg-white dark:bg-zinc-900 rounded-2xl p-4 border border-slate-200/70 dark:border-zinc-800 shadow-sm space-y-4">
          {/* Статус связи */}
          <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-zinc-800/80">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-full bg-indigo-50 dark:bg-indigo-950/70 border border-indigo-100 dark:border-indigo-900/40 flex items-center justify-center text-indigo-600 dark:text-indigo-400 shrink-0 font-bold text-xs">
                {user.first_name?.[0] || 'Я'}
              </div>
              <div className="min-w-0">
                {couple?.has_partner ? (
                  <>
                    <div className="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">
                      {user.first_name || 'Вы'} и {couple?.partner_name || 'Вторая половинка'}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="w-2 h-2 rounded-full bg-emerald-500" />
                      <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
                        Партнёр на связи
                      </span>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">
                      {user.first_name || 'Вы'}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                      <span className="text-[11px] text-slate-500 dark:text-slate-400">
                        Вторая половинка ещё не подключена
                      </span>
                    </div>
                  </>
                )}
              </div>
            </div>

            {!couple?.has_partner && (
              <button
                onClick={handleInvitePartner}
                className="inline-flex items-center gap-1.5 py-1.5 px-3 bg-indigo-50 hover:bg-indigo-100/80 dark:bg-indigo-950/60 dark:hover:bg-indigo-900 text-indigo-600 dark:text-indigo-400 rounded-xl text-xs font-medium transition-colors border border-indigo-100 dark:border-indigo-900/40 shrink-0"
              >
                <UserPlus size={13} />
                <span>Пригласить</span>
              </button>
            )}
          </div>

          {/* Слайдер «Погода в отношениях» */}
          <div>
            <div className="flex items-center justify-between text-xs mb-2">
              <div className="flex items-center gap-1.5 font-medium text-slate-700 dark:text-slate-300">
                <MoodIcon size={16} className={moodDesc.color} />
                <span>Погода в отношениях</span>
              </div>
              <span className={`font-semibold ${moodDesc.color}`}>
                {mood}/10 — {moodDesc.text}
              </span>
            </div>

            <div className="relative pt-1 pb-1">
              <input
                type="range"
                min="1"
                max="10"
                step="1"
                value={mood}
                onChange={handleMoodChange}
                className="w-full h-2 bg-slate-200 dark:bg-zinc-800 rounded-lg appearance-none cursor-pointer"
              />
            </div>

            <div className="flex items-center justify-between text-[10px] text-slate-400 mt-1">
              <span>1 (Гроза)</span>
              {couple?.partner_mood ? (
                <span className="text-indigo-600 dark:text-indigo-400 font-medium">
                  Оценка партнёра: {couple.partner_mood}/10
                </span>
              ) : (
                <span>5 (Нейтрально)</span>
              )}
              <span>10 (Солнечно)</span>
            </div>
          </div>
        </div>

        {/* =================================================================== */}
        {/* ЭЛЕМЕНТ 2: Центральная большая кнопка разбора конфликта             */}
        {/* =================================================================== */}
        <div className="pt-2 pb-2">
          {activeSession && activeSession.status !== 'completed' ? (
            /* Кнопка возврата к активному разбору */
            <button
              onClick={() => onOpenActiveSession(activeSession.id)}
              className="w-full p-5 rounded-2xl bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700 text-white shadow-lg shadow-amber-500/20 active:scale-[0.99] transition-all flex items-center justify-between text-left group"
            >
              <div>
                <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-white/20 text-white text-[10px] font-semibold tracking-wider uppercase mb-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                  Сессия в процессе
                </div>
                <div className="text-base sm:text-lg font-bold leading-tight">
                  Продолжить текущий разбор
                </div>
                <div className="text-xs text-white/80 mt-1">
                  Нажмите, чтобы проверить статус или прочесть готовый анализ
                </div>
              </div>
              <ArrowRight size={22} className="shrink-0 transition-transform group-hover:translate-x-1" />
            </button>
          ) : (
            /* Основная кнопка старта нового разбора */
            <button
              onClick={handleStartConflict}
              disabled={isStartingConflict}
              className="w-full p-6 rounded-2xl bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-700 hover:to-violet-700 text-white shadow-xl shadow-indigo-600/25 active:scale-[0.99] transition-all text-center flex flex-col items-center justify-center gap-2 group disabled:opacity-70 disabled:cursor-wait"
            >
              <div className="w-12 h-12 rounded-2xl bg-white/15 flex items-center justify-center text-white backdrop-blur-sm group-hover:scale-105 transition-transform">
                <Heart size={26} className="text-white fill-white/20" />
              </div>
              <div>
                <div className="text-lg sm:text-xl font-extrabold tracking-tight">
                  {isStartingConflict ? 'Запуск сессии...' : 'У нас конфликт'}
                </div>
                <div className="text-xs text-indigo-100 font-medium mt-0.5">
                  Разобрать ситуацию бережно через ИИ
                </div>
              </div>
            </button>
          )}
        </div>

        {/* Бейдж тайны исповеди */}
        <div className="flex items-center justify-center gap-1.5 py-2 px-3 rounded-xl bg-emerald-50/80 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 text-xs font-medium border border-emerald-200/60 dark:border-emerald-900/50">
          <Lock size={13} className="text-emerald-600 dark:text-emerald-400 shrink-0" />
          <span>Режим тайны исповеди активен: партнёр не увидит ваши слова</span>
        </div>

        {/* =================================================================== */}
        {/* ЭЛЕМЕНТ 3: Две кнопки быстрых сигналов (Белый флаг / Тонкий намёк)   */}
        {/* =================================================================== */}
        <div className="grid grid-cols-2 gap-3 pt-1">
          {/* Белый флаг */}
          <button
            onClick={handleWhiteFlag}
            disabled={isSendingWhiteFlag || whiteFlagSuccess}
            className={`p-3.5 rounded-2xl border text-left transition-all flex flex-col justify-between ${
              whiteFlagSuccess
                ? 'bg-emerald-50 dark:bg-emerald-950/60 border-emerald-300 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
                : 'bg-white dark:bg-zinc-900 border-slate-200/70 dark:border-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-800/60 text-slate-800 dark:text-slate-200 shadow-sm'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-2xl">🏳️</span>
              {whiteFlagSuccess && (
                <CheckCircle2 size={16} className="text-emerald-600 dark:text-emerald-400" />
              )}
            </div>
            <div className="mt-2">
              <div className="font-semibold text-xs sm:text-sm">
                {whiteFlagSuccess ? 'Флаг поднят!' : 'Белый флаг'}
              </div>
              <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5 leading-snug">
                {whiteFlagSuccess ? 'Бот передал сигнал' : 'Злюсь, но люблю'}
              </div>
            </div>
          </button>

          {/* Тонкий намёк */}
          <button
            onClick={() => setIsHintOpen(true)}
            className="p-3.5 rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200/70 dark:border-zinc-800 hover:bg-slate-50 dark:hover:bg-zinc-800/60 text-slate-800 dark:text-slate-200 shadow-sm text-left transition-all flex flex-col justify-between"
          >
            <div className="flex items-center justify-between">
              <span className="text-2xl">💡</span>
              <span className="text-[10px] font-semibold text-indigo-600 dark:text-indigo-400 uppercase tracking-wider">
                4 варианта
              </span>
            </div>
            <div className="mt-2">
              <div className="font-semibold text-xs sm:text-sm">Тонкий намёк</div>
              <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5 leading-snug">
                Мягкая подсказка ботом
              </div>
            </div>
          </button>
        </div>
      </div>

      {/* Подвал: Ссылки на документы и Удаление данных пары */}
      <div className="pt-6 pb-2 text-center space-y-3">
        <div className="flex items-center justify-center gap-3 text-[11px] text-slate-400">
          <button
            onClick={() => setActiveLegalDoc('terms')}
            className="hover:underline hover:text-slate-600 dark:hover:text-slate-300"
          >
            Оферта
          </button>
          <span>•</span>
          <button
            onClick={() => setActiveLegalDoc('privacy')}
            className="hover:underline hover:text-slate-600 dark:hover:text-slate-300"
          >
            Конфиденциальность
          </button>
          <span>•</span>
          <button
            onClick={() => setActiveLegalDoc('nda')}
            className="hover:underline hover:text-slate-600 dark:hover:text-slate-300"
          >
            Тайна исповеди
          </button>
        </div>

        <div className="flex items-center justify-center gap-2 pt-1">
          <button
            onClick={() => setIsConfirmHistoryOpen(true)}
            className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 font-medium py-1 px-2 rounded-lg hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <History size={12} />
            <span>Очистить историю</span>
          </button>
          <span className="text-slate-300 dark:text-zinc-700">•</span>
          <button
            onClick={() => setIsConfirmDeleteOpen(true)}
            className="inline-flex items-center gap-1 text-[11px] text-rose-500 hover:text-rose-700 dark:text-rose-400 dark:hover:text-rose-300 font-medium py-1 px-2 rounded-lg hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors"
          >
            <Trash2 size={12} />
            <span>Удалить пару</span>
          </button>
        </div>
      </div>

      {/* Модальные окна */}
      <HintModal
        isOpen={isHintOpen}
        onClose={() => setIsHintOpen(false)}
      />

      <ConfirmModal
        isOpen={isConfirmHistoryOpen}
        onClose={() => setIsConfirmHistoryOpen(false)}
        onConfirm={handleConfirmDeleteHistory}
        isDeleting={isDeletingHistory}
        isSingleStep={true}
        title="Очистить историю разборов?"
        description="Все завершенные сессии и карточки разбора будут удалены. Связка в паре и подписка останутся."
        confirmText="Очистить историю"
      />

      <ConfirmModal
        isOpen={isConfirmDeleteOpen}
        onClose={() => setIsConfirmDeleteOpen(false)}
        onConfirm={handleConfirmDelete}
        isDeleting={isDeletingCouple}
      />

      <LegalModal
        docKey={activeLegalDoc}
        onClose={() => setActiveLegalDoc(null)}
      />
    </div>
  );
}
