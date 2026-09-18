"""
Workbook reader (WBS 3.1): TrackF.xlsx tab by tab into raw rows, no interpretation.

What it handles that a generic "read the sheet" cannot:

- The two-row header. Headers sit on row 3 with a second line on row 4, so
  "Confidence" + "Level" and "Adjusted Revenue" read across two rows, and the
  FCST_Revenue quarterly blocks put the group name ("CY25 FCST [Kpcs]") on
  row 3 over a run of columns and "Q1".."TTL" on row 4. Row-3 group names are
  forward-filled across their run, and each column's header is the two lines
  joined.
- Shifted column letters on the terminal tabs. Mass Production and Design Lost
  have no Stage column, so every column right of Design Status is one letter
  left of ProjectTrack's. Fields are addressed by header, never by letter, so
  the shift is invisible to callers -- but each cell keeps its coordinate, so
  a finding can still say "FCST!AB21".
- Footer rows. FCST_Revenue rows 20-24 are regional roll-ups ("Korea Region",
  "Elevation Micro Total") that share the data columns. A row with a Region and
  no Customer and no Project is a footer, kept separately with its formulas,
  which is what the roll-up integrity rule (V-f) reads.
- Formulas. Cells carry both the cached value and the formula text, so a
  "#REF!" is reported as the formula that produced it, and a Disty ASP entered
  as "=M9*0.975" is recorded as derived rather than entered.

Nothing is coerced here: "TBD" stays "TBD", "Dec'24" stays a string. That is
app/intake/coerce.py's job, and keeping the layers apart is what lets a
finding cite the source string.
"""

from dataclasses import dataclass, field
from pathlib import Path

HEADER_ROWS = (3, 4)
FIRST_DATA_ROW = 5

# Header text -> field name. Keys are the joined, whitespace-normalised,
# lower-cased two-row header. Anything not listed keeps its raw header as
# the field name, so an undefined column (Funnel's "FCST") is still readable
# and reportable rather than silently dropped.
HEADER_FIELDS: dict[str, str] = {
    "region": "region",
    "customer": "customer",
    "end customer": "end_customer",
    "project name": "project",
    "application": "application",
    "product line": "product_line",
    "part#": "part_number",
    "design status": "design_status",
    "stage": "stage",
    "m/p": "mp_date",
    "eau [kpcs]": "eau_kpcs",
    "unit /set": "unit_set",
    "disty cost (asp)": "disty_asp",
    "resale (asp)": "resale_asp",
    "sales revenue": "sales_revenue_k",
    "competitor part#": "competitor_part",
    "comeptitor part#": "competitor_part",  # the workbook's own spelling on Funnel
    "confidence level": "confidence",
    "adjusted revenue": "adjusted_revenue_k",
    "comments": "comments",
    "remarks": "remarks",
    "fcst": "fcst_flag",  # Funnel column N: 1 or 2, defined nowhere (F-10)
    "pjt. status/note": "status_note",
    "next action to do": "next_action",
}

# FCST_Revenue quarterly blocks: group header on row 3, quarter on row 4.
QUARTER_GROUPS: dict[str, str] = {
    "cy25 fcst [kpcs]": "cy25_units",
    "cy25 revenue [k$]": "cy25_revenue_k",
    "cy26 fcst [kpcs]": "cy26_units",
    "cy26 revenue [k$]": "cy26_revenue_k",
}

DATA_TABS = ("Funnel", "FCST_Revenue", "ProjectTrack", "Mass Production", "Design Lost")


@dataclass(frozen=True)
class Cell:
    coordinate: str          # "FCST_Revenue!AB21"
    value: object            # cached value (what Excel last computed)
    formula: str | None      # "=SUM(#REF!)" when the cell is a formula, else None

    @property
    def is_formula(self) -> bool:
        return self.formula is not None

    @property
    def is_error(self) -> bool:
        return isinstance(self.value, str) and self.value.startswith("#")


@dataclass
class RawRow:
    tab: str
    row_number: int
    fields: dict[str, object] = field(default_factory=dict)   # field name -> value
    cells: dict[str, Cell] = field(default_factory=dict)      # field name -> Cell

    def cell(self, name: str) -> Cell | None:
        return self.cells.get(name)

    def coordinate(self, name: str) -> str | None:
        c = self.cells.get(name)
        return c.coordinate if c else None


@dataclass
class Tab:
    name: str
    headers: dict[str, str] = field(default_factory=dict)     # column letter -> field name
    raw_headers: dict[str, str] = field(default_factory=dict) # column letter -> joined header text
    rows: list[RawRow] = field(default_factory=list)
    footers: list[RawRow] = field(default_factory=list)
    as_of: object = None


@dataclass
class Workbook:
    path: str
    tabs: dict[str, Tab] = field(default_factory=dict)

    def rows(self, *tabs: str) -> list[RawRow]:
        wanted = tabs or tuple(self.tabs)
        return [r for t in wanted if t in self.tabs for r in self.tabs[t].rows]


def _norm(text: object) -> str:
    return " ".join(str(text).split()).strip().lower() if text is not None else ""


def _column_letter(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(index)


def _headers(ws_values, ws_formulas) -> tuple[dict[str, str], dict[str, str]]:
    """Column letter -> field name, from the two header rows, with row-3 group
    names forward-filled across their run."""
    headers: dict[str, str] = {}
    raw: dict[str, str] = {}
    group = ""
    for col in range(1, ws_values.max_column + 1):
        top = ws_values.cell(HEADER_ROWS[0], col).value
        bottom = ws_values.cell(HEADER_ROWS[1], col).value
        if top is not None:
            group = _norm(top)
        top_text = _norm(top)
        bottom_text = _norm(bottom)
        if not top_text and not bottom_text:
            continue
        letter = _column_letter(col)
        joined = " ".join(x for x in (top_text, bottom_text) if x)
        raw[letter] = joined
        if top_text and group in QUARTER_GROUPS and bottom_text:
            headers[letter] = f"{QUARTER_GROUPS[group]}_{bottom_text}"
        elif not top_text and group in QUARTER_GROUPS and bottom_text:
            headers[letter] = f"{QUARTER_GROUPS[group]}_{bottom_text}"
        else:
            headers[letter] = HEADER_FIELDS.get(joined, HEADER_FIELDS.get(top_text, joined.replace(" ", "_")))
    return headers, raw


def _is_footer(fields: dict, cells: dict) -> bool:
    """A roll-up footer carries a label in the Region column and formulas --
    nothing else entered. ProjectTrack's skeleton rows (14-18) also have no
    Customer or Project, but they carry an entered Design Status and EAU, which
    makes them data rows with findings, not footers."""
    if not fields.get("region") or fields.get("customer") or fields.get("project"):
        return False
    return all(name == "region" or c.is_formula for name, c in cells.items())


def _is_blank(fields: dict, cells: dict) -> bool:
    """A row is blank when it carries no entered value -- formula-only rows
    (FCST rows 15-19, which hold =SUM() over empty cells) are blank."""
    return all(c.is_formula or c.value is None for c in cells.values())


def read_workbook(path: str | Path) -> Workbook:
    import openpyxl

    path = Path(path)
    values_wb = openpyxl.load_workbook(path, data_only=True)
    formulas_wb = openpyxl.load_workbook(path, data_only=False)
    wb = Workbook(path=str(path))

    for name in values_wb.sheetnames:
        if name not in DATA_TABS:
            continue
        wsv, wsf = values_wb[name], formulas_wb[name]
        headers, raw = _headers(wsv, wsf)
        tab = Tab(name=name, headers=headers, raw_headers=raw)
        as_of = wsv.cell(2, 2).value if _norm(wsv.cell(2, 1).value).startswith("as of") else None
        tab.as_of = as_of

        for r in range(FIRST_DATA_ROW, wsv.max_row + 1):
            fields: dict[str, object] = {}
            cells: dict[str, Cell] = {}
            for letter, field_name in headers.items():
                vcell = wsv[f"{letter}{r}"]
                fcell = wsf[f"{letter}{r}"]
                formula = fcell.value if isinstance(fcell.value, str) and fcell.value.startswith("=") else None
                if vcell.value is None and formula is None:
                    continue
                cells[field_name] = Cell(coordinate=f"{name}!{letter}{r}", value=vcell.value, formula=formula)
                fields[field_name] = vcell.value
            if not cells or _is_blank(fields, cells):
                continue
            row = RawRow(tab=name, row_number=r, fields=fields, cells=cells)
            (tab.footers if _is_footer(fields, cells) else tab.rows).append(row)
        wb.tabs[name] = tab

    # Sheet1 is deliberately not a data tab: David Nam described it as a
    # leftover from the template, absent from the sheet he updated.
    return wb
