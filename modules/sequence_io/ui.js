/** Sequence import, viewing and export through the public module UI. */
export const runtime = { react: 19 };

export function parseSequence(text) {
  const lines = text.trim().split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const headers = lines.filter(line => line.startsWith('>'));
  if (headers.length > 1) throw new Error('Multiple FASTA records: use batch import.');
  if (headers.length && !lines[0].startsWith('>')) throw new Error('FASTA must start with a header.');
  const sequence = (headers.length ? lines.slice(1) : lines).join('').replace(/\s/g, '').toUpperCase();
  if (!sequence || !/^[ACDEFGHIKLMNPQRSTVWYBXZJUO_]+$/.test(sequence)) throw new Error('Enter amino-acid letters or _ for an unfilled position.');
  return { sequence, ...(headers.length && lines[0].slice(1).trim() ? { label: lines[0].slice(1).trim() } : {}) };
}

export function parseBatch(text) {
  const records = text.trim().split(/(?=^>)/m).filter(record => record.trim());
  if (!records.length || records.some(record => !record.trim().startsWith('>'))) throw new Error('Batch import requires FASTA records with headers.');
  return records.map(parseSequence);
}

function sequenceObjects(document) {
  if (!document || Object.keys(document).join() !== 'objects' || !Array.isArray(document.objects) || !document.objects.length) throw new Error('A nonempty sequence object batch is required.');
  const ids = new Set();
  for (const object of document.objects) {
    if (!object || typeof object !== 'object' || Object.keys(object).some(key => !['id', 'sequence', 'label', 'source', 'positions'].includes(key))) throw new Error('Unsupported sequence object components or conditions.');
    if (typeof object.id !== 'string' || !object.id || ids.has(object.id)) throw new Error('Sequence object IDs must be nonempty and unique.');
    ids.add(object.id);
    if (typeof object.sequence !== 'string' || !/^[ACDEFGHIKLMNPQRSTVWYBXZJUO_]+$/.test(object.sequence)) throw new Error('Sequence requires supported amino-acid letters or _.');
    if ('label' in object && typeof object.label !== 'string') throw new Error('Sequence label must be text.');
    if ('source' in object && (!object.source || Array.isArray(object.source) || typeof object.source !== 'object' || !Object.keys(object.source).length || Object.entries(object.source).some(([key, value]) => !['name', 'record', 'text'].includes(key) || typeof value !== 'string'))) throw new Error('Source requires explicit name, record or text fields.');
    if ('positions' in object) {
      if (!Array.isArray(object.positions) || object.positions.length !== object.sequence.length) throw new Error('Positions must cover every sequence residue.');
      const seen = new Set(), seenLabels = new Set();
      const positionIds = object.positions.filter(position => position && 'id' in position).map(position => position.id);
      if (positionIds.length && (positionIds.length !== object.positions.length || positionIds.some(id => typeof id !== 'string' || !id) || new Set(positionIds).size !== positionIds.length)) throw new Error('Position ids must be unique and cover the complete sequence.');
      object.positions.forEach((position, index) => {
        if (!position || Object.keys(position).some(key => !['sequence_index', 'id', 'chain', 'author_number', 'insertion_code', 'label_position'].includes(key)) || position.sequence_index !== index + 1) throw new Error('Positions require ordered one-based sequence_index values.');
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

export function sequenceInput(text, { batch = false, name, json = false } = {}) {
  const objects = json ? sequenceObjects(JSON.parse(text)) : (batch ? parseBatch(text) : [parseSequence(text)]).map(object => ({
    id: crypto.randomUUID(), ...object,
    source: { ...(name ? { name } : {}), ...(object.label ? { record: object.label } : {}), text },
    positions: Array.from(object.sequence, (_, index) => ({ sequence_index: index + 1 })),
  }));
  return { format: 'workbench.sequence', entry: 'manifest.json', files: {
    'manifest.json': new Blob([JSON.stringify({ objects })], { type: 'application/json' }),
  } };
}


export function register({ React }) {
  const h = React.createElement;
  function SequenceInput({ context, readOnly }) {
    const host=context.host;
    const [{ text, name }, setDraft] = React.useState({ text: '', name: '' });
    const [batch, setBatch] = React.useState(false);
    const [json, setJson] = React.useState(false);
    const [error, setError] = React.useState('');
    const [status, setStatus] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const inputId=context.inputs.file?.packages[0]?.id;
    React.useEffect(()=>{let active=true;const pkg=context.inputs.file?.packages[0];if(pkg)host.readFile(pkg.id,pkg.entry).then(b=>b.text()).then(JSON.parse).then(doc=>{if(active){setJson(true);setDraft({text:JSON.stringify(doc),name:doc.objects?.[0]?.source?.name??''});setStatus(`${doc.objects.length} 条序列`);}}).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[inputId]);
    const [reading, setReading] = React.useState(false);
    const pendingRead = React.useRef(null);
    const latestHost = React.useRef(host);
    latestHost.current = host;
    function invalidateRead() {
      pendingRead.current = null;
      setReading(false);
    }
    React.useEffect(() => {
      invalidateRead();
      return () => { pendingRead.current = null; };
    }, [host]);
    function currentRead(request) {
      return pendingRead.current === request && latestHost.current === request.host && !request.host.readOnly;
    }
    async function select(event) {
      invalidateRead();
      const file = event.target.files?.[0];
      if (!file) return;
      const request = { host };
      pendingRead.current = request;
      setReading(true); setError('');
      try {
        const value = await file.text();
        if (!currentRead(request)) return;
        setJson(/\.json$/i.test(file.name)); setDraft({ text: value, name: file.name }); setError('');
      } catch (failure) {
        if (currentRead(request)) setError(String(failure));
      } finally {
        if (currentRead(request)) invalidateRead();
      }
    }
    async function add() {
      if (pendingRead.current || host.readOnly || busy) return;
      setBusy(true); setError(''); setStatus('');
      try {
        await context.update({delivery:{input:sequenceInput(text,{batch,name,json}),port:'file'},replaceConnections:['file']});
        setStatus('已载入');
      } catch (failure) { setError(String(failure)); }
      finally { setBusy(false); }
    }
    return h('section', null,
      h('label', null, '格式', h('select', { 'aria-label': 'Sequence input format', value: json ? 'json' : 'fasta', disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setJson(event.target.value === 'json'); setDraft({text:'',name:''}); setStatus(''); setError(''); } }, h('option', { value: 'fasta' }, '序列 / FASTA'), h('option', { value: 'json' }, '序列数据文件'))),
      !json && h('label', null, h('input', { type: 'checkbox', 'aria-label': '多条序列', checked: batch, disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setBatch(event.target.checked); setError(''); } }), '多条序列'),
      !json && h('label', null, batch ? 'FASTA' : '序列', h('textarea', { value: text, disabled: host.readOnly || busy, onChange: event => { invalidateRead(); setDraft({ text: event.target.value, name: '' }); setError(''); } })),
      name&&h('span',{className:'inline-file-name'},name),h('label', {className:'inline-file-picker'}, '选择文件', h('input', { type: 'file', accept: json ? '.json' : '.fasta,.fa,.faa,.txt', disabled: host.readOnly || busy,
        onChange: select })),
      h('button', { disabled: host.readOnly || busy || reading, onClick: add }, busy ? '载入中…' : '载入'),
      status && h('p', { role: 'status' }, status),
      error && h('p', { role: 'alert' }, error));
  }
  function SequenceViewer({ package: pkg, host }) {
    const [objects, setObjects] = React.useState([]);
    const [selected, setSelected] = React.useState([]);
    const [error, setError] = React.useState('');
    React.useEffect(() => {
      let active = true;
      setObjects([]); setSelected([]); setError('');
      host.readFile(pkg.id, pkg.entry).then(blob => blob.text()).then(text => {
        const values = sequenceObjects(JSON.parse(text));
        if (active) { setObjects(values); setSelected(values.map(object => object.id)); }
      }).catch(failure => { if (active) setError(String(failure)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    return h('section', null, h('h3', null, '序列'),
      ...objects.map((object,index) => h('article', {key: object.id},
        h('label', null, h('input', {type:'checkbox', checked:selected.includes(object.id),
          onChange:event => setSelected(current => event.target.checked ? [...current,object.id] : current.filter(id=>id!==object.id))}), object.label || `序列 ${index+1}`),
        h('pre', null, object.sequence),
        object.source?.name && h('p', null, object.source.name),
        object.positions && h('details', null, h('summary', null, '位置对应'), h('table',null,h('thead',null,h('tr',null,...['位置','链','原始编号'].map(name=>h('th',{key:name},name)))),h('tbody',null,object.positions.map(p=>h('tr',{key:p.sequence_index},h('td',null,p.sequence_index),h('td',null,p.chain??'—'),h('td',null,p.author_number==null?'—':`${p.author_number}${p.insertion_code??''}`)))))))),
      h('button', {disabled:host.readOnly || !selected.length, onClick:async()=>{
        try { await host.addNode({type:'workbench.export_sequences',inputs:{sequences:[pkg.id]},parameters:{objects:objects.filter(object=>selected.includes(object.id)).map(object=>object.id)}}); }
        catch(failure){setError(String(failure));}
      }}, '导出 FASTA'), error && h('p', {role:'alert'}, error));
  }
  return {
    editors: [{node:'workbench.import_sequence',inline:true,component:SequenceInput}],
    viewers: [{id:'workbench.sequence.files',name:'序列',defaultFor:['workbench.sequence'],formats:['workbench.sequence'],component:SequenceViewer}],
  };
}
