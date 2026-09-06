import re

COLORS = {
    "white": "#FFFFFF",
    "red": "#F07178",
    "orange": "#F2A65A",
    "yellow": "#E8CF78",
    "green": "#85C995",
    "mint": "#8ED8BD",
    "teal": "#70C5BF",
    "cyan": "#87D3E8",
    "blue": "#82AAE8",
    "purple": "#B39DDB",
    "pink": "#E8A0BF",
    "peach": "#EFB49B",
}


def resolve_color(value):
    value = value.strip()
    if value.lower() in COLORS:
        return COLORS[value.lower()]
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.upper()
    raise ValueError("Color must be #RRGGBB or one of: " + ", ".join(COLORS))
