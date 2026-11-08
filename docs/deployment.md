# Развёртывание и ответственность инструментов

## Локальный Docker

Образ содержит Python, `iproute2`, `traceroute`; Python зависимости, включая транзитивные, закреплены в requirements. Системные Debian-пакеты берутся из репозитория на момент сборки: побитовая воспроизводимость образа не гарантируется. Для обновлений безопасности планируйте регулярную пересборку, проверку зависимостей и обновление версий. Версия 0.2.0 — версия приложения, `APP_REVISION` — исходный Git commit; в GHCR используется тег полного SHA и digest для развёртывания.

Процесс работает под UID/GID 10001, read-only root filesystem, все capabilities удалены, privilege escalation запрещён. Временные файлы приложению не нужны. Compose публикует порт только на 127.0.0.1. `docker compose down` сохраняет именованные volumes; `down -v` уничтожает историю мониторинга.

В облачной среде с инспектирующим TLS proxy сборка может потребовать:

```bash
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  --build-arg APP_REVISION="$(git rev-parse HEAD)" -t packet-road:local .
```

CA монтируется только на время установки pip, не помещается в слой образа. Нельзя отключать проверку TLS ради сборки. Это не меняет прямые DNS/TCP-пробы приложения: HTTP proxy не превращается в сетевой путь измерения.

## Terraform и Ansible

Провайдер не выбран. `infra/terraform` **не создаёт VM**: это валидируемый контракт адреса существующего узла и SSH-пользователя, из которого получается inventory. Он не выдаётся за реализованное provisioning. Для настоящего provider module нужны решение о провайдере, бюджет, region, размер/образ VM, SSH public key, разрешённые сети и место хранения state. Приватные ключи и tfstate не коммитятся. Нельзя запускать apply для платных ресурсов до согласования плана.

Ansible отвечает за ОС/компоненты, а не за создание сервера. `site.yml` устанавливает проверенный checksum бинарник k3s, конфигурацию и systemd unit. Поддерживается один Linux x86_64 сервер с systemd. Версия k3s закреплена и должна обновляться осознанно. Версия v1.37.2+k3s1 и SHA256 закреплены по официальному `sha256sum-amd64.txt`; при обновлении меняйте их вместе. Пустой/неверный checksum останавливает playbook. Не запускайте на существующем кластере без проверки конфликта портов и конфигурации.

k3s выбран для маленькой лаборатории: один бинарник и встроенные containerd, CNI, local-path storage уменьшают объём сопровождения. Это не HA: потеря сервера означает потерю доступности и, без backup, локальных данных. OS firewall, обновления ОС, резервное копирование и доступ по SSH остаются отдельными задачами перед реальным использованием.

Пример после согласования конкретного сервера и плана:

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
# Заполнить адрес и ssh_user.
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform plan
# apply для этого provider-neutral контракта сохраняет только outputs:
terraform -chdir=infra/terraform apply
terraform -chdir=infra/terraform output -raw ansible_inventory > infra/ansible/inventory.ini
ansible-playbook -i infra/ansible/inventory.ini infra/ansible/site.yml
```

Не открывайте Kubernetes API 6443 всему Интернету; ограничьте firewall/VPN адресами администратора и runner. GitHub-hosted runner должен иметь реальный сетевой доступ к API. Иначе нужен self-hosted runner в доверенной сети, а не отключение TLS.

## Kubernetes: начальный запуск администратором

Команды ниже — инструкция для вашего согласованного стенда; автоматически к реальному кластеру они не применялись.

```bash
kubectl apply -f deploy/kubernetes/namespace.yaml
# Секрет из переменной, не из Git. Отключите shell tracing.
export PACKET_ROAD_TOKEN="$(openssl rand -hex 32)"
kubectl -n packet-road create secret generic packet-road \
  --from-literal=PACKET_ROAD_TOKEN="$PACKET_ROAD_TOKEN"
# В app.yaml замените REPLACE_WITH_COMMIT_SHA опубликованным SHA,
# либо измените image через локальный kustomize edit set image.
kubectl apply -k deploy/kubernetes
kubectl -n packet-road rollout status deployment/packet-road --timeout=120s
kubectl -n packet-road port-forward service/packet-road 8000:8000
```

Secret `packet-road` нужен до запуска pod; это ссылка в envFrom, секрета с фиктивным значением в репозитории нет. Secret в Kubernetes — не шифрование сам по себе: настройте encryption at rest и RBAC. Для private GHCR добавьте imagePullSecret через безопасный локальный overlay; по умолчанию ожидается публичный package.

ConfigMap хранит точный allowlist доменов. Для изменения env из ConfigMap/Secret нужен `kubectl rollout restart deployment/packet-road -n packet-road`. Startup probe даёт время запуска, readiness управляет включением pod в endpoints, liveness проверяет живость процесса. Пробы не проверяют Интернет: сбой внешней цели не должен перезапускать API. Requests нужны планировщику, limits ограничивают ресурсы. Service ClusterIP не открывает порт наружу. NetworkPolicy допускает labeled клиентские pod в том же namespace и pod namespace `monitoring`; работа policy требует поддерживающего CNI. k3s включает network policy controller по умолчанию. Port-forward — административный путь через API server, не способ проверить pod-to-pod NetworkPolicy.

## CI/CD

Pull request запускает lint, 9 unit/API сценариев, синтаксис YAML/JSON, Terraform fmt/init/validate, Ansible syntax-check, рендер kustomize, сборку образа и отдельную инфраструктурную smoke-проверку HTTP readiness и UID с cap-drop ALL/read-only. Итого 10 автоматических сценариев: 9 pytest и один контейнерный smoke; параметризации нет.

Push в `main` после проверок публикует `ghcr.io/m1rua/packet-road:<full SHA>` через временный `GITHUB_TOKEN` с packages:write. Pull request не получает registry credential и не публикует образ. Ветки разработки на push не деплоятся.

Deploy job по умолчанию выключен. Для согласованного стенда создайте GitHub Environment `staging`, настройте required reviewers при необходимости, секрет `KUBE_CONFIG` с настоящим TLS CA и ограниченными namespaced правами. Администратор заранее создаёт namespace и Secret; pipeline не создаёт secret и не выбирает провайдера. После проверки доступа установите repository variable `DEPLOY_ENABLED=true`. Это осознанное включение deployment в ваш кластер после каждого успешного main pipeline. В этом сеансе переменная и секреты не менялись.

Нужные права deploy credential: get/list/watch/create/update/patch для deployments, services, configmaps, networkpolicies в `packet-road`; get конкретного Secret `packet-road` для preflight; get/list/watch pods/replicasets для диагностики. Не используйте admin kubeconfig k3s как постоянный CI secret. Учтите срок жизни credentials; для долгосрочного использования предпочтительны короткоживущие токены/OIDC с поддержкой со стороны выбранного кластера.

Pipeline заменяет placeholder **digest образа**, применяет манифесты, ждёт rollout до 120 секунд. Неуспешный rollout делает job красным; автоматический откат не скрывает проблему. Для rollback:

```bash
kubectl -n packet-road rollout history deployment/packet-road
kubectl -n packet-road rollout undo deployment/packet-road --to-revision=PREVIOUS_REVISION
kubectl -n packet-road rollout status deployment/packet-road --timeout=120s
```

Undo откатывает pod template, но не Secret/ConfigMap: их меняйте отдельно. Следующее применение декларативной конфигурации снова задаст её image; закрепите требуемый digest в конфигурации или исправьте код и повторите pipeline. Merge не выполняется автоматически.

## Мониторинг в Kubernetes

```bash
kubectl create namespace monitoring
kubectl label namespace monitoring pod-security.kubernetes.io/enforce=restricted
# Пароль заранее задайте в безопасной локальной переменной.
kubectl -n monitoring create secret generic grafana \
  --from-literal=admin-password="$GRAFANA_PASSWORD"
kubectl apply -k monitoring
kubectl -n monitoring rollout status deployment/prometheus
kubectl -n monitoring rollout status deployment/grafana
kubectl -n monitoring port-forward service/grafana 3000:3000
```

Нужен default StorageClass; у k3s это обычно local-path. PVC: Prometheus 5 GiB с retention 15 дней/4 GB, Grafana 1 GiB. На одном сервере storage переживает пересоздание pod, но не потерю диска. Настройте backup отдельно. Стек без доступа к node filesystem, privileged и cluster-admin. Здесь собираются метрики процесса API, а не полная телеметрия всех узлов и контейнеров. Node exporter/cAdvisor не добавлены, поскольку их host-доступ требует отдельной оценки.

Для namespaced CI RBAC добавлен `deploy/bootstrap/ci-rbac.yaml`, применяемый администратором отдельно. Он не даёт изменения Secret, namespace или cluster-scoped ресурсов. Доступ к изменению Deployment всё равно является сильным правом внутри namespace: deployer может менять pod template и ссылки на Secret, поэтому namespace должен оставаться выделенным проекту. Token для первоначальной краткой проверки можно получить `kubectl -n packet-road create token packet-road-deployer --duration=1h`; не печатайте его в общие логи. Соберите kubeconfig с адресом API, настоящим CA и этим токеном локально, загрузите в environment secret через защищённый интерфейс. Такой token истекает и не является решением для бессрочного CD. Постоянный механизм авторизации выбирается вместе с инфраструктурой.
