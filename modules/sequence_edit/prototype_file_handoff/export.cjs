// Throwaway bridge: execute the exact pure logic displayed by index.html.
const {readFileSync,writeFileSync}=require('node:fs');
const {join}=require('node:path');
const {runInNewContext}=require('node:vm');
if(process.argv.length!==4) throw new Error('Usage: node export.cjs CASE.json OUTPUT.json');
const html=readFileSync(join(__dirname,'index.html'),'utf8');
const scope={};
runInNewContext(html.match(/<script id="prototype-logic">([\s\S]*?)<\/script>/)[1],scope);
const P=scope.FileHandoffPrototype;
const input=JSON.parse(readFileSync(process.argv[2],'utf8'));
const state=input.actions.reduce((s,a)=>P.apply(s,a),P.initial());
writeFileSync(process.argv[3],JSON.stringify(P.payload(state),null,2)+'\n');
process.stdout.write(`Exported ${state.positions.length} target positions; mode=${state.fileOnly?'file only':'file and parameters'}.\n`);
