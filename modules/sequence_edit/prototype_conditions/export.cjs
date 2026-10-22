// Throwaway bridge: run both portable representations on an explicit input fixture.
const {readFileSync,writeFileSync} = require('node:fs');
const {join} = require('node:path');
const {runInNewContext} = require('node:vm');
const assert = require('node:assert/strict');
if (process.argv.length !== 4) throw new Error('Usage: node export.cjs INPUT.json OUTPUT.json');
const html=readFileSync(join(__dirname,'index.html'),'utf8');
const context={};
runInNewContext(html.match(/<script id="prototype-logic">([\s\S]*?)<\/script>/)[1],context);
const P=context.ConditionsPrototype;
const input=JSON.parse(readFileSync(process.argv[2],'utf8'));
const run=kind=>input.actions.reduce((state,action)=>P.apply(state,action),P.fromSeed(kind,input.seed));
const rows=run('rows'),tracks=run('tracks');
const request=P.exportRequest(rows);
assert.deepEqual(P.exportRequest(tracks),request);
writeFileSync(process.argv[3],JSON.stringify({request,representationsEqual:true},null,2)+'\n');
process.stdout.write(`Both representations agree: ${input.seed.positions.length} -> ${request.positions.length} positions.\n`);
