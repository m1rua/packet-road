terraform {
  required_version = ">= 1.6.0, < 2.0.0"
}

# Provider-neutral contract only: no VM or paid resource is created.
# Add a provider module after choosing provider, region, budget and network plan.
variable "server_address" {
  type        = string
  description = "Existing server IPv4/IPv6 or DNS address; not provisioned by this module"
  validation {
    condition     = can(regex("^[a-zA-Z0-9.:-]+$", var.server_address))
    error_message = "Provide an address or hostname, not a URL."
  }
}
variable "ssh_user" {
  type    = string
  default = "ubuntu"
  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]*$", var.ssh_user))
    error_message = "Invalid SSH username."
  }
}
output "ansible_inventory" {
  value = "[k3s]\npacket-road ansible_host=${var.server_address} ansible_user=${var.ssh_user}\n"
}
