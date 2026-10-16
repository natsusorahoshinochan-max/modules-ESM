import { createRequire } from 'node:module'

const requireTool = createRequire(new URL('./webui/package.json', import.meta.url))
const js = requireTool('@eslint/js')
const globals = requireTool('globals')
const reactHooks = requireTool('eslint-plugin-react-hooks')
const reactRefresh = requireTool('eslint-plugin-react-refresh')
const tseslint = requireTool('typescript-eslint')

export default tseslint.config(
  { ignores: ['webui/dist/**', 'modules/*/ui/build/**', '**/node_modules/**'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['webui/**/*.{ts,tsx}', 'modules/*/ui/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    },
  },
)
