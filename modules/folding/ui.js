/** Prediction UI uses only the public host interface and supplied React 19. */
export const runtime = { react: 19 };

function sequenceObjects(document) {
  if (!document || Object.keys(document).join() !== 'objects' || !Array.isArray(document.objects) || !document.objects.length) throw new Error('A nonempty sequence object batch is required.');
  const ids = new Set();
  for (const object of document.objects) {
    if (!object || typeof object !== 'object' || Object.keys(object).some(key => !['id', 'sequence', 'label', 'source', 'positions'].includes(key))) throw new Error('Unsupported sequence object components or conditions.');
    if (typeof object.id !== 'string' || !object.id || ids.has(object.id)) throw new Error('Sequence object IDs must be nonempty and unique.');
    ids.add(object.id);
    if (typeof object.sequence !== 'string' || !/^[ACDEFGHIKLMNPQRSTVWY]+$/.test(object.sequence)) throw new Error('Sequence requires the 20 standard amino acid letters.');
    if ('label' in object && typeof object.label !== 'string') throw new Error('Sequence label must be text.');
    if ('source' in object && (!object.source || Array.isArray(object.source) || typeof object.source !== 'object' || !Object.keys(object.source).length || Object.entries(object.source).some(([key, value]) => !['name', 'record', 'text'].includes(key) || typeof value !== 'string'))) throw new Error('Source requires explicit name, record or text fields.');
    if ('positions' in object) {
      if (!Array.isArray(object.positions) || object.positions.length !== object.sequence.length) throw new Error('Positions must cover every sequence residue.');
      const seen = new Set(), seenLabels = new Set();
      object.positions.forEach((position, index) => {
        if (!position || Object.keys(position).some(key => !['sequence_index', 'chain', 'author_number', 'insertion_code', 'label_position'].includes(key)) || position.sequence_index !== index + 1) throw new Error('Positions require ordered one-based sequence_index values.');
        const authorKeys = ['chain','author_number','insertion_code'];
        if (authorKeys.some(key=>key in position)) {
          if (!authorKeys.every(key=>key in position) || typeof position.chain !== 'string' || !Number.isSafeInteger(position.author_number) || typeof position.insertion_code !== 'string') throw new Error('Residue correspondence requires explicit chain, author_number and insertion_code.');
          const key = JSON.stringify([position.chain, position.author_number, position.insertion_code]);
          if (seen.has(key)) throw new Error('Repeated residue correspondence.');
          seen.add(key);
        }
        if ('label_position' in position) {
          const label=position.label_position;
          if (!label || Array.isArray(label) || Object.keys(label).length!==2 || typeof label.chain!=='string' || !label.chain || !Number.isSafeInteger(label.position) || label.position<1) throw new Error('Label correspondence requires chain and a positive one-based position.');
          const key=JSON.stringify([label.chain,label.position]);
          if(seenLabels.has(key))throw new Error('Repeated label correspondence.');
          seenLabels.add(key);
        }
      });
    }
  }
  return document.objects;
}

function predictionDocument(text) {
  const document = JSON.parse(text);
  if (!document || Object.keys(document).some(key => !['objects', 'tool'].includes(key)) || !document.tool || typeof document.tool.id !== 'string' || !document.tool.id || !document.tool.parameters || Array.isArray(document.tool.parameters) || typeof document.tool.parameters !== 'object') throw new Error('Prediction result requires the actual tool id and existing parameters.');
  if (!Array.isArray(document.objects) || !document.objects.length) throw new Error('Prediction result requires sequence objects.');
  sequenceObjects({ objects: document.objects.map(object => {
    if (!object || typeof object !== 'object' || Array.isArray(object)) throw new Error('Each prediction requires a sequence object.');
    return { id: object.id, sequence: object.sequence, ...('label' in object ? { label: object.label } : {}) };
  }) });
  const files = new Set();
  function file(key) {
    if (typeof key !== 'string' || !key || key === 'manifest.json') throw new Error('Result references require explicit file keys distinct from manifest.json.');
    files.add(key);
  }
  for (const object of document.objects) {
    if (Object.keys(object).some(key => !['id', 'sequence', 'label', 'input', 'structure', 'confidence', 'supplementary'].includes(key))) throw new Error('Unsupported prediction result fields.');
    if ('input' in object) {
      sequenceObjects({ objects: [object.input] });
      if (object.input.sequence !== object.sequence) throw new Error('Supplied input sequence and prediction sequence disagree.');
    }
    if (!object.structure || !['pdb', 'mmcif'].includes(object.structure.format)) throw new Error('Each prediction requires a PDB or mmCIF structure.');
    file(object.structure.file);
    if ('confidence' in object) {
      const confidence = object.confidence;
      if (!confidence || Object.keys(confidence).some(key => !['plddt', 'ptm'].includes(key))) throw new Error('Unsupported prediction confidence.');
      if ('plddt' in confidence) {
        if (confidence.plddt?.scale !== '0-1') throw new Error('Prediction pLDDT requires its declared 0-1 scale.');
        file(confidence.plddt.file);
      }
      if ('ptm' in confidence && (typeof confidence.ptm !== 'number' || !Number.isFinite(confidence.ptm) || confidence.ptm < 0 || confidence.ptm > 1)) throw new Error('Prediction pTM must be a finite 0-1 value.');
    }
    if ('supplementary' in object) file(object.supplementary?.file);
  }
  return { document, keys: [...files] };
}

export async function predictionInput(text, bindings) {
  const { document, keys } = predictionDocument(text);
  const files = Object.create(null);
  for (const key of keys) {
    const blob = Object.hasOwn(bindings, key) && bindings[key];
    if (!(blob instanceof Blob) || !blob.size) throw new Error(`Select the required file for ${key}.`);
    files[key] = blob;
  }
  for (const object of document.objects) {
    if (object.confidence?.plddt) {
      const { plddt } = JSON.parse(await files[object.confidence.plddt.file].text());
      if (!Array.isArray(plddt) || plddt.length !== object.sequence.length || plddt.some(value => typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 1)) throw new Error('Prediction pLDDT must contain one finite 0-1 value per sequence residue.');
    }
    if (object.supplementary) JSON.parse(await files[object.supplementary.file].text());
  }
  files['manifest.json'] = new Blob([text], { type: 'application/json' });
  return { format: 'workbench.prediction', entry: 'manifest.json', files };
}

export function register({ React }) {
  const h = React.createElement;
  function PredictionInput({ host }) {
    const [text, setText] = React.useState('');
    const [keys, setKeys] = React.useState([]);
    const [bindings, setBindings] = React.useState({});
    const [error, setError] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const generation = React.useRef(0);
    React.useEffect(() => () => { generation.current++; }, []);
    async function select(event) {
      const request = ++generation.current;
      setText(''); setKeys([]); setBindings({}); setError(''); setStatus('');
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        const value = await file.text();
        const { keys } = predictionDocument(value);
        if (generation.current !== request) return;
        setText(value); setKeys(keys);
      } catch (failure) { if (generation.current === request) setError(String(failure)); }
    }
    async function add() {
      setBusy(true); setError(''); setStatus('');
      try {
        const input = await predictionInput(text, bindings);
        await host.createInput(input);
        setStatus('已导入，可在结果面板查看。');
      } catch (failure) { setError(String(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null, h('h3', null, '导入预测结果'),
      h('label', null, '结果清单', h('input', { type: 'file', accept: '.json', 'aria-label': '结果清单', disabled: host.readOnly || busy, onChange: select })),
      ...keys.map(key => h('label', { key }, key, h('input', { type: 'file', 'aria-label': `File for ${key}`, disabled: host.readOnly || busy, onChange: event => { const file = event.target.files?.[0]; setBindings(current => ({ ...current, [key]: file })); setError(''); setStatus(''); } }))),
      h('button', { disabled: host.readOnly || busy || !text, onClick: add }, busy ? '导入中…' : '导入'),
      status && h('p', { role: 'status' }, status), error && h('p', { role: 'alert' }, error));
  }
  function PredictionViewer({ package: pkg, host }) {
    const [manifest,setManifest]=React.useState(null),[index,setIndex]=React.useState(0),[confidence,setConfidence]=React.useState(null),[error,setError]=React.useState(''),[format,setFormat]=React.useState('mmcif'),[added,setAdded]=React.useState(false);
    React.useEffect(()=>{let live=true;setManifest(null);setIndex(0);setError('');setAdded(false);host.readFile(pkg.id,pkg.entry).then(b=>b.text()).then(JSON.parse).then(value=>{if(live)setManifest(value)}).catch(e=>{if(live)setError(String(e))});return()=>{live=false}},[pkg.id,pkg.entry]);
    const object=manifest?.objects[index];
    React.useEffect(()=>{let live=true;setConfidence(null);if(object?.confidence?.plddt?.file)host.readFile(pkg.id,object.confidence.plddt.file).then(b=>b.text()).then(JSON.parse).then(value=>{if(live)setConfidence(value)}).catch(e=>{if(live)setError(String(e))});return()=>{live=false}},[pkg.id,object]);
    const values=confidence?.plddt??[],mean=values.length?values.reduce((sum,n)=>sum+n,0)/values.length:null;
    return h('section',null,error&&h('p',{role:'alert'},error),manifest&&h('label',null,'候选',h('select',{'aria-label':'预测候选',value:index,onChange:e=>{setIndex(Number(e.target.value));setAdded(false)}},manifest.objects.map((item,i)=>h('option',{key:item.id,value:i},item.label||`候选 ${i+1}`)))),
      object&&h(React.Fragment,null,h('p',null,`${object.sequence.length} 个残基`),h('pre',null,object.sequence),
        h('dl',{className:'metric-summary'},mean!==null&&h(React.Fragment,null,h('dt',null,'平均 pLDDT'),h('dd',null,mean.toFixed(3))),object.confidence?.ptm!==undefined&&h(React.Fragment,null,h('dt',null,'pTM'),h('dd',null,typeof object.confidence.ptm==='number'?object.confidence.ptm.toFixed(3):object.confidence.ptm.value))),
        values.length>0&&h('figure',null,h('svg',{viewBox:'0 0 360 110',role:'img','aria-label':'逐残基 pLDDT'},h('line',{x1:0,x2:360,y1:100,y2:100,stroke:'#ccd6e4'}),h('polyline',{points:values.map((n,i)=>`${i*360/Math.max(1,values.length-1)},${100-n*90}`).join(' '),fill:'none',stroke:'#5278d3',strokeWidth:2})),h('figcaption',null,`逐残基 pLDDT · 0–1 · ${values.length} 个位置`)),
        h('details',null,h('summary',null,'导出结构'),h('select',{'aria-label':'结构文件格式',value:format,onChange:e=>setFormat(e.target.value)},h('option',{value:'mmcif'},'mmCIF'),h('option',{value:'pdb'},'PDB')),h('button',{disabled:host.readOnly,onClick:async()=>{try{await host.addNode({type:'workbench.export_structure',inputs:{structures:[pkg.id]},parameters:{object:object.id,format}});setAdded(true)}catch(e){setError(String(e))}}},added?'已添加导出节点':'添加导出节点'))));
  }

  return {
    actions: [{ id: 'workbench.prediction.import', name: '导入预测结果', component: PredictionInput }],
    viewers: [{ id: 'workbench.prediction.files', name: '预测结果', defaultFor: ['workbench.prediction'], formats: ['workbench.prediction'], component: PredictionViewer }],
  };
}
