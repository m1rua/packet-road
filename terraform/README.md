# Terraform: новая Ubuntu VM на Arch/libvirt

Этот каталог создаёт **новую** VM `packet-road-tf`. Существующая `ubuntu26.04`,
её диск, Ansible inventory и работающий k3s не импортируются и не меняются.
Код запускается **на Arch**, где доступны KVM и `qemu:///system`, не внутри Ubuntu.

## Границы ответственности

```text
Terraform → cloud image, QCOW2 overlay, cloud-init ISO, новая VM
cloud-init → пользователь platinum, публичный SSH-ключ, DHCP, расширение /
Ansible → Docker, образ packet-road, Prometheus, Node Exporter, Grafana
Helm → интерактивный Pod в отдельно подготовленном k3s
```

Terraform не устанавливает k3s или приложения и не запускает Ansible автоматически.
В новой VM используется Ubuntu **24.04 LTS amd64 cloud image**, а не установочный
ISO и не копия существующей Ubuntu 26.04. Интерактивная установка ОС не нужна.

## Файлы

| Файл | Назначение |
|---|---|
| `providers.tf` | Terraform >= 1.7 и libvirt provider **0.9.9** |
| `.terraform.lock.hcl` | Версия provider и проверяемые контрольные суммы; хранится в Git |
| `variables.tf` | Имя VM, RAM, CPU, диск, образ, сеть и публичный ключ |
| `main.tf` | Ресурсы и зависимости между ними |
| `cloud-init/user-data.yaml.tftpl` | Настройка первого пользователя без пароля |
| `outputs.tf` | IP, SSH-команда и отдельный inventory для Ansible |
| `tests/lab.tftest.hcl` | Планирование с mock-provider, без создания VM |

Схема libvirt **0.9.x отличается от 0.8.x**. Не подставляй примеры старой версии
без проверки `terraform validate`.

## 1. Подготовка Arch

```bash
terraform version
virsh -c qemu:///system list --all
virsh -c qemu:///system net-info default
virsh -c qemu:///system pool-info default
free -h
df -h /var/lib/libvirt/images
```

Нужны работающий KVM, libvirt, доступ текущего пользователя к системному libvirt,
активная сеть `default` с NAT/DHCP и активный pool `default`. Проверка без sudo
важна: Terraform будет подключаться от этого же пользователя. Если virsh просит
подтверждение через polkit, запусти рабочий polkit-agent в графической сессии.
Не запускай весь Terraform через sudo ради обхода ошибки доступа.

Ранее созданные сеть и pool **используются**, но не управляются Terraform:
эта конфигурация не удаляет их при `destroy`. Их запуск/автозапуск остаётся
настройкой Arch. Проблемы host firewall Terraform здесь также не исправляет.

По умолчанию новая VM получает 4096 MiB RAM, 2 vCPU и 20 GiB виртуального диска.
QCOW2 overlay разреженный (`allocation = 0`), но это **не резервирование места**:
он растёт по мере записи. Нужен запас под cloud image, overlay и данные приложений.
При заполнении диска Arch пострадают обе VM. Можно сначала выключить старую VM
для экономии RAM; её диск это не освободит.

## 2. Локальные параметры

Из корня репозитория:

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
cat ~/.ssh/id_ed25519.pub
```

Вставь **содержимое публичного ключа** в `ssh_public_key` в `terraform.tfvars`.
Не вставляй приватный ключ. Задай новое уникальное имя VM, если нужно.
`terraform.tfvars`, state, планы и скачанные providers исключены из Git.

Пользователь cloud-init имеет вход только по ключу и passwordless sudo для
Ansible. Пароль пользователя старой VM здесь не применяется. Не помещай PAT
GitHub или пароли в cloud-init/state. GitHub-токен остаётся в Ansible Vault.

## 3. Инициализация и проверки

```bash
terraform -chdir=terraform init -lockfile=readonly
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform test
```

CI выполняет эти проверки без KVM, libvirt daemon, пользовательских ключей и
реальных VM. Тесты используют mock-provider; они не подтверждают фактическую
загрузку Ubuntu на твоём Arch.

### Если Registry заблокирован по географии

При `x-amzn-waf-reason: geo` реестр возвращает HTML вместо discovery JSON.
Можно использовать системный VPN либо подготовить локальное зеркало:

```bash
python3 terraform/scripts/install-provider-mirror.py
export TF_CLI_CONFIG_FILE="$PWD/terraform/.terraformrc.mirror"
terraform -chdir=terraform init -lockfile=readonly
```

Скрипт скачивает **официальный GitHub-релиз 0.9.9 для Linux amd64**, проверяет
закреплённый SHA256 и создаёт отдельную CLI-конфигурацию. Глобальный `~/.terraformrc`
не меняется, TLS и проверка lock-файла не отключаются. Доступ к GitHub всё ещё нужен.
При установке из filesystem mirror Terraform пишет `unauthenticated`: подпись
из Registry не запрашивается. Целостность архива проверяют закреплённый SHA256
скрипта и checksum из закоммиченного lock-файла; это не отключение TLS.
Переменная окружения действует в текущем терминале; для возврата к обычной настройке:

```bash
unset TF_CLI_CONFIG_FILE
```

### Cloud image

По умолчанию provider скачивает официальный образ Ubuntu по HTTPS. Этот release
URL обновляется Ubuntu и сам по себе не фиксирует содержимое образа навсегда.
Для повторяемой установки скачай образ заранее, проверь его по официальному
`SHA256SUMS` и укажи абсолютный путь через `cloud_image`. Сохрани SHA256 и дату
выбранного образа. Путь должен вести к QCOW2 cloud image, а не установочному ISO.

## 4. План и создание

```bash
terraform -chdir=terraform plan -out=lab.tfplan
```

Проверь имена и действия. Для первого запуска ожидаются **5 создаваемых ресурсов**:
базовый cloud image, writable root overlay, локальный cloud-init ISO, его volume
в libvirt и VM. Сеть, pool и старая VM в плане не должны заменяться или удаляться.
План может содержать данные cloud-init; файл не коммитится.

Только после проверки плана:

```bash
terraform -chdir=terraform apply lab.tfplan
terraform -chdir=terraform output
```

Получение DHCP lease не означает готовность SSH. Подожди загрузки cloud-init,
подключись по команде из `ssh_command`, затем **в новой Ubuntu** выполни:

```bash
sudo cloud-init status --wait
df -h /
```

Для просмотра загрузки с Arch: `virsh -c qemu:///system console packet-road-tf`
(выход Ctrl+]). Приватный ключ остаётся на Arch. `apply` выполняет только создание
инфраструктуры; Helm release и приложения в новой VM автоматически не появятся.

## 5. Передача новой VM в Ansible

На Arch, из корня проекта:

```bash
terraform -chdir=terraform output -raw ansible_inventory > ansible/inventory.tf.ini
ansible lab -i ansible/inventory.tf.ini -m ping
ansible-playbook -i ansible/inventory.tf.ini ansible/setup.yml --ask-vault-pass
```

При первом SSH-входе проверь ключ сервера. Старый `ansible/inventory.ini` не меняем:
новая VM получает собственный DHCP-адрес. `--ask-become-pass` здесь не нужен из-за
настройки sudo в cloud-init. Адрес не закреплён навсегда: после изменения DHCP lease
обнови Terraform outputs через `terraform apply -refresh-only` и пересоздай inventory.

## State и удаление

Локальный `terraform.tfstate` — связь конфигурации с реальными ресурсами. Не удаляй
его для «сброса ошибки», не редактируй вручную и храни резервную копию вне Git.
Cloud-init применяется при первом запуске: изменение ключа в конфигурации не является
универсальным способом обновить уже созданного пользователя; это делается Ansible.

`terraform destroy` удаляет **новую VM и её управляемые диски вместе с данными**.
Сначала посмотри `terraform plan -destroy`. Не используй `destroy` для остановки VM
и не импортируй существующую `ubuntu26.04` в этот state без отдельного разбора.
