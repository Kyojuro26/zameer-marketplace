// End-to-end for the add/delete customer+vendor UI added for Dylan.
// Loads the real HTML in jsdom against a live dev bridge, drives the new
// drawers/buttons, and asserts the store JSON on disk actually changed.
// Usage: NODE_PATH=<jsdom> node test_view_crud_e2e.js <html> <store>
const fs = require("fs");
const { JSDOM } = require("jsdom");
const HTML = process.argv[2], STORE = process.argv[3];
let pass = 0, fail = 0;
const check = (n, c, d = "") => { console.log(`  ${c ? "PASS" : "FAIL"}  ${n}${c ? "" : "  [" + d + "]"}`); c ? pass++ : fail++; };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const load = (f) => JSON.parse(fs.readFileSync(`${STORE}/${f}.json`));
async function waitFor(fn, ms = 5000) { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(80); } return false; }

(async () => {
  const dom = new JSDOM(fs.readFileSync(HTML, "utf8"), {
    runScripts: "dangerously", url: "http://localhost/",
    beforeParse(window) {
      window.fetch = fetch.bind(globalThis);
      window.AbortController = AbortController;
      window.open = () => ({});
      window.confirm = () => true;   // auto-approve the delete confirmation
    },
  });
  const w = dom.window;
  const live = await waitFor(() => w.document.getElementById("modePill").textContent.includes("dev bridge"));
  check("live pill (dev bridge)", live);
  check("add-row visible in live mode",
        w.document.getElementById("addrow").style.display === "flex");

  // ---- add customer ----
  const nCo0 = load("companies").length;
  w.eval("openNewCompany('customer')");
  w.document.getElementById("c_name").value = "UI Added Customer";
  w.document.getElementById("c_loc").value = "Jeffersonville, IN";
  await w.eval("saveNewCompany('customer')");
  await waitFor(() => load("companies").some(c => c.company_id === "ui-added-customer"));
  const cust = load("companies").find(c => c.company_id === "ui-added-customer");
  check("new customer persisted to disk", !!cust && cust.role === "customer" && !cust.archived);
  check("companies grew by 1", load("companies").length === nCo0 + 1);

  // ---- add vendor ----
  const nV0 = load("vendors").length;
  w.eval("openNewCompany('vendor')");
  w.document.getElementById("c_name").value = "UI Added Vendor";
  w.document.getElementById("c_rep").value = "Sam Vendor";
  w.document.getElementById("c_offer").value = "Racking";
  await w.eval("saveNewCompany('vendor')");
  await waitFor(() => load("vendors").some(v => v.company_id === "ui-added-vendor"));
  const ven = load("vendors").find(v => v.company_id === "ui-added-vendor");
  const venCo = load("companies").find(c => c.company_id === "ui-added-vendor");
  check("new vendor detail persisted", !!ven && ven.rep === "Sam Vendor");
  check("new vendor company is role=vendor", !!venCo && venCo.role === "vendor");
  check("vendors grew by 1", load("vendors").length === nV0 + 1);

  // ---- delete (archive) the customer ----
  await w.eval("deleteCompany('ui-added-customer')");
  await waitFor(() => { const c = load("companies").find(x => x.company_id === "ui-added-customer"); return c && c.archived; });
  const del = load("companies").find(c => c.company_id === "ui-added-customer");
  check("delete archives on disk (not destroyed)", !!del && del.archived === true && !!del.archived_at);
  check("archived customer removed from sidebar DATA",
        !w.eval("DATA.companies.some(c=>c.company_id==='ui-added-customer')"));

  const logOps = fs.readFileSync(`${STORE}/changelog.jsonl`, "utf8").trim().split("\n").map(JSON.parse).map(e => e.op);
  check("changelog logged create x2 + archive",
        logOps.filter(o => o === "create").length >= 2 && logOps.includes("archive"), logOps.slice(-5).join(","));

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
