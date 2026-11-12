"""The ``.ajbot`` export format, and the reader still taking ``.crewjam`` and ``.crewmate``.

An export writes ``ajcrew.ajbot`` with a ``ajbot.json`` manifest under a
``.ajbot`` name. A file made under an earlier name (``ajcrew.crewjam`` with
``crewjam.json``, or ``ajcrew.crewmate`` with ``crewmate.json``) still imports,
through the same checks.
"""

from __future__ import annotations

import io
import json
import stat
import zipfile

import pytest

from aj_crew import change_card_catalog as catalog
from aj_crew import crewmate_bundle as reader
from aj_crew import crewmate_bundle_export as ex

NEW = ("ajbot.json", "ajcrew.ajbot")
JAM = ("crewjam.json", "ajcrew.crewjam")
OLD = ("crewmate.json", "ajcrew.crewmate")


def _zip(entries: dict[str, bytes | str], *, links: tuple[str, ...] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            if name in links:
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, data)
    return buf.getvalue()


def _bundle(manifest_entry: str, fmt: str, **extra: bytes | str) -> dict[str, bytes | str]:
    manifest = {"format": fmt, "formatVersion": 1, "name": "Scout", "description": "d"}
    return {manifest_entry: json.dumps(manifest), "agent.json": "{}", **extra}


def _refused(data: bytes) -> str:
    with pytest.raises(catalog.CardCatalogError) as err:
        parsed = reader.read_crewmate_file(data)
        reader.crewmate_import_params(parsed.bundle, parsed)
    return str(err.value.code)


def test_an_export_writes_the_ajbot_format_and_name() -> None:
    plan = ex.plan_export(
        ex.ExportSources(name="Scout", description="Watches."), "scout", ex.ExportChoices()
    )
    with zipfile.ZipFile(io.BytesIO(ex.write_bundle(plan))) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("ajbot.json"))
    assert "ajbot.json" in names
    assert "crewjam.json" not in names and "crewmate.json" not in names
    assert manifest["format"] == "ajcrew.ajbot"
    assert ex.bundle_filename("Scout") == "Scout.ajbot"
    assert ex.content_disposition("Scout").endswith("UTF-8''Scout.ajbot")


@pytest.mark.parametrize(
    "entry,fmt",
    [NEW, JAM, OLD, ("ajbot.json", OLD[1]), ("crewjam.json", NEW[1]), ("crewmate.json", JAM[1])],
)
def test_the_new_and_both_old_files_import(entry: str, fmt: str) -> None:
    parsed = reader.read_crewmate_file(_zip(_bundle(entry, fmt)))
    params = reader.crewmate_import_params(parsed.bundle, parsed)
    assert params["name"] == "Scout" and params["format_version"] == 1


@pytest.mark.parametrize("second", [JAM[0], OLD[0]])
def test_a_file_holding_two_manifests_is_refused(second: str) -> None:
    entries = _bundle(*NEW)
    entries[second] = entries["ajbot.json"]
    assert _refused(_zip(entries)) == "invalid_bundle"


def test_a_file_holding_both_old_manifests_is_refused() -> None:
    entries = _bundle(*JAM)
    entries["crewmate.json"] = entries["crewjam.json"]
    assert _refused(_zip(entries)) == "invalid_bundle"


def test_another_format_name_is_refused() -> None:
    assert _refused(_zip(_bundle("ajbot.json", "ajcrew.other"))) == "invalid_bundle"


def test_a_file_without_a_manifest_is_refused() -> None:
    assert _refused(_zip({"agent.json": "{}"})) == "invalid_bundle"


@pytest.mark.parametrize("entry,fmt", [NEW, JAM, OLD])
@pytest.mark.parametrize(
    "bad,code",
    [
        ({"../evil.json": "{}"}, "invalid_path"),
        ({"skills/a/b/c.md": "x"}, "invalid_path"),
        ({"crons/run.sh": "x"}, "invalid_path"),
        ({"unknown.txt": "x"}, "unknown_entry"),
        ({"rules.json": "x" * (reader.JSON_MAX_BYTES + 1)}, "too_large"),
    ],
)
def test_the_safety_checks_refuse_bad_input_in_every_format(
    entry: str, fmt: str, bad: dict[str, str], code: str
) -> None:
    assert _refused(_zip(_bundle(entry, fmt, **{}) | bad)) == code


@pytest.mark.parametrize("entry,fmt", [NEW, JAM, OLD])
def test_a_link_and_too_many_entries_are_refused_in_every_format(entry: str, fmt: str) -> None:
    linked = _bundle(entry, fmt) | {"crons/run.py": "x"}
    assert _refused(_zip(linked, links=("crons/run.py",))) == "invalid_entry"
    many = _bundle(entry, fmt) | {f"crons/s{i}.py": "x" for i in range(reader.ENTRY_MAX)}
    assert _refused(_zip(many)) == "too_many_entries"
    assert _refused(b"x" * (reader.FILE_MAX_BYTES + 1)) == "too_large"


@pytest.mark.parametrize("part", ["ajbot.json", "agent.json"])
def test_a_json_part_saved_with_a_byte_order_mark_reads_as_without_it(part: str) -> None:
    plain = _bundle(*NEW)
    marked = plain | {part: b"\xef\xbb\xbf" + str(plain[part]).encode("utf-8")}
    try:
        parsed = reader.read_crewmate_file(_zip(marked))
    except catalog.CardCatalogError as exc:
        pytest.fail(f"a part with a byte-order mark was refused: {exc}")
    assert parsed.bundle == reader.read_crewmate_file(_zip(plain)).bundle
    assert _refused(_zip(plain | {part: b"\xff" + str(plain[part]).encode("utf-8")})) == (
        "invalid_bundle"
    )
