import pytest

from core.labels import is_machine_safe


@pytest.mark.parametrize(
    "label",
    ["bleb", "Chaetoceros", "C_didymus_sl", "Chaetoceros_morphotype1", "a.b-c", "9", "A"],
)
def test_machine_safe(label):
    assert is_machine_safe(label)


@pytest.mark.parametrize(
    "label",
    [
        "Chaetoceros didymus",
        "a/b",
        "_leading",
        ".leading",
        "-leading",
        "",
        "tab\there",
        "trailing\n",
        "ünicode",
        None,
        42,
    ],
)
def test_not_machine_safe(label):
    assert not is_machine_safe(label)
