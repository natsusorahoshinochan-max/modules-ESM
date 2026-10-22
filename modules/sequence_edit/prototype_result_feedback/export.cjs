// THROWAWAY bridge: execute the very same pure logic exposed by the shareable HTML.
const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'index.html'),'utf8');
const fixture=html.match(/<script id="fixture-data">([\s\S]*?)<\/script>/)[1];
const logic=html.match(/<script id="feedback-logic">([\s\S]*?)<\/script>/)[1];
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const context={};vm.createContext(context);vm.runInContext(fixture+'\n'+logic+'\nglobalThis.api=Feedback;globalThis.data=FEEDBACK_DATA;',context);
let state=context.api.initial();const snapshots=[];for(const action of input.actions){state=context.api.reduce(state,action,context.data);snapshots.push({action,state});}
fs.writeFileSync(process.argv[3],JSON.stringify({delivery:context.api.delivery(state),snapshots},null,2)+'\n');
