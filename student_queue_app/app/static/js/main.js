(function () {
  const navToggle = document.querySelector('.nav-toggle');
  const nav = document.querySelector('.nav');
  if (navToggle && nav) {
    navToggle.addEventListener('click', () => nav.classList.toggle('open'));
  }

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
