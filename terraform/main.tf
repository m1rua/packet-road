# Use the host's existing pool and network without adopting or changing them.
resource "libvirt_volume" "base" {
  name = "${var.vm_name}-base.qcow2"
  pool = var.storage_pool
  target = {
    format = { type = "qcow2" }
  }
  create = {
    content = { url = var.cloud_image }
  }
}

# Writable overlay; the downloaded base image must remain in place.
resource "libvirt_volume" "root" {
  name       = "${var.vm_name}-root.qcow2"
  pool       = var.storage_pool
  capacity   = var.disk_gib * 1024 * 1024 * 1024
  allocation = 0
  target = {
    format = { type = "qcow2" }
  }
  backing_store = {
    path   = libvirt_volume.base.path
    format = { type = "qcow2" }
  }
}

resource "libvirt_cloudinit_disk" "seed" {
  name = "${var.vm_name}-seed"
  meta_data = yamlencode({
    instance-id    = var.vm_name
    local-hostname = var.vm_name
  })
  user_data = templatefile("${path.module}/cloud-init/user-data.yaml.tftpl", {
    hostname       = var.vm_name
    ssh_user       = var.ssh_user
    ssh_public_key = trimspace(var.ssh_public_key)
  })
  network_config = yamlencode({
    version = 2
    ethernets = {
      primary = {
        match = { name = "en*" }
        dhcp4 = true
      }
    }
  })
}

resource "libvirt_volume" "seed" {
  name = "${var.vm_name}-seed.iso"
  pool = var.storage_pool
  create = {
    content = { url = libvirt_cloudinit_disk.seed.path }
  }
}

resource "libvirt_domain" "lab" {
  name        = var.vm_name
  type        = "kvm"
  memory      = var.memory_mib
  memory_unit = "MiB"
  vcpu        = var.vcpu
  running     = true
  autostart   = false

  os = {
    type         = "hvm"
    type_arch    = "x86_64"
    type_machine = "q35"
    boot_devices = [{ dev = "hd" }]
  }

  devices = {
    disks = [
      {
        device = "disk"
        driver = { type = "qcow2" }
        source = {
          volume = {
            pool   = libvirt_volume.root.pool
            volume = libvirt_volume.root.name
          }
        }
        target = { dev = "vda", bus = "virtio" }
      },
      {
        device    = "cdrom"
        read_only = true
        driver    = { type = "raw" }
        source = {
          volume = {
            pool   = libvirt_volume.seed.pool
            volume = libvirt_volume.seed.name
          }
        }
        target = { dev = "sda", bus = "sata" }
      }
    ]
    interfaces = [
      {
        type   = "network"
        model  = { type = "virtio" }
        source = { network = { network = var.network_name } }
        wait_for_ip = {
          source  = "lease"
          network = "0.0.0.0/0"
          timeout = 300
        }
      }
    ]
    consoles = [{
      target = { type = "serial", port = 0 }
    }]
  }
}

data "libvirt_domain_interface_addresses" "lab" {
  domain = libvirt_domain.lab.name
  source = "lease"
}

locals {
  ipv4_addresses = flatten([
    for interface in data.libvirt_domain_interface_addresses.lab.interfaces : [
      for address in interface.addrs : address.addr if address.type == "ipv4"
    ]
  ])
  ipv4_address = one(local.ipv4_addresses)
}
