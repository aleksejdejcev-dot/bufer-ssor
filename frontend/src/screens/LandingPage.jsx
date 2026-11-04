import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Lock,
  Scale,
  MessageSquareHeart,
  CheckCircle2,
  Send,
  X,
  FileText,
  ShieldCheck,
  RotateCcw,
  ExternalLink,
  Phone,
  Mail,
  MapPin,
  User,
  CreditCard,
  HeartHandshake
} from 'lucide-react';

export const LANDING_DOCS = {
  terms: {
    title: 'Публичная оферта',
    icon: FileText,
    subtitle: 'Договор возмездного оказания цифровых услуг по подписке',
    content: (
      <div className="space-y-4 text-xs sm:text-sm text-slate-300 leading-relaxed">
        <div>
          <h4 className="font-semibold text-white text-sm mb-1">1. ОБЩИЕ ПОЛОЖЕНИЯ</h4>
          <p>
            1.1. Настоящий документ представляет собой официальное предложение (публичную оферту в соответствии со ст. 437 Гражданского кодекса Российской Федерации) Самозанятого Дейцева Алексея Дмитриевича (ИНН: 540363371985), далее именуемого «Исполнитель», о заключении договора возмездного оказания цифровых услуг на условиях, изложенных ниже.
          </p>
          <p className="mt-1">
            1.2. Акцептом настоящей оферты признается совершение Пользователем оплаты доступа к сервису в порядке, предусмотренном настоящим документом. Моментом заключения договора является подтверждение успешного проведения платежа со стороны платежной системы.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">2. ПРЕДМЕТ ДОГОВОРА</h4>
          <p>
            2.1. Исполнитель обязуется предоставить Пользователю возмездный цифровой доступ к функционалу интерактивного сервиса медиации разногласий «Буфер Ссор» по подписке «Буфер Ссор Premium» (далее — «Сервис»), а Пользователь обязуется оплатить данный доступ по установленному тарифу.
          </p>
          <p className="mt-1">
            2.2. Сервис функционирует в виде программного обеспечения в мессенджере Telegram (Telegram Mini App) и предоставляет алгоритмический анализ текстовых описаний ситуаций разногласий с формированием нейтральных рекомендаций для экологичного разрешения споров.
          </p>
          <p className="mt-1">
            2.3. Сервис носит информационно-медиативный характер, не является психологической, медицинской или психотерапевтической помощью и не заменяет обращение к квалифицированным специалистам.
          </p>
          <p className="mt-1">
            2.4. Сервис предназначен исключительно для совершеннолетних пользователей (18+).
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">3. ПОРЯДОК И СПОСОБ ОКАЗАНИЯ УСЛУГ</h4>
          <p>
            3.1. Услуги носят исключительно цифровой характер. Физическая доставка товара не требуется и не осуществляется.
          </p>
          <p className="mt-1">
            3.2. Доступ к расширенному функционалу Буфер Ссор Premium активируется в автоматическом режиме моментально после подтверждения транзакции платежным шлюзом ЮKassa.
          </p>
          <p className="mt-1">
            3.3. Пользователю предоставляются: неограниченное количество сессий медиации в течение оплаченного периода, алгоритмический разбор ситуации и персональные рекомендации для конструктивного диалога пары.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">4. СТОИМОСТЬ И ПОРЯДОК ОПЛАТЫ</h4>
          <p>
            4.1. Стоимость подписки «Буфер Ссор Premium» составляет 199 (сто девяносто девять) рублей за 1 календарный месяц.
          </p>
          <p className="mt-1">
            4.2. Оплата производится в безналичном порядке через платежный сервис ЮKassa банковскими картами (МИР, Visa, Mastercard) или иными поддерживаемыми платежными инструментами.
          </p>
          <p className="mt-1">
            4.3. Исполнитель применяет специальный налоговый режим «Налог на профессиональный доход» (самозанятый). Кассовый чек формируется в электронной форме в приложении «Мой налог» и направляется Пользователю в соответствии с Федеральным законом № 422-ФЗ.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">5. ПРАВА И ОБЯЗАННОСТИ СТОРОН</h4>
          <p>
            5.1. Исполнитель обязуется обеспечивать функционирование Сервиса в режиме 24/7, за исключением периодов регламентных технических работ, и соблюдать конфиденциальность обращений Пользователя.
          </p>
          <p className="mt-1">
            5.2. Пользователь обязуется использовать Сервис только в законных целях и не использовать его в экстренных ситуациях, связанных с угрозой жизни, здоровью или насилием (в таких ситуациях следует незамедлительно обращаться в экстренные службы по номеру 112).
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">6. СРОК ДЕЙСТВИЯ ОФЕРТЫ И РЕКВИЗИТЫ</h4>
          <p>
            6.1. Настоящая оферта действует с момента публикации по адресу bufer-ssor.ru до момента ее отзыва Исполнителем.
          </p>
          <div className="mt-2 p-3 bg-zinc-800/60 rounded-xl text-xs space-y-1 text-slate-300">
            <div><strong>Исполнитель:</strong> Самозанятый Дейцев Алексей Дмитриевич</div>
            <div><strong>ИНН:</strong> 540363371985</div>
            <div><strong>Почтовый адрес:</strong> 630520, Россия, г. Новосибирск</div>
            <div><strong>Телефон:</strong> +79231777830</div>
            <div><strong>Email:</strong> aleksejdejcev@gmail.com</div>
            <div><strong>Telegram поддержки:</strong> @BufferSsorBot</div>
          </div>
        </div>
      </div>
    ),
  },
  privacy: {
    title: 'Политика конфиденциальности',
    icon: ShieldCheck,
    subtitle: 'Условия обработки персональных данных и режим тайны исповеди',
    content: (
      <div className="space-y-4 text-xs sm:text-sm text-slate-300 leading-relaxed">
        <div>
          <h4 className="font-semibold text-white text-sm mb-1">1. ОБЩИЕ ПОЛОЖЕНИЯ</h4>
          <p>
            1.1. Настоящая Политика определяет порядок обработки и защиты информации пользователей интерактивного сервиса «Буфер Ссор» (bufer-ssor.ru), администрируемого Самозанятым Дейцевым Алексеем Дмитриевичем (ИНН: 540363371985), далее — «Оператор».
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">2. ЦЕЛИ ОБРАБОТКИ</h4>
          <p>Данные используются для входа в Telegram Mini App, создания и обслуживания пары, проведения разборов, предоставления оплаченной подписки, поддержки, возвратов и платёжного учёта.</p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">3. КАКИЕ ДАННЫЕ ОБРАБАТЫВАЮТСЯ</h4>
          <ul className="list-disc list-inside space-y-0.5 pl-1">
            <li>Telegram ID и отображаемое имя, сведения о паре и принятии условий;</li>
            <li>Тексты и результаты разборов; голосовые сообщения сейчас не поддерживаются;</li>
            <li>Платёжные сведения: ID операции ЮKassa, сумма, валюта, продукт, статус и даты; хешированный идентификатор плательщика; ID пары, пока платёж с ней связан;</li>
            <li>Для действующей подписки — хешированный идентификатор плательщика и дата окончания срока.</li>
          </ul>
          <p className="mt-1">Хеширование уменьшает прямую идентифицируемость, но не является обещанием полной анонимности: оператор может вычислить хеш по Telegram ID и секретному ключу.</p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">4. ИИ-ПРОВАЙДЕРЫ И ЮKASSA</h4>
          <p>Тексты, необходимые для разбора, передаются провайдеру ИИ Sber GigaChat и не считаются полностью анонимизированными. GigaChat обрабатывает версии обоих участников для анализа; в приложении партнёры не получают исходные тексты друг друга. Голосовые сообщения сейчас не поддерживаются.</p>
          <p className="mt-1">Для проведения платежа ЮKassa получает Telegram ID плательщика, план и ID пары, если она создана к моменту оплаты, а также обрабатывает сведения, необходимые для проведения платежа, по своим условиям и политике.</p>
          <p className="mt-1">Данные не продаются и не используются для рекламных рассылок.</p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">5. СРОКИ ХРАНЕНИЯ</h4>
          <p>Исходные сообщения хранятся зашифрованными и удаляются после анализа; если партнёр не прислал свою часть, незавершённые материалы удаляются по истечении 48 часов. Готовые карточки и общий итог доступны, пока конфликт не завершён. Когда оба партнёра нажимают «Завершить конфликт», карточки, итог и связанные с конфликтом данные удаляются сразу после второго подтверждения. Если оба подтверждения не получены, данные конфликта удаляются после 48 часов с момента готовности разбора; фоновая очистка запускается каждую минуту.</p>
          <p className="mt-1">Хешированная запись подписки сохраняется до конца оплаченного срока и удаляется фоновой очисткой после его истечения. Платёжные записи сохраняются отдельно для возвратов, разбирательств и учёта. Автоматическая очистка таких записей работает только если оператор настроил срок хранения; без него записи автоматически не удаляются. Резервные копии могут сохранять данные до ротации по настроенному графику.</p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">6. УДАЛЕНИЕ ПАРЫ И ПОДПИСКИ</h4>
          <p>При удалении пары из рабочей базы удаляются связка, профили участников, история, исходники и результаты, относящиеся к этой паре. Telegram ID может снова сохраниться при следующем входе в приложение; восстановить удалённые данные пары нельзя.</p>
          <p className="mt-1">Активная оплаченная подписка плательщика не удаляется вместе с парой: она личная, сохраняется до конца оплаченного срока и позволяет плательщику создать новую пару. Поэтому удаление пары не означает удаление абсолютно всех сведений: минимальная запись о подписке, платёжные сведения, журнал факта удаления и резервные копии обрабатываются отдельно по срокам, указанным в этой Политике.</p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">7. ПРАВА И ОБРАЩЕНИЯ</h4>
          <p>Запросы о доступе, исправлении или удалении данных можно направить Оператору по адресу aleksejdejcev@gmail.com или через @BufferSsorBot. Платёжные сведения и действующая подписка обрабатываются отдельно от данных пары, как описано выше.</p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">8. КОНТАКТЫ ОПЕРАТОРА</h4>
          <div className="mt-2 p-3 bg-zinc-800/60 rounded-xl text-xs space-y-1 text-slate-300">
            <div><strong>Оператор:</strong> Самозанятый Дейцев Алексей Дмитриевич</div>
            <div><strong>ИНН:</strong> 540363371985</div>
            <div><strong>Почтовый адрес:</strong> 630520, Россия, г. Новосибирск</div>
            <div><strong>Email:</strong> aleksejdejcev@gmail.com</div>
            <div><strong>Telegram:</strong> @BufferSsorBot</div>
          </div>
        </div>
      </div>
    ),
  },
  refund: {
    title: 'Правила оплаты и порядок возврата средств',
    icon: RotateCcw,
    subtitle: 'Порядок проведения онлайн-платежей через ЮKassa и регламент возврата',
    content: (
      <div className="space-y-4 text-xs sm:text-sm text-slate-300 leading-relaxed">
        <div>
          <h4 className="font-semibold text-white text-sm mb-1">1. ПОРЯДОК ОПЛАТЫ ЧЕРЕЗ ЮKASSA</h4>
          <p>
            1.1. Оплата подписки на сервис «Буфер Ссор» осуществляется онлайн через сертифицированный платежный шлюз ЮKassa (ООО НКО «ЮМани»).
          </p>
          <p className="mt-1">
            1.2. К оплате принимаются банковские карты платежных систем МИР, Visa, Mastercard, а также иные электронные способы, поддерживаемые ЮKassa.
          </p>
          <p className="mt-1">
            1.3. При проведении оплаты данные Пользователя передаются по защищенному протоколу HTTPS. Безопасность обработки платежей обеспечивается применением технологии двухфакторной аутентификации 3D-Secure. Номера банковских карт и реквизиты платежей не хранятся на серверах сервиса «Буфер Ссор».
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">2. ДОСТАВКА ЦИФРОВОЙ УСЛУГИ</h4>
          <p>
            2.1. Предоставляемые услуги носят исключительно цифровой характер. Физическая доставка товара не требуется и не осуществляется.
          </p>
          <p className="mt-1">
            2.2. Активация подписки «Буфер Ссор Premium» происходит автоматически и мгновенно после подтверждения транзакции на стороне платежного шлюза ЮKassa внутри Telegram Mini App.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">3. РЕГЛАМЕНТ И ПОРЯДОК ВОЗВРАТА СРЕДСТВ</h4>
          <p>
            3.1. Пользователь вправе отказаться от услуги и запросить возврат денежных средств, направив мотивированное письменное заявление на адрес электронной почты: <strong>aleksejdejcev@gmail.com</strong>.
          </p>
          <p className="mt-1">
            3.2. В заявлении на возврат необходимо указать:
          </p>
          <ul className="list-disc list-inside mt-1 space-y-0.5 pl-1">
            <li>Фамилию, имя и отчество заявителя;</li>
            <li>Telegram ID пользователя (числовой идентификатор аккаунта);</li>
            <li>Дату и сумму совершенного платежа;</li>
            <li>Причину запроса на возврат денежных средств.</li>
          </ul>
          <p className="mt-1">
            3.3. Срок рассмотрения заявления и принятия решения о возврате составляет до 10 (десяти) рабочих дней с момента получения обращения.
          </p>
          <p className="mt-1">
            3.4. Возврат денежных средств осуществляется тем же безналичным способом и на ту же банковскую карту, с которой была совершена оплата. Срок фактического зачисления средств на счет Пользователя зависит от регламента банка-эмитента карты (как правило, от 1 до 5 рабочих дней).
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-white text-sm mb-1">4. СЛУЖБА ПОДДЕРЖКИ И РЕКВИЗИТЫ</h4>
          <div className="mt-2 p-3 bg-zinc-800/60 rounded-xl text-xs space-y-1 text-slate-300">
            <div><strong>Исполнитель:</strong> Самозанятый Дейцев Алексей Дмитриевич</div>
            <div><strong>ИНН:</strong> 540363371985</div>
            <div><strong>Почтовый адрес:</strong> 630520, Россия, г. Новосибирск</div>
            <div><strong>Email для обращений и возвратов:</strong> aleksejdejcev@gmail.com</div>
            <div><strong>Телефон для связи:</strong> +79231777830</div>
            <div><strong>Telegram-бот поддержки:</strong> @BufferSsorBot</div>
          </div>
        </div>
      </div>
    ),
  },
};

export default function LandingPage() {
  const [activeModalKey, setActiveModalKey] = useState(null);

  // Закрытие модального окна по клавише Escape
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setActiveModalKey(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const openModal = (key) => {
    setActiveModalKey(key);
  };

  const closeModal = () => {
    setActiveModalKey(null);
  };

  const activeDoc = activeModalKey ? LANDING_DOCS[activeModalKey] : null;

  return (
    <div className="min-h-screen bg-[#090a0f] text-slate-100 flex flex-col font-sans relative selection:bg-indigo-500/30 selection:text-indigo-200">
      {/* Декоративное фоновое свечение */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[450px] bg-[radial-gradient(ellipse_at_top,rgba(99,102,241,0.15),transparent_70%)] pointer-events-none" />
      <div className="absolute top-[800px] left-1/2 -translate-x-1/2 w-[900px] h-[400px] bg-[radial-gradient(ellipse_at_center,rgba(168,85,247,0.08),transparent_70%)] pointer-events-none" />

      {/* ШАПКА (HEADER) */}
      <header className="sticky top-0 z-30 backdrop-blur-md bg-[#090a0f]/80 border-b border-zinc-800/80">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          {/* Логотип и название */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-violet-500 flex items-center justify-center text-white shadow-md shadow-indigo-500/25">
              <Sparkles size={18} />
            </div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-base sm:text-lg text-white tracking-tight">
                Буфер Ссор
              </span>
              <span className="hidden sm:inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                ИИ-медиатор для пар
              </span>
            </div>
          </div>

          {/* Кнопка «Открыть в Telegram» */}
          <a
            href="https://t.me/BufferSsorBot"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-3.5 py-1.5 sm:px-4 sm:py-2 rounded-xl text-xs sm:text-sm font-medium bg-zinc-900 hover:bg-zinc-800 text-slate-200 border border-zinc-700/80 hover:border-zinc-600 transition-all shadow-xs"
          >
            <Send size={14} className="text-indigo-400" />
            <span>Открыть в Telegram</span>
          </a>
        </div>
      </header>

      {/* ОСНОВНОЙ КОНТЕНТ */}
      <main className="flex-1 max-w-5xl mx-auto px-4 sm:px-6 py-12 sm:py-20 w-full relative z-10">
        {/* ПЕРВЫЙ ЭКРАН (HERO) */}
        <section className="text-center max-w-3xl mx-auto">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-500/25 mb-6">
            <Sparkles size={13} className="text-indigo-400" />
            <span>Конфиденциальный цифровой медиатор</span>
          </div>

          <h1 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-white leading-tight sm:leading-tight">
            Буфер Ссор — сохраняйте гармонию в отношениях без обид и упрёков
          </h1>

          <p className="mt-5 text-sm sm:text-lg text-slate-400 leading-relaxed max-w-2xl mx-auto">
            Интеллектуальный конфиденциальный медиатор. Помогает экологично разобрать конфликты, услышать истинные мотивы партнёра и найти компромисс 24/7.
          </p>

          {/* Главная CTA-кнопка */}
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <a
              href="https://t.me/BufferSsorBot"
              target="_blank"
              rel="noopener noreferrer"
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2.5 px-8 py-3.5 rounded-2xl bg-gradient-to-r from-indigo-500 via-indigo-600 to-violet-600 hover:from-indigo-600 hover:to-violet-700 text-white font-semibold text-sm sm:text-base shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 hover:scale-[1.01] active:scale-[0.99] transition-all"
            >
              <Send size={16} />
              <span>Запустить медиатора в Telegram</span>
            </a>
          </div>

          {/* Тезисы доверия */}
          <div className="mt-8 pt-6 border-t border-zinc-800/60 flex flex-wrap items-center justify-center gap-y-2 gap-x-6 text-xs text-slate-400">
            <span className="flex items-center gap-1.5">
              <CheckCircle2 size={14} className="text-emerald-400" />
              Тайна исповеди между партнёрами
            </span>
            <span className="flex items-center gap-1.5">
              <CheckCircle2 size={14} className="text-emerald-400" />
              Без взаимных обвинений
            </span>
            <span className="flex items-center gap-1.5">
              <CheckCircle2 size={14} className="text-emerald-400" />
              Доступен круглосуточно 24/7
            </span>
          </div>
        </section>

        {/* ПРЕИМУЩЕСТВА СЕРВИСА */}
        <section className="mt-16 sm:mt-24">
          <div className="text-center mb-10">
            <h2 className="text-xl sm:text-2xl font-bold text-white tracking-tight">
              Как «Буфер Ссор» помогает вашей паре
            </h2>
            <p className="mt-2 text-xs sm:text-sm text-slate-400 max-w-xl mx-auto">
              Информационный барьер и поддержка искусственного интеллекта для бережного разрешения разногласий
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {/* Карточка 1 */}
            <div className="p-6 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 hover:border-zinc-700/80 transition-all flex flex-col shadow-xs">
              <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center mb-4">
                <Lock size={20} />
              </div>
              <h3 className="font-semibold text-white text-base mb-2">
                Полная тайна исповеди
              </h3>
              <p className="text-xs sm:text-sm text-slate-400 leading-relaxed">
                Строгий информационный барьер, данные переписки защищены и не передаются третьим лицам. Партнёр видит исключительно спокойный общий итог без прямого цитирования личных формулировок.
              </p>
            </div>

            {/* Карточка 2 */}
            <div className="p-6 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 hover:border-zinc-700/80 transition-all flex flex-col shadow-xs">
              <div className="w-10 h-10 rounded-xl bg-violet-500/10 border border-violet-500/20 text-violet-400 flex items-center justify-center mb-4">
                <Scale size={20} />
              </div>
              <h3 className="font-semibold text-white text-base mb-2">
                Беспристрастный анализ
              </h3>
              <p className="text-xs sm:text-sm text-slate-400 leading-relaxed">
                Искусственный интеллект выявляет скрытые потребности без взаимных обвинений. Нейтральный взгляд со стороны помогает увидеть истинные причины обид и переживаний.
              </p>
            </div>

            {/* Карточка 3 */}
            <div className="p-6 rounded-2xl bg-zinc-900/60 border border-zinc-800/80 hover:border-zinc-700/80 transition-all flex flex-col shadow-xs">
              <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400 flex items-center justify-center mb-4">
                <MessageSquareHeart size={20} />
              </div>
              <h3 className="font-semibold text-white text-base mb-2">
                Пошаговые алгоритмы примирения
              </h3>
              <p className="text-xs sm:text-sm text-slate-400 leading-relaxed">
                Понятные персональные рекомендации и готовые бережные фразы для восстановления открытого доверительного диалога без возобновления спора.
              </p>
            </div>
          </div>
        </section>

        {/* БЛОК ТАРИФА И УСЛУГ (ПУНКТ 1 ТРЕБОВАНИЙ ЮKASSA) */}
        <section className="mt-16 sm:mt-24">
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 mb-3">
              <CreditCard size={13} className="text-indigo-400" />
              <span>Тарифный план</span>
            </div>
            <h2 className="text-xl sm:text-3xl font-bold text-white tracking-tight">
              Единый прозрачный тариф для двоих
            </h2>
            <p className="mt-2 text-xs sm:text-sm text-slate-400 max-w-lg mx-auto">
              Одна подписка открывает полный безлимитный доступ к возможностям сервиса сразу для обоих партнеров
            </p>
          </div>

          <div className="max-w-md mx-auto rounded-3xl bg-gradient-to-b from-zinc-900 via-zinc-900/90 to-zinc-950 border border-indigo-500/30 p-6 sm:p-8 shadow-xl shadow-indigo-950/40 relative overflow-hidden">
            <div className="absolute top-0 right-0 -mr-16 -mt-16 w-32 h-32 bg-indigo-500/10 rounded-full blur-2xl pointer-events-none" />

            <div className="flex items-center justify-between gap-2 mb-4">
              <span className="text-xs font-semibold uppercase tracking-wider text-indigo-400">
                Тарифный план
              </span>
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                Доступ на 1 месяц
              </span>
            </div>

            <h3 className="text-xl font-bold text-white">
              Подписка Буфер Ссор Premium
            </h3>

            <div className="mt-4 flex items-baseline gap-2">
              <span className="text-4xl font-extrabold text-white tracking-tight">
                199 ₽
              </span>
              <span className="text-slate-400 text-sm font-medium">
                / месяц
              </span>
            </div>

            <div className="mt-6 pt-6 border-t border-zinc-800/80 space-y-3.5">
              <div className="flex items-start gap-3 text-xs sm:text-sm text-slate-300">
                <CheckCircle2 size={16} className="text-emerald-400 shrink-0 mt-0.5" />
                <span>Безлимитные сессии медиации разногласий 24/7</span>
              </div>
              <div className="flex items-start gap-3 text-xs sm:text-sm text-slate-300">
                <CheckCircle2 size={16} className="text-emerald-400 shrink-0 mt-0.5" />
                <span>Персональный разбор эмоционального фона пары</span>
              </div>
              <div className="flex items-start gap-3 text-xs sm:text-sm text-slate-300">
                <CheckCircle2 size={16} className="text-emerald-400 shrink-0 mt-0.5" />
                <span>Приоритетная скорость работы нейросети</span>
              </div>
              <div className="flex items-start gap-3 text-xs sm:text-sm text-slate-300">
                <CheckCircle2 size={16} className="text-emerald-400 shrink-0 mt-0.5" />
                <span>Доступ к полной истории сессий</span>
              </div>
            </div>

            <a
              href="https://t.me/BufferSsorBot"
              target="_blank"
              rel="noopener noreferrer"
              className="mt-8 w-full inline-flex items-center justify-center gap-2 py-3.5 px-6 rounded-2xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm transition-all shadow-md shadow-indigo-600/20 hover:shadow-indigo-600/40"
            >
              <span>Оформить подписку</span>
              <ExternalLink size={15} />
            </a>

            <p className="mt-3 text-center text-[11px] text-slate-500">
              Оплата производится через защищенный платежный шлюз ЮKassa
            </p>
          </div>
        </section>

        {/* СПОСОБ ПОЛУЧЕНИЯ ЗАКАЗА / ДОСТАВКА ЦИФРОВОЙ УСЛУГИ (ПУНКТ 2 ТРЕБОВАНИЙ ЮKASSA) */}
        <section className="mt-12 sm:mt-16 max-w-3xl mx-auto">
          <div className="p-5 sm:p-6 rounded-2xl bg-zinc-900/80 border border-indigo-500/25 shadow-xs">
            <div className="flex items-start gap-3.5">
              <div className="w-9 h-9 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center shrink-0 mt-0.5">
                <RotateCcw size={18} />
              </div>
              <div>
                <h3 className="font-semibold text-white text-sm sm:text-base mb-1.5">
                  Порядок и способ получения услуги
                </h3>
                <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
                  Предоставляемые услуги носят исключительно цифровой характер. Физическая доставка товара не требуется и не осуществляется. Активация подписки и доступ ко всем функциям Буфер Ссор Premium происходят в автоматическом режиме моментально после подтверждения оплаты на стороне платежного шлюза ЮKassa внутри Telegram Mini App.
                </p>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* ЮРИДИЧЕСКИЙ ПОДВАЛ (FOOTER — ПУНКТЫ 3 И 4 ТРЕБОВАНИЙ ЮKASSA) */}
      <footer className="mt-20 border-t border-zinc-800/80 bg-[#06070a] text-slate-400 text-xs">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-12">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8 pb-8 border-b border-zinc-800/80">
            {/* Реквизиты и контакты */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-white font-semibold text-sm mb-2">
                <User size={16} className="text-indigo-400" />
                <span>Информация о продавце и реквизиты</span>
              </div>
              <div className="text-slate-300 space-y-1.5 text-xs">
                <div><strong>Самозанятый:</strong> Дейцев Алексей Дмитриевич</div>
                <div><strong>ИНН:</strong> 540363371985</div>
                <div className="flex items-center gap-1.5">
                  <MapPin size={13} className="text-slate-500 shrink-0" />
                  <span><strong>Почтовый адрес:</strong> 630520, Россия, г. Новосибирск</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Phone size={13} className="text-slate-500 shrink-0" />
                  <span><strong>Телефон для связи:</strong> <a href="tel:+79231777830" className="text-indigo-400 hover:underline">+79231777830</a></span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Mail size={13} className="text-slate-500 shrink-0" />
                  <span><strong>Электронная почта:</strong> <a href="mailto:aleksejdejcev@gmail.com" className="text-indigo-400 hover:underline">aleksejdejcev@gmail.com</a></span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Send size={13} className="text-slate-500 shrink-0" />
                  <span><strong>Telegram поддержки:</strong> <a href="https://t.me/BufferSsorBot" target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:underline">@BufferSsorBot</a></span>
                </div>
              </div>
            </div>

            {/* Безопасность эквайринга и платежные системы */}
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-white font-semibold text-sm mb-2">
                <ShieldCheck size={16} className="text-emerald-400" />
                <span>Безопасность онлайн-платежей</span>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed">
                Оплата происходит через сервис ЮKassa с использованием банковских карт платежных систем МИР, Visa, Mastercard. Безопасность обработки платежей обеспечивается применением протоколов шифрования HTTPS и технологии двухфакторной аутентификации 3D-Secure.
              </p>

              {/* Логотипы и бейджи платежных систем */}
              <div className="pt-2 flex flex-wrap items-center gap-2.5">
                <span className="px-2.5 py-1 rounded-md bg-zinc-800 text-slate-200 border border-zinc-700 text-[11px] font-bold tracking-wider">
                  МИР
                </span>
                <span className="px-2.5 py-1 rounded-md bg-zinc-800 text-slate-200 border border-zinc-700 text-[11px] font-bold tracking-wider">
                  VISA
                </span>
                <span className="px-2.5 py-1 rounded-md bg-zinc-800 text-slate-200 border border-zinc-700 text-[11px] font-bold tracking-wider">
                  Mastercard
                </span>
                <span className="px-2.5 py-1 rounded-md bg-indigo-950/70 text-indigo-300 border border-indigo-800/60 text-[11px] font-semibold">
                  ЮKassa
                </span>
              </div>
            </div>
          </div>

          {/* Ссылки на модальные окна с юридическими документами */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-2">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
              <button
                type="button"
                onClick={() => openModal('terms')}
                className="text-slate-400 hover:text-white transition-colors underline underline-offset-4 decoration-zinc-700 hover:decoration-indigo-400 cursor-pointer text-left"
              >
                Публичная оферта
              </button>
              <button
                type="button"
                onClick={() => openModal('privacy')}
                className="text-slate-400 hover:text-white transition-colors underline underline-offset-4 decoration-zinc-700 hover:decoration-indigo-400 cursor-pointer text-left"
              >
                Политика конфиденциальности
              </button>
              <button
                type="button"
                onClick={() => openModal('refund')}
                className="text-slate-400 hover:text-white transition-colors underline underline-offset-4 decoration-zinc-700 hover:decoration-indigo-400 cursor-pointer text-left"
              >
                Правила оплаты и порядок возврата средств
              </button>
            </div>

            <div className="text-[11px] text-slate-500">
              © {new Date().getFullYear()} «Буфер Ссор». Все права защищены. Сервис для лиц старше 18 лет.
            </div>
          </div>
        </div>
      </footer>

      {/* МОДАЛЬНЫЕ ОКНА ДЛЯ ЮРИДИЧЕСКИХ ДОКУМЕНТОВ */}
      {activeDoc && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in"
          onClick={closeModal}
        >
          <div
            className="w-full max-w-2xl bg-zinc-900 border border-zinc-800 rounded-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Шапка модального окна */}
            <div className="flex items-center justify-between p-4 sm:p-5 border-b border-zinc-800">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center">
                  <activeDoc.icon size={18} />
                </div>
                <div>
                  <h3 className="font-semibold text-white text-sm sm:text-base leading-tight">
                    {activeDoc.title}
                  </h3>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    {activeDoc.subtitle}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={closeModal}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
                aria-label="Закрыть"
              >
                <X size={20} />
              </button>
            </div>

            {/* Контент документа со скроллом */}
            <div className="p-5 sm:p-6 overflow-y-auto space-y-4">
              {activeDoc.content}
            </div>

            {/* Подвал модального окна */}
            <div className="p-4 border-t border-zinc-800 flex justify-end bg-zinc-950/40">
              <button
                type="button"
                onClick={closeModal}
                className="px-4 py-2 rounded-xl text-xs sm:text-sm font-medium bg-zinc-800 hover:bg-zinc-700 text-white transition-colors cursor-pointer"
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
