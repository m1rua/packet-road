# Мониторинг и эксплуатация

## Метрики и графики

Prometheus опрашивает `/metrics` раз в 15 секунд. Labels ограничены фиксированными outcome и именами этапов, цель не используется как label. Grafana получает datasource с постоянным UID `prometheus` и dashboard из provisioning: ручная настройка через UI не требуется.

| График | Что показывает и как читать |
| --- | --- |
| Диагностики / сек | `rate(packet_road_diagnostics_total[5m])` по outcome. `ok` — все этапы выполнились; `partial` — ошибки отдельных измерений; `rejected` — адрес после DNS запрещён политикой; `error` — неожиданное исключение. Предварительные 401/403/429 в этот счётчик не входят. |
| Ошибки этапов / сек | `rate(packet_road_stage_errors_total[5m])` по dns/route/traceroute/tcp/tls/http. Это ошибки измерений; причины могут быть у цели, в окружении или в утилитах. |
| Длительность p95 | `histogram_quantile(0.95, ...)`: оценка времени, быстрее которого завершились 95% диагностик за последние 5 минут. Оценка из histogram buckets, не точный percentile; при отсутствии запросов возможен NaN. |
| Память процесса RSS | Физическая память процесса API в байтах; не memory usage всего pod и не лимит cgroup. Сравнивайте с установленным memory limit, учитывая дополнительные процессы traceroute. |
| CPU процесса, ядра | `rate(process_cpu_seconds_total[5m])`: 1 означает одно полностью занятое CPU ядро. Не включает дочерние утилиты и другие контейнеры. |
| Доступность scrape | `up`: 1 — Prometheus успешно получил метрики, 0 — нет. Это не доступность диагностируемого сайта. |

До первого запроса часть series отсутствует. Для осмысленного rate нужно несколько scrape, обычно подождать 1–5 минут. Никаких сгенерированных измерений или демонстрационных данных dashboard не содержит. HTTP 404/503 цели отображается в результате, но не увеличивает stage_errors: механизм измерения получил настоящий статус.

Prometheus также экспортирует собственные метрики. В Compose работают именованные volumes, в Kubernetes PVC. Лимит retention Prometheus предотвращает бесконечный рост, но не заменяет наблюдение за свободным диском. Пароль Grafana из переменной окружения обычно применяется при первом создании пользователя; изменение Secret не обязательно сменит пароль в уже существующей базе Grafana — используйте штатный механизм сброса.

## Диагностика проблем

| Симптом | Проверка и действие |
| --- | --- |
| API не стартует | Проверить наличие Secret/env, длину токена 32+, логи `docker compose logs app` или `kubectl logs -n packet-road deploy/packet-road`. |
| API 401 | Нужен `Authorization: Bearer ...`; не вставлять token в query string и не печатать его в CI-лог. |
| API 403 | Сверить точный allowlist, порт 80/443 и DNS A/AAAA. Любой запрещённый IP в ответе блокирует всю цель. |
| API 429 | Уже выполняются две диагностики или исчерпаны 10 запусков/минуту на процесс. Дождаться освобождения, не добавлять workers для обхода лимита. |
| DNS error | Проверить `/etc/resolv.conf`, доступ resolver UDP/TCP 53, NetworkPolicy/egress. Доступ через HTTP proxy не доказывает работоспособность прямого DNS. |
| `FileNotFoundError` route/traceroute | Установить iproute2/traceroute на Linux или использовать образ проекта. |
| Нет gateway/MAC | Возможны on-link маршрут, point-to-point, пустой cache; это допустимый частичный набор сведений. |
| Traceroute `*`, timeout | Возможны ICMP filtering/rate limit, отсутствие IPv6-маршрута или слишком короткое ожидание. Сопоставить с TCP результатом; не считать скрытые hops восстановленными. |
| TLS verification error | Проверить имя, срок и цепочку сертификата, время ОС, доверенный CA, TLS interception. Не отключать верификацию. |
| HTTP error при успешном TLS | Сервер может не поддерживать HEAD/HTTP1.1, долго отдавать headers или разрывать соединение. TLS-результат остаётся доступен. |
| `ImagePullBackOff` | Сверить полный SHA/digest, видимость GHCR package, imagePullSecret и доступ registry. |
| `Pending` PVC | Проверить StorageClass, provisioner и свободное место на узле. Local-path не является распределённым storage. |
| `CrashLoopBackOff` | Смотреть `kubectl describe pod` и `logs --previous`; проверить token, securityContext, memory limit. Не добавлять privileged как способ устранения ошибки. |
| Grafana No data | Prometheus Targets должен быть UP; проверить DNS имени Service, namespace monitoring, NetworkPolicy, UID datasource и наличие реальных диагностик. |
| Rollout timeout | `kubectl describe deployment`, `get pods`, Events, logs; предыдущий работающий pod может продолжать обслуживать запросы. Выполнить явный rollback по инструкции после определения причины. |

## Обновления и восстановление

Обновляйте Python/base images/k3s и pinned зависимости отдельными проверяемыми изменениями. Храните backup данных Grafana, Prometheus при необходимости истории, k3s datastore и server token в защищённом месте. Перед восстановлением на другом узле проверяйте соответствие версии и прав доступа.

Проверки syntax/render не доказывают успешный rollout, применение NetworkPolicy или сохранность PVC. Эти свойства проверяются только на выбранном Kubernetes-стенде. Команды реального apply в документации не означают, что они были выполнены в этом сеансе.
