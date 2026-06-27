from __future__ import annotations

import csv
import re
import struct
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Optional


@dataclass
class NoxNumericTable:
    source_path: str
    columns: list[str]
    rows: list[list[Any]]
    stream_offset: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def extract_nox_numeric_table(path: str | Path) -> NoxNumericTable:
    source = Path(path)
    data = source.read_bytes()
    candidates: list[NoxNumericTable] = []
    for offset in _nrbf_stream_offsets(data):
        try:
            parser = _RawNRBFParser(data[offset:])
            parser.parse()
        except Exception:
            continue
        columns = _extract_columns(parser.objects)
        if not columns:
            continue
        table = _table_from_columns(source, offset, columns)
        if table.rows:
            candidates.append(table)
    if not candidates:
        raise ValueError(f"No numeric NOVA table could be extracted from {source}")
    return max(candidates, key=lambda table: (len(table.rows), len(table.columns)))


def extract_nox_tree(target: str | Path) -> list[NoxNumericTable]:
    root = Path(target)
    paths = [root] if root.is_file() else sorted(root.rglob("*.nox"))
    tables = []
    for path in paths:
        try:
            tables.append(extract_nox_numeric_table(path))
        except ValueError:
            continue
    return tables


def write_nox_table_csv(table: NoxNumericTable, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(table.columns)
        writer.writerows(table.rows)
    return target


def write_nox_table_txt(table: NoxNumericTable, path: str | Path, delimiter: str = ";") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        handle.write(delimiter.join(table.columns) + "\n")
        for row in table.rows:
            handle.write(delimiter.join(_format_value(value) for value in row) + "\n")
    return target


def default_output_path(source_path: str | Path, output_root: str | Path, suffix: str = ".csv") -> Path:
    source = Path(source_path)
    return Path(output_root) / f"{source.stem}{suffix}"


def _extract_columns(objects: dict[int, Any]) -> list[tuple[str, list[Any]]]:
    columns: dict[str, list[Any]] = {}
    for obj in objects.values():
        if not isinstance(obj, dict) or obj.get("__class__") != "EcoChemie.Utils.Sequencer.CommandParameterDataArray":
            continue
        parameter = _deref(objects, obj.get("_parameter") or obj.get("CommandParameter+_parameter"))
        if not isinstance(parameter, dict):
            continue
        values = _list_values(objects, parameter.get("_value"))
        if not values:
            continue
        name = _column_label(
            _deref(objects, obj.get("CommandParameter+_text")) or obj.get("CommandParameter+_name") or "Column",
            _deref(objects, obj.get("CommandParameter+_unit")) or "",
        )
        if _is_useful_column(name, values):
            columns[name] = values
    if not columns:
        return []
    target_len = max(len(values) for values in columns.values())
    return [(name, values) for name, values in columns.items() if len(values) == target_len]


def _table_from_columns(source: Path, offset: int, columns: list[tuple[str, list[Any]]]) -> NoxNumericTable:
    headers = [name for name, _values in columns]
    row_count = min(len(values) for _name, values in columns) if columns else 0
    rows = [[values[idx] for _name, values in columns] for idx in range(row_count)]
    return NoxNumericTable(
        source_path=str(source),
        columns=headers,
        rows=rows,
        stream_offset=offset,
        metadata={"row_count": row_count, "column_count": len(headers)},
    )


def _nrbf_stream_offsets(data: bytes) -> list[int]:
    pattern = re.compile(b"\x00....\xff\xff\xff\xff\x01\x00\x00\x00\x00\x00\x00\x00", re.DOTALL)
    offsets = [match.start() for match in pattern.finditer(data)]
    return offsets or [0]


def _column_label(label: object, unit: object) -> str:
    text = str(label)
    unit_text = str(unit)
    if unit_text and unit_text not in text:
        return f"{text} ({unit_text})"
    return text


def _is_useful_column(name: str, values: list[Any]) -> bool:
    if len(values) < 2:
        return False
    if name.lower().startswith("raw "):
        return False
    return all(isinstance(value, (int, float, bool)) or value is None for value in values[:100])


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.15g}"
    return "" if value is None else str(value)


def _ref_id(value: Any) -> Optional[int]:
    if isinstance(value, dict) and set(value.keys()) == {"__ref__"}:
        return int(value["__ref__"])
    return None


def _deref(objects: dict[int, Any], value: Any) -> Any:
    seen: set[int] = set()
    while (ref_id := _ref_id(value)) is not None and ref_id not in seen:
        seen.add(ref_id)
        value = objects.get(ref_id)
    return value


def _list_values(objects: dict[int, Any], value: Any) -> Optional[list[Any]]:
    resolved = _deref(objects, value)
    if isinstance(resolved, dict) and "_items" in resolved:
        items = _deref(objects, resolved.get("_items"))
        if isinstance(items, list):
            return items[: int(resolved.get("_size", len(items)))]
    if isinstance(resolved, list):
        return resolved
    return None


class _RawNRBFParser:
    """Small BinaryFormatter reader for NOVA numeric extraction.

    It intentionally keeps object references unresolved so cyclic NOVA command
    graphs do not recurse. The record constants follow MS-NRBF.
    """

    def __init__(self, data: bytes) -> None:
        self._f = BytesIO(data)
        self.objects: dict[int, Any] = {}
        self._class_defs: dict[int, tuple[str, list[str], list[int], list[Any]]] = {}

    def parse(self) -> Any:
        if self._u8() != 0:
            raise ValueError("NRBF stream does not start with SerializationHeader")
        root_id = self._i32()
        self._i32()
        self._i32()
        self._i32()
        while True:
            raw = self._f.read(1)
            if not raw:
                break
            record_type = raw[0]
            if record_type == 11:
                break
            self._read_record(record_type)
        return self.objects.get(root_id)

    def _read_record(self, record_type: int) -> Any:
        if record_type == 12:
            self._i32()
            return self._lps()
        if record_type == 5:
            return self._read_class_with_members_and_types(has_library=True)
        if record_type == 4:
            return self._read_class_with_members_and_types(has_library=False)
        if record_type == 3:
            return self._read_class_with_members(has_library=True)
        if record_type == 2:
            return self._read_class_with_members(has_library=False)
        if record_type == 1:
            return self._read_class_with_id()
        if record_type == 6:
            return self._read_string()
        if record_type == 7:
            return self._read_binary_array()
        if record_type == 8:
            return self._primitive(self._u8())
        if record_type == 9:
            return {"__ref__": self._i32()}
        if record_type == 10:
            return None
        if record_type == 13:
            return [None] * self._u8()
        if record_type == 14:
            return [None] * self._i32()
        if record_type == 15:
            return self._read_array_single_primitive()
        if record_type == 16:
            return self._read_array_single_object()
        if record_type == 17:
            return self._read_array_single_object()
        raise ValueError(f"Unsupported NRBF record type {record_type} at {self._f.tell() - 1}")

    def _read_class_info(self) -> tuple[int, str, list[str]]:
        object_id = self._i32()
        class_name = self._lps()
        member_count = self._i32()
        member_names = [self._lps() for _ in range(member_count)]
        return object_id, class_name, member_names

    def _read_member_type_info(self, count: int) -> tuple[list[int], list[Any]]:
        binary_types = [self._u8() for _ in range(count)]
        additional = []
        for binary_type in binary_types:
            if binary_type in {0, 7}:
                additional.append(self._u8())
            elif binary_type == 3:
                additional.append(self._lps())
            elif binary_type == 4:
                additional.append((self._lps(), self._i32()))
            else:
                additional.append(None)
        return binary_types, additional

    def _read_class_with_members_and_types(self, has_library: bool) -> int:
        object_id, class_name, member_names = self._read_class_info()
        binary_types, additional = self._read_member_type_info(len(member_names))
        if has_library:
            self._i32()
        self._class_defs[object_id] = (class_name, member_names, binary_types, additional)
        values = [self._read_value(binary_type, extra) for binary_type, extra in zip(binary_types, additional)]
        self.objects[object_id] = {**dict(zip(member_names, values)), "__class__": class_name}
        return object_id

    def _read_class_with_members(self, has_library: bool) -> int:
        object_id, class_name, member_names = self._read_class_info()
        if has_library:
            self._i32()
        binary_types = [2] * len(member_names)
        additional = [None] * len(member_names)
        self._class_defs[object_id] = (class_name, member_names, binary_types, additional)
        values = [self._read_inline_value() for _ in member_names]
        self.objects[object_id] = {**dict(zip(member_names, values)), "__class__": class_name}
        return object_id

    def _read_class_with_id(self) -> int:
        object_id = self._i32()
        metadata_id = self._i32()
        class_name, member_names, binary_types, additional = self._class_defs[metadata_id]
        values = [self._read_value(binary_type, extra) for binary_type, extra in zip(binary_types, additional)]
        self.objects[object_id] = {**dict(zip(member_names, values)), "__class__": class_name}
        return object_id

    def _read_value(self, binary_type: int, additional: Any) -> Any:
        if binary_type == 0:
            return self._primitive(int(additional))
        return self._read_inline_value()

    def _read_inline_value(self) -> Any:
        raw = self._f.read(1)
        if not raw:
            return None
        return self._read_record(raw[0])

    def _read_string(self) -> str:
        object_id = self._i32()
        value = self._lps()
        self.objects[object_id] = value
        return value

    def _read_array_single_primitive(self) -> list[Any]:
        object_id = self._i32()
        length = self._i32()
        primitive_type = self._u8()
        values = [self._primitive(primitive_type) for _ in range(length)]
        self.objects[object_id] = values
        return values

    def _read_array_single_object(self) -> list[Any]:
        object_id = self._i32()
        length = self._i32()
        values = self._read_array_elements(length)
        self.objects[object_id] = values
        return values

    def _read_binary_array(self) -> list[Any]:
        object_id = self._i32()
        array_type = self._u8()
        rank = self._i32()
        lengths = [self._i32() for _ in range(rank)]
        if array_type in {3, 4, 5}:
            for _ in range(rank):
                self._i32()
        binary_type = self._u8()
        additional = None
        if binary_type in {0, 7}:
            additional = self._u8()
        elif binary_type == 3:
            additional = self._lps()
        elif binary_type == 4:
            additional = (self._lps(), self._i32())
        length = 1
        for item in lengths:
            length *= item
        if binary_type in {0, 7} and additional is not None:
            values = [self._primitive(int(additional)) for _ in range(length)]
        else:
            values = self._read_array_elements(length)
        self.objects[object_id] = values
        return values

    def _read_array_elements(self, length: int) -> list[Any]:
        values: list[Any] = []
        while len(values) < length:
            pos = self._f.tell()
            raw = self._f.read(1)
            if not raw:
                break
            record_type = raw[0]
            if record_type == 10:
                values.append(None)
            elif record_type == 13:
                values.extend([None] * self._u8())
            elif record_type == 14:
                values.extend([None] * self._i32())
            else:
                self._f.seek(pos)
                values.append(self._read_inline_value())
        return values[:length]

    def _primitive(self, primitive_type: int) -> Any:
        if primitive_type == 1:
            return bool(self._u8())
        if primitive_type == 2:
            return self._u8()
        if primitive_type == 3:
            return chr(self._u8())
        if primitive_type == 5:
            return self._lps()
        if primitive_type == 6:
            return self._f64()
        if primitive_type == 7:
            return self._i16()
        if primitive_type == 8:
            return self._i32()
        if primitive_type == 9:
            return self._i64()
        if primitive_type == 10:
            return self._i8()
        if primitive_type == 11:
            return self._f32()
        if primitive_type == 12:
            return self._i64()
        if primitive_type == 13:
            return self._u64()
        if primitive_type == 14:
            return self._u16()
        if primitive_type == 15:
            return self._u32()
        if primitive_type == 16:
            return self._u64()
        raise ValueError(f"Unsupported primitive type {primitive_type}")

    def _read(self, size: int) -> bytes:
        data = self._f.read(size)
        if len(data) != size:
            raise EOFError("Unexpected end of NRBF stream")
        return data

    def _u8(self) -> int:
        return self._read(1)[0]

    def _i8(self) -> int:
        return struct.unpack("<b", self._read(1))[0]

    def _u16(self) -> int:
        return struct.unpack("<H", self._read(2))[0]

    def _i16(self) -> int:
        return struct.unpack("<h", self._read(2))[0]

    def _i32(self) -> int:
        return struct.unpack("<i", self._read(4))[0]

    def _u32(self) -> int:
        return struct.unpack("<I", self._read(4))[0]

    def _i64(self) -> int:
        return struct.unpack("<q", self._read(8))[0]

    def _u64(self) -> int:
        return struct.unpack("<Q", self._read(8))[0]

    def _f32(self) -> float:
        return struct.unpack("<f", self._read(4))[0]

    def _f64(self) -> float:
        return struct.unpack("<d", self._read(8))[0]

    def _lps(self) -> str:
        length = 0
        shift = 0
        while True:
            byte = self._u8()
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        return self._read(length).decode("utf-8", errors="replace")
