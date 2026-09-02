#!/usr/bin/env bash
# Seeded LibreOffice document corpus: flat ODF text documents (headings,
# formatted runs, tables, lists, footnotes) and flat ODF spreadsheets whose
# formulas carry no cached values, so import must calculate them.
set -euo pipefail
directory="${LDA_FIXTURE_DIR:-/opt/lda/fixtures/libreoffice}"
seed="${LDA_FIXTURE_SEED:-20260423}"
mkdir -p "$directory"
rm -f "$directory"/writer-*.fodt "$directory"/calc-*.fods
python3 - "$directory" "$seed" <<'PY'
import sys
from xml.sax.saxutils import escape
directory, seed = sys.argv[1], int(sys.argv[2])
state = seed * 2654435761 % 2**31 or 1
def rng(bound):
    global state
    state = (1103515245 * state + 12345) % 2**31
    return state % bound
WORDS = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore "
         "et dolore magna aliqua enim ad minim veniam quis nostrud exercitation ullamco laboris nisi aliquip "
         "ex ea commodo consequat duis aute irure reprehenderit voluptate velit esse cillum fugiat nulla "
         "pariatur excepteur sint occaecat cupidatat non proident sunt culpa officia deserunt mollit anim "
         "laborum surgical replacement ubuntu package benchmark deterministic corpus").split()
def sentence(n):
    return " ".join(WORDS[rng(len(WORDS))] for _ in range(n)).capitalize() + "."
def paragraph():
    return " ".join(sentence(6 + rng(14)) for _ in range(3 + rng(6)))
HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
        'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
        'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" office:version="1.3" ')
for doc in range(2):
    parts = [HEAD + 'office:mimetype="application/vnd.oasis.opendocument.text">',
             '<office:automatic-styles><style:style style:name="B" style:family="text"><style:text-properties fo:font-weight="bold"/></style:style>'
             '<style:style style:name="I" style:family="text"><style:text-properties fo:font-style="italic"/></style:style></office:automatic-styles>',
             '<office:body><office:text>']
    fn = 0
    for section in range(28 + rng(8)):
        parts.append(f'<text:h text:outline-level="{1 + rng(3)}">{escape(sentence(4 + rng(5)))}</text:h>')
        for _ in range(4 + rng(5)):
            words = paragraph().split()
            k = rng(len(words)); words[k] = f'<text:span text:style-name="B">{escape(words[k])}</text:span>'
            k = rng(len(words)); words[k] = f'<text:span text:style-name="I">{escape(words[k])}</text:span>'
            if rng(4) == 0:
                fn += 1
                words.append(f'<text:note text:note-class="footnote"><text:note-citation>{fn}</text:note-citation><text:note-body><text:p>{escape(sentence(8))}</text:p></text:note-body></text:note>')
            parts.append("<text:p>" + " ".join(words) + "</text:p>")
        if section % 3 == 0:
            rows = 8 + rng(14)
            parts.append('<table:table><table:table-column table:number-columns-repeated="5"/>')
            for r in range(rows):
                parts.append("<table:table-row>" + "".join(f"<table:table-cell office:value-type=\"string\"><text:p>{escape(WORDS[rng(len(WORDS))])} {rng(1000)}</text:p></table:table-cell>" for _ in range(5)) + "</table:table-row>")
            parts.append("</table:table>")
        if section % 4 == 1:
            parts.append("<text:list>" + "".join(f"<text:list-item><text:p>{escape(sentence(5 + rng(6)))}</text:p></text:list-item>" for _ in range(4 + rng(6))) + "</text:list>")
    parts.append("</office:text></office:body></office:document>")
    with open(f"{directory}/writer-{doc}.fodt", "w", encoding="utf-8") as stream:
        stream.write("\n".join(parts))
for doc in range(2):
    rows, cols = 220 + rng(60), 24
    parts = [HEAD + 'office:mimetype="application/vnd.oasis.opendocument.spreadsheet">',
             '<office:body><office:spreadsheet><table:table table:name="Data">']
    parts.append(f'<table:table-column table:number-columns-repeated="{cols}"/>')
    letters = [chr(65 + c) for c in range(cols)]
    for r in range(1, rows + 1):
        cells = []
        for c in range(cols):
            if c < 6:
                cells.append(f'<table:table-cell office:value-type="float" office:value="{rng(10000) / 7:.4f}"/>')
            elif c < 12:
                cells.append(f'<table:table-cell table:formula="of:=[.{letters[c-6]}{r}]*2+[.{letters[(c+1)%6]}{r}]/3" office:value-type="float"/>')
            elif c < 18:
                cells.append(f'<table:table-cell table:formula="of:=IF([.{letters[c-12]}{r}]&gt;500;SUM([.A{r}:.F{r}]);AVERAGE([.G{r}:.L{r}]))" office:value-type="float"/>')
            else:
                top = max(1, r - 10)
                cells.append(f'<table:table-cell table:formula="of:=SUM([.{letters[c-18]}{top}:.{letters[c-18]}{r}])" office:value-type="float"/>')
        parts.append("<table:table-row>" + "".join(cells) + "</table:table-row>")
    parts.append("</table:table></office:spreadsheet></office:body></office:document>")
    with open(f"{directory}/calc-{doc}.fods", "w", encoding="utf-8") as stream:
        stream.write("\n".join(parts))
with open(f"{directory}/params.env", "w", encoding="utf-8") as stream:
    stream.write(f"LO_FIXTURE_SEED={seed}\n")
print(f"libreoffice fixtures: 2 writer + 2 calc documents, seed {seed}")
PY
