#!/usr/bin/env python3
"""Drive the built page in a real headless Chromium, for a node test.

The node suite runs the bundle under a DOM shim (lib/view.js), which cannot
say what a browser paints. This driver loads the generated view.html from
disk in Chromium and runs a short script of clicks and evaluations, so a
node module can assert on rendered text. Playwright for node is not
installed on the build machine; Python's is, with its Chromium already
present. This never runs `playwright install`.

    stdin   {"html": "/abs/path/view.html" | "url": "http://127.0.0.1:PORT/",
             "steps": [{"wait": ms} | {"click": css} | {"eval": js, "as": name}
                       | {"select": css, "value": v} | {"fill": css, "value": v}]}
    stdout  {name: value, ..., "__pageerrors": [str, ...]}
            -- a step that fails is one of the __pageerrors, and ends the run

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
        # a live local_server.py page (a real server behind the clicks) or a
        # built file (embedded data)
        page.goto(req.get("url") or ("file://" + req["html"]), wait_until="load")
        # A step that fails -- a click on an element this build does not
        # render, an evaluation that throws -- ends the script and is REPORTED
        # as a page error, so the node module's own "the page ran with no
        # script error" check fails by name. Raising here killed the module
        # before it printed a verdict (0.1.38). The steps after it are skipped:
        # they assume a page state the failed step did not produce.
        for n, step in enumerate(req.get("steps", [])):
            try:
                if "wait" in step:
                    page.wait_for_timeout(step["wait"])
                elif "click" in step:
                    page.click(step["click"], timeout=5000)
                elif "select" in step:
                    page.select_option(step["select"], step["value"], timeout=5000)
                elif "fill" in step:
                    page.fill(step["fill"], step["value"], timeout=5000)
                elif "eval" in step:
                    out[step["as"]] = page.evaluate(step["eval"])
            except Exception as e:                    # noqa: BLE001
                what = (step.get("click") or step.get("select") or step.get("fill")
                        or step.get("as") or "wait")
                errors.append(f"step {n} ({what}) failed: "
                              f"{str(e).splitlines()[0][:200]}")
                break
        browser.close()
    out["__pageerrors"] = errors
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
