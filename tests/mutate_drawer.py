#!/usr/bin/env python3
"""Mutation-test tests/regression/test_drawer_close.js.

Every anchor is asserted present before the mutation is applied. An anchor that
has drifted is reported as ANCHOR-MISSING and counted as a FAILURE, never as a
pass -- a mutation script that silently no-ops produces a green run that proves
nothing, which has happened twice in this repo already.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
F = "view/build_view.py"

M = [
 # ---- the close guard itself -------------------------------------------
 ("guard removed from requestCloseDrawer",
  "  if(!leaveDrawerOk()) return;\n  closeDrawer();", "  closeDrawer();"),
 ("dirty flag cleared BEFORE the prompt (silent 2nd discard)",
  "function requestCloseDrawer(){\n  if(!leaveDrawerOk()) return;",
  "function requestCloseDrawer(){\n  const w=drawerDirty; drawerDirty=false;\n  if(w && !confirmDiscard()) return;"),
 ("guard leaked into the save path",
  "function closeDrawer(){\n  drawerDirty = false;",
  "function closeDrawer(){\n  if(!leaveDrawerOk()) return;\n  drawerDirty = false;"),
 ("confirm wording inverted (OK now means keep)",
  "  return confirm('Discard your unsaved changes to '", "  return confirm('Keep editing '"),
 ("confirm no longer names the record",
  "    + (what ? '\"' + what + '\"' : 'this record')", "    + 'this record'"),

 # ---- the three close affordances ---------------------------------------
 ("Escape wired to the bare close",
  "    requestCloseDrawer();\n  }\n});", "    closeDrawer();\n  }\n});"),
 ("Escape loses its is-open check",
  "  if(e.key === 'Escape' && document.getElementById('drawer').classList.contains('open')){",
  "  if(e.key === 'Escape'){"),
 ("X reverted to the bare close",
  'id="drawerX" onclick="requestCloseDrawer()"', 'id="drawerX" onclick="closeDrawer()"'),
 ("X reverted BUT a decoy requestCloseDrawer button added elsewhere",
  '<div class="drawer" id="drawer" tabindex="-1"><div class="dh"><h3 id="dtitle"></h3><button class="x" id="drawerX" onclick="requestCloseDrawer()">',
  '<button class="x" onclick="requestCloseDrawer()" hidden></button>\n<div class="drawer" id="drawer" tabindex="-1"><div class="dh"><h3 id="dtitle"></h3><button class="x" id="drawerX" onclick="closeDrawer()">'),
 ("scrim click listener removed",
  "document.getElementById('scrim').addEventListener('click', e=>{", "const _dead = (e=>{"),
 ("double-click guard removed (detail>1)", "  if(e && e.detail > 1) return;\n", ""),

 # ---- the dirty flag -----------------------------------------------------
 ("dirty listener never bound",
  "['input','change'].forEach(ev=>\n  document.getElementById('dbody').addEventListener(ev, ()=>{\n    drawerDirty = true;\n  }));", ""),
 ("openDrawer forgets to reset dirty",
  "function openDrawer(){\n  drawerDirty = false;", "function openDrawer(){"),
 ("a successful save no longer clears the dirty flag",
  "      drawerDirty = false;\n      msg.textContent='\u2713 Saved';",
  "      msg.textContent='\u2713 Saved';"),
  ("navFromDrawer clears dirty even though the opener may bail",
  "  // clean, to be discarded later without asking.\n  open();",
  "  // clean, to be discarded later without asking.\n  open();\n  drawerDirty = false;"),
 ("+ Add shipment bypasses navFromDrawer again",
  "onclick=\"navFromDrawer(()=>openNewShipment('${jesc(pno)}'))\"",
  "onclick=\"openNewShipment('${jesc(pno)}')\""),

 # ---- the failed-save path ----------------------------------------------
 ("failed save still triggers the reopen (hides a partial write)",
  "if(renamed && ok) openProject(pno);", "if(renamed) openProject(pno);"),
 ("doSave stops reporting success",
  "      kpis(); renderMain();\n      return true;",
  "      kpis(); renderMain();\n      return undefined;"),

 # ---- the scrim ----------------------------------------------------------
 ("scrim never shown on open",
  "  document.getElementById('scrim').classList.add('open');\n", ""),
 ("scrim base pointer-events:none dropped (app-wide click eater)",
  "  .scrim{position:fixed;inset:0;background:rgba(20,30,50,.28);opacity:0;\n         pointer-events:none;",
  "  .scrim{position:fixed;inset:0;background:rgba(20,30,50,.28);opacity:0;\n         "),
 ("scrim inset:0 -> inset:auto (covers nothing)",
  ".scrim{position:fixed;inset:0;", ".scrim{position:fixed;inset:auto;"),
 ("scrim z-index below the sticky header",
  "pointer-events:none;transition:opacity .18s ease;z-index:19}",
  "pointer-events:none;transition:opacity .18s ease;z-index:1}"),

 # ---- focus containment --------------------------------------------------
 ("page never goes inert (keyboard reaches under the scrim)", "  pageInert(true);\n", ""),
 ("page left inert after close (app becomes unclickable)", "  pageInert(false);\n", ""),
 ("closed drawer left in the tab order", "  d.inert = true;\n  // restore focus", "  // restore focus"),
 ("open drawer left inert (cannot be typed into)",
  "  d.inert = false;                       // must precede focus()\n", ""),
 ("focusin fallback removed", "document.addEventListener('focusin', e=>{", "const _dead3 = (e=>{"),

 # ---- unload -------------------------------------------------------------
 ("beforeunload guard removed", "window.addEventListener('beforeunload', e=>{", "const _dead2 = (e=>{"),
 ("beforeunload returnValue set to '' (the do-not-prompt value)",
  "e.returnValue = 'You have unsaved changes in the open record.';", "e.returnValue = '';"),

 ("doSave clears the dirty flag on the FAILURE path",
  "    msg.textContent='\u2717 ' + ((r && r.error) || 'save failed'); msg.className='saved show errc';\n    return false;",
  "    msg.textContent='\u2717 ' + ((r && r.error) || 'save failed'); msg.className='saved show errc';\n    drawerDirty = false;\n    return false;"),
 ("doSave clears the dirty flag in catch()",
  "    msg.textContent='\u2717 ' + e.message; msg.className='saved show errc';\n    return false;",
  "    msg.textContent='\u2717 ' + e.message; msg.className='saved show errc';\n    drawerDirty = false;\n    return false;"),
 ("doSave applies the local write even when the store refused",
  "    const r = await CRM.call(tool, args);\n    if (r && r.ok){\n      applyLocal(r);",
  "    const r = await CRM.call(tool, args);\n    applyLocal(r);\n    if (r && r.ok){"),
 ("a refused rename falls through instead of aborting",
  "    const rr = await CRM.call('rename_project', {old_project_no: pno, new_project_no: newPno});\n    if(!rr || !rr.ok){",
  "    const rr = await CRM.call('rename_project', {old_project_no: pno, new_project_no: newPno});\n    if(!rr){"),
 ("a refused rename leaves the save button disabled",
  "      msg.textContent='\u2717 '+((rr&&rr.error)||'rename failed'); msg.className='saved show errc';\n      btn.disabled=false;\n      return;\n    }\n    // Mirror the rename",
  "      msg.textContent='\u2717 '+((rr&&rr.error)||'rename failed'); msg.className='saved show errc';\n      return;\n    }\n    // Mirror the rename"),
 ("a committed rename is not recorded, so a retry re-fires it",
  "    pnoEl.setAttribute('data-orig', newPno);\n", ""),
  ("the drawer no longer starts inert at page load",
  "document.getElementById('drawer').inert = true;\n", ""),
 ("the save-time form lock is removed",
  "    body.querySelectorAll('input,select,textarea').forEach(el=>{\n      if(!el.disabled){ el.disabled = true; locked.push(el); }\n    });\n", ""),
 ("the form is never unlocked after a save",
  "    locked.forEach(el=>{ el.disabled = false; });\n", ""),
 # ---- structural ---------------------------------------------------------
 ("a 12th opener added that bypasses openDrawer (double quotes)",
  "function closeDrawer(){",
  'function openQuickNote(cid){\n  document.getElementById("dbody").innerHTML = "<textarea id=q_note></textarea>";\n  document.getElementById("drawer").classList.add("open");\n}\nfunction closeDrawer(){'),
 ("openDrawer made infinitely recursive",
  "  d.classList.add('open');", "  openDrawer();"),
]

sys.exit(mutate(SRC, "./tests/regression/test_drawer_close.js", F, M))
