"""Picking an action's image by pairing tag."""

from pathlib import Path

import pytest

from roleplay.actions import image_files, pairing_of, pick_image, pool_of


def _folder(tmp_path: Path, *names: str) -> Path:
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"GIF89a")
    return tmp_path


@pytest.mark.parametrize(
    ("name", "pairing"),
    [
        ("SPOILER_cunnilingus_wlw_30c43b4328d8.gif", "wlw"),
        ("hug_MLM_eros8_1_2.gif", "mlm"),
        ("hug_eros_1351828556_143913.gif", None),
        ("slapwlw_1.gif", None),
        ("hug_417e74cf32ab.gif", None),
    ],
)
def test_pairing_is_a_whole_part_of_the_name(name: str, pairing: str | None) -> None:
    assert pairing_of(Path(name)) == pairing


def test_default_pool_leaves_out_wlw_and_mlm(tmp_path: Path) -> None:
    folder = _folder(tmp_path, "hug_1.gif", "hug_mlw_2.gif", "hug_wlm_3.gif", "hug_wlw_4.gif", "hug_mlm_5.gif")

    picked = {pick_image(folder)[0].name for _ in range(200)}  # pyright: ignore[reportOptionalMemberAccess]

    assert picked == {"hug_1.gif", "hug_mlw_2.gif", "hug_wlm_3.gif"}


def test_requested_pairing_is_matched_exactly(tmp_path: Path) -> None:
    folder = _folder(tmp_path, "kiss_1.gif", "kiss_mlw_2.gif", "kiss_wlm_3.gif")

    for _ in range(50):
        image, missing = pick_image(folder, "mlw")
        assert image is not None and image.name == "kiss_mlw_2.gif"
        assert not missing


def test_missing_pairing_falls_back_to_the_default_pool(tmp_path: Path) -> None:
    folder = _folder(tmp_path, "suck_1.gif", "suck_mlm_2.gif")

    image, missing = pick_image(folder, "wlw")

    assert image is not None and image.name == "suck_1.gif"
    assert missing


def test_only_image_files_are_used_including_subfolders(tmp_path: Path) -> None:
    folder = _folder(tmp_path, "Thumbs.db", "notes.txt", "wlw/hug_wlw_1.GIF")

    assert pick_image(folder, "wlw") == (folder / "wlw" / "hug_wlw_1.GIF", False)
    assert pick_image(folder) == (None, False)


def test_missing_folder_has_no_image(tmp_path: Path) -> None:
    assert pick_image(tmp_path / "nope") == (None, False)
    assert pick_image(tmp_path / "nope", "mlm") == (None, True)


@pytest.mark.parametrize(
    ("name", "pool"),
    [
        ("bite_1.gif", "default"),
        ("bite_mlw_2.gif", "default"),
        ("bite_WLM_3.gif", "default"),
        ("bite_wlw_4.gif", "wlw"),
        ("bite_mlm_5.gif", "mlm"),
        ("bitewlw_6.gif", "default"),
    ],
)
def test_pool_is_the_one_the_bot_picks_from(name: str, pool: str) -> None:
    assert pool_of(Path(name)) == pool


def test_image_files_are_sorted_and_skip_other_files(tmp_path: Path) -> None:
    folder = _folder(tmp_path, "b.gif", "Thumbs.db", "a.GIF", "notes.txt", "sub/c.png")

    assert [f.name for f in image_files(folder)] == ["a.GIF", "b.gif", "c.png"]
    assert image_files(tmp_path / "nope") == []
