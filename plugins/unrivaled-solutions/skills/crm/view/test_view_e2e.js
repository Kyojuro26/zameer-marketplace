// End-to-end verification of the wired CRM view (run in /tmp/viewtest).
// Loads the real unrivaled-crm.html in jsdom, lets it detect the dev bridge,
// drives the actual UI functions (open drawer, set fields, save), then
// asserts the store JSON ON DISK changed. Also verifies the embedded
// (demo) fallback when no backend is reachable.
const fs = require("fs");
const { JSDOM } = require("jsdom");

const HTML = process.argv[2];
const STORE = process.argv[3];
let pass = 0, fail = 0;
const check = (name, cond, detail = "") => {
  console.log(`  ${cond ? "PASS" : "FAIL"}  ${name}${cond ? "" : "  [" + detail + "]"}`);
  cond ? pass++ : fail++;
};
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function makeDom({ withFetch }) {
  return new JSDOM(fs.readFileSync(HTML, "utf8"), {
    runScripts: "dangerously",
    url: "http://localhost/",
    beforeParse(window) {
      window.fetch = withFetch ? fetch.bind(globalThis) : () => Promise.reject(new Error("offline"));
      window.AbortController = AbortController;
      window.__opens = []; window.open = (u) => { window.__opens.push(u); return {}; };
    },
  });
}

async function waitFor(fn, ms = 5000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(100); }
  return false;
}

(async () => {
  console.log("== live mode (dev bridge) ==");
  const dom = makeDom({ withFetch: true });
  const w = dom.window;
  const livePill = await waitFor(() =>
    w.document.getElementById("modePill").textContent.includes("dev bridge"));
  check("backend auto-detected -> Live pill", livePill,
        w.document.getElementById("modePill").textContent);
  const nCo = Number(w.eval("DATA.companies.length"));
  const nStore = JSON.parse(fs.readFileSync(`${STORE}/companies.json`)).length;
  check("live refresh loaded companies", nCo === nStore, `${nCo} vs ${nStore}`);

  // -- project edit through the real UI path
  w.select("total-truck-parts");
  check("company page rendered",
        w.document.getElementById("main").textContent.includes("Total Truck Parts"));
  w.openProject("1338");
  check("project drawer open",
        w.document.getElementById("drawer").classList.contains("open"));
  w.document.getElementById("f_status").value = "won";
  w.document.getElementById("f_coll").value = "paid";
  w.document.getElementById("f_owner").value = "D";
  w.document.getElementById("f_notes").value = "e2e-view-test";
  await w.saveProject("1338");
  const savedMsg = w.document.getElementById("savedMsg");
  check("UI shows Saved", savedMsg.textContent.includes("Saved"), savedMsg.textContent);
  const proj = JSON.parse(fs.readFileSync(`${STORE}/projects.json`))
    .find(p => String(p.project_no) === "1338");
  check("edit persisted to disk (notes)", proj.notes === "e2e-view-test", proj.notes);
  check("edit persisted to disk (status/coll/owner)",
        proj.status === "won" && proj.collection_status === "paid"
        && JSON.stringify(proj.owner) === '["D"]');

  // -- validation error surfaces in UI (bad stage via direct call path)
  const bad = await w.eval("CRM.call('update_project',{project_no:'1338',fields:{status:'bogus'}})");
  check("server rejects bad value through view client", bad.ok === false);

  // -- shipment stage advance through the real UI path
  const sid = w.eval("DATA.shipments.find(s => s.company_id === 'inked-brands').shipment_id");
  w.select("inked-brands");
  w.openShipment(sid);
  check("shipment drawer open",
        w.document.getElementById("dtitle").textContent.includes(sid));
  w.document.getElementById("s_stage").value = "Delivered";
  w.document.getElementById("s_date").value = "2026-07-02";
  await w.saveShipment(sid);
  const ship = JSON.parse(fs.readFileSync(`${STORE}/shipments.json`))
    .find(s => s.shipment_id === sid);
  check("stage advance persisted to disk",
        ship.stage === "Delivered" && ship.ship_date === "2026-07-02",
        `${ship.stage} ${ship.ship_date}`);

  // -- changelog records the UI-driven writes
  const log = fs.readFileSync(`${STORE}/changelog.jsonl`, "utf8").trim().split("\n").map(JSON.parse);
  check("changelog captured UI writes",
        log.some(e => e.entity === "project" && e.key === "1338" && e.fields.notes === "e2e-view-test")
        && log.some(e => e.entity === "shipment" && e.key === sid));

  // -- enrichment overlay renders on the company page (Phase 4)
  await fetch("http://127.0.0.1:8765/call", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool: "set_enrichment", args: { company_id: "ford", data: {
      last_contact: "2026-06-30",
      threads: [{ subject: "RE: racking quote", with: "jhaysley@ford.com",
                  date: "2026-06-30", webLink: "https://outlook.example/t1" }],
      source: "e2e" } } }) });
  w.select("ford");
  const enriched = await waitFor(() =>
    w.document.getElementById("main").textContent.includes("RE: racking quote"));
  check("enrichment section renders threads + last contact", enriched
        && w.document.getElementById("main").textContent.includes("2026-06-30"));
  w.select("total-truck-parts");
  const emptyEnrich = await waitFor(() =>
    w.document.getElementById("main").textContent.includes("No Outlook signal"));
  check("un-enriched company shows honest empty state", emptyEnrich);

  // -- invoices section (pipeline v2 receivables ledger)
  w.select("blu-distribution");
  await sleep(150);
  check("invoices section renders for invoice client",
        w.document.getElementById("main").textContent.includes("Invoices / customer orders"),
        w.document.getElementById("main").textContent.slice(0,80));

  // -- click-to-draft: falls back to compose link when Outlook unconfigured
  await w.draft("jhaysley@ford.com", "Jeff Haysley");
  check("draft falls back to mailto when Graph unconfigured",
        w.__opens.length === 1 && w.__opens[0].startsWith("mailto:jhaysley@ford.com"),
        JSON.stringify(w.__opens));
  // -- click-to-draft: opens the real draft webLink when the tool succeeds
  w.eval("window.__origCall = CRM.call.bind(CRM); CRM.call = async (t,a) => t==='draft_email' ? ({ok:true,draft:{webLink:'https://outlook.example/d9'}}) : ({ok:false})");
  await w.draft("jhaysley@ford.com", "Jeff Haysley");
  check("draft opens Outlook webLink when draft_email succeeds",
        w.__opens[1] === "https://outlook.example/d9", JSON.stringify(w.__opens));
  w.eval("CRM.call = window.__origCall");  // restore the real client

  // -- create records through the UI (live mode only)
  w.select("total-truck-parts");
  await sleep(150);
  check("create buttons visible when live",
        w.document.getElementById("main").innerHTML.includes("+ New project"));
  w.openNewProject("total-truck-parts");
  w.document.getElementById("n_pno").value = "7777";
  w.document.getElementById("n_desc").value = "e2e new project";
  w.document.getElementById("n_rev").value = "1200";
  w.document.getElementById("n_owner").value = "D";
  await w.saveNewProject("total-truck-parts");
  const newProj = JSON.parse(fs.readFileSync(`${STORE}/projects.json`))
    .find(p => String(p.project_no) === "7777");
  check("new project persisted to disk", !!newProj && newProj.description === "e2e new project",
        JSON.stringify(newProj || null));
  w.openNewProject("total-truck-parts");
  w.document.getElementById("n_pno").value = "7777";
  await w.saveNewProject("total-truck-parts");
  check("duplicate project # rejected in UI",
        w.document.getElementById("savedMsg").textContent.includes("already exists"),
        w.document.getElementById("savedMsg").textContent);
  w.openNewContact("total-truck-parts");
  w.document.getElementById("n_name").value = "E2E Person";
  w.document.getElementById("n_email").value = "e2e@totaltruck.com";
  await w.saveNewContact("total-truck-parts");
  check("new contact persisted to disk",
        JSON.parse(fs.readFileSync(`${STORE}/contacts.json`))
          .some(c => c.email === "e2e@totaltruck.com"));
  w.openNewShipment("7777");
  w.document.getElementById("n_po").value = "PO# E2E";
  await w.saveNewShipment("7777");
  const newShip = JSON.parse(fs.readFileSync(`${STORE}/shipments.json`))
    .find(s => s.shipment_id === "7777-L1");
  check("new shipment persisted with derived id + Ordered default",
        !!newShip && newShip.stage === "Ordered", JSON.stringify(newShip || null));

  console.log("== demo fallback (no backend) ==");
  const dom2 = makeDom({ withFetch: false });
  const w2 = dom2.window;
  const demoPill = await waitFor(() =>
    w2.document.getElementById("modePill").textContent.includes("Demo"));
  check("no backend -> Demo pill", demoPill, w2.document.getElementById("modePill").textContent);
  w2.select("total-truck-parts");
  w2.openProject("1338");
  w2.document.getElementById("f_notes").value = "demo-only";
  await w2.saveProject("1338");
  check("demo save works in-session",
        w2.eval("DATA.projects.find(p => String(p.project_no) === '1338').notes") === "demo-only");
  const projAfter = JSON.parse(fs.readFileSync(`${STORE}/projects.json`))
    .find(p => String(p.project_no) === "1338");
  check("demo save does NOT touch disk", projAfter.notes === "e2e-view-test");

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
