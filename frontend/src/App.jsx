import React, { useState, useEffect, useCallback } from 'react';
import WebApp from '@twa-dev/sdk';
import { api, ApiError } from './api/client';
import Onboarding from './screens/Onboarding';
import Home from './screens/Home';
import Session from './screens/Session';
import PaywallStub from './components/PaywallStub';
import LandingPage from './screens/LandingPage';
import { Sparkles, AlertCircle, RefreshCw } from 'lucide-react';

export default function App() {
  const [currentScreen, setCurrentScreen] = useState('loading'); // 'loading' | 'onboarding' | 'home' | 'session' | 'paywall'
  const [meData, setMeData] = useState(null);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [initError, setInitError] = useState(null);

  // Инициализация Telegram WebApp и синхронизация темы
  useEffect(() => {
    let themeHandler;
    try {
      if (WebApp) {
        WebApp.ready();
        WebApp.expand();

        // Синхронизация темы (светлая/тёмная)
        const isDark = WebApp.colorScheme === 'dark';
        if (isDark) {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }

        // Подписка на смену темы в Telegram
        themeHandler = () => {
          if (WebApp.colorScheme === 'dark') {
            document.documentElement.classList.add('dark');
          } else {
            document.documentElement.classList.remove('dark');
          }
        };
        WebApp.onEvent('themeChanged', themeHandler);
      }
    } catch (e) {
      console.warn('WebApp initialization error:', e);
    }
    return () => {
      if (themeHandler) WebApp.offEvent('themeChanged', themeHandler);
    };
  }, []);

  // Загрузка профиля пользователя и пары
  const loadProfile = useCallback(async () => {
    setInitError(null);
    try {
      const data = await api.getMe();
      setMeData(data);

      // Server is authoritative: the local cache can outlive a deleted/recreated user profile.
      const hasAcceptedLegal = Boolean(data.user?.accepted_legal_at);

      if (!hasAcceptedLegal) {
        setCurrentScreen('onboarding');
      } else {
        // Если уже есть активная сессия в статусе waiting или analyzing — остаемся на главной с бейджем,
        // либо пользователь может продолжить по кнопке
        setCurrentScreen('home');
      }
    } catch (err) {
      console.error('Failed to load user profile:', err);
      setInitError(err);
      setCurrentScreen('error');
    }
  }, []);

  const isInsideTelegram = Boolean(
    typeof window !== 'undefined' &&
    ((window.Telegram?.WebApp?.initData && window.Telegram.WebApp.initData.length > 0) ||
     window.__DEV_INIT_DATA__)
  );

  useEffect(() => {
    if (!isInsideTelegram) return;
    loadProfile();
  }, [loadProfile, isInsideTelegram]);

  // Если приложение открыто в обычном браузере вне Telegram — отображаем публичный лендинг
  if (!isInsideTelegram) {
    return <LandingPage />;
  }

  // Экран загрузки
  if (currentScreen === 'loading') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-slate-50/50 dark:bg-zinc-950 text-center animate-fade-in">
        <div className="w-12 h-12 rounded-2xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 flex items-center justify-center animate-pulse mb-3 shadow-sm">
          <Sparkles size={24} />
        </div>
        <div className="text-base font-bold text-slate-900 dark:text-slate-100">
          Буфер Ссор
        </div>
        <div className="text-xs text-slate-400 mt-1">
          Подключение к защищённому каналу...
        </div>
      </div>
    );
  }

  // Экран ошибки инициализации
  if (currentScreen === 'error') {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-slate-50/50 dark:bg-zinc-950 text-center animate-fade-in">
        <div className="w-12 h-12 rounded-2xl bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 flex items-center justify-center mb-3">
          <AlertCircle size={24} />
        </div>
        <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Не удалось загрузить приложение
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xs leading-relaxed">
          {initError?.message || 'Пожалуйста, откройте приложение заново через Telegram-бота @BufferSsorBot'}
        </div>
        <button
          onClick={loadProfile}
          className="mt-4 inline-flex items-center gap-1.5 py-2 px-4 bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 rounded-xl text-xs font-medium hover:opacity-90 transition-opacity"
        >
          <RefreshCw size={13} />
          <span>Попробовать снова</span>
        </button>
      </div>
    );
  }

  const handleLegalAccepted = async (legalRes) => {
    // Мгновенно обновляем стейт и переключаем экран на главную страницу
    setMeData((prev) => ({
      ...prev,
      user: {
        ...(prev?.user || {}),
        accepted_legal_at: legalRes?.accepted_legal_at || new Date().toISOString(),
      },
    }));
    setCurrentScreen('home');
    try {
      await loadProfile();
    } catch (err) {
      console.warn('Silent refresh after legal accept failed:', err);
    }
  };

  // ЭКРАН 1: Онбординг и согласие
  if (currentScreen === 'onboarding') {
    return (
      <Onboarding
        initialCouple={meData?.couple}
        onAccepted={handleLegalAccepted}
      />
    );
  }

  // ЭКРАН ЗАГЛУШКИ ОПЛАТЫ / ПЕЙВОЛЛ
  if (currentScreen === 'paywall') {
    return (
      <PaywallStub
        onBack={() => {
          setCurrentScreen('home');
          loadProfile();
        }}
      />
    );
  }

  // ЭКРАН 3: Разбор конфликта
  if (currentScreen === 'session' && activeSessionId) {
    return (
      <Session
        sessionId={activeSessionId}
        onBack={() => {
          setCurrentScreen('home');
          loadProfile();
        }}
      />
    );
  }

  // ЭКРАН 2: Главный экран
  return (
    <Home
      meData={meData}
      onStartSession={(sessionId) => {
        setActiveSessionId(sessionId);
        setCurrentScreen('session');
      }}
      onOpenActiveSession={(sessionId) => {
        setActiveSessionId(sessionId);
        setCurrentScreen('session');
      }}
      onRefreshProfile={loadProfile}
      onPaywallRequired={() => {
        setCurrentScreen('paywall');
      }}
    />
  );
}
