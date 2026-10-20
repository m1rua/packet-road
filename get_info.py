from scapy.all import conf, IP, ICMP, TCP, sr1
from getmac import get_mac_address 
import os
import sys
import time
import random
from dns import message, query, exception

if os.geteuid() != 0:
    print("The script was not executed via sudo.")
    sys.exit(1)

net_interface, usr_IP, gateway = conf.route.route("8.8.8.8")
mac = get_mac_address(net_interface, gateway)


print ("your network interface:", net_interface)
print ("source IP:", usr_IP)
print ("gateway:", gateway, "\n")

if mac is not None: 
    print ("ARP search MAC address for this gateway:", mac)
else:
    print ("cant find your MAC-addres, check your internet connection / router / turn off VPN ")


#DNS resolving + get target IP addr
target_domain = input ("\nEnter domain or IP: ")
root_servers_list = ["198.41.0.4", "199.9.14.201", "192.33.4.12", "199.7.91.13", "192.203.230.10"]

request = message.make_query (target_domain, "A")
for server_ip in root_servers_list:
    try:
        print (f"sending a query to the root server: {server_ip}")
        response = query.udp(request, server_ip, timeout=2)
        print (f"successful response from {server_ip}")
        print(response)
        break
    except excpetion.timeout:
        print (f"server timeout exceeded, trying another one root-server")
    except Exception as e:
        print (f"an error occurred during polling {server_ip}: {e}")





target = input("\n enter the ip: ")
max_hops = 30
dport = 443
sport = random.randint(1024, 65535)  # один порт источника на все пробы

for ttl in range(1, max_hops + 1):
    packet = IP(dst=target, ttl=ttl) / TCP(sport=sport, dport=dport, flags="S")

    start = time.perf_counter()
    reply = sr1(packet, verbose=0, timeout=2)
    rtt = (time.perf_counter() - start) * 1000  # секунды -> мс

    if reply is None:
        print(f"{ttl:2d}  *  (time-out)")
        continue

    if reply.haslayer(ICMP) and reply[ICMP].type == 11:
        print(f"{ttl:2d}  {reply.src}  {rtt:.1f} ms")
    elif reply.haslayer(TCP):
        flags = str(reply[TCP].flags)
        if "R" in flags:
            print(f"{ttl:2d}  {reply.src}  {rtt:.1f} ms  (target reached, port {dport} is closed)")
        elif "S" in flags and "A" in flags:
            print(f"{ttl:2d}  {reply.src}  {rtt:.1f} ms  (target reached, port {dport} is open)")
        else:
            print(f"{ttl:2d}  {reply.src}  {rtt:.1f} ms  (unexpected TCP flags: {flags})")
        break
    else:
        print(f"{ttl:2d}  {reply.src}  {rtt:.1f} ms  (unexpected reply, possibly filtered)")
else:
    print(f"target was not reached within {max_hops} hops")