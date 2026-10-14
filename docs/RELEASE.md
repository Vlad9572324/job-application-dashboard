# CI и релизы

Актуальный выпуск доступен на [странице релизов](https://github.com/Vlad9572324/job-application-dashboard/releases/latest).

Workflow [CI and release](../.github/workflows/ci-release.yml) запускает Python и GUI
тесты для PR, коммитов в `main` и тегов `v*`. Тег вида `vX.Y.Z` или
`vX.Y.Z-rc.1` на коммите из `main` после успешных тестов создаёт:

- [job-application-dashboard-linux-x64.tar.gz](https://github.com/Vlad9572324/job-application-dashboard/releases/latest/download/job-application-dashboard-linux-x64.tar.gz) — Linux x64;
- [job-application-dashboard-windows-x64.zip](https://github.com/Vlad9572324/job-application-dashboard/releases/latest/download/job-application-dashboard-windows-x64.zip) — Windows x64;
- [SHA256SUMS.txt](https://github.com/Vlad9572324/job-application-dashboard/releases/latest/download/SHA256SUMS.txt) — контрольные суммы архивов;

Архивы и контрольные суммы прикладываются к GitHub Release. GHCR-образ
публикуется только при закрытом репозитории; публичные пакеты удалены.

Предрелизный тег с суффиксом, например `v1.0.3-rc.1`, отмечается как prerelease
и не обновляет `latest`. При повторном запуске workflow архивы в существующем
релизе заменяются.

## Запуск бинарников

Скачайте архив для своей системы и `SHA256SUMS.txt` из одного релиза. В Linux
проверьте свой архив командой
`grep ' job-application-dashboard-linux-x64.tar.gz$' SHA256SUMS.txt | sha256sum -c -`.
В Windows сверьте значение
`Get-FileHash .\job-application-dashboard-windows-x64.zip -Algorithm SHA256` со
строкой для Windows архива в `SHA256SUMS.txt`.

Распакуйте архив и запускайте `./job-application-dashboard` (Linux) или `job-application-dashboard.exe`
(Windows). Откройте `http://127.0.0.1:8000`. Приложение хранит настройки,
аккаунты и историю в папке `data/` рядом с исполняемым файлом.
Основная CAPTCHA-модель (`models/captcha/model.pt` и `charset.txt`) уже входит
в архив. Дополнительные модели можно загрузить через интерфейс.
Личные данные в архивы не включены.

По умолчанию веб-интерфейс слушает только localhost. Для доступа из сети
настройте `HH_BOT_API_KEY`, `HH_BOT_HOST` и `HH_BOT_UNSAFE_EXPOSE` согласно
[руководству по безопасности](SECURITY.md).

## Запуск Docker-образа

На Linux из корня проекта с локальными `data/` и `.env`:

```bash
docker build -t job-application-dashboard:local .
mkdir -p data
docker run --name job-application-dashboard --rm \
  --user "$(id -u):$(id -g)" \
  --env-file .env \
  -e HH_BOT_HOST=0.0.0.0 -e HH_BOT_ALLOW_CONTAINER_BIND=1 \
  -p 127.0.0.1:8000:8000 \
  -v "$PWD/data:/app/data" \
  job-application-dashboard:local
```

В `.env` нужен `HH_BOT_API_KEY`. Контейнер доступен только с хоста через
`127.0.0.1:8000`; внутри он слушает `0.0.0.0` для Docker DNAT. Замените
тег локального образа при необходимости.
Docker-образ содержит основную CAPTCHA-модель, но не данные аккаунтов.
Если нужны дополнительные загружаемые модели, подключите папку `models/`
с правом записи и сохраните в ней основную модель до монтирования: bind mount
скрывает файлы, встроенные в образ.

## Публикация

После слияния и зелёного CI создайте тег на коммите из `main` и отправьте его
в GitHub:

```bash
git checkout main
git pull --ff-only
git tag -a vX.Y.Z -m 'Release vX.Y.Z'
git push origin vX.Y.Z
```

Замените `X.Y.Z` на новую версию. Публикация выполняется только после успешных
тестов и проверок запуска Linux и Windows бинарников. Проверяйте статус в
[GitHub Actions](https://github.com/Vlad9572324/job-application-dashboard/actions/workflows/ci-release.yml);
локальное создание тега без отправки ничего не публикует.
