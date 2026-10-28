# Проверка Docker на Windows 11

Фактический запуск здесь не выполнен: команда Docker отсутствует.

Установите и запустите Docker Desktop с WSL 2 и Linux containers. Остановите прямой сервер на порту 8080. Откройте PowerShell в корне проекта:

```powershell
docker version
docker compose version
docker info
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build
```

В другом PowerShell:

```powershell
Invoke-RestMethod http://localhost:8080/health
Start-Process http://localhost:8080/
docker compose ps
docker compose logs --tail 100 app db
docker compose exec db pg_isready -U oplan -d oplan
```

Ожидается status=ok, healthy у обоих сервисов и каталог без ручного сидирования. Проверьте поиск, изменение дат, выбор и демозаказ. Выполните `docker compose restart app`, обновите страницу и проверьте восстановление сессии.

Отдельно проверьте пустой LLM_API_KEY и заполненный ключ в локальном .env. После изменения окружения пересоздайте контейнер обычным `docker compose up --build`. Не публикуйте .env и развёрнутую конфигурацию Compose: в ней подставляется ключ. Для проверки PostgreSQL не задавайте SQLite DB_URL. Порт остаётся 8080:8080.
