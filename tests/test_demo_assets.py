import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, is_zipfile

from utils.generate_demo_assets import DEMO_SWF_COLORS, generate


def _read_swf_tag_codes(content):
    if content[:3] != b"FWS" or content[3] < 9:
        raise AssertionError("Expected an uncompressed SWF version 9 or newer.")
    if int.from_bytes(content[4:8], "little") != len(content):
        raise AssertionError("SWF header length does not match the file.")

    rect_bits = content[8] >> 3
    rect_bytes = (5 + 4 * rect_bits + 7) // 8
    offset = 8 + rect_bytes + 4
    codes = []
    while offset < len(content):
        header = int.from_bytes(content[offset:offset + 2], "little")
        offset += 2
        code = header >> 6
        length = header & 0x3F
        if length == 0x3F:
            length = int.from_bytes(content[offset:offset + 4], "little")
            offset += 4
        offset += length
        if offset > len(content):
            raise AssertionError("SWF tag extends past the end of the file.")
        codes.append(code)
        if code == 0:
            break
    if offset != len(content) or not codes or codes[-1] != 0:
        raise AssertionError("SWF tags are not terminated cleanly.")
    return codes


class DemoAssetTests(unittest.TestCase):
    def test_generated_manifest_points_to_valid_swf_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            generate(output)
            manifest = json.loads(
                (output / "versions.json").read_text(encoding="utf-8")
            )

            expected_keys = {
                f"swf/{name}.swf"
                for name in DEMO_SWF_COLORS
                if name not in ("pnz-city-container", "pnz-city")
            }
            self.assertTrue(expected_keys.issubset(manifest))

            for asset_path, digest in manifest.items():
                relative_path = Path(asset_path)
                versioned_name = (
                    f"{relative_path.stem}_{digest}{relative_path.suffix}"
                )
                asset = output / relative_path.parent / versioned_name
                with self.subTest(asset=asset_path):
                    content = asset.read_bytes()
                    self.assertEqual(
                        hashlib.md5(content).hexdigest(),
                        digest,
                    )
                    if relative_path.suffix == ".swf":
                        self.assertEqual(
                            _read_swf_tag_codes(content),
                            [32, 26, 1, 0],
                        )
                    else:
                        self.assertTrue(is_zipfile(asset))
                        with ZipFile(asset) as archive:
                            self.assertIn(
                                "modules/relations.xml",
                                archive.namelist(),
                            )

            for name in ("pnz-city-container", "pnz-city"):
                with self.subTest(asset=name):
                    self.assertEqual(
                        _read_swf_tag_codes(
                            (output / f"{name}.swf").read_bytes()
                        ),
                        [32, 26, 1, 0],
                    )


if __name__ == "__main__":
    unittest.main()
