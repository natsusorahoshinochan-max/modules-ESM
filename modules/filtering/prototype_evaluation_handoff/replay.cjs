// THROWAWAY: execute the exact pure logic embedded in the shareable HTML.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const script = html.match(/<script id="logic">([\s\S]*?)<\/script>/)[1];
const context = vm.createContext({});
vm.runInContext(script + '\nglobalThis.logic = Logic;', context);
const collection = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const plan = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const packages = collection.objects.map(object => ({...collection, objects:[object], evaluations:collection.evaluations.filter(e => e.subject_id === object.object_id)}));
const merged = context.logic.merge(packages);
function run(parameters) {
  const selected = context.logic.select(merged, parameters);
  return {parameters, selected_ids:selected.map(row=>row.object.object_id), values:selected.map(row=>row.value), extracted:context.logic.extract(merged, selected)};
}
const primary = run(plan.primary_filter);
const empty = run(plan.empty_filter);
if (empty.selected_ids.length) throw Error('Strict threshold should be empty');
const choices = collection.score_options.map(option => run({...plan.primary_filter, score_key:option.key}));
process.stdout.write(JSON.stringify({primary, empty, choices, shared_logic:'index.html#logic'}));
