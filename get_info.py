import subprocess

ip_addr = subprocess.run(["ip", "route"], capture_output=True, text=True)

gateway = ip_addr.stdout[ip_addr.stdout.find("via")+4:ip_addr.stdout.find('dev')-1]
net_interface = ip_addr.stdout[ip_addr.stdout.find("dev")+4:ip_addr.stdout.find("proto")-1]
usrIP = ip_addr.stdout[ip_addr.stdout.find("src")+4:ip_addr.stdout.find("metric")-1]


print("your IP-addres:", usrIP)
print("your network interface:", net_interface)
print("your gateway:", gateway)

