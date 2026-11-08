# Packet Road

Учебный проект Junior DevOps: измеряет, что видно при обращении к домену **из сети процесса**, контейнера или pod. Возвращает JSON через CLI и HTTP API. Скрытые узлы, NAT/SNAT и маршрут конкретного HTTP-запроса не восстанавливает.

Состояние: реализация и локальные проверки; это не заявление о production-ready. Подробные результаты проверки — в [журнале](docs/changes.md).

## Быстрый запуск

Нужны Python 3.12+ и Linux с `iproute2`, `traceroute`. В контейнере утилиты уже установлены.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt -e .
packet-road example.com --max-hops 8
# Для собственной локальной лаборатории — только явное разрешение в CLI:
packet-road 127.0.0.1 --port 80 --allow-private
```

CLI завершается с кодом 0 при успехе всех этапов, 1 при частичном результате, 2 при неверном вводе/запрете цели. Linux-утилиты могут отсутствовать: тогда соответствующие этапы вернут ошибку, остальные продолжатся.

```bash
cp .env.example .env
# Замените PACKET_ROAD_TOKEN: openssl rand -hex 32
# Замените GRAFANA_PASSWORD уникальным паролем.
docker compose up --build -d app
set -a; . ./.env; set +a
curl -sS http://127.0.0.1:8000/v1/diagnostics \
  -H "Authorization: Bearer $PACKET_ROAD_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"target":"example.com","max_hops":8}'
docker compose --profile monitoring up -d
```

Прямой запуск API: экспортируйте `PACKET_ROAD_TOKEN` (минимум 32 символа) и `PACKET_ROAD_TARGETS=example.com`, затем `uvicorn packet_road.api:app --host 127.0.0.1 --port 8000 --workers 1`. Токен храните в `.env` с правами `0600`, вне Git. Без токена API не стартует; пустой список целей запрещает все диагностики. Список — точные имена/адреса через запятую, без wildcard. API разрешает порты 80 и 443.

Grafana: http://127.0.0.1:3000 (admin и ваш пароль); Prometheus: http://127.0.0.1:9090. API привязан к loopback хоста. Не публикуйте эти порты напрямую в Интернет.

## Архитектура

```mermaid
flowchart LR
  CLI --> Core[Ядро диагностики]
  Client --> Auth[Bearer token + allowlist + лимиты]
  Auth --> API[FastAPI]
  API --> Core
  Core --> DNS[DNS A/AAAA: проверка всех IP]
  DNS --> Pin[Выбор одного IP]
  Pin --> Route[ip route / neighbor cache]
  Pin --> Trace[UDP traceroute]
  Pin --> TCP[TCP connect]
  Pin --> TLS[TLS с проверкой сертификата]
  Pin --> HTTP[HTTP HEAD без redirects]
  API --> Metrics[/metrics]
  Metrics --> Prometheus --> Grafana
```

Основные файлы: `src/packet_road/core.py` — измерения; `api.py` — доступ, лимиты и метрики; `cli.py` — CLI; `deploy/kubernetes/` — приложение; `monitoring/` — обе среды мониторинга; `infra/` — подготовка инфраструктуры. `get_info.py` сохранён как совместимая точка входа с аргументами вместо интерактивного ввода.

Каждый этап имеет `status`, `data` либо `error`, `error_type`, `duration_seconds`. HTTP 200 означает выполненную диагностику, а не доступность цели: проверяйте статусы этапов. DNS-сбой завершает дальнейшие этапы, поскольку нет адреса; запрет адреса возвращает API 403 без соединений к нему. Из A/AAAA выбирается первый адрес, альтернативные адреса автоматически не перебираются.

## Документация

- [Сеть, безопасность и ограничения](docs/network.md)
- [Kubernetes, Terraform, Ansible и CI/CD](docs/deployment.md)
- [Мониторинг, графики и типичные проблемы](docs/operations.md)
- [Изменения, проверки и вопросы для собеседования](docs/changes.md)

Проверки разработчика:

```bash
ruff check .
pytest -q                   # 9 сценариев + 1 контейнерный smoke в CI
python scripts/check_configs.py
terraform -chdir=infra/terraform fmt -check
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
ansible-playbook -i k3s, infra/ansible/site.yml --syntax-check
kubectl kustomize deploy/kubernetes
kubectl kustomize monitoring
```
