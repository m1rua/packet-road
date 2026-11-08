"""Packet Road: DNS, локальный маршрут и TCP traceroute."""

import ipaddress
import os
import random
import socket
import sys
import time

import dns.exception
import dns.resolver
from scapy.all import ARP, ICMP, IP, TCP, Ether, conf, get_if_hwaddr, sr1, srp


def heading(title):
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def ask_number(prompt, default, converter, minimum, maximum):
    while True:
        value = input(f"{prompt} [{default}]: ").strip()

        if not value:
            return default

        try:
            number = converter(value)

            if minimum <= number <= maximum:
                return number
        except ValueError:
            pass

        print(f"Введите число от {minimum} до {maximum}.")


def ask_settings():
    heading("PACKET ROAD — исследуем путь до сервера")

    print(
        "\nСкрипт определит IP сайта, покажет локальный маршрут"
        "\nи попробует найти промежуточные узлы до сервера."
        "\n\nДля выбора значения по умолчанию нажмите Enter."
    )

    while True:
        target = input(
            "\nВведите домен или IPv4 [example.com]: "
        ).strip() or "example.com"

        try:
            address = ipaddress.ip_address(target)
        except ValueError:
            if (
                any(char.isspace() for char in target)
                or any(char in target for char in "/:@")
            ):
                print(
                    "Введите только домен или IPv4."
                    "\nНапример: example.com или 1.1.1.1."
                    "\nБез https://, номера порта и пути."
                )
                continue
        else:
            if address.version != 4:
                print("Пока поддерживается только IPv4.")
                continue

        break

    print(
        "\nTCP-порт определяет сервис, к которому обращаемся."
        "\n443 обычно используется для HTTPS, 80 — для HTTP."
    )

    port = ask_number(
        "TCP-порт",
        default=443,
        converter=int,
        minimum=1,
        maximum=65535,
    )

    print(
        "\nМаксимальное число переходов ограничивает трассировку."
        "\nОбычно достаточно 30."
    )

    max_hops = ask_number(
        "Максимум переходов",
        default=30,
        converter=int,
        minimum=1,
        maximum=255,
    )

    print(
        "\nТаймаут — сколько секунд ждать ответ на каждую пробу."
        "\nЧем он больше, тем дольше могут занимать проверки."
    )

    timeout = ask_number(
        "Ожидание ответа, секунд",
        default=2.0,
        converter=float,
        minimum=0.1,
        maximum=60,
    )

    return target, port, max_hops, timeout


def resolve_target(target, timeout):
    heading("ШАГ 1. ОПРЕДЕЛЯЕМ IP-АДРЕС")

    try:
        address = ipaddress.ip_address(target)
    except ValueError:
        pass
    else:
        print(f"\nВы указали IPv4: {address}")
        print("DNS-запрос не требуется.")
        return str(address)

    print(f"\nВы указали домен: {target}")
    print(
        "\nДля отправки IP-пакетов нужен IP-адрес сервера."
        "\nЗапросим DNS-запись типа A: она связывает доменное"
        "\nимя с IPv4-адресом."
    )

    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout

    print(
        "\nНастроенные DNS-серверы:",
        ", ".join(map(str, resolver.nameservers)),
    )

    print(
        "Обращаемся к настроенному резолверу."
        "\nОн может вернуть ответ из кеша или найти его через"
        "\nдругие DNS-серверы. Ручной обход корневых серверов"
        "\nэтот скрипт пока не выполняет.",
        flush=True,
    )

    try:
        answer = resolver.resolve(target, "A", search=False)
    except dns.resolver.NXDOMAIN:
        raise RuntimeError(
            f"домен {target} не существует по ответу DNS"
        ) from None
    except dns.resolver.NoAnswer:
        raise RuntimeError(
            f"DNS не вернул IPv4-запись A для {target}"
        ) from None
    except dns.resolver.NoNameservers:
        raise RuntimeError(
            "настроенные DNS-серверы не смогли обработать запрос"
        ) from None
    except dns.exception.Timeout:
        raise RuntimeError(
            f"DNS не ответил за {timeout} сек."
        ) from None

    addresses = list(
        dict.fromkeys(record.address for record in answer)
    )

    print("\nПолучены IPv4-адреса:")

    for address in addresses:
        print(f"  • {address}")

    selected = addresses[0]

    print(f"\nДля дальнейших проверок выбираем: {selected}")

    if len(addresses) > 1:
        print(
            "У домена несколько адресов. В этом запуске"
            "\nпроверяется только первый."
        )

    return selected


def show_route(target, timeout):
    heading("ШАГ 2. КАК ПАКЕТ ПОКИНЕТ ЭТОТ КОМПЬЮТЕР")

    interface, source, gateway = conf.route.route(target)

    if source == "0.0.0.0":
        raise RuntimeError(
            f"не найден подходящий IPv4-маршрут к {target}"
        )

    print(
        "\nСмотрим таблицу маршрутизации: она определяет,"
        "\nчерез какой интерфейс отправлять пакет к выбранной цели."
    )

    print(f"\nЦелевой IPv4:   {target}")
    print(f"Интерфейс:      {interface}")
    print(f"Исходный IPv4:  {source}")

    print(
        "\nЭто локальный исходный адрес. При выходе в интернет"
        "\nроутер или VPN могут изменить его с помощью NAT."
    )

    if str(interface) == "lo":
        print(
            "\nВыбран loopback: адрес относится к этому компьютеру."
            "\nДля такого маршрута ARP не требуется."
        )
        return

    try:
        print("MAC интерфейса:", get_if_hwaddr(interface))
    except OSError:
        print("MAC интерфейса определить не удалось.")

    if gateway != "0.0.0.0":
        next_hop = gateway

        print(f"\nСледующий узел — шлюз: {gateway}")
        print(
            "IP-пакет адресован конечному серверу, но в локальной"
            "\nсети кадр сначала передаётся шлюзу."
        )
    else:
        next_hop = target

        print("\nМаршрут не использует отдельный IP-шлюз.")
        print(
            "Цель находится в подключённой сети либо маршрут"
            "\nидёт через интерфейс с другой моделью передачи."
        )

    print(
        f"\nПробуем узнать MAC следующего узла {next_hop} через ARP."
        "\nARP используется в локальных IPv4-сетях с Ethernet."
        "\nНа VPN и других туннелях он может быть неприменим.",
        flush=True,
    )

    packet = (
        Ether(dst="ff:ff:ff:ff:ff:ff")
        / ARP(pdst=next_hop)
    )

    try:
        answered, _ = srp(
            packet,
            iface=interface,
            timeout=timeout,
            verbose=0,
        )
    except (OSError, RuntimeError) as error:
        print(f"\nARP-проверку выполнить не удалось: {error}")
        print("Продолжаем TCP-проверки.")
        return

    if answered:
        mac = answered[0][1][ARP].hwsrc

        print(f"\nПолучен ARP-ответ: {next_hop} → {mac}")
        print(
            "Это MAC следующего узла локального канала,"
            "\nа не MAC удалённого сайта."
        )
    else:
        print(f"\nARP-ответ не получен за {timeout} сек.")
        print(
            "Это может быть связано с типом интерфейса,"
            "\nтуннелем или отсутствием ответа в локальной сети."
            "\nПродолжаем TCP-проверки."
        )


def trace_route(target, port, max_hops, timeout):
    heading("ШАГ 3. ИССЛЕДУЕМ ПУТЬ ДО СЕРВЕРА")

    print(f"\nАдрес сервера: {target}")
    print(f"TCP-порт:      {port}")
    print(f"Ожидание:      {timeout} сек. на каждую пробу")
    print(f"Лимит:         {max_hops} переходов")

    print(
        "\nОтправляем TCP SYN — пакеты, которыми обычно начинается"
        "\nустановка TCP-соединения."
        "\n"
        "\nУ IP-пакета есть TTL — ограничение числа переходов."
        "\nКаждый маршрутизатор уменьшает TTL на 1. Когда TTL"
        "\nзаканчивается, пакет удаляется, а маршрутизатор"
        "\nможет ответить сообщением ICMP Time Exceeded."
        "\n"
        "\nНачнём с TTL=1 и будем постепенно увеличивать его."
        "\nТак попробуем увидеть промежуточные узлы."
        "\nНе все узлы отвечают на диагностические пробы."
    )

    sport = random.randint(32768, 60999)
    reached = False
    received_replies = 0

    for ttl in range(1, max_hops + 1):
        print(f"\n── Проба {ttl}/{max_hops}: TTL={ttl} ──")
        print(
            f"Отправляем TCP SYN на {target}:{port}.",
            flush=True,
        )

        packet = (
            IP(dst=target, ttl=ttl)
            / TCP(sport=sport, dport=port, flags="S")
        )

        start = time.perf_counter()
        reply = sr1(packet, verbose=0, timeout=timeout)
        rtt = (time.perf_counter() - start) * 1000

        if reply is None:
            print(f"Ответ не получен за {timeout} сек.")
            print(
                "Адрес этого перехода определить не удалось."
                "\nЭто не доказывает, что трафик здесь обрывается."
            )
            continue

        received_replies += 1

        print(f"Получен ответ от: {reply.src}")
        print(f"Время до ответа:  {rtt:.1f} мс")

        # ICMP-ошибка может содержать исходную TCP-пробу.
        # Сначала проверяем ICMP, чтобы не принять её за ответ цели.
        if reply.haslayer(ICMP):
            icmp = reply[ICMP]

            if icmp.type == 11 and icmp.code == 0:
                print("Тип ответа: ICMP Time Exceeded.")
                print(
                    "TTL закончился на этом маршрутизаторе."
                    "\nУвеличиваем TTL и пробуем пройти дальше."
                )
                continue

            if icmp.type == 3:
                reasons = {
                    0: "сеть назначения недоступна",
                    1: "узел назначения недоступен",
                    2: "протокол недоступен",
                    3: "порт недоступен",
                    4: "нужна фрагментация, но она запрещена",
                    9: "доступ к сети запрещён",
                    10: "доступ к узлу запрещён",
                    13: "передача запрещена административными правилами",
                }

                reason = reasons.get(
                    icmp.code,
                    "другая причина недоступности",
                )

                print("Тип ответа: ICMP Destination Unreachable.")
                print(f"Причина: {reason}; код {icmp.code}.")
                print(
                    "Узел сообщил, что пробу нельзя доставить."
                    "\nОстанавливаем трассировку."
                )
                break

            print(
                f"Другое ICMP-сообщение: "
                f"type={icmp.type}, code={icmp.code}."
            )
            continue

        if reply.src == target and reply.haslayer(TCP):
            flags = int(reply[TCP].flags)

            if flags & 0x04:
                print("Тип ответа: TCP RST — отказ в соединении.")
                print(
                    "Получен ответ с адреса цели."
                    "\nПорт может быть закрыт или соединение"
                    "\nотклонено фильтром."
                )
                reached = True
                break

            if (flags & 0x12) == 0x12:
                print("Тип ответа: TCP SYN-ACK.")
                print(
                    "Получен ответ с адреса цели: порт открыт"
                    "\nи готов к установке TCP-соединения."
                )
                print(
                    "Эта проба не выполняет TLS и не запрашивает"
                    "\nстраницу по HTTP."
                )
                reached = True
                break

            print(
                f"Неожиданные TCP-флаги: {reply[TCP].flags}."
                "\nПродолжаем трассировку."
            )
        else:
            print(
                "Получен ответ, который не удалось распознать"
                "\nкак ожидаемый ответ маршрутизатора или цели."
            )

    heading("РЕЗУЛЬТАТ ТРАССИРОВКИ")

    if reached:
        print("\nПолучен TCP-ответ с адреса цели.")
    elif received_replies == 0:
        print("\nНи одна проба не получила ответа.")
        print(
            "По этим данным нельзя определить маршрут"
            "\nили сделать вывод о доступности сайта."
        )
    else:
        print(f"\nПолучено ответов на пробы: {received_replies}.")
        print(
            "Часть маршрута видна, но конечный TCP-ответ"
            "\nне получен в пределах заданного числа переходов."
        )

    print(
        "\nТрассировка использует отдельные диагностические пакеты."
        "\nЭто не перехват запроса браузера. Маршрут может меняться,"
        "\nа обратный путь может отличаться от прямого."
    )

    return reached


def check_tcp_connection(target, port, timeout):
    heading("ШАГ 4. ПРОВЕРЯЕМ ОБЫЧНОЕ TCP-СОЕДИНЕНИЕ")

    print(
        "\nТеперь попросим операционную систему установить обычное"
        "\nTCP-соединение без искусственного уменьшения TTL."
        "\nЭто отдельная проверка доступности порта."
    )

    print(f"\nПодключаемся к {target}:{port}…", flush=True)

    start = time.perf_counter()

    try:
        with socket.create_connection(
            (target, port),
            timeout=timeout,
        ):
            elapsed = (time.perf_counter() - start) * 1000

        print("\nTCP-соединение успешно установлено.")
        print(f"Время установки: {elapsed:.1f} мс.")
        print(
            "Операционная система выполнила TCP-рукопожатие."
            "\nЗатем скрипт закрыл соединение без отправки"
            "\nприкладных данных."
        )
        print(
            "\nОткрытый TCP-порт ещё не означает, что сайт"
            "\nкорректно отвечает по HTTPS: TLS и HTTP"
            "\nв этой версии не проверяются."
        )

        return True

    except ConnectionRefusedError:
        print("\nВ TCP-соединении отказано.")
        print(
            "Возможно, на порту нет слушающего сервиса"
            "\nили соединение активно отклоняется."
        )

    except (socket.timeout, TimeoutError):
        print(
            f"\nСоединение не установлено за {timeout} сек."
        )
        print(
            "Возможны фильтрация, проблемы маршрута"
            "\nили недоступность сервера."
            "\nОдного таймаута недостаточно для точного вывода."
        )

    except OSError as error:
        print(f"\nОшибка TCP-соединения: {error}")

    return False


def main():
    try:
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            print(
                "Для ARP и TCP-проб нужны права root."
                "\nЗапустите: sudo .venv/bin/python get_info.py",
                file=sys.stderr,
            )
            return 1

        target, port, max_hops, timeout = ask_settings()

        target_ip = resolve_target(target, timeout)

        show_route(target_ip, timeout)

        trace_reached = trace_route(
            target_ip,
            port,
            max_hops,
            timeout,
        )

        tcp_connected = check_tcp_connection(
            target_ip,
            port,
            timeout,
        )

        heading("ИТОГ")

        print(f"\nЦель: {target} → {target_ip}:{port}")

        if trace_reached:
            print("Трассировка: получен TCP-ответ с адреса цели.")
        else:
            print("Трассировка: конечный TCP-ответ не получен.")

        if tcp_connected:
            print("Обычное TCP-соединение: успешно.")

            if not trace_reached:
                print(
                    "\nTCP-порт доступен, хотя трассировка"
                    "\nне получила конечный ответ."
                    "\nНужно отдельно исследовать фильтрацию проб,"
                    "\nVPN и особенности отправки raw-пакетов."
                )
        else:
            print("Обычное TCP-соединение: не установлено.")

        return 0 if tcp_connected else 2

    except (KeyboardInterrupt, EOFError):
        print("\nРабота остановлена пользователем.")
        return 130

    except Exception as error:
        print(f"\nОшибка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())