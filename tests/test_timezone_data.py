"""Проверка доступности поставляемых данных часовых поясов."""

from importlib.resources import files
from zoneinfo import ZoneInfo


def test_tzdata_package_contains_minsk_timezone():
    """Пакет tzdata обеспечивает работу ZoneInfo на Windows без системной базы."""
    zonefile = files("tzdata").joinpath("zoneinfo", "Europe", "Minsk")
    assert zonefile.is_file()
    assert ZoneInfo("Europe/Minsk").key == "Europe/Minsk"
