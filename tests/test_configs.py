import json
from pathlib import Path
import tempfile
import unittest

from scripts.check_configs import ConfigError, check_grafana, check_image_defaults, load_yaml


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_duplicate_restart_policy_is_rejected(self):
        path = self.write("pod.yaml", "spec:\n  restartPolicy: Never\n  restartPolicy: Always\n")
        with self.assertRaisesRegex(ConfigError, "duplicate YAML key 'restartPolicy'"):
            load_yaml(path)

    def test_deployment_tag_drift_is_rejected(self):
        self.write("ansible/setup.yml", "- vars:\n    packet_road_image: ghcr.io/test/app:old\n")
        self.write("helm/packet-road/values.yaml", "image:\n  repository: ghcr.io/test/app\n  tag: new\n")
        self.write("k8s/packet-road-pod.yml", "spec:\n  containers:\n    - image: ghcr.io/test/app:new\n")
        with self.assertRaisesRegex(ConfigError, "CLI image differs"):
            check_image_defaults(self.root)

    def test_dashboard_with_missing_datasource_is_rejected(self):
        self.write("monitoring/grafana/provisioning/datasources/prometheus.yml",
                   "datasources:\n  - type: prometheus\n    uid: expected\n")
        self.write("monitoring/grafana/dashboards/test.json", json.dumps({
            "panels": [{"datasource": {"type": "prometheus", "uid": "missing"}}],
        }))
        with self.assertRaisesRegex(ConfigError, "unknown Prometheus datasource"):
            check_grafana(self.root)
