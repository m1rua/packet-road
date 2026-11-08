# Журнал реализации

## Исходное состояние

Проверены удалённые ветки: доступна только `main`, исходный HEAD `70e429b`. README состоял из одной строки. `get_info.py` требовал root, использовал Scapy/getmac/dnspython, выбирал маршрут к 8.8.8.8, отправлял запрос root DNS без обработки referral и отдельно запрашивал IP для TCP SYN traceroute. `.github/workflows/ci.yml` только устанавливал неприкреплённые зависимости на push main. Изменения выполняются в отдельной ветке `feat/packet-road-service`; main не переписывается.

## Этап 1: приложение

- Добавлен пакет `src/packet_road` с общим ядром, argparse CLI и FastAPI API. Старый entry point делегирует CLI.
- DNS, маршрут/neighbor cache, UDP traceroute, TCP, TLS и HTTP имеют отдельные результаты и ошибки. HTTP не стирает ранее измеренный TLS при сбое.
- Ввод — домен либо IP, отдельный порт, ограничение hops. Resolver и сетевые операции имеют таймауты, subprocess без shell.
- API требует токен и точный allowlist, блокирует непубличные адреса во всём DNS-ответе, закрепляет адрес для connect, не следует redirects; лимит 2 одновременно и 10/минуту на процесс.
- Метрики: диагностики по результату, ошибки этапов, полная длительность, стандартные метрики процесса Python.
- Образовательный компромисс: UDP traceroute вместо Scapy TCP SYN ради работы без raw capabilities. Отличия и наблюдательная точка подробно описаны в network.md.

Путь запроса: проверка токена → нормализация/allowlist → admission/rate limit → DNS → проверка всех IP → выбор одного → независимые измерения → JSON + метрики. Ошибки DNS прекращают сетевые этапы; сбой route/traceroute не мешает TCP/TLS/HTTP.

## Этап 2: контейнер и Kubernetes

- Dockerfile с сетевыми утилитами и UID 10001, один uvicorn worker. Compose: read-only, cap-drop ALL, no-new-privileges, loopback port, CPU/memory/PID limits.
- Kubernetes Deployment/Service/ConfigMap, внешний Secret reference, три вида probes, resources, restricted securityContext, отключённый service account token, ingress NetworkPolicy.
- Namespace создаётся отдельным административным bootstrap шагом: pipeline не нужны cluster-scoped права на него.
- Probes проверяют процесс/конфигурацию, а не чужой сайт, поэтому внешние сетевые сбои не создают restart loop.

## Этап 3: доставка и инфраструктура

- GitHub Actions проверяет код и конфигурации, собирает образ и проверяет его без root/capabilities. После main публикует full SHA tag в GHCR; deploy использует digest.
- Deployment только после явного включения `DEPLOY_ENABLED`, через environment `staging` и внешний `KUBE_CONFIG`. Rollout имеет timeout, rollback документирован; автоматического merge нет.
- Terraform ограничен provider-neutral контрактом и inventory output. Реальное создание инфраструктуры отложено до выбора провайдера; это существенная незавершённая зависимость, а не работающий provisioning.
- Ansible подготавливает один k3s сервер через checksum-verified binary и systemd, использует закреплённые v1.37.2+k3s1 и официальный SHA256, требует подходящей ОС. Не выполнялся против сервера пользователя.

## Этап 4: наблюдаемость и документация

- Compose и Kubernetes Prometheus/Grafana с постоянным хранением и автоматическим provisioning datasource/dashboard.
- Графики показывают реальные series; CPU/RSS относятся к API процессу, не ко всем ресурсам кластера.
- Добавлены инструкции запуска, deploy, CI secrets/права, откат, модель безопасности и таблица проблем.

## Проверки

Итоговый набор ограничен **10 автоматическими сценариями**: 9 pytest без параметризации и одна container smoke-проверка в CI. Проверки синтаксиса, lint, сборки и рендера конфигурации идут отдельно. Фактические результаты и ограничения текущей среды приведены в `validation.md`.

## Что объяснять на собеседовании

1. Почему root для сетевой диагностики избыточен; чем UDP traceroute отличается от TCP SYN и зачем TTL/ICMP Time Exceeded.
2. Почему контейнер видит свой gateway, а не gateway посетителя; почему нельзя увидеть MAC через Интернет или вывести NAT по частному IP.
3. Чем referral root DNS отличается от результата рекурсивного resolver; зачем A/AAAA и фиксация IP после проверки.
4. SSRF/DNS rebinding: allowlist, проверка всех адресов, отказ от redirects, отсутствие повторного DNS в connect; где нужны сетевые ограничения.
5. Почему TCP/TLS/HTTP соединения независимы и их тайминги не составляют waterfall одного запроса.
6. Для чего разные Kubernetes probes, requests/limits, capabilities, read-only filesystem и service account token.
7. Разница Terraform provisioning и Ansible configuration; почему текущий Terraform не создаёт VM и какие параметры ещё нужны.
8. Почему образ идентифицируется commit SHA и digest, как pipeline проверяет rollout и что именно откатывает rollout undo.
9. Counter/Histogram, rate и p95, cardinality; почему ошибки измерений не равны поломке сервиса.
10. Ограничения одной VM/k3s/local-path, секретов, лимита на процесс и отсутствия реального rollout в локальных проверках.
