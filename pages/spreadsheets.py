import csv

from django.http import HttpResponse


def _cell(value):
    """Keeps spreadsheet apps from running anything that looks like a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def csv_download(filename, header, rows):
    """A spreadsheet (CSV file) to download, which Excel opens with accented names intact."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # lets Excel read accented names correctly
    writer = csv.writer(response)
    writer.writerow([str(h) for h in header])
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return response
