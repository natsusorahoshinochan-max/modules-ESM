/** Complete coordinate-file UI using only public React and package file access. */
export const runtime = { react: 19 };
export function register({ React }) {
  const h = React.createElement;
  function Import({ context, parameters, onChange, readOnly }) {
    const h=React.createElement, [name,setName]=React.useState(''),[error,setError]=React.useState(''),[busy,setBusy]=React.useState(false);
    const pkg=context.inputs.file?.packages[0];
    React.useEffect(()=>{let active=true;setName('');if(pkg)context.host.readFile(pkg.id,pkg.entry).then(b=>b.text()).then(JSON.parse).then(d=>{if(active)setName(d.name??'已选择文件')}).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[pkg?.id]);
    async function select(e){const file=e.target.files?.[0];if(!file)return;setBusy(true);setError('');try{const format=/\.pdb$/i.test(file.name)?'pdb':/\.(cif|mmcif)$/i.test(file.name)?'mmcif':null;if(!format)throw new Error('请选择 PDB 或 mmCIF 文件');await context.update({delivery:{port:'file',input:{format:'workbench.structure_file',entry:'manifest.json',files:{'manifest.json':new Blob([JSON.stringify({name:file.name,file:'original',format})]),original:file}}},replaceConnections:['file']});setName(file.name)}catch(e){setError(String(e))}finally{setBusy(false)}}
    return h('section',null,name&&h('span',{className:'inline-file-name',title:name},name),h('label',{className:'inline-file-picker'},busy?'载入中…':name?'更换文件':'选择 PDB / mmCIF',h('input',{type:'file',accept:'.pdb,.cif,.mmcif',disabled:readOnly||busy,onChange:select})),h('details',null,h('summary',null,'构象'),h('select',{'aria-label':'构象',disabled:readOnly||busy,value:parameters.models==='all'||parameters.models===undefined?'all':'one',onChange:e=>onChange({...parameters,models:e.target.value==='all'?'all':1})},h('option',{value:'all'},'全部'),h('option',{value:'one'},'指定编号')),parameters.models!=='all'&&parameters.models!==undefined&&h('input',{type:'number','aria-label':'构象编号',step:1,value:parameters.models,disabled:readOnly||busy,onChange:e=>onChange({...parameters,models:Number(e.target.value)})})),error&&h('p',{role:'alert'},error));
  }
  function OperationEditor({context,parameters,onChange,readOnly,operation}) {
    const [objects,setObjects]=React.useState([]),[error,setError]=React.useState('');
    const pkg=context.inputs.structures?.packages[0];
    React.useEffect(()=>{let live=true;setObjects([]);setError('');if(pkg)context.host.readFile(pkg.id,pkg.entry).then(b=>b.text()).then(JSON.parse).then(data=>{if(live)setObjects(data.objects??[])}).catch(e=>{if(live)setError(String(e))});return()=>{live=false}},[pkg?.id]);
    const update=(key,value)=>{const next={...parameters,...(operation==='workbench.transform_structure'&&(key==='rotation'||key==='translation')?{rotation:parameters.rotation??[[1,0,0],[0,1,0],[0,0,1]],translation:parameters.translation??[0,0,0]}:{})};if(value===undefined)delete next[key];else next[key]=value;onChange(next)};
    const selection=parameters.selection??{},mode=selection.chains?'chains':selection.positions?'positions':selection.atoms?'atoms':'all';
    const matrix=parameters.rotation??[[1,0,0],[0,1,0],[0,0,1]],translation=parameters.translation??[0,0,0];
    return h('section',null,
      h('label',null,'对象',h('select',{'aria-label':'结构对象',disabled:readOnly,value:parameters.object??'',onChange:e=>update('object',e.target.value||undefined)},h('option',{value:''},objects.length===1?'唯一对象':'选择对象'),parameters.object&&!objects.some(o=>o.id===parameters.object)&&h('option',{value:parameters.object},'已选对象'),...objects.map((o,i)=>h('option',{key:o.id,value:o.id},o.label||`对象 ${i+1}`)))),
      h('label',null,'文件格式',h('select',{disabled:readOnly,value:parameters.format??'',onChange:e=>update('format',e.target.value)},h('option',{value:''},'选择格式'),h('option',{value:'mmcif'},'mmCIF'),h('option',{value:'pdb'},'PDB'))),
      operation!=='workbench.export_structure'&&h('label',null,'选区',h('select',{disabled:readOnly,value:mode,onChange:e=>update('selection',e.target.value==='all'?undefined:{[e.target.value]:[]})},h('option',{value:'all'},operation==='workbench.extract_structure'?'选择选区':'整体'),h('option',{value:'chains'},'链'),h('option',{value:'positions'},'残基'),h('option',{value:'atoms'},'原子'))),
      mode==='chains'&&h('label',null,'链（逗号分隔）',h('input',{disabled:readOnly,value:selection.chains.join(','),onChange:e=>update('selection',{chains:e.target.value.split(',')})})),
      mode==='atoms'&&h('label',null,'原子索引',h('input',{disabled:readOnly,value:selection.atoms.join(','),onChange:e=>{const tokens=e.target.value.split(',').filter(t=>t.trim());if(tokens.every(t=>/^\d+$/.test(t.trim())))update('selection',{atoms:tokens.map(Number)})}})),
      mode==='positions'&&h('div',null,...selection.positions.map((p,i)=>h('div',{className:'position-fields',key:i},...['chain','author_number','insertion_code'].map((key,j)=>h('label',{key},['链','编号','插入码'][j],h('input',{disabled:readOnly,type:key==='author_number'?'number':'text',value:p[key]??'',onChange:e=>update('selection',{positions:selection.positions.map((old,index)=>index===i?{...old,[key]:key==='author_number'?Number(e.target.value):e.target.value}:old)})}))),h('button',{disabled:readOnly,onClick:()=>update('selection',{positions:selection.positions.filter((_,index)=>index!==i)})},'×'))),h('button',{disabled:readOnly,onClick:()=>update('selection',{positions:[...selection.positions,{chain:'A',author_number:1,insertion_code:''}]})},'添加残基')),
      operation==='workbench.transform_structure'&&h('fieldset',null,h('legend',null,'坐标变换'),...matrix.map((row,i)=>h('div',{className:'matrix-row',key:`matrix-${i}`},...row.map((value,j)=>h('input',{key:j,type:'number',step:'any','aria-label':`旋转矩阵 ${i+1},${j+1}`,disabled:readOnly,value,onChange:e=>update('rotation',matrix.map((r,a)=>r.map((n,b)=>a===i&&b===j?Number(e.target.value):n)))})))),...translation.map((value,i)=>h('label',{key:`translation-${i}`},`${'XYZ'[i]} (Å)`,h('input',{type:'number',step:'any',disabled:readOnly,value,onChange:e=>update('translation',translation.map((old,j)=>i===j?Number(e.target.value):old))})))),
      operation==='workbench.export_structure'&&h('label',null,'原子索引（留空导出全部）',h('input',{disabled:readOnly,value:(parameters.atoms??[]).join(','),onChange:e=>{const tokens=e.target.value.split(',').filter(t=>t.trim());if(tokens.every(t=>/^\d+$/.test(t.trim())))update('atoms',tokens.length?tokens.map(Number):undefined)}})),
      error&&h('p',{role:'alert'},error));
  }
  function Viewer({ package: pkg, host }) {
    const [data, setData] = React.useState(null), [object, setObject] = React.useState('');
    const [atoms, setAtoms] = React.useState([]), [selected, setSelected] = React.useState([]);
    const [angle, setAngle] = React.useState(0), [tilt, set俯仰] = React.useState(0), [format, setFormat] = React.useState('mmcif');
    const [error, setError] = React.useState('');
    const [rotation, set旋转视角] = React.useState([[1,0,0],[0,1,0],[0,0,1]]), [translation, setTranslation] = React.useState([0,0,0]);
    React.useEffect(() => {
      let active = true; setData(null); setObject(''); setAtoms([]); setSelected([]); setError('');
      host.readFile(pkg.id, pkg.entry).then(b => b.text()).then(JSON.parse).then(d => { if (active) { setData(d); setObject(d.objects[0].id); } }).catch(e => { if (active) setError(String(e)); });
      return () => { active = false; };
    }, [pkg.id, pkg.entry, host.readFile]);
    React.useEffect(() => {
      let active = true; setAtoms([]); setSelected([]);
      const obj = data?.objects.find(o => o.id === object);
      if (obj) host.readFile(pkg.id, obj.atoms).then(b => b.text()).then(JSON.parse).then(a => { if (active) setAtoms(a); }).catch(e => { if (active) setError(String(e)); });
      return () => { active = false; };
    }, [data, object, pkg.id, host.readFile]);
    function toggle(index) { setSelected(s => s.includes(index) ? s.filter(i => i !== index) : [...s, index]); }
    async function exportSelection() {
      if (host.readOnly) return;
      try {
        await host.addNode({ type: 'workbench.export_structure', inputs: { structures: [pkg.id] }, parameters: { object, format, ...(selected.length ? { atoms: selected } : {}) } });
        setError('已添加导出节点');
      } catch (failure) { setError(String(failure)); }
    }
    async function addOperation(kind) {
      if (host.readOnly) return;
      try {
        if (kind === 'extract' && !selected.length) throw new Error('请先选择原子、链或组分');
        const parameters = { object, format, ...(selected.length ? { selection: { atoms: selected } } : {}) };
        if (kind === 'transform') {
          parameters.rotation = rotation;
          parameters.translation = translation;
        }
        await host.addNode({ type: `workbench.${kind}_structure`, inputs: { structures: [pkg.id] }, parameters });
        setError('已添加节点');
      } catch (failure) { setError(String(failure)); }
    }
    const limits = [0, 1, 2].map(axis => atoms.reduce(([lo, hi], a) => [Math.min(lo, a.position[axis]), Math.max(hi, a.position[axis])], [Infinity, -Infinity]));
    const center = limits.map(([lo, hi]) => (lo + hi) / 2), span = Math.max(1, Math.hypot(...limits.map(([lo, hi]) => hi - lo)));
    const yaw = angle * Math.PI / 180, pitch = tilt * Math.PI / 180;
    const projected = atoms.map(a => {
      const [x, y, z] = a.position.map((p, i) => p - center[i]);
      const rx = x * Math.cos(yaw) + z * Math.sin(yaw), rz = z * Math.cos(yaw) - x * Math.sin(yaw);
      return { a, x: 300 + rx * 400 / span, y: 220 - (y * Math.cos(pitch) - rz * Math.sin(pitch)) * 400 / span, z: y * Math.sin(pitch) + rz * Math.cos(pitch) };
    }).sort((a, b) => a.z - b.z);
    const components = [...new Set(atoms.map(a => JSON.stringify([a.chain, a.author_number, a.insertion_code, a.residue_name])))];
    return h('section', null, h('h3', null, '三维结构'),
      data && h('select', { 'aria-label': '候选', value: object, onChange: e => setObject(e.target.value) }, data.objects.map(o => h('option', { key: o.id, value: o.id }, o.label || o.id))),
      h('label', null, '旋转视角', h('input', { type: 'range', min: -180, max: 180, value: angle, 'aria-label': 'Structure rotation', onChange: e => setAngle(Number(e.target.value)) })),
      h('label', null, '俯仰', h('input', { type: 'range', min: -90, max: 90, value: tilt, 'aria-label': 'Structure tilt', onChange: e => set俯仰(Number(e.target.value)) })),
      h('svg', { viewBox: '0 0 600 440', role: 'img', 'aria-label': 'Complete structure atoms', style: { width: '100%', maxWidth: 800, background: '#edf3fa' } }, projected.map(({ a, x, y }) => h('circle', {
        key: a.index, cx: x, cy: y, r: selected.includes(a.index) ? 6 : 4, fill: selected.includes(a.index) ? '#e65c00' : '#2563aa', tabIndex: 0,
        'aria-label': `${a.model}: ${a.chain} ${a.author_number}${a.insertion_code} ${a.residue_name} ${a.atom_name} ${a.altloc}`,
        onClick: () => toggle(a.index), onKeyDown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(a.index); } },
      }, h('title', null, `${a.residue_name} ${a.atom_name}: ${a.position.join(', ')} Å`)))),
      h('p', null, `${atoms.length} 个原子 · 已选 ${selected.length}`),
      h('button', { onClick: () => setSelected([]) }, '取消选择'),
      h('details', null, h('summary', null, '选择链'), [...new Set(atoms.map(a => a.chain))].map(chain => {
        const indices = atoms.filter(a => a.chain === chain).map(a => a.index);
        return h('label', { key: chain, style: { display: 'block' } }, h('input', { type: 'checkbox', checked: indices.every(i => selected.includes(i)), onChange: e => setSelected(s => e.target.checked ? [...new Set([...s, ...indices])] : s.filter(i => !indices.includes(i))) }), `链 ${chain || '空白'}`);
      })),
      h('details', null, h('summary', null, '原子坐标 (Å)'), h('table', null,
        h('thead', null, h('tr', null, ['构象 / 链 / 残基', '原子 / 构象', 'x, y, z Å'].map(label => h('th', { key: label }, label)))),
        h('tbody', null, atoms.map(a => h('tr', { key: a.index }, h('td', null, `${a.model} / ${a.chain} / ${a.author_number}${a.insertion_code} ${a.residue_name}`), h('td', null, `${a.atom_name} ${a.altloc}`), h('td', null, `${a.position.join(', ')} Å`)))))),
      h('details', null, h('summary', null, '选择残基与组分'), components.map(key => {
        const [chain, number, insertion, name] = JSON.parse(key);
        const indices = atoms.filter(a => a.chain === chain && a.author_number === number && a.insertion_code === insertion && a.residue_name === name).map(a => a.index);
        return h('label', { key, style: { display: 'block' } }, h('input', { type: 'checkbox', checked: indices.every(i => selected.includes(i)), onChange: e => setSelected(s => e.target.checked ? [...new Set([...s, ...indices])] : s.filter(i => !indices.includes(i))) }), `${chain} ${number}${insertion} ${name}`);
      })),
      h('select', { 'aria-label': 'Export structure format', value: format, onChange: e => setFormat(e.target.value) }, h('option', { value: 'mmcif' }, 'mmCIF'), h('option', { value: 'pdb' }, 'PDB')),
      h('button', { disabled: host.readOnly || !atoms.length, onClick: exportSelection }, '添加导出节点'),
      h('button', { disabled: host.readOnly || !selected.length, onClick: () => addOperation('extract') }, '提取选区'),
      h('details', null, h('summary', null, '移动与旋转'),
        h('fieldset',null,h('legend',null,'旋转矩阵 · 绕原点'),...rotation.map((row,i)=>h('div',{className:'matrix-row',key:`matrix-${i}`},...row.map((value,j)=>h('input',{key:j,type:'number',step:'any','aria-label':`旋转矩阵 ${i+1},${j+1}`,value,disabled:host.readOnly,onChange:e=>set旋转视角(old=>old.map((r,a)=>r.map((n,b)=>a===i&&b===j?Number(e.target.value):n)))}))))),
        ...translation.map((value,i)=>h('label',{key:`translation-${i}`},`${'XYZ'[i]} (Å)`,h('input',{type:'number',step:'any',value,disabled:host.readOnly,onChange:e=>setTranslation(old=>old.map((n,j)=>i===j?Number(e.target.value):n))}))),
        h('button', { disabled: host.readOnly || !atoms.length, onClick: () => addOperation('transform') }, '添加变换节点')),
      error && h('p', { role: 'status' }, error));
  }
  return { editors: [{ node: 'workbench.import_structure', inline: true, component: Import }, ...['workbench.extract_structure','workbench.transform_structure','workbench.export_structure'].map(node=>({node,component:props=>h(OperationEditor,{...props,operation:node})}))], viewers: [{ id: 'workbench.structure_io.complete', name: '三维结构', defaultFor: ['workbench.structure_set', 'workbench.coordinates'], formats: ['workbench.structure_set', 'workbench.coordinates'], component: Viewer }] };
}
