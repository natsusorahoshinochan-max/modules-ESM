export const runtime = { react: 19 }
export function register({React}) {
  const h = React.createElement
  const project = xyz => [xyz[0]+.3*xyz[2],-xyz[1]-.2*xyz[2]]
  function fit(points) {
    const projected = points.map(project)
    if (!projected.length) return {scale:10,x:210,y:150}
    let left=Infinity,right=-Infinity,top=Infinity,bottom=-Infinity
    for (const [x,y] of projected) {left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y)}
    const scale=Math.min(10,372/Math.max(1,right-left),252/Math.max(1,bottom-top))
    return {scale,x:210-(left+right)/2*scale,y:150-(top+bottom)/2*scale}
  }
  function pointer(event, inverse) {
    return [inverse.a*event.clientX+inverse.c*event.clientY+inverse.e,inverse.b*event.clientX+inverse.d*event.clientY+inverse.f]
  }
  function Editor({context, parameters, readOnly}) {
    const [document, setDocument] = React.useState(null)
    const [preview, setPreview] = React.useState(null)
    const [geometry, setGeometry] = React.useState([]), [structureObject, setStructureObject] = React.useState('')
    const [structureRecord, setStructureRecord] = React.useState('')
    const [mapping, setMapping] = React.useState({}), [tracks, setTracks] = React.useState(['coordinates'])
    const [drag, setDrag] = React.useState(null), dragRef = React.useRef(null)
    const [undo, setUndo] = React.useState([])
    const [sequence, setSequence] = React.useState(parameters.sequence ?? '')
    const [seed, setSeed] = React.useState('0'), [count, setCount] = React.useState('1')
    const [start, setStart] = React.useState('0'), [end, setEnd] = React.useState('0')
    const [alphabet, setAlphabet] = React.useState('_'), [index, setIndex] = React.useState('0'), [insertion, setInsertion] = React.useState('_')
    const [selected, setSelected] = React.useState([]), [changes, setChanges] = React.useState('{"prompt":"_","fixed":false}')
    const [requesting,setRequesting] = React.useState(false)
    const [object, setObject] = React.useState(''), [busy, setBusy] = React.useState(false), [error, setError] = React.useState('')
    const expectedRevision = React.useRef(null), scope = `${context.projectId}:${context.nodeId}`, seenScope = React.useRef(scope), seenRevision = React.useRef(context.revision)
    const pending = React.useRef(null)
    const epoch = React.useRef(0), mounted = React.useRef(true), tokens = React.useRef(new Map())
    function releaseToken(id) {
      const origin = tokens.current.get(id)
      if (!origin) return Promise.resolve()
      tokens.current.delete(id)
      return origin.host.cancelPreview(id).catch(()=>{})
    }
    function stopRequests() {
      const owner = pending.current
      pending.current = null
      owner?.controller.abort()
      for (const id of tokens.current.keys()) void releaseToken(id)
    }
    React.useEffect(() => {
      mounted.current = true
      return () => {
        mounted.current = false; epoch.current++; stopRequests()
      }
    }, [])
    React.useEffect(() => {
      if (seenScope.current === scope && seenRevision.current === context.revision) return
      const sameScope = seenScope.current === scope
      seenScope.current = scope; seenRevision.current = context.revision
      if (sameScope && expectedRevision.current === context.revision) { expectedRevision.current = null; return }
      epoch.current++; stopRequests()
      setDocument(null); setPreview(null); setGeometry([]); setStructureRecord(''); setMapping({}); setDrag(null); dragRef.current=null; setUndo([]); setSelected([]); setBusy(false); setRequesting(false)
      setSequence(context.parameters.sequence ?? ''); setError('Node draft changed; load the current input again')
    }, [scope, context.revision])
    async function cancel() {
      epoch.current++; stopRequests(); setDrag(null); dragRef.current=null; setBusy(false); setRequesting(false); setError(''); setPreview(null)
    }
    async function request(operation, load = false, structural = false) {
      stopRequests()
      const current = ++epoch.current, origin = context, owner = {controller:new AbortController(),origin,token:null,ready:false}
      pending.current = owner
      const live = () => mounted.current && current === epoch.current && pending.current === owner
      setBusy(true); setRequesting(true); setError(''); setPreview(null)
      const inputs = Object.fromEntries(Object.entries(origin.inputs).map(([port,input]) => [port,input.packages.map(pkg => pkg.id)]))
      try {
        const accepted = origin.inputs.source?.packages.some(pkg=>pkg.format === 'workbench.sequence_conditions')
        if (!accepted && document && (document.structures?.length || document.positions.some(row=>row.coordinates !== null))) throw new Error('Select the accepted editing package before changing coordinate conditions')
        const parameters = accepted ? {} : document ? {document} : {sequence, ...(object ? {object} : {})}
        if (structural && (!operation || operation.kind === 'adopt_structure')) {
          parameters.structure = structureRecord ? {retained:structureRecord} : {input:'structures',object:structureObject}
          if (structureRecord) delete inputs.structures
        } else delete inputs.structures
        if (operation) parameters.operation = operation
        const result = await origin.host.preview(structural ? 'workbench.sequence_structure' : 'workbench.sequence_edit', inputs, parameters, {signal:owner.controller.signal})
        owner.token = result.id; tokens.current.set(result.id,origin)
        if (!live()) return
        if (result.data.document_file) {
          const blob = await origin.host.readPreviewFile(result.id,'edited',result.data.document_file,{signal:owner.controller.signal})
          if (!live()) return
          const actual = JSON.parse(await blob.text())
          if (!live()) return
          const view = result.data.view_file ? JSON.parse(await (await origin.host.readPreviewFile(result.id,'edited',result.data.view_file,{signal:owner.controller.signal})).text()) : []
          if (!live()) return
          result.data = {...result.data,document:actual}
          if (view.length) setGeometry(view)
        }
        setDrag(null); dragRef.current=null
        if (load) {
          setDocument(result.data.document); setEnd(String(result.data.document.positions.length)); setSelected([])
        } else { owner.ready=true; setPreview({...result, origin}) }
      } catch(error) { if (live()) {setDrag(null);dragRef.current=null;setError(error.message)} }
      finally {
        if (!owner.ready && owner.token) void releaseToken(owner.token)
        if (live()) {pending.current=null;setBusy(false);setRequesting(false)}
      }
    }
    async function confirm() {
      if (!preview) return
      setBusy(true); setError('')
      const before = {document, geometry, structureRecord, parameters: preview.origin.parameters, bindings: preview.origin.bindings,
        connections: preview.origin.edges.filter(edge => edge.target === preview.origin.nodeId)}
      try {
        expectedRevision.current = preview.origin.revision + 1
        // The admitted context transaction now owns reception of these files.
        tokens.current.delete(preview.id)
        await preview.origin.update({parameters: {}, delivery: {interaction:preview.id,output:'edited',port:'source'}, replaceConnections:['source']})
        if (!mounted.current) return
        setUndo(previous => [...previous,before]); setDocument(preview.data.document); setPreview(null); setSelected([])
        const added = (preview.data.document.structures ?? []).filter(record=>!document.structures?.some(old=>old.id === record.id))
        if (added.length === 1) setStructureRecord(added[0].id)
      } catch(error) { tokens.current.delete(preview.id); await preview.origin.host.cancelPreview(preview.id).catch(()=>{}); if (mounted.current) { expectedRevision.current=null; setError(error.message); setPreview(null) } }
      finally { if (mounted.current) setBusy(false) }
    }
    async function restore() {
      const previous = undo.at(-1)
      if (!previous) return
      setBusy(true); setError('')
      try {
        expectedRevision.current = context.revision + 1
        await context.update({parameters:previous.parameters,inputs:{...previous.bindings,source:previous.bindings.source ?? []},replaceConnections:['source'],connections:previous.connections})
        setDocument(previous.document); setGeometry(previous.geometry); setStructureRecord(previous.structureRecord); setUndo(undo.slice(0,-1)); setSelected([])
      } catch(error) { setError(error.message) }
      finally { if (mounted.current) setBusy(false) }
    }
    function field(label, value, setter, type='text') {
      return h('label',null,label,h('input',{type,value,onChange:event=>setter(event.target.value),disabled:readOnly || busy || !!preview}))
    }
    const rows = (drag?.document ?? preview?.data.document ?? document)?.positions ?? []
    const sourcePositions = [...new Map(geometry.map(atom=>[JSON.stringify([atom.model,atom.chain,atom.author_number,atom.insertion_code,atom.residue_name]),atom])).entries()]
    function move(event) {
      const current = dragRef.current
      if (!current || current.pointerId !== event.pointerId || readOnly || busy || preview) return
      const [x,y] = pointer(event,current.inverse)
      const translation = [(x-current.x)/current.frame.scale, -(y-current.y)/current.frame.scale, 0]
      const next = structuredClone(current.base)
      for (const row of next.positions) if (current.selected.includes(row.id) && row.coordinates) {
        row.coordinates = Object.fromEntries(Object.entries(row.coordinates).map(([name,xyz])=>[name,xyz.map((value,i)=>value+translation[i])]))
      }
      const value = {...current,translation,document:next}
      dragRef.current=value;setDrag(value)
    }
    const points = rows.flatMap(row=>Object.entries(row.coordinates ?? {}).map(([name,xyz])=>({row:row.id,name,xyz})))
    const frame = drag?.frame ?? fit([...points.map(point=>point.xyz),...geometry.map(atom=>atom.position)])
    const projected = xyz => {const [x,y]=project(xyz);return [frame.x+x*frame.scale,frame.y+y*frame.scale]}

    const disabled = readOnly || busy || !!preview || !document
    return h('section',{'aria-label':'Sequence and condition editor'},
      error && h('p',{role:'alert'},error),
      !document && h(React.Fragment,null,
        ...Object.values(context.inputs).map((input,i)=>input.unavailable && h('p',{key:i},input.unavailable)),
        field('Explicit initial sequence',sequence,setSequence),field('Sequence object (required for multiple objects)',object,setObject),
        h('button',{disabled:busy,onClick:()=>request(null,true)},'Load current sequence')),
      document && h(React.Fragment,null,
        h('p',null,'Sequence: ',(preview?.data.document ?? document).sequence),
        h('table',null,h('thead',null,h('tr',null,...['Select','Position','Residue','Prompt','Fixed','Structure conditions','Source position'].map(label=>h('th',{key:label},label)))),
          h('tbody',null,...rows.map((row,i)=>h('tr',{key:row.id},
            h('td',null,h('input',{type:'checkbox','aria-label':`Select position ${i+1}`,disabled:disabled,checked:selected.includes(row.id),onChange:event=>setSelected(event.target.checked ? [...selected,row.id] : selected.filter(id=>id!==row.id))})),
            h('td',null,i+1),h('td',null,row.residue),h('td',null,row.prompt),h('td',null,String(row.fixed)),h('td',null,JSON.stringify(row.coordinates)),h('td',null,JSON.stringify(row.source ?? null)))))),
        h('section',{'aria-label':'Structure conditions'},
          h('label',null,'Full structure source',h('select',{'aria-label':'Full structure source',value:structureRecord,disabled:busy || !!preview,onChange:event=>{setStructureRecord(event.target.value);setGeometry([]);setMapping({})}},
            h('option',{value:''},'Explicit structure input'),...(document.structures ?? []).map((record,i)=>h('option',{key:record.id,value:record.id},`Retained full structure ${i+1}`)))),
          !structureRecord && field('Structure object ID',structureObject,setStructureObject),
          h('button',{disabled:busy || !!preview,onClick:()=>request(null,true,true)},'Read selected structure'),
          ...['coordinates','residue','fixed'].map(track=>h('label',{key:track},h('input',{type:'checkbox',checked:tracks.includes(track),disabled,onChange:event=>setTracks(event.target.checked?[...tracks,track]:tracks.filter(value=>value!==track))}),`Adopt ${track} track`)),
          ...selected.map(id=>h('label',{key:id},`Source for edit position ${document.positions.findIndex(row=>row.id===id)+1}`,h('select',{value:mapping[id] ?? '',disabled,onChange:event=>setMapping({...mapping,[id]:event.target.value})},h('option',{value:''},'Choose actual structure position'),...sourcePositions.map(([key,atom])=>h('option',{key,value:key},`${atom.chain}:${atom.author_number}${atom.insertion_code} ${atom.residue_name} (model ${atom.model})`))))),
          h('button',{disabled:disabled || !selected.length || !tracks.length || selected.some(id=>!mapping[id]),onClick:()=>request({kind:'adopt_structure',tracks,mapping:selected.map(id=>{const [model,chain,author_number,insertion_code,residue_name]=JSON.parse(mapping[id]);return{edit_position:id,position:{model,chain,author_number,insertion_code,residue_name}}})},false,true)},'Preview local structure adoption'),
          h('p',null,'Drag selected coordinate conditions in the XY plane. Depth is projected diagonally; full source components remain visible in gray.'),
          h('svg',{'aria-label':'Structure condition geometry',width:420,height:300,viewBox:'0 0 420 300',style:{border:'1px solid #778',touchAction:'none',background:'#101b30'},
            onPointerDown:event=>{
              if(disabled || !selected.length || !selected.some(id=>document.positions.some(row=>row.id===id && row.coordinates)))return
              const matrix=event.currentTarget.getScreenCTM?.()
              if(!matrix){setError('The coordinate viewport is not visible');return}
              const inverse=matrix.inverse(),[x,y]=pointer(event,inverse)
              if(!Number.isFinite(x)||!Number.isFinite(y))return
              event.currentTarget.setPointerCapture?.(event.pointerId)
              dragRef.current={x,y,pointerId:event.pointerId,inverse,frame,base:document,selected:[...selected],document}
              setDrag(dragRef.current)
            },
            onPointerMove:move,
            onPointerCancel:()=>{dragRef.current=null;setDrag(null)},
            onPointerUp:event=>{
              if(!dragRef.current || dragRef.current.pointerId!==event.pointerId)return
              move(event);const value=dragRef.current;dragRef.current=null
              event.currentTarget.releasePointerCapture?.(event.pointerId)
              if(!readOnly && !busy && !preview && value.translation?.some(number=>number!==0))void request({kind:'transform_coordinates',positions:value.selected,rotation:[[1,0,0],[0,1,0],[0,0,1]],translation:value.translation},false,true)
              else setDrag(null)
            }},
            ...geometry.map(atom=>{const [cx,cy]=projected(atom.position);return h('circle',{key:'source'+atom.index,cx,cy,r:3,fill:'#7c8599'})}),
            ...points.map(point=>{const [cx,cy]=projected(point.xyz);return h('circle',{key:point.row+point.name,'data-condition-atom':point.row+':'+point.name,cx,cy,r:6,fill:selected.includes(point.row)?'#ffb347':'#50d9fa'},h('title',null,`${point.name}: ${point.xyz.join(', ')}`))})),
          h('button',{disabled:disabled || !selected.length,onClick:()=>request({kind:'update',positions:selected,changes:{coordinates:null}})},'Preview clear coordinates')),
        h('label',null,'Selected position changes (residue, prompt, fixed, coordinates)',h('textarea',{value:changes,disabled,onChange:event=>setChanges(event.target.value)})),
        h('button',{disabled:disabled || !selected.length,onClick:()=>{try{request({kind:'update',positions:selected,changes:JSON.parse(changes)})}catch(error){setError(error.message)}}},'Preview position changes'),
        h('button',{disabled:disabled || !selected.length,onClick:()=>request({kind:'delete',positions:selected})},'Preview delete'),
        h('button',{disabled:disabled || selected.length!==1,onClick:()=>{const order=document.positions.map(row=>row.id),at=order.indexOf(selected[0]);if(at>0){[order[at-1],order[at]]=[order[at],order[at-1]];request({kind:'reorder',positions:order})}}},'Preview move earlier'),
        h('button',{disabled:disabled || selected.length!==1,onClick:()=>{const order=document.positions.map(row=>row.id),at=order.indexOf(selected[0]);if(at>=0 && at<order.length-1){[order[at+1],order[at]]=[order[at],order[at+1]];request({kind:'reorder',positions:order})}}},'Preview move later'),
        field('Insertion gap (zero based)',index,setIndex,'number'),field('Insert residues',insertion,setInsertion),
        h('button',{disabled,onClick:()=>request({kind:'insert',index:Number(index),sequence:insertion})},'Preview insertion'),
        field('Random seed',seed,setSeed,'number'),field('Random count',count,setCount,'number'),field('First current gap',start,setStart,'number'),field('Last current gap (inclusive)',end,setEnd,'number'),field('Random residue alphabet',alphabet,setAlphabet),
        h('button',{disabled,onClick:()=>request({kind:'random_insert',seed:Number(seed),count:Number(count),start:Number(start),end:Number(end),alphabet})},'Preview random insertion'),
        h('button',{disabled,onClick:()=>request(null)},'Preview current content'),
        h('details',null,h('summary',null,'Accepted random operations (read only)'),h('pre',null,JSON.stringify(document.random_operations,null,2))),
        h('button',{disabled:disabled || !undo.length,onClick:restore},'Undo accepted edit')),
      preview && h('section',{'aria-label':'Actual edit preview'},h('p',null,'Confirm this actual sequence, positions and conditions: ',preview.data.document.sequence),
        h('pre',null,JSON.stringify(preview.data.document.random_operations,null,2)),
        context.edges.some(edge=>edge.target===context.nodeId && edge.target_port==='source') && h('p',null,'Confirm replaces the current source connection with this received input.'),
        h('button',{disabled:readOnly || busy,onClick:confirm},'Confirm edit and replace source input'),
        h('button',{disabled:busy,onClick:cancel},'Cancel preview')),
      requesting && h('button',{onClick:cancel},'Cancel pending preview'))
  }
  function Action({host}) {
    const [sequence,setSequence] = React.useState(''), [error,setError] = React.useState('')
    return h('section',null,h('label',null,'New edit sequence',h('input',{value:sequence,disabled:host.readOnly,onChange:event=>setSequence(event.target.value)})),
      h('button',{disabled:host.readOnly,onClick:async()=>{try{await host.addNode({type:'workbench.edit_sequence',parameters:{sequence},inputs:{}});setError('')}catch(error){setError(error.message)}}},'Add sequence editor'),error && h('p',{role:'alert'},error))
  }
  function Viewer({package:pkg,host}) {
    const [data,setData]=React.useState(null),[error,setError]=React.useState('')
    React.useEffect(()=>{let active=true;host.readFile(pkg.id,pkg.entry).then(blob=>blob.text()).then(text=>{if(active)setData(JSON.parse(text))}).catch(error=>{if(active)setError(error.message)});return()=>{active=false}},[pkg.id])
    return error ? h('p',{role:'alert'},error) : h('pre',null,JSON.stringify(data,null,2))
  }
  return {actions:[{id:'workbench.sequence_editor',name:'Sequence editor',component:Action}],editors:[{node:'workbench.edit_sequence',component:Editor}],
    viewers:[{id:'workbench.sequence_conditions',name:'Sequence and condition positions',formats:['workbench.sequence_conditions'],component:Viewer}]}
}
