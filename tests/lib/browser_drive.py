#!/usr/bin/env python3
"""Drive the built page in a real headless Chromium, for a node test.

The node suite runs the bundle under a DOM shim (lib/view.js), which cannot
say what a browser paints. This driver loads the generated view.html from
disk in Chromium and runs a short script of clicks and evaluations, so a
node module can assert on rendered text. Playwright for node is not
installed on the build machine; Python's is, with its Chromium already
present. This never runs `playwright install`.

    stdin   {"html": "/abs/path/view.html",
             "steps": [{"wait": ms} | {"click": css} | {"eval": js, "as": name}]}
    stdout  {name: value, ..., "__pageerrors": [str, ...]}

Loaded over file://, the page's CRM.detect() finds no bridge and no Cowork
and stays in embedded mode -- the data baked in at build time, which is what
these tests seed.
"""
import json
import sys

from playwright.sync_api import sync_playwright


def main():
    req = json.load(sys.stdin)
    out, errors = {}, []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("file://" + req["html"], wait_until="load")
        for step in req.get("steps", []):
            if "wait" in step:
                page.wait_for_timeout(step["wait"])
            elif "click" in step:
                page.click(step["click"])
            elif "eval" in step:
                out[step["as"]] = page.evaluate(step["eval"])
        browser.close()
    out["__pageerrors"] = errors
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
