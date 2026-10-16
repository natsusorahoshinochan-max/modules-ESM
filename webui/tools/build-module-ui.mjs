import { createRequire } from 'node:module'
import { readFile, readdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const toolchain = process.env.PROTEIN_WORKBENCH_UI_TOOLCHAIN ?? resolve(root, 'webui')
const requireTool = createRequire(resolve(toolchain, 'package.json'))
const { build } = requireTool('esbuild')
const destination = process.argv[2] ? resolve(process.argv[2]) : root
const shared = ['react', 'react/jsx-runtime', 'react-dom']
const runtimeFields = { react: 'React', 'react/jsx-runtime': 'jsxRuntime', 'react-dom': 'ReactDOM' }
for (const entry of await readdir(resolve(root, 'modules'), { withFileTypes: true })) {
  if (!entry.isDirectory()) continue
  const moduleDirectory = resolve(root, 'modules', entry.name)
  const children = await readdir(moduleDirectory)
  if (!children.includes('ui')) continue
  const config = JSON.parse(await readFile(resolve(moduleDirectory, 'ui/module-ui.json'), 'utf8'))
  await build({
    entryPoints: [resolve(moduleDirectory, 'ui', config.entry)],
    outfile: resolve(destination, 'modules', entry.name, 'ui', config.output),
    nodePaths: [resolve(toolchain, 'node_modules')],
    bundle: true, format: 'esm', platform: 'browser', target: 'es2022', jsx: 'automatic',
    minify: false, legalComments: 'none',
    plugins: [{ name: 'shared-react', setup(builder) {
      builder.onResolve({ filter: /^react(?:\/jsx-runtime)?$|^react-dom$/ }, args => ({ path: args.path, namespace: 'host-runtime' }))
      builder.onLoad({ filter: /.*/, namespace: 'host-runtime' }, args => {
        if (!shared.includes(args.path)) throw new Error(`Unsupported shared dependency ${args.path}`)
        const names = Object.keys(requireTool(args.path)).filter(name => name !== 'default' && !name.startsWith('__'))
        return { contents: `const runtime = globalThis[Symbol.for('protein-workbench.module-ui.v1')].${runtimeFields[args.path]}; export default runtime; export const {${names.join(',')}} = runtime;`, loader: 'js' }
      })
    } }],
  })
}
