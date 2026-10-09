import re
import unittest
from pathlib import Path

CSS_PATH = Path(__file__).resolve().parents[1] / "public" / "styles.css"
COLOR_FUNCTION = re.compile(r"\b(?:rgb|rgba|hsl|hsla|oklch)\s*\(", re.IGNORECASE)
HEX_COLOR = re.compile(r"#[\da-f]{3,8}\b", re.IGNORECASE)
COLOR_NAME = re.compile(
    r"(?<![-\w])(?:aliceblue|antiquewhite|aqua|aquamarine|azure|beige|bisque|black|"
    r"blanchedalmond|blue|blueviolet|brown|burlywood|cadetblue|chartreuse|"
    r"chocolate|coral|cornflowerblue|cornsilk|crimson|cyan|darkblue|darkcyan|"
    r"darkgoldenrod|darkgray|darkgreen|darkgrey|darkkhaki|darkmagenta|darkolivegreen|"
    r"darkorange|darkorchid|darkred|darksalmon|darkseagreen|darkslateblue|"
    r"darkslategray|darkslategrey|darkturquoise|darkviolet|deeppink|deepskyblue|"
    r"dimgray|dimgrey|dodgerblue|firebrick|floralwhite|forestgreen|fuchsia|"
    r"gainsboro|ghostwhite|gold|goldenrod|gray|green|greenyellow|grey|honeydew|"
    r"hotpink|indianred|indigo|ivory|khaki|lavender|lavenderblush|lawngreen|"
    r"lemonchiffon|lightblue|lightcoral|lightcyan|lightgoldenrodyellow|lightgray|"
    r"lightgreen|lightgrey|lightpink|lightsalmon|lightseagreen|lightskyblue|"
    r"lightslategray|lightslategrey|lightsteelblue|lightyellow|lime|limegreen|"
    r"linen|magenta|maroon|mediumaquamarine|mediumblue|mediumorchid|mediumpurple|"
    r"mediumseagreen|mediumslateblue|mediumspringgreen|mediumturquoise|"
    r"mediumvioletred|midnightblue|mintcream|mistyrose|moccasin|navajowhite|navy|"
    r"oldlace|olive|olivedrab|orange|orangered|orchid|palegoldenrod|palegreen|"
    r"paleturquoise|palevioletred|papayawhip|peachpuff|peru|pink|plum|powderblue|"
    r"purple|rebeccapurple|red|rosybrown|royalblue|saddlebrown|salmon|sandybrown|"
    r"seagreen|seashell|sienna|silver|skyblue|slateblue|slategray|slategrey|snow|"
    r"springgreen|steelblue|tan|teal|thistle|tomato|turquoise|violet|wheat|white|"
    r"whitesmoke|yellow|yellowgreen|transparent)(?![-\w])",
    re.IGNORECASE,
)
COLOR_LITERAL = re.compile(
    rf"(?:{HEX_COLOR.pattern}|{COLOR_FUNCTION.pattern}|{COLOR_NAME.pattern})",
    re.IGNORECASE,
)
RULE_LITERAL_ALLOWLIST: set[tuple[str, str, str]] = set()


def _declarations(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    declarations: list[tuple[str, str, str]] = []
    blocks: list[str] = []
    start = 0
    quote = None
    escaped = False
    depth = 0
    for index, character in enumerate(css):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in "\"'":
            quote = character
        elif character == "{":
            blocks.append(css[start:index].strip())
            start = index + 1
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character in ";}" and depth == 0:
            declaration = css[start:index].strip()
            if ":" in declaration:
                name, value = declaration.split(":", 1)
                selector = blocks[-1] if blocks else ""
                declarations.append((selector, name.strip(), value.strip()))
            if character == "}":
                if blocks:
                    blocks.pop()
                start = index + 1
            else:
                start = index + 1
    return declarations


def _color_literals(value):
    value = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', "", value)
    return sorted({match.group(0).lower() for match in COLOR_LITERAL.finditer(value)})


class CssDesignTokenTests(unittest.TestCase):
    def test_completed_session_token_pairs_meet_wcag_aa_in_both_themes(self):
        declarations = _declarations(CSS_PATH.read_text(encoding="utf-8"))
        tokens = {}
        for theme in (":root", ':root[data-theme="light"]'):
            tokens.update(
                {
                    name: value
                    for selector, name, value in declarations
                    if selector == theme
                }
            )

            def luminance(value):
                while value.startswith("var("):
                    value = tokens[value[4:-1]]
                self.assertRegex(value, r"^#[0-9a-fA-F]{6}$")
                channels = [
                    int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)
                ]
                linear = [
                    channel / 12.92
                    if channel <= 0.04045
                    else ((channel + 0.055) / 1.055) ** 2.4
                    for channel in channels
                ]
                return sum(
                    channel * weight
                    for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722))
                )

            for sport in ("default", "bike", "run", "swim", "strength"):
                with self.subTest(theme=theme, sport=sport):
                    background = luminance(tokens[f"--planned-session-{sport}"])
                    foreground = luminance(tokens[f"--planned-session-{sport}-on"])
                    self.assertGreaterEqual(
                        (max(background, foreground) + 0.05)
                        / (min(background, foreground) + 0.05),
                        4.5,
                    )

    def test_stylesheet_uses_semantic_tokens_and_documented_status_roles(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("--palette-color-", css)
        root_tokens = {
            name
            for selector, name, _ in _declarations(css)
            if selector in {":root", ':root[data-theme="light"]'}
            and name.startswith("--")
        }
        self.assertTrue({"--danger", "--stop", "--disabled-ink"}.issubset(root_tokens))

    def test_color_literals_are_confined_to_theme_token_blocks(self):
        violations = []
        for selector, name, value in _declarations(
            CSS_PATH.read_text(encoding="utf-8")
        ):
            literals = _color_literals(value)
            if not literals:
                continue
            if selector in {":root", ':root[data-theme="light"]'} and name.startswith(
                "--"
            ):
                continue
            if (selector, name, value) in RULE_LITERAL_ALLOWLIST:
                continue
            violations.append(f"{selector} {name}: {', '.join(literals)}")
        self.assertEqual(violations, [])

    def test_parser_detects_color_literal_forms(self):
        css = """
        :root { --white: #fff; --bad: white; }
        .sample { color: rgba(0, 0, 0, .5); background: hsl(0 0% 0%); border-color: oklch(.2 0 0); outline-color: white; }
        """
        violations = [
            (selector, name, _color_literals(value))
            for selector, name, value in _declarations(css)
            if _color_literals(value)
            and not (selector == ":root" and name.startswith("--"))
        ]
        self.assertEqual(len(violations), 4)
        self.assertEqual(violations[0][1], "color")
        self.assertIn("white", violations[-1][2])


if __name__ == "__main__":
    unittest.main()
