import hashlib
import json
import struct
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "demo-assets"
CONFIG_FILES = {
    "avatarAppearance/appearance.xml": (
        "<appearance><boy/><girl/></appearance>"
    ),
    "inventory/bathroom.xml": "<config/>",
    "inventory/boyClothes.xml": "<config/>",
    "inventory/decor.xml": "<config/>",
    "inventory/extend/clothesRules.xml": "<config/>",
    "inventory/extend/clothesSets.xml": "<config/>",
    "inventory/furniture.xml": "<config/>",
    "inventory/game.xml": "<config/>",
    "inventory/girlClothes.xml": "<config/>",
    "inventory/kitchen.xml": "<config/>",
    "inventory/present.xml": "<config/>",
    "inventory/roomLayout.xml": "<config/>",
    "modules/achievements.xml": "<config/>",
    "modules/acl.xml": "<config/>",
    "modules/craft.xml": "<config/>",
    "modules/relations.xml": "<relations><statuses/><progresses/></relations>",
    "modules/trophies.xml": "<config/>",
}
DEMO_SWF_COLORS = {
    "Ui": (22, 38, 62),
    "UiInit": (37, 76, 110),
    "UiLang_pl": (43, 92, 75),
    "AvatarIcons": (108, 76, 50),
    "AvatarAnimation": (91, 55, 111),
    "pnz-city-container": (29, 66, 75),
    "pnz-city": (57, 78, 98),
}


class _BitWriter:
    def __init__(self):
        self._value = 0
        self._bit_count = 0
        self._bytes = bytearray()

    def write(self, value, bit_count):
        if bit_count < 0 or value < 0 or value >= 1 << bit_count:
            raise ValueError("Bit field value does not fit its width.")
        for shift in range(bit_count - 1, -1, -1):
            self._value = (self._value << 1) | ((value >> shift) & 1)
            self._bit_count += 1
            if self._bit_count == 8:
                self._bytes.append(self._value)
                self._value = 0
                self._bit_count = 0

    def write_signed(self, value, bit_count):
        minimum = -(1 << (bit_count - 1))
        maximum = (1 << (bit_count - 1)) - 1
        if not minimum <= value <= maximum:
            raise ValueError("Signed bit field value does not fit its width.")
        self.write(value & ((1 << bit_count) - 1), bit_count)

    def finish(self):
        if self._bit_count:
            self._bytes.append(self._value << (8 - self._bit_count))
            self._value = 0
            self._bit_count = 0
        return bytes(self._bytes)


def _signed_bit_width(values):
    return max(
        1,
        max(
            (value.bit_length() + 1 if value >= 0
             else (~value).bit_length() + 1)
            for value in values
        ),
    )


def _swf_rect(x_min, x_max, y_min, y_max):
    coordinates = (x_min, x_max, y_min, y_max)
    bit_width = _signed_bit_width(coordinates)
    writer = _BitWriter()
    writer.write(bit_width, 5)
    for coordinate in coordinates:
        writer.write_signed(coordinate, bit_width)
    return writer.finish()


def _swf_tag(code, payload=b""):
    length = len(payload)
    if length < 63:
        header = struct.pack("<H", (code << 6) | length)
    else:
        header = struct.pack("<HI", (code << 6) | 63, length)
    return header + payload


def _straight_edge(writer, delta_x, delta_y, bit_width):
    writer.write(1, 1)
    writer.write(1, 1)
    writer.write(bit_width - 2, 4)
    writer.write(1, 1)
    writer.write_signed(delta_x, bit_width)
    writer.write_signed(delta_y, bit_width)


def _demo_swf(color):
    width_twips = 6400
    height_twips = 4800
    bounds = _swf_rect(0, width_twips, 0, height_twips)

    shape_records = _BitWriter()
    shape_records.write(1, 4)
    shape_records.write(0, 4)
    shape_records.write(0, 1)
    shape_records.write(0, 1)
    shape_records.write(0, 1)
    shape_records.write(0, 1)
    shape_records.write(1, 1)
    shape_records.write(1, 1)
    shape_records.write(1, 5)
    shape_records.write_signed(0, 1)
    shape_records.write_signed(0, 1)
    shape_records.write(1, 1)

    edge_width = _signed_bit_width(
        (width_twips, height_twips, -width_twips, -height_twips)
    )
    for delta_x, delta_y in (
        (width_twips, 0),
        (0, height_twips),
        (-width_twips, 0),
        (0, -height_twips),
    ):
        _straight_edge(shape_records, delta_x, delta_y, edge_width)

    shape_records.write(0, 6)
    shape_data = shape_records.finish()
    shape_payload = (
        struct.pack("<H", 1)
        + bounds
        + b"\x01\x00"
        + bytes(color)
        + b"\x00\x10"
        + shape_data
    )
    define_shape = _swf_tag(32, shape_payload)

    matrix = _BitWriter()
    matrix.write(0, 1)
    matrix.write(0, 1)
    matrix.write(1, 1)
    matrix.write(1, 5)
    matrix.write_signed(0, 1)
    matrix.write_signed(0, 1)
    place_object = _swf_tag(
        26,
        b"\x06" + struct.pack("<HH", 1, 1) + matrix.finish(),
    )
    frame_tags = define_shape + place_object + _swf_tag(1) + _swf_tag(0)
    body = bounds + struct.pack("<HH", 12 * 256, 1) + frame_tags
    return b"FWS\x09" + struct.pack("<I", 8 + len(body)) + body


def _write_config_archive(path):
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(CONFIG_FILES.items()):
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content.encode("utf-8"))
    return hashlib.md5(path.read_bytes()).hexdigest()


def generate(output_dir=OUTPUT):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    versions = {
        f"swf/{name}.swf": hashlib.md5(
            _demo_swf(DEMO_SWF_COLORS[name])
        ).hexdigest()
        for name in DEMO_SWF_COLORS
        if name not in ("pnz-city-container", "pnz-city")
    }

    data_dir = output_dir / "data"
    data_dir.mkdir(exist_ok=True)
    for language in ("fb_pl", "fb_tr"):
        config_path = data_dir / f"config_{language}.zip"
        config_hash = _write_config_archive(config_path)
        config_path.replace(data_dir / f"config_{language}_{config_hash}.zip")
        versions[f"data/config_{language}.zip"] = config_hash

    swf_dir = output_dir / "swf"
    swf_dir.mkdir(exist_ok=True)
    for name in (
        "Ui", "UiInit", "UiLang_pl", "AvatarIcons", "AvatarAnimation"
    ):
        swf = _demo_swf(DEMO_SWF_COLORS[name])
        swf_hash = versions[f"swf/{name}.swf"]
        (swf_dir / f"{name}_{swf_hash}.swf").write_bytes(swf)

    for name in ("pnz-city-container", "pnz-city"):
        (output_dir / f"{name}.swf").write_bytes(
            _demo_swf(DEMO_SWF_COLORS[name])
        )
    (output_dir / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<rect width="16" height="16" rx="3" fill="#435a78"/>'
        '<text x="3" y="12" fill="white" font-size="11">T</text></svg>\n',
        encoding="utf-8",
    )
    (output_dir / "versions.json").write_text(
        json.dumps(versions, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    generate()
