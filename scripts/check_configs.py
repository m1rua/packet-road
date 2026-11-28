"""Validate repository YAML, Grafana references and Kubernetes Pod schemas."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_URL = (
    "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/"
    "14355cdd490a43d21e05985668815a36a6f97da6/"
    "v1.37.0-standalone-strict/pod-v1.json"
)
SCHEMA_SHA256 = "e7629f45cce4493f02b9b5d97638a5b832fb5f28cdc978a5d786ab5b2981f617"


class ConfigError(ValueError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ConfigError(f"duplicate YAML key {key!r}, line {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(path):
    try:
        return list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader))
    except (yaml.YAMLError, ConfigError) as error:
        raise ConfigError(f"{path}: {error}") from error


def one_document(path):
    documents = load_yaml(path)
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise ConfigError(f"{path}: expected one YAML object")
    return documents[0]


def pod_schema(path=None):
    if path:
        content = path.read_bytes()
    else:
        with urllib.request.urlopen(SCHEMA_URL, timeout=30) as response:
            content = response.read(2 * 1024 * 1024)
    if hashlib.sha256(content).hexdigest() != SCHEMA_SHA256:
        raise ConfigError("Kubernetes schema checksum mismatch")
    return json.loads(content)


def check_pod(document, schema, source):
    if document.get("apiVersion") != "v1" or document.get("kind") != "Pod":
        raise ConfigError(f"{source}: expected a v1 Pod")
    validator = jsonschema.Draft4Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        location = ".".join(map(str, error.path)) or "root"
        raise ConfigError(f"{source}: {location}: {error.message}")


def check_grafana(root):
    config = one_document(root / "monitoring/grafana/provisioning/datasources/prometheus.yml")
    uids = {source["uid"] for source in config["datasources"] if source["type"] == "prometheus"}

    def walk(value, source):
        if isinstance(value, dict):
            datasource = value.get("datasource")
            if isinstance(datasource, dict) and datasource.get("type") == "prometheus":
                if datasource.get("uid") not in uids:
                    raise ConfigError(f"{source}: unknown Prometheus datasource UID")
            for child in value.values():
                walk(child, source)
        elif isinstance(value, list):
            for child in value:
                walk(child, source)

    dashboards = list((root / "monitoring/grafana/dashboards").glob("*.json"))
    if not dashboards:
        raise ConfigError("No Grafana dashboards found")
    for path in dashboards:
        walk(json.loads(path.read_text(encoding="utf-8")), path)

    provider = one_document(root / "monitoring/grafana/provisioning/dashboards/dashboards.yml")
    play = load_yaml(root / "ansible/setup.yml")[0]
    grafana = next(task["community.docker.docker_container"] for task in play[0]["tasks"]
                   if task.get("community.docker.docker_container", {}).get("name") == "grafana")
    for entry in provider["providers"]:
        target = entry["options"]["path"]
        if not any(volume.endswith(f":{target}:ro") for volume in grafana["volumes"]):
            raise ConfigError(f"Grafana provider directory {target} is not mounted read-only")


def check_image_defaults(root):
    play = load_yaml(root / "ansible/setup.yml")[0][0]
    values = one_document(root / "helm/packet-road/values.yaml")
    pod = one_document(root / "k8s/packet-road-pod.yml")
    images = {
        play["vars"]["packet_road_image"],
        f"{values['image']['repository']}:{values['image']['tag']}",
        pod["spec"]["containers"][0]["image"],
    }
    if len(images) != 1:
        raise ConfigError("CLI image differs between Ansible, Helm and the plain Pod manifest")


def check_tracked_files(root):
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root, text=True).split("\0")
    for name in tracked:
        if name in (".env", "ansible/vault.yml") or name.endswith((".tfstate", ".tfvars", ".tfplan")):
            raise ConfigError(f"Local credentials/state must not be tracked: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pod-schema", type=Path, help="Verified local schema for offline checks")
    parser.add_argument("--rendered-pod", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        check_tracked_files(ROOT)
        files = set()
        for directory in ("ansible", "monitoring", "k8s", ".github/workflows"):
            for extension in ("*.yml", "*.yaml"):
                files.update((ROOT / directory).rglob(extension))
        files.update(ROOT / "helm/packet-road" / name for name in ("Chart.yaml", "values.yaml"))
        files.discard(ROOT / "ansible/vault.yml")
        for path in sorted(files):
            load_yaml(path)
        schema = pod_schema(args.pod_schema)
        for path in [ROOT / "k8s/packet-road-pod.yml", *args.rendered_pod]:
            check_pod(one_document(path), schema, path)
        check_grafana(ROOT)
        check_image_defaults(ROOT)
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        parser.exit(1, f"Config check failed: {error}\n")
    print("YAML, Kubernetes Pods, Grafana references and deployment image defaults: OK")


if __name__ == "__main__":
    main()
