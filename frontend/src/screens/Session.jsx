import React, { useState, useEffect, useRef } from 'react';
import { 
  ArrowLeft, 
  Clock, 
  Sparkles, 
  ShieldAlert, 
  HeartHandshake, 
  Eye, 
  Lightbulb, 
  MessageSquare, 
  Users2, 
  PhoneCall, 
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  XCircle
} from 'lucide-react';
import WebApp from '@twa-dev/sdk';
import { api } from '../api/client';
import CopyButton from '../components/CopyButton';

export default function Session({ sessionId, onBack }) {
  const [session, setSession] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const pollerRef = useRef(null);

  // Нативная кнопка BackButton Telegram
  useEffect(() => {
    try {
      if (WebApp && WebApp.BackButton) {
        WebApp.BackButton.show();
        const handleBack = () => {
          onBack();
        };
        WebApp.BackButton.onClick(handleBack);
        return () => {
          WebApp.BackButton.offClick(handleBack);
          WebApp.BackButton.hide();
        };
      }
    } catch (e) {
      console.warn('BackButton error:', e);
    }
  }, [onBack]);

  // Загрузка и поллинг статуса сессии
  const fetchSessionStatus = async (isInitial = false) => {
    try {
      if (isInitial) setIsLoading(true);
      const data = await api.getConflict(sessionId);
      setSession(data);
      setErrorMsg(null);

      // Если статус финальный — останавливаем поллинг
      if (['completed', 'failed', 'expired'].includes(data.status)) {
        if (pollerRef.current) {
          clearInterval(pollerRef.current);
          pollerRef.current = null;
        }
        if (data.status === 'completed') {
          try {
            WebApp.HapticFeedback?.notificationOccurred('success');
          } catch {}
        }
      }
    } catch (err) {
      console.error('Fetch session error:', err);
      setErrorMsg(err.message || 'Ошибка загрузки статуса сессии');
      if (pollerRef.current) {
        clearInterval(pollerRef.current);
        pollerRef.current = null;
      }
    } finally {
      if (isInitial) setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSessionStatus(true);

    // Запускаем поллинг каждые 5 секунд
    pollerRef.current = setInterval(() => {
      fetchSessionStatus(false);
    }, 5000);

    return () => {
      if (pollerRef.current) {
        clearInterval(pollerRef.current);
        pollerRef.current = null;
      }
    };
  }, [sessionId]);

  // Экран первичной загрузки
  if (isLoading && !session) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-slate-50/50 dark:bg-zinc-950 text-center animate-fade-in">
        <div className="w-12 h-12 rounded-2xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 flex items-center justify-center animate-pulse mb-3">
          <Sparkles size={24} />
        </div>
        <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">
          Загрузка сессии...
        </div>
      </div>
    );
  }

  const status = session?.status || 'waiting_partner_2';
  const riskLevel = session?.risk_level || 'none';
  const personalAdvice = session?.personal_advice || {};
  const sharedSummary = session?.shared_summary || {};

  return (
    <div className="min-h-screen flex flex-col justify-between p-4 sm:p-5 max-w-md mx-auto animate-fade-in bg-slate-50/50 dark:bg-zinc-950">
      <div className="space-y-4">
        {/* Верхняя навигация */}
        <div className="flex items-center justify-between pb-1">
          <button
            onClick={onBack}
            className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100 py-1 px-2 -ml-2 rounded-lg transition-colors"
          >
            <ArrowLeft size={16} />
            <span>На главную</span>
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                try {
                  if (window.Telegram?.WebApp) {
                    window.Telegram.WebApp.close();
                  }
                } catch (e) {
                  console.error(e);
                }
              }}
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-600 hover:text-rose-700 bg-rose-50 dark:bg-rose-950/60 dark:text-rose-400 border border-rose-200 dark:border-rose-900/50 py-1 px-2.5 rounded-lg transition-colors shadow-sm"
              title="Экстренно закрыть"
            >
              <XCircle size={14} />
              <span>Быстро закрыть</span>
            </button>
            <span className="text-[10px] text-slate-400 uppercase tracking-widest font-mono">
              ID: {sessionId.slice(0, 8)}
            </span>
          </div>
        </div>

        {errorMsg && (
          <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 text-xs border border-rose-200 dark:border-rose-900 flex items-center gap-2">
            <AlertCircle size={16} className="shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* =================================================================== */}
        {/* СТАТУС 1: Ждём версию партнёра (waiting_partner_2)                  */}
        {/* =================================================================== */}
        {status === 'waiting_partner_2' && (
          <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-slate-200/70 dark:border-zinc-800 shadow-sm text-center space-y-4 my-6 animate-fade-in">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 flex items-center justify-center border border-amber-100 dark:border-amber-900/40 animate-pulse">
              <Clock size={28} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
                Ждём версию партнёра
              </h2>
              <p className="mt-2 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed max-w-xs mx-auto">
                Бот уже отправил партнёру деликатное сообщение. Как только он расскажет свою сторону — ИИ сразу приступит к анализу.
              </p>
            </div>

            <div className="p-3 rounded-xl bg-slate-50 dark:bg-zinc-800/60 text-[11px] text-slate-500 dark:text-slate-400 border border-slate-100 dark:border-zinc-700/60 leading-normal">
              💡 Напомните партнёру проверить чат с ботом{' '}
              <span className="font-semibold text-slate-700 dark:text-slate-300">@BufferSsorBot</span>
            </div>

            <div className="pt-2">
              <button
                onClick={() => fetchSessionStatus(false)}
                className="inline-flex items-center gap-1.5 text-xs text-indigo-600 dark:text-indigo-400 font-medium hover:underline"
              >
                <RefreshCw size={12} className="animate-spin" />
                <span>Обновляем статус каждые 5 сек...</span>
              </button>
            </div>
          </div>
        )}

        {/* =================================================================== */}
        {/* СТАТУС 2: ИИ анализирует ситуацию (analyzing)                       */}
        {/* =================================================================== */}
        {status === 'analyzing' && (
          <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-slate-200/70 dark:border-zinc-800 shadow-sm text-center space-y-4 my-6 animate-fade-in">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 flex items-center justify-center border border-indigo-100 dark:border-indigo-900/40">
              <Sparkles size={28} className="animate-pulse" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
                ИИ анализирует ситуацию
              </h2>
              <p className="mt-2 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed max-w-xs mx-auto">
                Обе версии получены. Медиатор сопоставляет потребности, проверяет конфиденциальный барьер и готовит бережные рекомендации.
              </p>
            </div>

            <div className="flex items-center justify-center gap-2 text-xs text-indigo-600 dark:text-indigo-400 font-medium">
              <RefreshCw size={13} className="animate-spin" />
              <span>Осталось совсем немного...</span>
            </div>
          </div>
        )}

        {/* =================================================================== */}
        {/* СТАТУСЫ ОШИБОК / ТАЙМАУТА: failed или expired                       */}
        {/* =================================================================== */}
        {(status === 'failed' || status === 'expired') && (
          <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-slate-200/70 dark:border-zinc-800 shadow-sm text-center space-y-4 my-6 animate-fade-in">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 flex items-center justify-center border border-rose-100 dark:border-rose-900/40">
              <AlertCircle size={28} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
                {status === 'expired' ? 'Время ожидания истекло' : 'Сессия не завершена'}
              </h2>
              <p className="mt-2 text-xs sm:text-sm text-slate-500 dark:text-slate-400 leading-relaxed max-w-xs mx-auto">
                {status === 'expired'
                  ? 'Партнёр не успел ответить в течение 48 часов. Срок действия сессии завершился.'
                  : 'Для полноценного анализа нужны ответы обоих партнёров. Бесплатный разбор не списан.'}
              </p>
            </div>

            <div className="pt-3">
              <button
                onClick={onBack}
                className="w-full py-2.5 px-4 bg-indigo-600 hover:bg-indigo-700 text-white text-xs sm:text-sm font-semibold rounded-xl transition-colors shadow-sm"
              >
                Попробовать снова
              </button>
            </div>
          </div>
        )}

        {/* =================================================================== */}
        {/* СТАТУС 3: ЗАВЕРШЕНО (completed)                                     */}
        {/* =================================================================== */}
        {status === 'completed' && (
          <div className="space-y-4 animate-fade-in">
            {/* Заголовок готовности */}
            <div className="flex items-center gap-2 p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200/60 dark:border-emerald-900/50 text-xs font-semibold">
              <CheckCircle2 size={16} className="text-emerald-600 dark:text-emerald-400 shrink-0" />
              <span>Ваш персональный разбор готов</span>
            </div>

            {/* ВЕТКА БЕЗОПАСНОСТИ: RISK_LEVEL == HIGH                              */}
            {riskLevel === 'high' ? (
              <div className="bg-white dark:bg-zinc-900 rounded-2xl p-5 border-2 border-rose-200 dark:border-rose-900 shadow-sm space-y-4">
                <div className="flex items-center justify-between gap-2.5">
                  <div className="flex items-center gap-2.5 text-rose-600 dark:text-rose-400">
                    <ShieldAlert size={22} className="shrink-0" />
                    <h3 className="font-bold text-sm sm:text-base">
                      Безопасность превыше всего
                    </h3>
                  </div>
                </div>

                {/* Кнопка "Быстро закрыть" (Panic button) */}
                <button
                  type="button"
                  onClick={() => {
                    try {
                      if (window.Telegram?.WebApp) {
                        window.Telegram.WebApp.close();
                      }
                    } catch (e) {
                      console.error(e);
                    }
                  }}
                  className="w-full py-3 px-4 rounded-xl bg-slate-900 hover:bg-black text-white dark:bg-white dark:hover:bg-slate-100 dark:text-slate-900 font-bold text-xs sm:text-sm transition-all shadow-md flex items-center justify-center gap-2"
                >
                  <XCircle size={18} />
                  <span>Быстро закрыть</span>
                </button>

                <p className="text-xs sm:text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
                  {session.safety_note ||
                    'В текущей ситуации первостепенное значение имеет ваша личная безопасность. Мы не даем стандартных советов по примирению, когда есть риск насилия или давления.'}
                </p>

                {personalAdvice?.validation && (
                  <div className="p-3.5 rounded-xl bg-rose-50/50 dark:bg-rose-950/20 text-xs text-rose-900 dark:text-rose-200 border border-rose-100 dark:border-rose-900/40 italic">
                    «{personalAdvice.validation}»
                  </div>
                )}

                <div className="pt-2 border-t border-slate-100 dark:border-zinc-800 space-y-2">
                  <div className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                    Экстренная и кризисная помощь (бесплатно, анонимно):
                  </div>

                  <a
                    href="tel:112"
                    className="flex items-center justify-between p-3 rounded-xl bg-rose-600 hover:bg-rose-700 text-white font-medium text-xs transition-colors shadow-sm"
                  >
                    <span>Единый номер экстренных служб (круглосуточно)</span>
                    <span className="font-bold flex items-center gap-1">
                      <PhoneCall size={14} /> 112
                    </span>
                  </a>

                  <a
                    href="tel:88007000600"
                    className="flex items-center justify-between p-3 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-slate-800 dark:text-slate-200 text-xs transition-colors"
                  >
                    <span>Телефон доверия для женщин, пострадавших от насилия</span>
                    <span className="font-semibold text-indigo-600 dark:text-indigo-400">
                      8-800-7000-600
                    </span>
                  </a>
                </div>

                <div className="text-[11px] text-slate-400 dark:text-slate-500 text-center pt-1">
                  Перед запуском проверьте актуальность номеров на сайтах организаций.
                </div>
              </div>
            ) : (
              /* ВЕТКА ОБЫЧНОГО РАЗБОРА: RISK_LEVEL == NONE ИЛИ ELEVATED */
              <div className="space-y-3.5">
                {/* Мягкий safety_note сверху при elevated */}
                {riskLevel === 'elevated' && session.safety_note && (
                  <div className="p-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200 border border-amber-200 dark:border-amber-900/50 text-xs leading-relaxed flex items-start gap-2.5">
                    <ShieldAlert size={16} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      <div className="font-semibold">Обратите внимание:</div>
                      <div className="mt-0.5">{session.safety_note}</div>
                    </div>
                  </div>
                )}

                {/* БЛОК 1: Понимание (Validation) */}
                {personalAdvice?.validation && (
                  <div className="bg-white dark:bg-zinc-900 rounded-2xl p-4 sm:p-5 border border-slate-200/70 dark:border-zinc-800 shadow-sm space-y-2">
                    <div className="flex items-center gap-2 text-rose-600 dark:text-rose-400 font-semibold text-xs uppercase tracking-wider">
                      <HeartHandshake size={15} />
                      <span>Понимание ваших чувств</span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-700 dark:text-slate-200 leading-relaxed">
                      {personalAdvice.validation}
                    </p>
                  </div>
                )}

                {/* БЛОК 2: Взгляд партнёра (Partner Perspective) */}
                {personalAdvice?.partner_perspective && (
                  <div className="bg-white dark:bg-zinc-900 rounded-2xl p-4 sm:p-5 border border-slate-200/70 dark:border-zinc-800 shadow-sm space-y-2">
                    <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-400 font-semibold text-xs uppercase tracking-wider">
                      <Eye size={15} />
                      <span>Взгляд партнёра (гипотеза)</span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-700 dark:text-slate-200 leading-relaxed">
                      {personalAdvice.partner_perspective}
                    </p>
                  </div>
                )}

                {/* БЛОК 3: Точка роста (Blind Spot) */}
                {personalAdvice?.blind_spot && (
                  <div className="bg-white dark:bg-zinc-900 rounded-2xl p-4 sm:p-5 border border-slate-200/70 dark:border-zinc-800 shadow-sm space-y-2">
                    <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400 font-semibold text-xs uppercase tracking-wider">
                      <Lightbulb size={15} />
                      <span>Точка роста</span>
                    </div>
                    <p className="text-xs sm:text-sm text-slate-700 dark:text-slate-200 leading-relaxed">
                      {personalAdvice.blind_spot}
                    </p>
                  </div>
                )}

                {/* БЛОК 4: Скрипты примирения (Action Scripts) */}
                {personalAdvice?.action_scripts && personalAdvice.action_scripts.length > 0 && (
                  <div className="bg-white dark:bg-zinc-900 rounded-2xl p-4 sm:p-5 border border-slate-200/70 dark:border-zinc-800 shadow-sm space-y-3">
                    <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 font-semibold text-xs uppercase tracking-wider">
                      <MessageSquare size={15} />
                      <span>Скрипты примирения (от 1-го лица)</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-snug">
                      Готовые фразы для мягкого возобновления диалога. Нажмите, чтобы скопировать:
                    </p>

                    <div className="space-y-3">
                      {personalAdvice.action_scripts.map((script, idx) => {
                        const isObj = typeof script === 'object' && script !== null;
                        const label = isObj ? script.label : (idx === 0 ? 'Сообщение прямо сейчас' : 'Предложение на сегодня или завтра');
                        const text = isObj ? script.text : script;
                        const why = isObj ? script.why : null;

                        return (
                          <div
                            key={idx}
                            className="p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/60 border border-slate-200/60 dark:border-zinc-700/60 flex flex-col justify-between gap-2.5"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 px-2 py-0.5 rounded-md bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-100 dark:border-emerald-900/50">
                                {label}
                              </span>
                            </div>
                            <div className="text-xs sm:text-sm text-slate-800 dark:text-slate-200 leading-relaxed italic">
                              «{text}»
                            </div>
                            {session?.script_hints?.[idx] && (
                              <div className="text-[11px] text-slate-500 dark:text-slate-400 leading-normal">
                                {session.script_hints[idx]}
                              </div>
                            )}
                            <div className="flex justify-end pt-1">
                              <CopyButton text={text} label="Скопировать фразу" />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* БЛОК 5: Для вас двоих (Shared Summary) */}
                {sharedSummary && (sharedSummary.situation_overview || sharedSummary.shared_advice) && (
                  <div className="bg-gradient-to-br from-indigo-50/70 to-purple-50/70 dark:from-indigo-950/40 dark:to-purple-950/40 rounded-2xl p-4 sm:p-5 border border-indigo-100 dark:border-indigo-900/50 shadow-sm space-y-3.5">
                    <div className="flex items-center gap-2 text-indigo-700 dark:text-indigo-300 font-bold text-xs uppercase tracking-wider">
                      <Users2 size={16} />
                      <span>Для вас двоих (общий итог)</span>
                    </div>

                    {sharedSummary.situation_overview && (
                      <div>
                        <div className="text-[11px] font-semibold text-indigo-900 dark:text-indigo-200">
                          Общая динамика:
                        </div>
                        <p className="text-xs sm:text-sm text-slate-700 dark:text-slate-300 mt-0.5 leading-relaxed">
                          {sharedSummary.situation_overview}
                        </p>
                      </div>
                    )}

                    {sharedSummary.shared_advice && (
                      <div>
                        <div className="text-[11px] font-semibold text-indigo-900 dark:text-indigo-200">
                          Совместный шаг навстречу:
                        </div>
                        <p className="text-xs sm:text-sm text-slate-700 dark:text-slate-300 mt-0.5 leading-relaxed">
                          {sharedSummary.shared_advice}
                        </p>
                      </div>
                    )}

                    {sharedSummary.conversation_starter && (
                      <div className="p-3 rounded-xl bg-white/80 dark:bg-zinc-900/80 border border-indigo-100/80 dark:border-indigo-900/40 space-y-2">
                        <div className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">
                          Фраза для совместного старта диалога:
                        </div>
                        <div className="text-xs sm:text-sm text-slate-800 dark:text-slate-200 italic leading-relaxed">
                          «{sharedSummary.conversation_starter}»
                        </div>
                        <div className="flex justify-end">
                          <CopyButton text={sharedSummary.conversation_starter} label="Скопировать" />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Кнопка внизу экрана */}
      <div className="pt-6 pb-2">
        <button
          onClick={onBack}
          className="w-full py-3 px-4 bg-slate-900 dark:bg-slate-100 hover:bg-slate-800 dark:hover:bg-white text-white dark:text-slate-900 text-xs sm:text-sm font-semibold rounded-xl transition-all shadow-sm"
        >
          Вернуться на главную
        </button>
      </div>
    </div>
  );
}
