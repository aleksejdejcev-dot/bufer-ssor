import React, { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Heart, Sparkles, LoaderCircle, Check } from 'lucide-react';
import { api } from '../api/client';

const QUESTIONS = [
  'Мне легко говорить с партнёром о том, что для меня важно.',
  'Я чувствую, что партнёр старается понять мою точку зрения.',
  'Нам хватает времени, когда мы можем побыть вместе и не отвлекаться.',
  'Я могу рассчитывать на поддержку партнёра в непростой момент.',
  'Наши повседневные дела и ответственность распределены приемлемо для меня.',
  'В наших отношениях достаточно тепла, внимания и нежности.',
];

const OPTIONS = ['Почти никогда', 'Редко', 'Иногда', 'Часто', 'Почти всегда'];
const DIMENSIONS = ['Разговоры', 'Понимание', 'Время вместе', 'Поддержка', 'Общие дела', 'Тепло'];

export default function RelationshipBalance({ sessionId, onBack }) {
  const [session, setSession] = useState(null);
  const [answers, setAnswers] = useState(Array(QUESTIONS.length).fill(0));
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const data = await api.getRelationshipBalance(sessionId);
      setSession(data);
      setError('');
    } catch (err) {
      setError(err.message || 'Не удалось загрузить баланс отношений');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  const submit = async () => {
    if (answers.some((answer) => !answer)) return;
    setSubmitting(true);
    setError('');
    try {
      await api.submitRelationshipBalance(sessionId, answers);
      await refresh();
    } catch (err) {
      setError(err.message || 'Не удалось отправить ответы. Попробуйте ещё раз.');
    } finally {
      setSubmitting(false);
    }
  };

  const finish = async () => {
    try {
      await api.finishRelationshipBalance(sessionId);
      onBack();
    } catch (err) {
      setError(err.message || 'Не удалось завершить баланс');
    }
  };

  if (loading) return <div className="min-h-screen flex items-center justify-center text-slate-500"><LoaderCircle className="animate-spin mr-2" />Загружаем…</div>;

  return (
    <main className="min-h-screen bg-slate-50 dark:bg-zinc-950 text-slate-900 dark:text-slate-100 px-4 pt-5 pb-10">
      <div className="max-w-xl mx-auto space-y-5">
        <button onClick={onBack} className="inline-flex items-center gap-2 text-sm text-slate-500"><ArrowLeft size={17} />На главную</button>
        <header className="rounded-3xl p-6 bg-gradient-to-br from-indigo-600 to-violet-700 text-white shadow-lg">
          <div className="w-11 h-11 rounded-2xl bg-white/15 flex items-center justify-center mb-3"><Heart size={23} /></div>
          <h1 className="text-2xl font-extrabold">Баланс отношений</h1>
          <p className="mt-2 text-sm text-indigo-100 leading-relaxed">Ответьте каждый отдельно. Партнёр не увидит ваши отдельные ответы — вместе вы получите общий бережный итог и идеи для пары.</p>
        </header>

        {error && <div role="alert" className="rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 p-3 text-sm text-rose-700 dark:text-rose-300">{error}</div>}

        {session?.status === 'completed' && session.result ? (
          <section className="space-y-4">
            <div className="rounded-2xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 text-center">
              <div className="text-xs font-semibold uppercase tracking-widest text-indigo-500">Ваш общий ориентир</div>
              <div className="text-5xl font-black mt-2">{session.result.score}<span className="text-xl text-slate-400">/100</span></div>
              <div className="font-bold mt-2">{session.result.label}</div>
              <p className="text-sm text-slate-600 dark:text-slate-300 mt-3 leading-relaxed">{session.result.summary}</p>
              <p className="text-[11px] text-slate-400 mt-3">Это повод для разговора, а не оценка качества или совместимости пары.</p>
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 space-y-3">
              <h2 className="font-bold text-sm">Темы для общего внимания</h2>
              {session.result.dimension_scores?.map((value, index) => <div key={index}>
                <div className="flex justify-between text-xs mb-1"><span>{DIMENSIONS[index]}</span><span className="text-slate-400">{value}/5</span></div>
                <div className="h-2 rounded-full bg-slate-100 dark:bg-zinc-800 overflow-hidden"><div className="h-full rounded-full bg-violet-500" style={{ width: `${value * 20}%` }} /></div>
              </div>)}
            </div>
            <div className="rounded-2xl border border-slate-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5">
              <h2 className="font-bold flex items-center gap-2"><Sparkles size={17} className="text-violet-500" />Небольшие шаги</h2>
              <ul className="mt-3 space-y-3 text-sm text-slate-700 dark:text-slate-300">{session.result.tips?.map((tip, i) => <li key={i} className="flex gap-2"><span className="text-indigo-500">•</span>{tip}</li>)}</ul>
              <div className="mt-4 rounded-xl bg-indigo-50 dark:bg-indigo-950/40 p-3 text-sm"><b>Идея для вас:</b> {session.result.activity_idea}</div>
            </div>
            <button onClick={finish} disabled={session.finish_confirmed_by_me} className="w-full rounded-xl bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-400 text-white py-3 font-semibold inline-flex items-center justify-center gap-2"><Check size={18} />{session.finish_confirmed_by_me ? 'Ожидаем подтверждение партнёра' : 'Завершить баланс'}</button>
            <p className="text-center text-xs text-slate-400">Результат удалится после подтверждения обоих или автоматически через 48 часов.</p>
          </section>
        ) : session?.answered ? (
          <section className="rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 p-6 text-center">
            <LoaderCircle className="animate-spin mx-auto text-indigo-500" size={28} />
            <h2 className="font-bold mt-4">Ждём ответы партнёра</h2>
            <p className="text-sm text-slate-500 mt-2">Когда он или она закончит, ИИ подготовит общий результат. Ответы хранятся зашифрованными только до анализа.</p>
          </section>
        ) : (
          <section className="space-y-4">
            <p className="text-sm text-slate-500">Насколько часто это бывает для вас? Выберите один ответ для каждого утверждения.</p>
            {QUESTIONS.map((question, index) => (
              <fieldset key={question} className="rounded-2xl bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 p-4">
                <legend className="font-semibold text-sm leading-relaxed">{index + 1}. {question}</legend>
                <div className="mt-3 grid grid-cols-1 gap-2">
                  {OPTIONS.map((option, optionIndex) => {
                    const value = optionIndex + 1;
                    return <label key={option} className={`flex items-center gap-3 rounded-xl border p-3 text-sm cursor-pointer ${answers[index] === value ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/50' : 'border-slate-200 dark:border-zinc-700'}`}>
                      <input type="radio" name={`q-${index}`} value={value} checked={answers[index] === value} onChange={() => setAnswers((prev) => prev.map((v, i) => i === index ? value : v))} />{option}
                    </label>;
                  })}
                </div>
              </fieldset>
            ))}
            <button disabled={answers.some((answer) => !answer) || submitting} onClick={submit} className="w-full rounded-xl bg-indigo-600 disabled:opacity-50 text-white py-3 font-bold inline-flex items-center justify-center gap-2">
              {submitting ? <><LoaderCircle className="animate-spin" size={18} />Отправляем</> : 'Отправить ответы'}
            </button>
          </section>
        )}
      </div>
    </main>
  );
}
