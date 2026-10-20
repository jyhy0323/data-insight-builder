const CACHE_NAME = 'datainsight-v1';
const STATIC_ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];

// 서비스 워커 설치: 정적 자산 캐싱
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[PWA] 기본 정적 자산 사전 캐싱');
      return cache.addAll(STATIC_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

// 활성화: 이전 버전 캐시 정리
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[PWA] 구버전 캐시 삭제:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 요청 중계: 네트워크 우선 (Network First)
self.addEventListener('fetch', (event) => {
  // API 및 백엔드 POST 요청은 캐시하지 않고 항상 네트워크로 통신
  if (event.request.method !== 'GET' || event.request.url.includes('/api/') || event.request.url.includes('/inspect') || event.request.url.includes('/run') || event.request.url.includes('/query') || event.request.url.includes('/explain') || event.request.url.includes('/ask')) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // 성공 시 응답 복사본을 캐시에 업데이트
        if (response && response.status === 200 && response.type === 'basic') {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseClone);
          });
        }
        return response;
      })
      .catch(() => {
        // 네트워크 실패 시 캐시된 자산 반환
        return caches.match(event.request);
      })
  );
});
