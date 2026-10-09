# Гайд: RSS для Pinterest

## 1. Подготовка

Нужны Pinterest Business, подтверждённый сайт, ключи Gemini/Higgsfield и репозиторий сайта с веткой main и автоматическим деплоем. ADV запускает генератор; push этого репозитория сам по себе не создаёт сайт и не подключает Pinterest.

Сайт должен отдавать public/pins/ по адресу https://ВАШ-ДОМЕН/pins/. Для Next.js/Vite public — стандартная папка статических файлов. Для другого движка настройте её публикацию. XML и JPEG должны открываться без входа и защиты деплоя.

## 2. GitHub

LittleAtlas-dev/ADV → Settings → Secrets and variables → Actions.

Добавьте Secrets:

| Имя | Значение |
|---|---|
| GEMINI_API_KEY | Ключ Gemini |
| HF_API_KEY | Полный API-ключ из open.higgsfield.ai, вставленный как есть |
| LANDING_REPO_TOKEN | Fine-grained GitHub token с Contents Read and write только для репозитория сайта |
| TELEGRAM_BOT_TOKEN | Необязательно: бот для ошибок/ручной публикации |
| TELEGRAM_CHAT_ID | Необязательно: ID чата, нужен вместе с токеном бота |

Добавьте Variables:

| Имя | Значение |
|---|---|
| LANDING_REPO | Реальный репозиторий сайта, например LittleAtlas-dev/your-website |
| SITE_URL | https://your-domain.com — подтверждённый домен, без пути |
| PIN_COMMIT_NAME | Имя автора коммитов |
| PIN_COMMIT_EMAIL | Email GitHub-пользователя, которому разрешён деплой сайта |

Для Vercel автор должен быть связан с аккаунтом/командой проекта. Токену могут понадобиться одобрение организации и разрешение записи в защищённую main. Ключи не добавляйте в Git.

## 3. Проверка генерации

Actions → Pinterest pin → Run workflow → pin_type: strengths, dry_run: true.

Скачайте artifact pinterest-preview с pin_preview.jpg. Dry run не публикует RSS и Telegram, но вызывает реальные Gemini/Higgsfield API и может расходовать кредиты. Права записи в сайт и Pinterest этим запуском не проверяются.

## 4. Создание RSS

Запустите strengths с dry_run: false. В main репозитория сайта появятся JPEG, public/pins/pins.json и XML. Дождитесь успешного деплоя сайта. Откройте XML и изображение из enclosure без входа: должен вернуться XML/JPEG, а не HTML приложения или 404.

Чтобы создать все пять лент, выполните обычные запуски strengths, parenting, mandala, keepsake, free_atlas. Лента появляется после первого пина соответствующей доски.

| Доска | URL (замените домен) |
|---|---|
| Little Atlas Child Strengths | https://ВАШ-ДОМЕН/pins/little-atlas-child-strengths.xml |
| Little Atlas Mindful Parenting | https://ВАШ-ДОМЕН/pins/little-atlas-mindful-parenting.xml |
| Little Atlas Personal Mandalas | https://ВАШ-ДОМЕН/pins/little-atlas-personal-mandalas.xml |
| Little Atlas Family Keepsakes | https://ВАШ-ДОМЕН/pins/little-atlas-family-keepsakes.xml |
| Little Atlas Free Atlas | https://ВАШ-ДОМЕН/pins/little-atlas-free-atlas.xml |

## 5. Pinterest

На компьютере войдите в Pinterest Business. В настройках подтверждения сайта добавьте домен SITE_URL и подтвердите через HTML-тег, файл или DNS по подсказкам Pinterest. HTML-файл разместите в public сайта и дождитесь деплоя.

Settings → Create Pins in bulk → Auto-publish → Connect RSS feed → адрес существующей XML-ленты → доска в Save Pins to → Save. Повторите для остальных лент. Пункт подключения появляется после подтверждения сайта.

Pinterest поддерживает RSS 1/2, требует ссылки item на подтверждённый домен и читает картинки из enclosure/media:content. Код формирует RSS 2.0 с этими полями. Ссылки ведут на SITE_URL с UTM; атрибуцию переходов при необходимости реализует сайт.

По официальной инструкции обновления обрабатываются в течение 24 часов, старые записи публикуются первыми. Успех Actions означает обновление RSS; появление пина проверяйте на выбранной доске.

## 6. Диагностика

| Проблема | Проверка |
|---|---|
| Missing required environment variable | Имена и значения Secrets/Variables |
| Gemini/Higgsfield 401/403 или ошибка модели | Ключ, квота и доступ модели у провайдера |
| GitHub 403/404 | LANDING_REPO, права токена, одобрение организации, наличие main |
| GitHub 409/422 | Защита ветки или параллельные коммиты; проверьте и повторите |
| Коммит есть, RSS 404 | Деплой, автор коммита, публикация public/pins и маршрутизация |
| RSS cannot be fetched/parsed | Публичный URL, XML вместо HTML, отсутствие входа |
| Links not under claimed domain | SITE_URL совпадает с подтверждённым доменом, сайт Little Atlas |
| Пин только в Telegram | LANDING_REPO_TOKEN отсутствует: включён ручной резервный режим |

Расписание: ежедневно 07:40 UTC; GitHub может задерживать запуск. Работает из default branch. Без LANDING_REPO_TOKEN для ручной публикации нужны оба Telegram Secret.

Хранятся 60 последних пинов суммарно по доскам; старые картинки удаляются с сайта. Для бессрочных ссылок измените политику хранения до запуска.

Остановить генерацию: Actions → Pinterest pin → Disable workflow. Уже добавленные записи Pinterest может дочитать; для полной остановки отключите также RSS в Pinterest.

Официальные источники (проверены 9 октября 2026): [Pinterest RSS](https://help.pinterest.com/en/business/article/auto-publish-pins-from-your-rss-feed), [подтверждение сайта](https://help.pinterest.com/en/business/article/claim-your-website).

## Переход с Kie на Higgsfield

В GitHub добавьте Secret HF_API_KEY: полный ключ, скопированный из [Higgsfield API keys](https://open.higgsfield.ai/api-keys). Не добавляйте префикс Key в значение. KIE_API_KEY больше не используется активной автоматизацией и может быть удалён из Secrets.

Изображения создаёт Soul Standard (higgsfield-ai/soul/standard), 1080p, 2:3, одна картинка на запуск; итоговый JPEG остаётся 1000×1500. Gemini продолжает писать текст. Для API нужен доступ и баланс API-аккаунта; подключение плагина Higgsfield в чате не передаёт авторизацию в GitHub Actions.

При сетевой ошибке отправки генератор не повторяет запрос автоматически, чтобы не создать платный дубль. При таймауте ожидания запрос может продолжить работу на стороне Higgsfield: проверьте историю запросов перед повторным запуском. Ошибки и ID запроса видны в Actions, уведомления Telegram работают как раньше.

Проверка после добавления ключа: Actions → Pinterest pin → Run workflow → dry_run: true. Этот режим расходует реальные API-кредиты, но не обновляет RSS. Затем запустите dry_run: false для публикации.

Документация: [API quick start](https://open.higgsfield.ai/quick-start), [Soul Standard](https://open.higgsfield.ai/models/higgsfield-ai/soul/standard/api-reference).

## Контент Little Atlas

Темы ручного запуска: strengths, parenting, mandala, keepsake, free_atlas. Старые темы Face Slimmer больше не поддерживаются. Пины пишутся на английском, изображения создаются Higgsfield, тексты — Gemini. В оформлении используется Little Atlas.

SITE_URL задайте как адрес подтверждённого сайта Little Atlas, например https://little-atlas.com; LANDING_REPO — репозиторий, который публикует файлы на этом сайте. Изменение переменной само по себе не настраивает публикацию /pins/ на сервере.

В Pinterest создайте пять тематических досок и подключите новые ленты из таблицы. Если раньше подключались старые ленты Face Slimmer, отключите их отдельно: переименование тем в ADV не удаляет старые RSS и опубликованные пины с сайта или Pinterest.

Free Atlas описывается как символический профиль ребёнка, а Premium — как художественные возрастные карточки и расширенный PDF. Не обещаем психологическую диагностику, научную достоверность или предсказание внешности, судьбы и профессии. Не используем реальные детские фото и данные клиентов для рекламных иллюстраций. Продуктовые факты сверены с локальным LITTLE_ATLAS_HANDOFF_CLAUDE.md от 9 октября 2026; никаких цен в промптах нет.
