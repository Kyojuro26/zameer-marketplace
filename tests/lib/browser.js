// A real browser for a node test: hands lib/browser_drive.py a page and a
// script of clicks and evaluations, and returns what Chromium painted.
const { execFileSync } = require('child_process');
const path = require('path');

/**
 * @param {string} htmlPath  absolute path of a built view.html
 * @param {Array}  steps     [{wait: ms} | {click: css} | {eval: js, as: name}]
 * @returns {object}         {name: value, ..., __pageerrors: [...]}
 */
function drive(htmlPath, steps) {
  const out = execFileSync('python3', [path.join(__dirname, 'browser_drive.py')], {
    input: JSON.stringify({ html: htmlPath, steps }),
    encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 120000,
  });
  return JSON.parse(out);
}

/** The same, against a live URL (a local_server.py started by the test). */
function driveUrl(url, steps) {
  const out = execFileSync('python3', [path.join(__dirname, 'browser_drive.py')], {
    input: JSON.stringify({ url, steps }),
    encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'], timeout: 180000,
  });
  return JSON.parse(out);
}

module.exports = { drive, driveUrl };
