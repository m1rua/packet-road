output "vm_name" {
  description = "Name of the Terraform-managed VM."
  value       = libvirt_domain.lab.name
}

output "ipv4_address" {
  description = "DHCP address; obtaining a lease does not guarantee cloud-init has finished."
  value       = local.ipv4_address
}

output "ssh_command" {
  description = "Run on Arch after cloud-init completes."
  value       = "ssh ${var.ssh_user}@${local.ipv4_address}"
}

output "ansible_inventory" {
  description = "Separate inventory for the NEW VM; the original inventory is not changed."
  value       = "[lab]\n${var.vm_name} ansible_host=${local.ipv4_address} ansible_user=${var.ssh_user} ansible_python_interpreter=/usr/bin/python3\n"
}
