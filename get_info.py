import subprocess

ip_addr = subprocess.run(["ip", "route"], capture_output=True, text=True)

ip_neigh = subprocess.run(["ip", "neigh"], capture_output=True, text=True)

gateway = ip_addr.stdout[ip_addr.stdout.find("via") + 4 :ip_addr.stdout.find('dev') - 1]
net_interface = ip_addr.stdout[ip_addr.stdout.find("dev") + 4:ip_addr.stdout.find("proto") - 1]
usrIP = ip_addr.stdout[ip_addr.stdout.find("src") + 4:ip_addr.stdout.find("metric")- 1 ]
mac = ip_neigh.stdout[ip_neigh.stdout.find("lladdr") + 7 :ip_neigh.stdout.find("REACHABLE") - 1]

print("Your IP-addres:", usrIP, ",", "network interface:", net_interface, ",", "gateway:", gateway)
print("ARP: 'who is MAC-addres for this gateway?'")
print ("MAC-addres for this gataway is:", mac)
