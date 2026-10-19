"""The labor types an estimate prints - one list for both parsers, the checks, the summary and the job numbers."""

BODY, PAINT, MECHANICAL = "Body Labor", "Paint Labor", "Mechanical Labor"
LABOR_CATEGORIES = [BODY, PAINT, MECHANICAL, "Structural Labor", "Frame Labor", "Electrical Labor",
                    "Diagnostic Labor", "Glass Labor"]

# CCC prints a labor type after the hours ('2.0 M') or as a word in the labor-type column
CCC_TYPES = {
    "body": BODY, "mech": MECHANICAL, "m": MECHANICAL, "struc": "Structural Labor", "s": "Structural Labor",
    "frame": "Frame Labor", "f": "Frame Labor", "diag": "Diagnostic Labor", "d": "Diagnostic Labor",
    "elec": "Electrical Labor", "e": "Electrical Labor", "glass": "Glass Labor", "g": "Glass Labor",
}
# Mitchell prints the type as a word ('Body', 'Refinish', ...)
MITCHELL_TYPES = {
    "body": BODY, "refinish": PAINT, "mechanical": MECHANICAL, "frame": "Frame Labor",
    "structural": "Structural Labor", "glass": "Glass Labor", "electrical": "Electrical Labor",
    "diagnostic": "Diagnostic Labor",
}

# the job list's hour columns; every other labor type is 'Other'
GROUPS = {"Body labor": [BODY], "Paint labor": [PAINT], "Mechanical labor": [MECHANICAL]}


def category(labor_type):
    """'Frame' -> 'Frame Labor'; a type the shop made up keeps its own name; no type at all is body labor."""
    if not labor_type:
        return BODY
    return labor_type if labor_type.endswith(" Labor") else f"{labor_type} Labor"


def is_labor(label):
    """A labor category or a printed labor totals row (not the 'Total Labor' row)."""
    return label.endswith(" Labor") and label != "Total Labor"
