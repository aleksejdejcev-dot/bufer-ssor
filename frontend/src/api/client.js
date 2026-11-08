/**
 * Единый API-клиент «Буфер Ссор» для взаимодействия с бэкендом.
 * 
 * ПРАВИЛА БЕЗОПАСНОСТИ:
 * 1. Никаких токенов или чувствительных данных в localStorage.
 * 2. Каждый запрос передает заголовок Authorization: tma <initData>.
 * 3. Единая обработка статусов и ошибок (401, 403, 429).
 */

import WebApp from '@twa-dev/sdk';

const BASE_URL = import.meta.env.VITE_API_URL || '';

export class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

let devInitDataCache = null;

/**
 * Получение строки initData из Telegram WebApp SDK.
 * Если приложение запущено в обычном браузере для отладки, запрашивает
 * валидный подписанный dev-токен с локального сервера.
 */
export async function getInitData() {
  try {
    if (WebApp && WebApp.initData) {
      return WebApp.initData;
    }
  } catch (e) {
    console.warn('Failed to read WebApp.initData:', e);
  }

  // Для локальной разработки initData может передаваться через window.__DEV_INIT_DATA__
  if (typeof window !== 'undefined' && window.__DEV_INIT_DATA__) {
    return window.__DEV_INIT_DATA__;
  }

  return '';
}

/**
 * Базовый метод отправки HTTP-запросов с валидацией и авторизацией Telegram
 */
async function request(endpoint, options = {}) {
  const initData = await getInitData();

  const headers = {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
    ...(options.headers || {}),
  };

  if (initData) {
    headers['Authorization'] = `tma ${initData}`;
    headers['X-Telegram-Init-Data'] = initData;
  }

  const url = `${BASE_URL}${endpoint}`;

  let response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (networkError) {
    throw new ApiError(0, 'Ошибка сети. Проверьте интернет-соединение.');
  }

  // Обработка 204 No Content
  if (response.status === 204) {
    return null;
  }

  let data = null;
  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  } else {
    try {
      const text = await response.text();
      data = text ? { detail: text } : null;
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const errorMsg = data?.detail || data?.message || `Ошибка сервера (${response.status})`;
    throw new ApiError(response.status, errorMsg, data);
  }

  return data;
}

export const api = {
  /**
   * Получить профиль пользователя, статус пары и активную сессию
   */
  async getMe() {
    return request('/me', { method: 'GET' });
  },

  /**
   * Зафиксировать согласие с условиями 18+ и политиками
   */
  async acceptLegal(confirm18Plus = true, acceptTerms = true) {
    return request('/legal/accept', {
      method: 'POST',
      body: JSON.stringify({
        confirm_18_plus: confirm18Plus,
        accept_terms: acceptTerms,
      }),
    });
  },

  /**
   * Создать или получить ссылку-приглашение для второго партнера
   */
  async createInvite() {
    return request('/couple/invite', { method: 'POST' });
  },

  async joinCouple(inviteCode) {
    return request('/couple/join', {
      method: 'POST',
      body: JSON.stringify({ invite_code: inviteCode }),
    });
  },

  async startRelationshipBalance() {
    return request('/relationship-balance/start', { method: 'POST' });
  },

  async getRelationshipBalance(sessionId) {
    return request(`/relationship-balance/${sessionId}`, { method: 'GET' });
  },

  async submitRelationshipBalance(sessionId, answers) {
    return request(`/relationship-balance/${sessionId}/answer`, {
      method: 'POST',
      body: JSON.stringify({ answers }),
    });
  },

  async finishRelationshipBalance(sessionId) {
    return request(`/relationship-balance/${sessionId}/finish`, { method: 'POST' });
  },

  /**
   * Удаляет пару, профили и данные разборов; финансовые записи и личная подписка плательщика сохраняются отдельно.
   */
  async deleteCouple() {
    return request('/couple', { method: 'DELETE' });
  },

  /**
   * Удаление только истории сессий и разборов пары (связка и профили остаются)
   */
  async deleteHistory() {
    return request('/history', { method: 'DELETE' });
  },

  /**
   * Начать новую сессию разбора конфликта
   */
  async startConflict() {
    return request('/conflict/start', { method: 'POST' });
  },

  /**
   * Получить статус и результаты сессии
   */
  async getConflict(sessionId) {
    return request(`/conflict/${sessionId}`, { method: 'GET' });
  },

  async confirmConflictFinished(sessionId) {
    return request(`/conflict/${sessionId}/finish`, { method: 'POST' });
  },

  /**
   * Обновить оценку погоды в отношениях (1-10)
   */
  async updateMood(mood) {
    return request('/mood', {
      method: 'POST',
      body: JSON.stringify({ mood: Number(mood) }),
    });
  },

  /**
   * Отправить сигнал перемирия «Белый флаг»
   */
  async sendWhiteFlag() {
    return request('/signal/white-flag', { method: 'POST' });
  },

  /**
   * Отправить деликатный намек (hug, silence, talk_evening, support)
   */
  async sendHint(hintType) {
    return request('/signal/hint', {
      method: 'POST',
      body: JSON.stringify({ hint_type: hintType }),
    });
  },

  /**
   * Создать платежную сессию в ЮKassa для оформления подписки
   */
  async createPayment(plan = 'month_sub') {
    return request('/payment/create', {
      method: 'POST',
      body: JSON.stringify({ plan }),
    });
  },
};
