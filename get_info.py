import http.client
import ipaddress
import os
import random
import socket
import ssl
import sys
import time

import dns.exception
import dns.flags
import dns.rcode
import dns.resolver

from scapy.all import (
    ARP,
    ICMP,
    IP,
    TCP,
    Ether,
    conf,
    get_if_hwaddr,
    sr1,
    srp,
)


def heading(title):
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


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
    heading("PACKET ROAD — путь от имени сайта до HTTP-ответа")

    print(
        "\nМы последовательно проверим:"
        "\n  1. Как домен превращается в IPv4 через DNS."
        "\n  2. Как выбирается локальный маршрут."
        "\n  3. Какие узлы отвечают на traceroute."
        "\n  4. Устанавливается ли TCP-соединение."
        "\n  5. Как проходит TLS для HTTPS."
        "\n  6. Какой HTTP-ответ возвращает сервер."
        "\n\nНажмите Enter для выбора значения по умолчанию."
    )

    while True:
        target = input(
            "\nДомен или IPv4 [example.com]: "
        ).strip() or "example.com"

        try:
            address = ipaddress.ip_address(target)
        except ValueError:
            if (
                any(char.isspace() for char in target)
                or any(char in target for char in "/:@?#")
            ):
                print("Введите домен без https://, порта и пути.")
                continue

            try:
                target = target.encode("idna").decode("ascii")
            except UnicodeError:
                print("Не удалось преобразовать доменное имя.")
                continue
        else:
            if address.version != 4:
                print("Пока поддерживается только IPv4.")
                continue

        break

    while True:
        scheme = input(
            "Протокол: https или http [https]: "
        ).strip().lower() or "https"

        if scheme in ("https", "http"):
            break

        print("Введите https или http.")

    port = ask_number(
        "TCP-порт",
        443 if scheme == "https" else 80,
        int,
        1,
        65535,
    )

    while True:
        path = input("Путь страницы [/]: ").strip() or "/"

        if (
            path.startswith("/")
            and not any(
                char.isspace() or ord(char) < 32 or ord(char) == 127
                for char in path
            )
            and path.isascii()
            and "#" not in path
        ):
            break

        print(
            "Путь должен начинаться с /, без пробелов и #."
            "\nНе-ASCII символы используйте в URL-кодировке."
        )

    max_hops = ask_number(
        "Максимум переходов traceroute",
        20,
        int,
        1,
        255,
    )

    timeout = ask_number(
        "Таймаут каждой сетевой операции, секунд",
        3.0,
        float,
        0.1,
        60,
    )

    print(
        "\nПри отсутствии ответов traceroute может занять примерно"
        f"\n{max_hops * timeout:.0f} секунд плюс время остальных проверок."
    )

    return target, scheme, port, path, max_hops, timeout


def resolve_target(target, timeout):
    heading("1. DNS — ПОЛУЧАЕМ IP-АДРЕС")

    try:
        address = ipaddress.ip_address(target)
    except ValueError:
        pass
    else:
        print(f"\nУказан IPv4: {address}")
        print("Имя разрешать не нужно — пропускаем DNS.")
        return str(address)

    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout

    print(
        f"\nИмя сайта: {target}"
        "\nДля отправки IP-пакетов нам нужен числовой адрес."
        "\nЗапрашиваем DNS-запись A — IPv4 для этого имени."
    )

    print("\nDNS-серверы из настроек системы:")
    for server in resolver.nameservers:
        print(f"  • {server}")

    print(
        "\nСкрипт обращается к настроенному резолверу."
        "\nЭто может быть роутер, локальный DNS-сервис или внешний DNS."
        "\nРезолвер может использовать кеш либо обращаться к другим"
        "\nсерверам. Его внутренние запросы здесь не наблюдаются."
        "\n\nОтправляем запрос…",
        flush=True,
    )

    start = time.perf_counter()

    try:
        answer = resolver.resolve(target, "A", search=False)
    except dns.resolver.NXDOMAIN:
        raise RuntimeError(
            f"DNS сообщил NXDOMAIN: имя {target} не существует"
        ) from None
    except dns.resolver.NoAnswer:
        raise RuntimeError(
            f"для {target} не получена запись A"
        ) from None
    except dns.resolver.NoNameservers:
        raise RuntimeError(
            "DNS-серверы не смогли обработать запрос"
        ) from None
    except dns.exception.Timeout:
        raise RuntimeError(
            f"DNS-проверка превысила {timeout} сек."
        ) from None

    elapsed = (time.perf_counter() - start) * 1000
    response = answer.response

    print(f"\nОтвет получен за {elapsed:.1f} мс.")
    print("Ответивший DNS-сервер:", answer.nameserver)
    print("Код ответа:", dns.rcode.to_text(response.rcode()))
    print("Флаги:", dns.flags.to_text(response.flags))

    print(
        "\nЗаписи в секции Answer:"
        "\nФормат: имя | TTL кеширования в секундах | класс | тип | значение"
    )

    for rrset in response.answer:
        print(rrset.to_text())

    print(
        "\nDNS TTL — время кеширования записи."
        "\nЭто другая величина, чем TTL IP-пакета в traceroute."
    )

    if answer.canonical_name != answer.qname:
        print(
            "\nКаноническое имя после DNS-псевдонимов:",
            answer.canonical_name,
        )

    addresses = list(
        dict.fromkeys(record.address for record in answer)
    )

    print("\nПолученные IPv4:", ", ".join(addresses))
    print("Для дальнейших проверок выбран:", addresses[0])

    return addresses[0]


def show_route(target, timeout):
    heading("2. МАРШРУТИЗАЦИЯ — КУДА ОТПРАВИТЬ ПАКЕТ")

    interface, source, gateway = conf.route.route(target)

    if source == "0.0.0.0":
        raise RuntimeError(f"нет подходящего IPv4-маршрута к {target}")

    print(
        "\nScapy выбирает маршрут к целевому IP из своей таблицы"
        "\nмаршрутизации, загруженной из системы."
    )

    print(f"\nIP назначения:   {target}")
    print(f"Исходный IP:     {source}")
    print(f"Интерфейс:       {interface}")
    print(f"Шлюз:           {gateway}")

    print(
        "\nДля обычного IP-маршрута каждый маршрутизатор выбирает"
        "\nследующий узел по своей таблице маршрутизации."
        "\nIP назначения остаётся адресом сервера, а заголовок"
        "\nлокального канала меняется между сегментами сети."
        "\nNAT, VPN и прокси могут менять эту картину."
    )

    if str(interface) == "lo":
        print("\nLoopback: пакет остаётся внутри компьютера. ARP не нужен.")
        return

    try:
        print("\nMAC интерфейса:", get_if_hwaddr(interface))
    except OSError:
        print("\nMAC интерфейса определить не удалось.")

    next_hop = gateway if gateway != "0.0.0.0" else target

    print(
        f"\nПробуем узнать MAC следующего узла: {next_hop}."
        "\nВ Ethernet для этого используется широковещательный ARP:"
        f'\n«У кого IP {next_hop}? Сообщите свой MAC».'
        "\nНа туннельных интерфейсах ARP может быть неприменим.",
        flush=True,
    )

    try:
        answered, _ = srp(
            Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=next_hop),
            iface=interface,
            timeout=timeout,
            verbose=0,
        )

        if answered:
            print(
                "\nПолучен ARP-ответ. MAC следующего узла:",
                answered[0][1][ARP].hwsrc,
            )
        else:
            print("\nARP-ответ не получен. Продолжаем проверки.")

    except Exception as error:
        print(f"\nARP-проверка не выполнена: {error}")
        print("Продолжаем проверки.")

    print(
        "\nЭто MAC локального следующего узла, а не удалённого сайта."
        "\nОбычные TCP-соединения ниже создаёт ядро ОС. При VPN"
        "\nи сложной policy routing их путь может отличаться"
        "\nот пути raw-пакетов Scapy."
    )


def trace_route(target, port, max_hops, timeout):
    heading("3. TRACEROUTE — ИЩЕМ ПРОМЕЖУТОЧНЫЕ УЗЛЫ")

    print(
        "\nОтправляем отдельные TCP SYN с возрастающим IP TTL."
        "\nTTL=1 позволяет попробовать увидеть первый маршрутизатор,"
        "\nTTL=2 — второй и так далее."
        "\n\nПри исчерпании TTL маршрутизатор может ответить"
        "\nICMP Time Exceeded. Отсутствие ответа не доказывает,"
        "\nчто через него не проходит обычный трафик."
    )

    sport = random.randint(32768, 60999)
    reached = False

    try:
        for ttl in range(1, max_hops + 1):
            print(
                f"\nTTL={ttl}: отправляем TCP SYN → {target}:{port}",
                flush=True,
            )

            packet = (
                IP(dst=target, ttl=ttl)
                / TCP(sport=sport, dport=port, flags="S")
            )

            start = time.perf_counter()
            reply = sr1(packet, timeout=timeout, verbose=0)
            elapsed = (time.perf_counter() - start) * 1000

            if reply is None:
                print(
                    f"  Ответа нет за {timeout} сек."
                    "\n  Узел не определён; продолжаем."
                )
                continue

            print(f"  Ответ от {reply.src}, RTT {elapsed:.1f} мс.")

            if reply.haslayer(ICMP):
                icmp = reply[ICMP]

                if icmp.type == 11 and icmp.code == 0:
                    print(
                        "  ICMP Time Exceeded: здесь закончился TTL."
                    )
                elif icmp.type == 3:
                    print(
                        "  ICMP Destination Unreachable:"
                        f" узел сообщил о недоступности, код {icmp.code}."
                        "\n  Останавливаем трассировку."
                    )
                    break
                else:
                    print(
                        f"  ICMP type={icmp.type}, code={icmp.code}."
                    )

            elif reply.src == target and reply.haslayer(TCP):
                flags = int(reply[TCP].flags)

                if flags & 0x04:
                    print(
                        "  TCP RST с адреса цели: порт закрыт"
                        "\n  или соединение отклонено."
                    )
                    reached = True
                    break

                if (flags & 0x12) == 0x12:
                    print(
                        "  TCP SYN-ACK с адреса цели: порт открыт."
                    )
                    reached = True
                    break

                print(f"  Другие TCP-флаги: {reply[TCP].flags}.")
            else:
                print("  Неожиданный ответ.")

    except Exception as error:
        print(f"\nОшибка traceroute: {error}")
        print("Продолжаем обычное TCP-подключение.")

    if not reached:
        print(
            "\nКонечный TCP-ответ в трассировке не получен."
            "\nЭто ещё не означает, что сайт недоступен."
        )

    print(
        "\nЭто диагностические пробы, а не перехват HTTP-запроса."
        "\nСледующее соединение может пройти другим маршрутом."
    )

    return reached


def format_certificate_name(parts):
    return ", ".join(
        f"{key}={value}"
        for group in parts
        for key, value in group
    )


def request_site(target, target_ip, scheme, port, path, timeout):
    heading("4. TCP — УСТАНАВЛИВАЕМ СОЕДИНЕНИЕ")

    print(
        f"\nПодключаемся к {target_ip}:{port}."
        "\nВызываем обычный socket.connect()."
        "\nЯдро ОС выполняет TCP-рукопожатие:"
        "\n  клиент → SYN"
        "\n  сервер → SYN-ACK"
        "\n  клиент → ACK"
        "\n\nЭто объяснение протокола. Отдельные пакеты этого"
        "\nсоединения скрипт не захватывает.",
        flush=True,
    )

    connection = None
    response = None

    try:
        start = time.perf_counter()

        connection = socket.create_connection(
            (target_ip, port),
            timeout=timeout,
        )

        elapsed = (time.perf_counter() - start) * 1000

        local_ip, local_port = connection.getsockname()
        peer_ip, peer_port = connection.getpeername()

        print(f"\nTCP-соединение установлено за {elapsed:.1f} мс.")
        print(f"Локальный сокет: {local_ip}:{local_port}")
        print(f"Удалённый сокет: {peer_ip}:{peer_port}")

        if scheme == "https":
            heading("5. TLS — ЗАЩИЩАЕМ СОЕДИНЕНИЕ")

            print(
                "\nПоверх установленного TCP запускаем TLS."
                "\nДля домена передаём имя через SNI, чтобы сервер"
                "\nмог выбрать нужный сайт и сертификат."
                "\nПри подключении по IP библиотека SNI с IP не отправляет."
                "\n\nПроверяем сертификат по системным доверенным CA"
                "\nи соответствие сертификата введённому домену или IP."
                "\nПроверка сертификата включена.",
                flush=True,
            )

            context = ssl.create_default_context()
            start = time.perf_counter()

            connection = context.wrap_socket(
                connection,
                server_hostname=target,
            )

            elapsed = (time.perf_counter() - start) * 1000
            certificate = connection.getpeercert()
            cipher = connection.cipher()

            print(f"\nTLS установлен за {elapsed:.1f} мс.")
            print("Версия:", connection.version())
            print("Набор шифров:", cipher[0] if cipher else "неизвестен")

            print(
                "Субъект сертификата:",
                format_certificate_name(
                    certificate.get("subject", ())
                ),
            )
            print(
                "Издатель сертификата:",
                format_certificate_name(
                    certificate.get("issuer", ())
                ),
            )
            print(
                "Сертификат действует до:",
                certificate.get("notAfter", "неизвестно"),
            )

            print(
                "\nПроверка сертификата прошла."
                "\nПрикладные данные будут защищены TLS."
                "\nIP-адреса и TCP-порты TLS не скрывает."
            )
        else:
            heading("5. TLS — ПРОПУСКАЕМ")

            print(
                "\nВыбран HTTP: TLS не используется."
                "\nЗапрос и ответ передаются без защиты TLS."
            )

        heading("6. HTTP — ЗАПРАШИВАЕМ СТРАНИЦУ")

        default_port = 443 if scheme == "https" else 80
        host = target if port == default_port else f"{target}:{port}"

        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: packet-road/1.0\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n"
            "\r\n"
        )

        print(
            "\nОтправляем HTTP/1.1 GET."
            "\nЗаголовок Host сообщает, какой сайт запрашивается:"
            "\nодин IP может обслуживать несколько доменов."
            "\n\nСодержимое запроса до шифрования:\n"
        )

        print(request.rstrip())

        if scheme == "https":
            print(
                "\nНа сетевом канале этот HTTP-запрос передаётся"
                "\nвнутри зашифрованных TLS-записей."
            )

        start = time.perf_counter()

        connection.sendall(request.encode("ascii"))

        response = http.client.HTTPResponse(connection)
        response.begin()

        for _ in range(10):
            if not (
                100 <= response.status < 200
                and response.status != 101
            ):
                break

            print(f"\nПромежуточный HTTP-ответ: {response.status}")
            response.close()
            response = http.client.HTTPResponse(connection)
            response.begin()
        else:
            raise RuntimeError("слишком много промежуточных HTTP-ответов")

        elapsed = (time.perf_counter() - start) * 1000

        version = {
            10: "HTTP/1.0",
            11: "HTTP/1.1",
        }.get(response.version, f"HTTP version={response.version}")

        print(
            f"\nПолучен ответ: {version} "
            f"{response.status} {response.reason}"
        )

        print(
            f"От отправки запроса до получения заголовков: "
            f"{elapsed:.1f} мс."
        )

        print("\nЗаголовки ответа:")
        for name, value in response.getheaders():
            print(f"  {name}: {value}")

        if 200 <= response.status < 300:
            print("\nСервер сообщил об успешной обработке запроса.")
        elif 300 <= response.status < 400:
            print(
                "\nСервер вернул ответ класса 3xx."
                "\nЕсли это перенаправление, адрес указан в Location."
                "\nСкрипт автоматически по нему не переходит."
            )
        elif 400 <= response.status < 500:
            print(
                "\nHTTP-сервер доступен, но сообщил об ошибке"
                "\nкласса 4xx, например 404 — страница не найдена."
            )
        elif response.status >= 500:
            print(
                "\nHTTP-сервер ответил ошибкой класса 5xx."
                "\nПроблема может быть в приложении или upstream-сервисе."
            )

        print(
            "\nТело страницы не скачиваем и не отображаем."
            "\nHTTP-ответ получен; соединение закрываем."
        )

        return True

    except ssl.SSLCertVerificationError as error:
        print(f"\nНе прошла проверка TLS-сертификата: {error}")
        print(
            "TCP работал, но доверенное HTTPS-соединение"
            "\nустановить не удалось. Проверку не отключаем."
            "\nПри вводе IP сертификат должен содержать именно"
            "\nэтот IP; обычно для HTTPS следует вводить домен."
        )

    except ssl.SSLError as error:
        print(f"\nОшибка TLS: {error}")
        print("Проверьте, поддерживает ли выбранный порт HTTPS.")

    except ConnectionRefusedError:
        print(
            "\nВ TCP-соединении отказано."
            "\nСервис может не слушать порт или соединение отклоняется."
        )

    except (socket.timeout, TimeoutError):
        print(
            "\nТекущая сетевая операция превысила таймаут."
            "\nСмотрите последний начатый шаг: TCP, TLS или HTTP."
        )

    except (OSError, http.client.HTTPException, RuntimeError) as error:
        print(f"\nПроверку завершить не удалось: {error}")

    finally:
        if response is not None:
            response.close()

        if connection is not None:
            connection.close()

    return False


def main():
    try:
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            print(
                "Для ARP и traceroute нужны права root."
                "\nЗапуск: sudo .venv/bin/python get_info.py",
                file=sys.stderr,
            )
            return 1

        (
            target,
            scheme,
            port,
            path,
            max_hops,
            timeout,
        ) = ask_settings()

        target_ip = resolve_target(target, timeout)

        show_route(target_ip, timeout)

        trace_reached = trace_route(
            target_ip,
            port,
            max_hops,
            timeout,
        )

        http_received = request_site(
            target,
            target_ip,
            scheme,
            port,
            path,
            timeout,
        )

        heading("ИТОГ")

        print(f"\nДомен или адрес: {target}")
        print(f"Выбранный IPv4: {target_ip}")
        print(f"Протокол и порт: {scheme}, {port}")

        print(
            "Traceroute:",
            "получен TCP-ответ цели"
            if trace_reached
            else "конечный TCP-ответ не получен",
        )

        print(
            "HTTP:",
            "ответ получен"
            if http_received
            else "проверка не завершена",
        )

        if http_received and not trace_reached:
            print(
                "\nHTTP работает, хотя traceroute не достиг цели."
                "\nОтветы на диагностические пробы и доступность"
                "\nприложения — разные проверки."
            )

        print(
            "\nУпрощённая вложенность данных для HTTPS:"
            "\n  HTTP → TLS → TCP → IP → локальный канал"
            "\n\nДанные могут делиться на несколько сегментов и пакетов."
            "\nТочный путь внутри инфраструктуры сайта этот CLI"
            "\nне видит: для него нужны логи, метрики и трассировка"
            "\nсо стороны сервера."
        )

        return 0 if http_received else 2

    except (KeyboardInterrupt, EOFError):
        print("\nРабота остановлена пользователем.")
        return 130

    except Exception as error:
        print(f"\nОшибка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())