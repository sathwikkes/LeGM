import pytest

from legm.data.names import normalize_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Nikola Jokić", "nikola jokic"),
        ("Luka Dončić", "luka doncic"),
        ("Jaren Jackson Jr.", "jaren jackson"),
        ("Jaren Jackson Jr", "jaren jackson"),
        ("Robert Williams III", "robert williams"),
        ("Gary Payton II", "gary payton"),
        ("Larry Nance Sr.", "larry nance"),
        ("De'Aaron Fox", "deaaron fox"),
        ("De’Aaron Fox", "deaaron fox"),
        ("Royce O'Neale", "royce oneale"),
        ("Shai Gilgeous-Alexander", "shai gilgeous alexander"),
        ("Karl-Anthony Towns", "karl anthony towns"),
        ("  LeBron   James ", "lebron james"),
        ("P.J. Washington", "pj washington"),
        ("Moritz Wagner", "moritz wagner"),
        ("Kelly Oubre Jr.", "kelly oubre"),
        ("V", "v"),  # a lone suffix-looking token is not dropped
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_variants_collide():
    assert normalize_name("Nikola Jokic") == normalize_name("Nikola Jokić")
    assert normalize_name("Jaren Jackson Jr.") == normalize_name("Jaren Jackson")
