import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import LandingPage from './screens/LandingPage.jsx';
import './index.css';

// Устанавливаем Telegram-тему до первого React-рендера, чтобы не было вспышки светлой темы.
if (typeof document !== 'undefined') {
  document.documentElement.classList.toggle(
    'dark',
    window.Telegram?.WebApp?.colorScheme === 'dark',
  );
}

// Проверка наличия Telegram WebApp initData для определения окружения
const isInsideTelegram = Boolean(
  typeof window !== 'undefined' &&
  ((window.Telegram?.WebApp?.initData && window.Telegram.WebApp.initData.length > 0) ||
   window.__DEV_INIT_DATA__)
);

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isInsideTelegram ? <App /> : <LandingPage />}
  </React.StrictMode>,
);
