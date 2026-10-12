# CI и релизы

Актуальный выпуск — [v1.0.2](https://github.com/Vlad9572324/hh.ru-clicker/releases/tag/v1.0.2).
Его [запуск CI](https://github.com/Vlad9572324/hh.ru-clicker/actions/runs/38183388182)
успешно завершил тесты и проверки запуска обоих бинарников.

Workflow [CI and release](../.github/workflows/ci-release.yml) запускает Python и GUI
тесты для PR, коммитов в `main` и тегов `v*`. Тег вида `vX.Y.Z` или
`vX.Y.Z-rc.1` на коммите из `main` после успешных тестов создаёт:

- [hh-clicker-linux-x64.tar.gz](https://github.com/Vlad9572324/hh.ru-clicker/releases/download/v1.0.2/hh-clicker-linux-x64.tar.gz) — Linux x64;
- [hh-clicker-windows-x64.zip](https://github.com/Vlad9572324/hh.ru-clicker/releases/download/v1.0.2/hh-clicker-windows-x64.zip) — Windows x64;
- [SHA256SUMS.txt](https://github.com/Vlad9572324/hh.ru-clicker/releases/download/v1.0.2/SHA256SUMS.txt) — контрольные суммы архивов;
- [Docker-образ](https://github.com/Vlad9572324/hh.ru-clicker/pkgs/container/hh.ru-clicker) `ghcr.io/vlad9572324/hh.ru-clicker:1.0.2` в GitHub Packages.

Архивы и контрольные суммы прикладываются к GitHub Release. Стабильный тег
обновляет также Docker-тег `latest`.

Предрелизный тег с суффиксом, например `v1.0.3-rc.1`, отмечается как prerelease
и не обновляет `latest`. При повторном запуске workflow архивы в существующем
релизе заменяются.

## Запуск бинарников

Скачайте архив для своей системы и `SHA256SUMS.txt` из одного релиза. В Linux
проверьте свой архив командой
`grep ' hh-clicker-linux-x64.tar.gz$' SHA256SUMS.txt | sha256sum -c -`.
В Windows сверьте значение
`Get-FileHash .\hh-clicker-windows-x64.zip -Algorithm SHA256` со
строкой для Windows архива в `SHA256SUMS.txt`.

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
  ghcr.io/vlad9572324/hh.ru-clicker:1.0.2
```

В `.env` нужен `HH_BOT_API_KEY`. Контейнер доступен только с хоста через
`127.0.0.1:8000`; внутри он слушает `0.0.0.0` для Docker DNAT. Замените
версию образа на нужный релиз.
Docker-образ также не содержит данные аккаунтов и веса модели.

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
[GitHub Actions](https://github.com/Vlad9572324/hh.ru-clicker/actions/workflows/ci-release.yml);
локальное создание тега без отправки ничего не публикует.
