"""配置模型单元测试。"""

import json
import pytest

from attp.protocol_node.config.config import ProtocolNodeConfigFile


class TestLoad:
    def test_from_json(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "web": {"host": "127.0.0.1", "port": 8080},
            "storage": {"dataDir": "/tmp/attp", "dbPath": "test.db"},
            "analysis": {"enabled": True, "apiKey": "sk-xxx"},
        }))

        cfg = ProtocolNodeConfigFile.load(cfg_path)
        assert cfg.web.host == "127.0.0.1"
        assert cfg.web.port == 8080
        assert cfg.storage.data_dir == "/tmp/attp"
        assert cfg.analysis.enabled is True

    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = ProtocolNodeConfigFile.load(tmp_path / "nonexistent.json")
        assert cfg.web.host == "0.0.0.0"
        assert cfg.web.port == 9000

    def test_invalid_json_returns_defaults(self, tmp_path):
        cfg_path = tmp_path / "bad.json"
        cfg_path.write_text("{invalid json")
        cfg = ProtocolNodeConfigFile.load(cfg_path)
        assert cfg.web.port == 9000


class TestSave:
    def test_save_and_reload(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg = ProtocolNodeConfigFile(
            web={"host": "192.168.1.1", "port": 5000},
            storage={"data_dir": "/data", "db_path": "attp.db"},
        )
        cfg.save(cfg_path)

        loaded = ProtocolNodeConfigFile.load(cfg_path)
        assert loaded.web.host == "192.168.1.1"
        assert loaded.web.port == 5000
        assert loaded.storage.data_dir == "/data"


class TestDbPath:
    def test_get_db_path_joins(self):
        cfg = ProtocolNodeConfigFile(
            storage={"data_dir": "/tmp/attp", "db_path": "test.db"},
        )
        path = cfg.get_db_path()
        assert "test.db" in path

    def test_camel_case_alias(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({
            "storage": {"dataDir": "/camel", "dbPath": "c.db"},
        }))
        cfg = ProtocolNodeConfigFile.load(cfg_path)
        assert cfg.storage.data_dir == "/camel"
        assert cfg.storage.db_path == "c.db"
