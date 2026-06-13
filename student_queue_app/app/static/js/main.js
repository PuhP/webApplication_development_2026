(function () {
  // ── Mobile nav toggle ────────────────────────────────────────────────────
  const navToggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.nav');
  if (navToggle && nav) {
    navToggle.addEventListener('click', () => nav.classList.toggle('open'));
  }

  // ── Set minimum date/time on all datetime-local inputs to "now" ──────────
  const dtInputs = document.querySelectorAll('input[type="datetime-local"]');
  if (dtInputs.length) {
    const now = new Date();
    now.setSeconds(0);
    now.setMilliseconds(0);
    // Convert to local ISO string (YYYY-MM-DDTHH:MM) without timezone offset
    const pad = n => String(n).padStart(2, '0');
    const localIso = now.getFullYear() + '-' +
      pad(now.getMonth() + 1) + '-' +
      pad(now.getDate()) + 'T' +
      pad(now.getHours()) + ':' +
      pad(now.getMinutes());
    dtInputs.forEach(function (input) {
      input.min = localIso;
      // Client-side guard: warn if user picks a past time
      input.addEventListener('change', function () {
        const picked = new Date(this.value);
        if (picked < new Date()) {
          this.setCustomValidity('Дата и время не могут быть в прошлом.');
        } else {
          this.setCustomValidity('');
        }
      });
    });
  }

  // ── Number field bounds guard (HTML5 validity message in Russian) ─────────
  document.querySelectorAll('input[type="number"]').forEach(function (input) {
    input.addEventListener('input', function () {
      const val = parseInt(this.value, 10);
      const min = parseInt(this.min, 10);
      const max = parseInt(this.max, 10);
      if (!isNaN(min) && val < min) {
        this.setCustomValidity('Минимальное значение: ' + min + '.');
      } else if (!isNaN(max) && val > max) {
        this.setCustomValidity('Максимальное значение: ' + max + '.');
      } else {
        this.setCustomValidity('');
      }
    });
  });

  // ── WebSocket / queue table refresh ─────────────────────────────────────
  const queueTable = document.querySelector('#queue-table[data-session-id]');
  if (!queueTable) return;

  const sessionId = queueTable.dataset.sessionId;
  const liveIndicator = document.querySelector('[data-live-indicator]');
  let lastRefresh = 0;

  function setLive(text, className) {
    if (!liveIndicator) return;
    liveIndicator.textContent = text;
    liveIndicator.classList.remove('online', 'offline');
    if (className) liveIndicator.classList.add(className);
  }

  async function refreshQueueTable(force) {
    const now = Date.now();
    if (!force && now - lastRefresh < 900) return;
    lastRefresh = now;
    try {
      const response = await fetch(`/api/sessions/${sessionId}/table`, { headers: { 'X-Requested-With': 'fetch' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      queueTable.innerHTML = await response.text();
      setLive('Обновлено', 'online');
    } catch (error) {
      console.warn('Queue table refresh failed:', error);
      setLive('Нет соединения, будет повтор', 'offline');
    }
  }

  function connectSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/session/${sessionId}`);

    socket.addEventListener('open', () => setLive('Онлайн', 'online'));
    socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'snapshot') refreshQueueTable(true);
      } catch (_error) {
        refreshQueueTable(true);
      }
    });
    socket.addEventListener('close', () => {
      setLive('Переподключение...', 'offline');
      window.setTimeout(connectSocket, 3000);
    });
    socket.addEventListener('error', () => {
      setLive('Ошибка WebSocket', 'offline');
      socket.close();
    });
  }

  connectSocket();
  window.setInterval(() => refreshQueueTable(false), 8000);
})();
