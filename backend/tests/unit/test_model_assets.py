"""``model_assets`` 的单元测试：定位优先级、体积校验、解压与镜像回退。

不访问网络、不加载 dlib，全部用临时文件与假响应对象构造。

运行方式（项目根目录）::

    python -m unittest backend.tests.unit.test_model_assets -v
"""

import bz2
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.src.config import model_assets


class _FakeResponse:
    """最小的 urlopen 返回值：支持 with 语句、headers 与分块 read。"""

    def __init__(self, payload: bytes):
        self._payload = payload
        self._sent = False
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


class CandidateOrderTest(unittest.TestCase):
    def test_environment_variable_wins_over_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "from_env.dat"
            explicit = Path(tmp) / "explicit.dat"
            with patch.dict(os.environ, {model_assets.ENV_FACE_PREDICTOR: str(env_path)}):
                candidates = model_assets.candidate_face_predictor_paths(explicit)
            self.assertEqual(candidates[0], env_path)
            self.assertEqual(candidates[1], explicit)

    def test_candidates_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            explicit = Path(tmp) / "x.dat"
            with patch.dict(os.environ, {model_assets.ENV_FACE_PREDICTOR: str(explicit)}):
                candidates = model_assets.candidate_face_predictor_paths(explicit)
            self.assertEqual(len(candidates), len(set(candidates)))


class ValidationTest(unittest.TestCase):
    def test_missing_file_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(model_assets.is_valid_face_predictor(Path(tmp) / "nope.dat"))

    def test_truncated_file_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "small.dat"
            target.write_bytes(b"0" * 16)
            with patch.object(model_assets, "FACE_PREDICTOR_MIN_BYTES", 1024):
                self.assertFalse(model_assets.is_valid_face_predictor(target))

            target.write_bytes(b"0" * 2048)
            with patch.object(model_assets, "FACE_PREDICTOR_MIN_BYTES", 1024):
                self.assertTrue(model_assets.is_valid_face_predictor(target))

    def test_resolve_returns_existing_file_without_touching_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / model_assets.FACE_PREDICTOR_NAME
            target.write_bytes(b"0" * 4096)
            with patch.object(model_assets, "FACE_PREDICTOR_MIN_BYTES", 1024), \
                    patch.object(model_assets, "candidate_face_predictor_paths", return_value=(target,)):
                self.assertEqual(model_assets.resolve_face_predictor(download=False), target)

    def test_missing_model_without_download_raises_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / model_assets.FACE_PREDICTOR_NAME
            with patch.object(model_assets, "candidate_face_predictor_paths", return_value=(missing,)):
                with self.assertRaises(FileNotFoundError) as ctx:
                    model_assets.resolve_face_predictor(download=False)
            message = str(ctx.exception)
            self.assertIn(model_assets.FACE_PREDICTOR_NAME, message)
            self.assertIn(model_assets.ENV_FACE_PREDICTOR, message)
            self.assertIn(str(missing), message)


class DestinationTest(unittest.TestCase):
    def test_dat_suffix_is_treated_as_file(self):
        target = Path("C:/models") / model_assets.FACE_PREDICTOR_NAME
        self.assertEqual(model_assets._destination_candidates(target), [target])

    def test_directory_gets_file_name_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidates = model_assets._destination_candidates(Path(tmp))
            self.assertEqual(candidates, [Path(tmp) / model_assets.FACE_PREDICTOR_NAME])


class DownloadTest(unittest.TestCase):
    def test_extract_bz2_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.bz2"
            dst = Path(tmp) / "a.dat"
            src.write_bytes(bz2.compress(b"payload" * 100))
            model_assets._extract_bz2(src, dst)
            self.assertEqual(dst.read_bytes(), b"payload" * 100)

    def test_download_falls_back_to_next_mirror(self):
        payload = b"model-bytes" * 200
        archive = bz2.compress(payload)
        responses = [OSError("mirror down"), _FakeResponse(archive)]

        def fake_urlopen(request, timeout=None):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(model_assets, "FACE_PREDICTOR_MIN_BYTES", 64), \
                    patch.object(model_assets.urllib.request, "urlopen", side_effect=fake_urlopen):
                target = model_assets.download_face_predictor(Path(tmp))
            self.assertEqual(target.read_bytes(), payload)
            leftovers = [p.name for p in Path(tmp).iterdir() if p != target]
            self.assertEqual(leftovers, [])

    def test_download_failure_reports_mirror_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(model_assets.urllib.request, "urlopen", side_effect=OSError("offline")):
                with self.assertRaises(RuntimeError) as ctx:
                    model_assets.download_face_predictor(Path(tmp))
            self.assertIn("offline", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
