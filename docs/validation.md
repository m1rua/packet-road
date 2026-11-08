# Фактические проверки — 8 ноября 2026

Проверки проведены в Linux cloud workspace, в отдельной ветке от `main@70e429b`. Удалённый сервер пользователя не изменялся. Реальный GitHub Actions run после открытия PR проверяется отдельно; приведённые ниже результаты получены локально, а не выданы за выполненный CI/CD.

| Проверка | Результат |
| --- | --- |
| Ruff | Успех, `All checks passed` |
| pytest | **9 passed**, без параметризации. Вместе с контейнерной smoke-проверкой итоговый автоматический набор содержит 10 сценариев. |
| YAML/JSON | Все файлы разбираются `scripts/check_configs.py` |
| Workflow actionlint 1.7.7 | Успех; shellcheck отдельно не запускался |
| Terraform 1.11.4 | fmt -check, init -backend=false, validate успешны; providers/resources отсутствуют по проектному ограничению |
| Ansible core 2.18.5 | syntax-check успешен. Потребовалось перенести ANSIBLE_HOME/LOCAL_TEMP в workspace из-за read-only home этой среды. Playbook не выполнялся на сервере. |
| kubectl 1.37.2 kustomize | Успешный рендер приложения и мониторинга |
| kubeconform 0.6.7 | 18 ресурсов: приложение, мониторинг, bootstrap namespace и CI RBAC. 18 valid, 0 invalid, 0 errors, 0 skipped, strict Kubernetes 1.37 schemas |
| Docker build | Успешно собран образ с закреплённым digest Python base и pinned Python dependencies |
| Контейнерная smoke-проверка | Compose API запущен: UID 10001, cap-drop ALL, CapEff=0, NoNewPrivs=1, read-only rootfs, readiness и Docker health healthy |
| Реальная диагностика example.com из контейнера | DNS, route, traceroute вернули результаты. TCP, TLS и HTTP вернули отдельные `Connection refused`. Это частичный результат, а не доказательство недоступности сайта вне этой среды. |
| Локальное контролируемое TLS-измерение | На временном loopback HTTPS-сервере с собственным сертификатом и явно доверенным временным CA получены TCP success, TLSv1.3 и HTTP 200. Проверка TLS не отключалась. Отсутствующий на host traceroute дал отдельную ошибку; в Docker утилита есть. Это проверка механизма, не измерение публичного сайта. |
| Prometheus 3.16.0 | Запущен в Compose, readiness успешен; оба targets (app, prometheus) UP. Получен настоящий `packet_road_diagnostics_total{outcome="partial"}=1` после запроса API. |
| Grafana 13.3.0 | **Не запущена**: Docker vfs не смог распаковать официальный образ из-за `no space left on device`. После удаления собственного build cache сделана одна повторная попытка с тем же ограничением. Provisioning и dashboard проверены на синтаксис, но импорт/отрисовка UI и контейнерный запуск не подтверждены. |
| Kubernetes rollout/probes/PVC/NetworkPolicy | **Не выполнялись**: выбранный кластер и kubeconfig не предоставлены. Schema validation не доказывает эти свойства. |
| GHCR публикация и CD | **Не выполнялись** в локальных проверках; требуют main pipeline, registry permissions, включённого deploy и целевого кластера. |

Docker daemon среды работает rootless с vfs и без cgroups. Поэтому наличие CPU/memory limits в Compose проверено в конфигурации, но реальное enforcement лимитов здесь не подтверждено. Системный диск около 8 GiB ограничил распаковку большого образа Grafana. После проверок временные контейнеры можно остановить `docker compose --env-file work/smoke.env --profile monitoring down`; секреты и сертификаты из `work/` не включаются в Git.

Для настоящего стенда ещё нужны: провайдер/бюджет/region/VM/network plan, сервер или согласованный план его создания, подтверждение версии k3s для ОС, доступ к Kubernetes API и схема CI credentials, секреты, registry visibility, проверка storage и backup. Никакие платные ресурсы автоматически не создавались.
