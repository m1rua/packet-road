variable "libvirt_uri" {
  description = "Local libvirt connection on the Arch host."
  type        = string
  default     = "qemu:///system"
}

variable "vm_name" {
  description = "Name of a NEW VM; do not reuse ubuntu26.04 or existing volume names."
  type        = string
  default     = "packet-road-tf"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,49}$", var.vm_name))
    error_message = "Use a lowercase hostname, starting with a letter, up to 50 characters."
  }
}

variable "memory_mib" {
  description = "Guest memory in MiB. Check free RAM on Arch before applying."
  type        = number
  default     = 4096

  validation {
    condition     = var.memory_mib >= 1024 && floor(var.memory_mib) == var.memory_mib
    error_message = "memory_mib must be an integer of at least 1024."
  }
}

variable "vcpu" {
  description = "Number of virtual CPUs."
  type        = number
  default     = 2

  validation {
    condition     = var.vcpu >= 1 && floor(var.vcpu) == var.vcpu
    error_message = "vcpu must be a positive integer."
  }
}

variable "disk_gib" {
  description = "Virtual disk capacity; sparse allocation does not reserve physical host space."
  type        = number
  default     = 20

  validation {
    condition     = var.disk_gib >= 10 && floor(var.disk_gib) == var.disk_gib
    error_message = "disk_gib must be an integer of at least 10."
  }
}

variable "storage_pool" {
  description = "Existing active libvirt storage pool. Terraform does not manage the pool."
  type        = string
  default     = "default"
}

variable "network_name" {
  description = "Existing active NAT network with DHCP. Terraform does not manage the network."
  type        = string
  default     = "default"
}

variable "cloud_image" {
  description = "Ubuntu amd64 QCOW2 cloud image: HTTPS URL or absolute local path. Not an installer ISO."
  type        = string
  default     = "https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img"

  validation {
    condition     = startswith(var.cloud_image, "https://") || startswith(var.cloud_image, "/")
    error_message = "Use an HTTPS URL or an absolute path to a verified local QCOW2 cloud image."
  }
}

variable "ssh_user" {
  description = "Cloud-init user with key-only SSH and passwordless sudo for Ansible."
  type        = string
  default     = "platinum"

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,30}$", var.ssh_user)) && var.ssh_user != "root"
    error_message = "Use a valid non-root Linux username."
  }
}

variable "ssh_public_key" {
  description = "Contents of your .pub file, never the private key. No default key is provided."
  type        = string

  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[^ ]+) [A-Za-z0-9+/]+=*( .*)?$", trimspace(var.ssh_public_key)))
    error_message = "Provide one OpenSSH PUBLIC key, for example the contents of ~/.ssh/id_ed25519.pub."
  }
}
