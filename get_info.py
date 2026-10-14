from scapy.all import conf
from getmac import get_mac_address 

net_interface, usr_IP, gateway = conf.route.route("8.8.8.8")
mac = get_mac_address(net_interface, gateway)


print ("your network interface:", net_interface)
print ("source IP:", usr_IP)
print ("gateway:", gateway, "\n")

if mac != "None": 
    print ("ARP search MAC address for this gateway:", mac)
else:
    print ("cant find your MAC-addres, check your internet connection / router / turn off VPN ")