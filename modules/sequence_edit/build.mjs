import { build } from 'esbuild';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));

await build({
  absWorkingDir: root,
  entryPoints: ['ui/index.js'],
  bundle: true,
  format: 'esm',
  minify: true,
  supported: { 'template-literal': false },
  legalComments: 'inline',
  outfile: 'ui.js',
  plugins: [{
    name: 'studio-ribbon-lighting',
    setup(builder) {
      builder.onLoad({ filter: /3Dmol\.es6\.js$/ }, async ({ path }) => {
        const source = await readFile(path, 'utf8');
        // 3Dmol 2.5.5's mesh shaders have no ambient fill. Keep their geometry
        // and directional shading, with a light floor for the Studio palette.
        const ambient = /vLight(Front|Back) = vec3\( 0\.0 \);/g;
        const directional = /\+= directionalLightColor\[ 0 \] \*/g;
        if ([...source.matchAll(ambient)].length !== 4 ||
            [...source.matchAll(directional)].length !== 4) {
          throw new Error('3Dmol lighting source changed; review the Studio lighting adjustment.');
        }
        return {
          contents: source
            .replace(ambient, 'vLight$1 = vec3( 0.62 );')
            .replace(directional, '+= 0.38 * directionalLightColor[ 0 ] *'),
          loader: 'js',
        };
      });
    },
  }],
});
