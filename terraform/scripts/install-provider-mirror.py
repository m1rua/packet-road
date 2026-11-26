"""Fetch the pinned official provider when Terraform Registry is geo-blocked."""

import hashlib
import json
from pathlib import Path
import platform
import shlex
import urllib.request


VERSION = "0.9.9"
# Official v0.9.9 release asset digest, also present in .terraform.lock.hcl.
SHA256 = "70a9d5af99a60179c7d38032662f443c3d2ad8bddab11d535c545c5c44273b2d"
ASSET = f"terraform-provider-libvirt_{VERSION}_linux_amd64.zip"
URL = (
    "https://github.com/dmacvicar/terraform-provider-libvirt/"
    f"releases/download/v{VERSION}/{ASSET}"
)


def main():
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise SystemExit("This lab mirror supports Linux amd64 (the Arch host).")

    root = Path(__file__).resolve().parents[1]
    mirror = root / ".provider-mirror"
    destination = mirror / "registry.terraform.io" / "dmacvicar" / "libvirt" / ASSET
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == SHA256:
        print("Verified provider archive already exists.")
    else:
        print(f"Downloading official libvirt {VERSION} release from GitHub...")
        with urllib.request.urlopen(URL, timeout=60) as response:
            archive = response.read(32 * 1024 * 1024)
        if hashlib.sha256(archive).hexdigest() != SHA256:
            raise SystemExit("Checksum mismatch; archive was not installed.")
        temporary = destination.with_suffix(".zip.tmp")
        temporary.write_bytes(archive)
        temporary.replace(destination)

    config = root / ".terraformrc.mirror"
    config.write_text(
        "provider_installation {\n"
        "  filesystem_mirror {\n"
        f"    path = {json.dumps(str(mirror))}\n"
        '    include = ["registry.terraform.io/dmacvicar/libvirt"]\n'
        "  }\n"
        "  direct {\n"
        '    exclude = ["registry.terraform.io/dmacvicar/libvirt"]\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    print("SHA256 verified. Mirror and CLI config created locally (ignored by Git).")
    print("Run this in your current shell before terraform init:")
    print(f"export TF_CLI_CONFIG_FILE={shlex.quote(str(config))}")


if __name__ == "__main__":
    main()
