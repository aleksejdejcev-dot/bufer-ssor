import React, { useEffect } from 'react';
import { X, ShieldCheck, FileText, Lock } from 'lucide-react';
import WebApp from '@twa-dev/sdk';

export const LEGAL_DOCS = {
  terms: {
    title: 'Пользовательское соглашение (оферта)',
    icon: FileText,
    content: `
1. Общие положения
Сервис «Буфер Ссор» представляет собой программный инструмент содействия бережной коммуникации между совершеннолетними партнерами с использованием искусственного интеллекта.

2. Отказ от медицинской и психотерапевтической помощи
Сервис НЕ является медицинской организацией, не оказывает медицинских, психиатрических или психотерапевтических услуг. Рекомендации ИИ носят исключительно информационный и медиативный характер.

3. Ограничения возраста
Использование сервиса разрешено исключительно лицам, достигшим возраста 18 лет. Регистрируясь в сервисе, пользователь подтверждает свое совершеннолетие.

4. Безопасность и экстренные ситуации
При наличии угрозы физической безопасности, насилию или суицидальному риску пользователи обязуются незамедлительно обращаться в экстренные службы (112).
    `.trim(),
  },
  privacy: {
    title: 'Политика конфиденциальности',
    icon: ShieldCheck,
    content: `
1. Сбор и минимизация данных
Мы обрабатываем только данные, необходимые для функционирования сервиса: telegram_id, имя пользователя Telegram и зашифрованные исходные версии конфликта.

2. Сквозное удаление исходников
Исходные сообщения партнеров хранятся исключительно в зашифрованном виде (алгоритм Fernet) и безвозвратно удаляются сразу после завершения анализа сессии ИИ.

3. Третьи лица
Персональные данные партнеров не продаются и не передаются третьим лицам. Модель искусственного интеллекта получает исключительно обезличенный текст без имен и контактов.
    `.trim(),
  },
  nda: {
    title: 'Режим неразглашения и тайна исповеди',
    icon: Lock,
    content: `
1. Информационный барьер между партнерами
Архитектура сервиса реализует строгое соблюдение принципа тайны исповеди: ни при каких обстоятельствах исходный текст сообщений одного партнера не показывается и не передается второму партнеру.

2. Персональный характер разборов
Каждый партнер получает исключительно свою персональную карточку и нейтральный общий итог. Личные признания, сомнения и уязвимости остаются строго конфиденциальными.

3. Право на забвение
В любой момент любой из партнеров может нажать кнопку «Удалить все наши данные», что приведет к моментальному и необратимому стиранию истории и связки в базе данных.
    `.trim(),
  },
};

export default function LegalModal({ docKey, onClose }) {
  useEffect(() => {
    try {
      WebApp.HapticFeedback?.impactOccurred('light');
    } catch {}
  }, []);

  if (!docKey || !LEGAL_DOCS[docKey]) return null;

  const doc = LEGAL_DOCS[docKey];
  const Icon = doc.icon;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 bg-black/50 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div 
        className="w-full sm:max-w-md bg-white dark:bg-zinc-900 rounded-t-2xl sm:rounded-2xl max-h-[85vh] flex flex-col shadow-xl animate-slide-up border border-slate-200/60 dark:border-zinc-800"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Заголовок модального окна */}
        <div className="flex items-center justify-between p-4 border-b border-slate-100 dark:border-zinc-800/80">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 dark:bg-indigo-950/50 flex items-center justify-center text-indigo-600 dark:text-indigo-400">
              <Icon size={18} />
            </div>
            <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm leading-tight">
              {doc.title}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-zinc-800 transition-colors"
            aria-label="Закрыть"
          >
            <X size={20} />
          </button>
        </div>

        {/* Предупреждающий баннер */}
        <div className="mx-5 mt-4 p-3 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/50 rounded-xl text-amber-800 dark:text-amber-200 text-xs font-medium flex items-center gap-2">
          <span>⚠️</span>
          <span>Черновик, требует проверки юристом. Не является публичной офертой.</span>
        </div>

        {/* Текст документа */}
        <div className="p-5 overflow-y-auto text-xs sm:text-sm text-slate-600 dark:text-slate-300 space-y-3 leading-relaxed whitespace-pre-line">
          {doc.content}
        </div>

        {/* Кнопка закрытия */}
        <div className="p-4 border-t border-slate-100 dark:border-zinc-800/80 bg-slate-50/50 dark:bg-zinc-900/50 rounded-b-2xl">
          <button
            onClick={onClose}
            className="w-full py-2.5 px-4 bg-slate-900 dark:bg-slate-100 hover:bg-slate-800 dark:hover:bg-white text-white dark:text-slate-900 text-sm font-medium rounded-xl transition-colors"
          >
            Понятно
          </button>
        </div>
      </div>
    </div>
  );
}
