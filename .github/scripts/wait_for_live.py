"""Waits until the live website runs a given commit, as /healthz reports it.

The publish workflow (.github/workflows/publish.yml) runs this after it moves the live
branch. The server checks GitHub every minute (deploy/publish.sh), so a new version
usually shows up within two or three minutes.

    python wait_for_live.py https://example.org/healthz COMMIT [SECONDS]
"""

import json
import sys
import time
import urllib.error
import urllib.request


def read_health(url):
    request = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "User-Agent": "tnt-publish-check"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:  # a 503 still carries the JSON
        try:
            return json.load(error)
        except ValueError:
            return {"error": f"HTTP {error.code}"}
    except (urllib.error.URLError, OSError, ValueError) as error:
        return {"error": str(error)}


def describe(health):
    if "error" in health:
        return f"The website didn't answer: {health['error']}"
    publish = health.get("publish") or {}
    line = f"Website runs {str(health.get('revision'))[:7]}, status {health.get('status')}"
    if publish:
        line += (
            f"; latest publish: {str(publish.get('revision'))[:7]} {publish.get('state')}"
            f" ({publish.get('message')})"
        )
    return line


def main(argv):
    url, revision = argv[1], argv[2]
    timeout = int(argv[3]) if len(argv) > 3 else 600
    deadline = time.monotonic() + timeout
    last = None
    while True:
        health = read_health(url)
        line = describe(health)
        if line != last:
            print(line, flush=True)
            last = line
        if health.get("revision") == revision and health.get("status") == "ok":
            print(f"The website is running {revision}.")
            return 0
        publish = health.get("publish") or {}
        if publish.get("revision") == revision and publish.get("state") == "failed":
            print(f"Publishing {revision} failed on the server: {publish.get('message')}")
            return 1
        if time.monotonic() >= deadline:
            print(f"The website didn't start running {revision} within {timeout} seconds.")
            return 1
        time.sleep(10)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
