"""Finds the site's English text and keeps the Spanish translation files in step with it.

The site's text is marked for translation in the usual Django way: {% translate %} and
{% blocktranslate %} in templates, gettext() and friends in Python, and gettext() in the site's
scripts. Translations live in locale/<language>/LC_MESSAGES/: django.po for pages and Python,
djangojs.po for scripts. Django reads the compiled .mo files next to them.

This does the jobs of Django's makemessages and compilemessages without needing GNU gettext
installed. Run it with `python manage.py translations update|compile|check`.
"""
import ast
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.utils.translation.template import templatize

SKIP_DIRS = {".git", ".github", "__pycache__", "node_modules", "venv", ".venv", "env", "locale",
             "migrations", "deploy", "staticfiles", "media"}

PY_KEYWORDS = {
    # name: positions of (context, singular, plural); None if not used
    "gettext": (None, 0, None), "gettext_lazy": (None, 0, None), "gettext_noop": (None, 0, None),
    "_": (None, 0, None),
    "ngettext": (None, 0, 1), "ngettext_lazy": (None, 0, 1),
    "pgettext": (0, 1, None), "pgettext_lazy": (0, 1, None),
    "npgettext": (0, 1, 2), "npgettext_lazy": (0, 1, 2),
}
JS_KEYWORDS = {
    "gettext": (None, 0, None), "gettext_noop": (None, 0, None), "ngettext": (None, 0, 1),
    "pgettext": (0, 1, None), "npgettext": (0, 1, 2),
}
FORMAT_RE = re.compile(r"%(?:\((\w+)\))?[sd]")
TAG_RE = re.compile(r"</?([a-zA-Z][\w-]*)")


class ExtractError(Exception):
    pass


@dataclass
class Message:
    msgid: str
    context: str | None = None
    plural: str | None = None
    msgstr: str = ""
    msgstr_plural: dict = field(default_factory=dict)
    locations: list = field(default_factory=list)
    notes: list = field(default_factory=list)  # comments for translators, from the code
    comments: list = field(default_factory=list)  # comments written in the .po file itself
    flags: set = field(default_factory=set)
    obsolete: bool = False

    @property
    def key(self):
        return (self.context, self.msgid)

    def is_translated(self, nplurals):
        if self.plural is None:
            return bool(self.msgstr)
        return all(self.msgstr_plural.get(i) for i in range(nplurals))


# Finding text in the code ------------------------------------------------------------------------

def source_files(root):
    """Python, template and script files that can hold text for visitors, in a stable order."""
    static_root = Path(settings.STATIC_ROOT).resolve()
    found = {"django": [], "djangojs": []}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if path.resolve().is_relative_to(static_root):
            continue
        parts = rel.parts
        if path.suffix == ".py":
            if path.name in ("tests.py", "manage.py") or path.name.startswith("test_") or "tests" in parts:
                continue
            found["django"].append(path)
        elif path.suffix in (".html", ".txt") and "templates" in parts:
            found["django"].append(path)
        elif path.suffix == ".js" and "static" in parts and not path.name.endswith(".min.js"):
            found["djangojs"].append(path)
    return found


def _translator_notes(lines, lineno, marker):
    """Comments starting with "Translators:" on the lines just above a call."""
    block = []
    i = lineno - 2
    while i >= 0 and lines[i].strip().startswith(marker):
        block.insert(0, lines[i].strip()[len(marker):].strip())
        i -= 1
    for n, text in enumerate(block):
        if text.startswith("Translators:"):
            return [" ".join(block[n:])]
    return []


def _message_from_args(keyword_spec, args, where):
    ctx_i, one_i, many_i = keyword_spec
    needed = [i for i in (ctx_i, one_i, many_i) if i is not None]
    values = {}
    for i in needed:
        if i >= len(args) or not isinstance(args[i], str):
            raise ExtractError(f"{where}: the text to translate must be written out in quotes here.")
        values[i] = args[i]
    return Message(
        msgid=values[one_i],
        context=values.get(ctx_i) if ctx_i is not None else None,
        plural=values.get(many_i) if many_i is not None else None,
    )


def _literal_args(call):
    return [a.value if isinstance(a, ast.Constant) else None for a in call.args]


def extract_python(path, rel):
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name not in PY_KEYWORDS:
            continue
        message = _message_from_args(PY_KEYWORDS[name], _literal_args(node), f"{rel}:{node.lineno}")
        message.notes = _translator_notes(lines, node.lineno, "#")
        found.append((node.lineno, node.col_offset, message))
    return [m for _, _, m in sorted(found, key=lambda f: (f[0], f[1]))], "python-format"


def _call_end(text, start):
    """Index just past the ) that closes the ( at text[start], skipping over quoted text."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            i += 1
            while i < n and text[i] != c:
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


CALL_RE = re.compile(r"(?<![\w.])(gettext|pgettext|ngettext|npgettext|_)\(")


def extract_template(path, rel):
    """Text in a template, read the same way Django's makemessages reads it."""
    code = templatize(path.read_text(encoding="utf-8"), origin=str(rel))
    lines = code.splitlines()
    found = []
    for match in CALL_RE.finditer(code):
        end = _call_end(code, match.end() - 1)
        lineno = code.count("\n", 0, match.start()) + 1
        try:
            call = ast.parse(code[match.start():end], mode="eval").body
        except SyntaxError as exc:
            raise ExtractError(f"{rel}:{lineno}: couldn't read this translation tag.") from exc
        message = _message_from_args(PY_KEYWORDS[match[1]], _literal_args(call), f"{rel}:{lineno}")
        message.notes = _translator_notes(lines, lineno, "#")
        found.append(message)
    return found, "python-format"


JS_CALL_RE = re.compile(r"(?<![\w$.])(gettext|gettext_noop|ngettext|pgettext|npgettext)\s*\(")
JS_STRING_RE = re.compile(r"""\s*('(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")\s*([,)])""")


def extract_script(path, rel):
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    found = []
    for match in JS_CALL_RE.finditer(source):
        spec = JS_KEYWORDS[match[1]]
        count = sum(i is not None for i in spec)
        lineno = source.count("\n", 0, match.start()) + 1
        args, pos = [], match.end()
        for _ in range(count):
            arg = JS_STRING_RE.match(source, pos)
            if not arg:
                raise ExtractError(f"{rel}:{lineno}: the text to translate must be written out in quotes here.")
            try:
                args.append(ast.literal_eval(arg[1]))
            except (ValueError, SyntaxError) as exc:
                raise ExtractError(f"{rel}:{lineno}: couldn't read this text.") from exc
            pos = arg.end()
            if arg[2] == ")":
                break
        message = _message_from_args(spec, args, f"{rel}:{lineno}")
        message.notes = _translator_notes(lines, lineno, "//")
        found.append(message)
    return found, "javascript-format"


def extract(root=None):
    """Every piece of text marked for translation: {"django": [Message, …], "djangojs": […]}."""
    root = Path(root or settings.BASE_DIR)
    catalogs = {}
    for domain, paths in source_files(root).items():
        messages = {}
        for path in paths:
            rel = path.relative_to(root).as_posix()
            if domain == "djangojs":
                found, fmt = extract_script(path, rel)
            elif path.suffix == ".py":
                found, fmt = extract_python(path, rel)
            else:
                found, fmt = extract_template(path, rel)
            for message in found:
                existing = messages.get(message.key)
                if existing is None:
                    existing = messages[message.key] = message
                    existing.locations = []
                elif message.plural and not existing.plural:
                    existing.plural = message.plural
                if rel not in existing.locations:
                    existing.locations.append(rel)
                for note in message.notes:
                    if note not in existing.notes:
                        existing.notes.append(note)
                if FORMAT_RE.search(message.msgid) or (message.plural and FORMAT_RE.search(message.plural)):
                    existing.flags.add(fmt)
        catalogs[domain] = list(messages.values())
    return catalogs


# Reading and writing .po files -------------------------------------------------------------------

def _unquote(text):
    body = text.strip()
    if not (body.startswith('"') and body.endswith('"')):
        raise ValueError(f"Expected text in quotes: {text}")
    return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t", "r": "\r"}.get(m[1], m[1]), body[1:-1])


def _parse_entry(lines):
    m = Message(msgid="")
    field_name = None
    for line in lines:
        if line.startswith("#~"):
            m.obsolete = True
            line = line[2:].lstrip()
            if not line:
                continue
        if line.startswith("#"):
            kind = line[:2]
            if kind == "#.":
                m.notes.append(line[2:].strip())
            elif kind == "#:":
                m.locations.extend(line[2:].split())
            elif kind == "#,":
                m.flags.update(f.strip() for f in line[2:].split(",") if f.strip())
            elif kind != "#|":
                m.comments.append(line[1:].strip())
            continue
        if line.startswith('"'):
            value = _unquote(line)
            if field_name == "msgctxt":
                m.context += value
            elif field_name == "msgid":
                m.msgid += value
            elif field_name == "msgid_plural":
                m.plural += value
            elif field_name == "msgstr":
                m.msgstr += value
            elif field_name and field_name.startswith("msgstr["):
                m.msgstr_plural[int(field_name[7:-1])] += value
            else:
                raise ValueError(f"Can't read this line of the .po file: {line}")
            continue
        keyword, _, rest = line.partition(" ")
        value = _unquote(rest)
        if keyword == "msgctxt":
            m.context = value
        elif keyword == "msgid":
            m.msgid = value
        elif keyword == "msgid_plural":
            m.plural = value
        elif keyword == "msgstr":
            m.msgstr = value
        elif keyword.startswith("msgstr["):
            m.msgstr_plural[int(keyword[7:-1])] = value
        else:
            raise ValueError(f"Can't read this line of the .po file: {line}")
        field_name = keyword
    return m


def parse_po(text):
    """Returns (the comments at the top of the file, the header, [Message, …])."""
    head_comments, header, messages = [], None, []
    # Entries are separated by blank lines. The text inside an entry is always in quotes,
    # so a blank line can't be part of one.
    for block in re.split(r"\n[ \t]*\n", text.strip("\n")):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        m = _parse_entry(lines)
        if header is None and m.msgid == "" and m.context is None and not m.obsolete:
            header = m.msgstr
            head_comments = [line for line in lines if line.startswith("#")]
        else:
            messages.append(m)
    return head_comments, header or "", messages


def _po_text(keyword, text, prefix=""):
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\r", "\\r")
    lines = escaped.split("\n")
    if len(lines) == 1:
        return [f'{prefix}{keyword} "{escaped}"']
    parts = [line + "\\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    return [f'{prefix}{keyword} ""'] + [f'{prefix}"{p}"' for p in parts]


def format_po(head_comments, header, messages):
    out = list(head_comments)
    out += _po_text("msgid", "") + _po_text("msgstr", header)
    for m in sorted(messages, key=lambda m: m.obsolete):
        out.append("")
        prefix = "#~ " if m.obsolete else ""
        out += [f"# {c}".rstrip() for c in m.comments]
        if not m.obsolete:
            out += [f"#. {n}" for n in m.notes]
            out += [f"#: {loc}" for loc in m.locations]
            if m.flags:
                out.append("#, " + ", ".join(sorted(m.flags)))
        if m.context is not None:
            out += _po_text("msgctxt", m.context, prefix)
        out += _po_text("msgid", m.msgid, prefix)
        if m.plural is not None:
            out += _po_text("msgid_plural", m.plural, prefix)
            for n in sorted(m.msgstr_plural):
                out += _po_text(f"msgstr[{n}]", m.msgstr_plural[n], prefix)
        else:
            out += _po_text("msgstr", m.msgstr, prefix)
    return "\n".join(out) + "\n"


def nplurals_of(header):
    match = re.search(r"nplurals\s*=\s*(\d+)", header)
    return int(match[1]) if match else 2


# Keeping a language's files in step --------------------------------------------------------------

LANGUAGE_NAMES = {"es": "Spanish"}
PLURAL_FORMS = {"es": "nplurals=2; plural=(n != 1);"}


def default_header(language):
    return (
        "Project-Id-Version: Tahoe Neighborhood Table\n"
        f"Language: {language}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 8bit\n"
        f"Plural-Forms: {PLURAL_FORMS.get(language, 'nplurals=2; plural=(n != 1);')}\n"
    )


def po_path(language, domain):
    return Path(settings.LOCALE_PATHS[0]) / language / "LC_MESSAGES" / f"{domain}.po"


def merged(language, domain, extracted):
    """The .po file for a language with the code's current text: (text of the file, messages)."""
    path = po_path(language, domain)
    if path.exists():
        head_comments, header, old = parse_po(path.read_text(encoding="utf-8"))
    else:
        name = LANGUAGE_NAMES.get(language, language)
        head_comments = [f"# {name} text for the Tahoe Neighborhood Table website.",
                         "# Keep this file up to date with: python manage.py translations update"]
        header, old = default_header(language), []
    nplurals = nplurals_of(header)
    previous = {m.key: m for m in old}
    messages = []
    for new in extracted:
        m = Message(msgid=new.msgid, context=new.context, plural=new.plural,
                    locations=list(new.locations), notes=list(new.notes), flags=set(new.flags))
        before = previous.pop(new.key, None)
        if before:
            m.comments = before.comments
            if "fuzzy" in before.flags:
                m.flags.add("fuzzy")
            if m.plural is None:
                m.msgstr = before.msgstr or before.msgstr_plural.get(0, "")
            else:
                m.msgstr_plural = {i: before.msgstr_plural.get(i, before.msgstr if i == 0 else "")
                                   for i in range(nplurals)}
        elif m.plural is not None:
            m.msgstr_plural = {i: "" for i in range(nplurals)}
        messages.append(m)
    # Text that's gone from the code stays at the end of the file, in case it comes back.
    for gone in previous.values():
        if gone.is_translated(nplurals) or gone.obsolete:
            gone.obsolete = True
            gone.locations, gone.notes = [], []
            messages.append(gone)
    return format_po(head_comments, header, messages), header, messages


def compile_mo(header, messages):
    """The .mo file for these messages, laid out like GNU msgfmt (and Python's msgfmt.py) does."""
    nplurals = nplurals_of(header)
    table = {b"": header.encode("utf-8")}
    for m in messages:
        if m.obsolete or "fuzzy" in m.flags or not m.is_translated(nplurals):
            continue
        key = m.msgid if m.context is None else f"{m.context}\x04{m.msgid}"
        if m.plural is None:
            table[key.encode("utf-8")] = m.msgstr.encode("utf-8")
        else:
            table[f"{key}\x00{m.plural}".encode("utf-8")] = "\x00".join(
                m.msgstr_plural[i] for i in range(nplurals)).encode("utf-8")
    keys = sorted(table)
    ids = strs = b""
    offsets = []
    for k in keys:
        offsets.append((len(ids), len(k), len(strs), len(table[k])))
        ids += k + b"\0"
        strs += table[k] + b"\0"
    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets, voffsets = [], []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    output = struct.pack("Iiiiiii", 0x950412DE, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, keystart)
    output += struct.pack(f"{len(koffsets)}i", *koffsets) if koffsets else b""
    output += struct.pack(f"{len(voffsets)}i", *voffsets) if voffsets else b""
    return output + ids + strs


def languages():
    return [code for code, _ in settings.LANGUAGES if code != settings.LANGUAGE_CODE]


def problems_in(message, nplurals):
    """Mistakes in a translation that would break the page: missing placeholders or tags."""
    found = []
    if message.plural is None:
        pairs = [(message.msgid, message.msgstr)]
    else:
        pairs = [(message.msgid if i == 0 else message.plural, message.msgstr_plural.get(i, ""))
                 for i in range(nplurals)]
    for english, translated in pairs:
        if not translated:
            continue
        want, got = FORMAT_RE.findall(english), FORMAT_RE.findall(translated)
        named = [w for w in want if w]
        if named:
            if sorted(set(got)) != sorted(set(named)) or "" in got:
                found.append("the placeholders (%(…)s) don't match the English")
        elif len(got) != len(want) and not (message.plural and len(want) == 1 and len(got) == 0):
            found.append("the number of %s placeholders doesn't match the English")
        if sorted(TAG_RE.findall(english)) != sorted(TAG_RE.findall(translated)):
            found.append("the HTML tags don't match the English")
    return found


def status():
    """What `translations check` reports: a list of problems, empty when everything is in order."""
    report = []
    try:
        extracted = extract()
    except ExtractError as exc:
        return [str(exc)]
    for language in languages():
        for domain, found in extracted.items():
            path = po_path(language, domain)
            rel = path.relative_to(settings.BASE_DIR)
            text, header, messages = merged(language, domain, found)
            nplurals = nplurals_of(header)
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                report.append(f"{rel} doesn't match the site's text. Run: python manage.py translations update")
            for m in messages:
                if m.obsolete:
                    continue
                label = f'"{m.msgid}"' + (f" ({m.context})" if m.context else "")
                if not m.is_translated(nplurals):
                    report.append(f"{rel}: no translation yet for {label}")
                elif "fuzzy" in m.flags:
                    report.append(f"{rel}: the translation of {label} is marked fuzzy (needs checking)")
                for problem in problems_in(m, nplurals):
                    report.append(f"{rel}: in the translation of {label}, {problem}")
            mo = path.with_suffix(".mo")
            if not mo.exists() or mo.read_bytes() != compile_mo(header, messages):
                report.append(f"{mo.relative_to(settings.BASE_DIR)} is out of date. "
                              "Run: python manage.py translations compile")
    return report


def update():
    """Writes each language's .po files with the current text. Returns what changed, for display."""
    extracted = extract()
    changes = []
    for language in languages():
        for domain, found in extracted.items():
            path = po_path(language, domain)
            text, header, messages = merged(language, domain, found)
            missing = sum(1 for m in messages if not m.obsolete and not m.is_translated(nplurals_of(header)))
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                changes.append(f"Updated {path.relative_to(settings.BASE_DIR)} ({missing} still to translate)")
            else:
                changes.append(f"{path.relative_to(settings.BASE_DIR)} was already up to date "
                               f"({missing} still to translate)")
    return changes


def compile_all():
    changes = []
    for language in languages():
        for domain in ("django", "djangojs"):
            path = po_path(language, domain)
            if not path.exists():
                continue
            _, header, messages = parse_po(path.read_text(encoding="utf-8"))
            data = compile_mo(header, messages)
            mo = path.with_suffix(".mo")
            if not mo.exists() or mo.read_bytes() != data:
                mo.write_bytes(data)
                changes.append(f"Compiled {mo.relative_to(settings.BASE_DIR)}")
            else:
                changes.append(f"{mo.relative_to(settings.BASE_DIR)} was already up to date")
    return changes
