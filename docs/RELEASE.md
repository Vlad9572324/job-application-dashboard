# CI и релизы

Workflow [CI and release](../.github/workflows/ci-release.yml) запускает Python и GUI
тесты для PR, коммитов в `main` и тегов `v*`. Тег вида `v1.2.3` или
`v1.2.3-rc.1` на коммите из `main` после успешных тестов создаёт:

- `hh-clicker-linux-x64.tar.gz` — приложение для Linux x64;
- `hh-clicker-windows-x64.zip` — приложение для Windows x64;
- `SHA256SUMS.txt` — контрольные суммы архивов;
- Docker-образ `ghcr.io/vlad9572324/hh.ru-clicker:1.2.3` в GitHub Packages;
- GitHub Release с бинарными архивами. Стабильный тег обновляет также `latest`.

Предрелизный тег с суффиксом, например `v1.2.3-rc.1`, отмечается как prerelease
и не обновляет `latest`. При повторном запуске workflow архивы в существующем
релизе заменяются.

## Запуск бинарников

Распакуйте архив и запускайте `./hh-clicker` (Linux) или `hh-clicker.exe`
(Windows). Откройте `http://127.0.0.1:8000`. Приложение хранит настройки,
аккаунты и историю в папке `data/` рядом с исполняемым файлом. Для локальной
CAPTCHA-модели положите `model.pt` и `charset.txt` в `models/captcha/` рядом с ним.
Веса модели и личные данные в архивы не включены.

По умолчанию веб-интерфейс слушает только localhost. Для доступа из сети
настройте `HH_BOT_API_KEY`, `HH_BOT_HOST` и `HH_BOT_UNSAFE_EXPOSE` согласно
[руководству по безопасности](SECURITY.md).

## Запуск Docker-образа

На Linux из каталога с локальными `data/`, `models/` и `.env`:

```bash
mkdir -p data models/captcha
docker run --name hh-clicker --rm \
  --user "$(id -u):$(id -g)" \
  --env-file .env \
  -e HH_BOT_HOST=0.0.0.0 -e HH_BOT_ALLOW_CONTAINER_BIND=1 \
  -p 127.0.0.1:8000:8000 \
  -v "$PWD/data:/app/data" -v "$PWD/models:/app/models" \
  ghcr.io/vlad9572324/hh.ru-clicker:1.2.3
```

В `.env` нужен `HH_BOT_API_KEY`. Замените версию образа на нужный релиз.
Docker-образ также не содержит данные аккаунтов и веса модели.

## Публикация

После слияния и зелёного CI создайте тег на коммите из `main` и отправьте его
в GitHub. Публикация выполняется только после успешных тестов и проверок
запуска Linux и Windows бинарников. Локальное создание тега без отправки
ничего не публикует.
