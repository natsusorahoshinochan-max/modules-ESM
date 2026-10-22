// THROWAWAY: run the actual HTML compiler and serialize NaN coordinates explicitly.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const [inputPath, outputPath] = process.argv.slice(2);
const html = fs.readFileSync(path.join(__dirname, '../prototype_tool_boundary/index.html'), 'utf8');
const context = { structuredClone };
vm.runInNewContext(html.match(/<script id="prototype-core">([\s\S]*?)<\/script>/)[1], context);
const positions = JSON.parse(fs.readFileSync(inputPath, 'utf8')).positions;
// Explicitly selected condition tracks: this compiler exposes four tracks.
// Function intervals are exercised separately by the conditions→native adapter experiment.
const request = {
  task: 'complete_sequence', frame: '1PGA-frame',
  positions: positions.map(row => ({key: row.id, source: row.source, condition: {
    sequence: row.sequence_condition, atoms: row.coordinate_condition || {},
    secondary: row.secondary_structure_condition, sasa: row.sasa_condition
  }}))
};
const compiled = context.ToolBoundary.compileESM(request);
fs.writeFileSync(outputPath, JSON.stringify({
  executed: 'actual prototype_tool_boundary HTML compileESM pure function; no simulated transport called',
  selected_tracks: ['sequence', 'coordinates', 'secondary_structure', 'sasa'],
  coordinate_missing_encoding: 'JSON null explicitly represents compiler NaN; restore to float NaN before ESMProtein',
  request, compiled
}, null, 2) + '\n');
