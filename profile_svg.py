"""Language colours and the SVG language bar for the profile README."""

LANG_COLOURS = {
    "PHP": "#4F5D95",
    "C#": "#178600",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Python": "#3572A5",
    "HTML": "#e34c26",
    "CSS": "#663399",
    "C": "#555555",
    "Perl": "#0298c3",
    "Java": "#b07219",
    "Smarty": "#f0c040",
    "Shell": "#89e051",
    "Go": "#00ADD8",
    "C++": "#f34b7d",
    "Ruby": "#701516",
    "Puppet": "#302B6D",
    "Makefile": "#427819",
}


def lang_colour(lang):
    """Return the GitHub colour for a language, grey if unknown."""
    return LANG_COLOURS.get(lang, "#8b949e")


def human_bytes(size):
    """Format a byte count as KB or MB."""
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    return f"{size / 1_000:.0f} KB"


def svg_languages_bar(languages, width=860, height=14):
    """Render an SVG stacked bar of language sizes."""
    total = sum(size for _, size in languages) or 1
    x = 0.0
    rects = ""
    for lang, size in languages:
        w = size / total * width
        rects += f'  <rect x="{x:.2f}" y="0" width="{w:.2f}" height="{height}" fill="{lang_colour(lang)}"/>\n'
        x += w
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <clipPath id="r"><rect width="{width}" height="{height}" rx="7"/></clipPath>
  <g clip-path="url(#r)">
{rects}  </g>
</svg>"""
