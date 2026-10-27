import { build } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
const directory = mkdtempSync(fileURLToPath(new URL('../../node_modules/.language-', import.meta.url)))
process.once('exit', () => rmSync(directory, {recursive: true, force: true}))
await build({stdin: {contents: `export * from './i18n'; export {loadExtensions} from './host-ui'; export {ParameterFields} from './ParameterFields';`, resolveDir: fileURLToPath(new URL('../../src', import.meta.url)), loader:'tsx'},bundle:true,format:'esm',jsx:'automatic',external:['react','react/jsx-runtime'],outfile:directory+'/runtime.mjs'})
const runtime = await import(pathToFileURL(directory+'/runtime.mjs'))
export const {i18n,setLocale,text,useLocale,LanguagePicker,initialLocale,loadExtensions,localizeCatalog,ParameterFields}=runtime
