# Planning tests use a mocked provider: no libvirt daemon, KVM or image download.
mock_provider "libvirt" {
  mock_resource "libvirt_volume" {
    defaults = {
      path = "/var/lib/libvirt/images/mock.qcow2"
    }
  }

  mock_data "libvirt_domain_interface_addresses" {
    defaults = {
      interfaces = [{
        name   = "vnet-test"
        hwaddr = "52:54:00:00:00:01"
        addrs  = [{ addr = "192.168.122.50", prefix = 24, type = "ipv4" }]
      }]
    }
  }
}

variables {
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnlyNotARealLoginKey test@ci"
}

run "default_lab" {
  command = plan

  assert {
    condition     = libvirt_domain.lab.name == "packet-road-tf" && libvirt_domain.lab.autostart == false
    error_message = "Create a separately named VM without host autostart."
  }

  assert {
    condition     = libvirt_domain.lab.memory == 4096 && libvirt_domain.lab.memory_unit == "MiB"
    error_message = "Guest memory must be expressed explicitly in MiB."
  }

  assert {
    condition     = libvirt_volume.root.capacity == 20 * 1024 * 1024 * 1024 && libvirt_volume.root.allocation == 0
    error_message = "The lab disk must be sparse with a 20 GiB virtual capacity."
  }

  assert {
    condition     = libvirt_domain.lab.devices.interfaces[0].source.network.network == "default"
    error_message = "Attach to the existing default network."
  }

  assert {
    condition     = yamldecode(libvirt_cloudinit_disk.seed.user_data).ssh_pwauth == false
    error_message = "SSH password authentication must stay disabled."
  }

  assert {
    condition     = yamldecode(libvirt_cloudinit_disk.seed.user_data).users[0].ssh_authorized_keys[0] == var.ssh_public_key
    error_message = "Cloud-init must receive the supplied public key without modification."
  }
}

run "custom_resources" {
  command = plan
  variables {
    vm_name    = "packet-road-test"
    memory_mib = 2048
    vcpu       = 1
    disk_gib   = 12
    ssh_user   = "devops"
  }

  assert {
    condition     = libvirt_domain.lab.name == "packet-road-test" && libvirt_domain.lab.memory == 2048 && libvirt_domain.lab.vcpu == 1
    error_message = "Overrides must reach the domain definition."
  }

  assert {
    condition     = libvirt_volume.root.capacity == 12 * 1024 * 1024 * 1024 && yamldecode(libvirt_cloudinit_disk.seed.user_data).users[0].name == "devops"
    error_message = "Disk and guest user overrides must reach their resources."
  }
}

run "reject_private_key" {
  command = plan
  variables {
    ssh_public_key = "-----BEGIN OPENSSH PRIVATE KEY-----"
  }
  expect_failures = [var.ssh_public_key]
}

run "reject_small_disk" {
  command = plan
  variables {
    disk_gib = 1
  }
  expect_failures = [var.disk_gib]
}
