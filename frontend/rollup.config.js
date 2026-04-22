import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import terser from '@rollup/plugin-terser';

const production = process.env.NODE_ENV === 'production';

export default {
  input: 'src/splitsmart-card.ts',
  output: {
    file: '../custom_components/splitsmart/frontend/splitsmart-card.js',
    format: 'es',
    sourcemap: true,
    inlineDynamicImports: true,
  },
  plugins: [
    resolve({ browser: true }),
    typescript({ tsconfig: './tsconfig.json', sourceMap: true, inlineSources: !production }),
    production && terser({
      format: { comments: false },
      compress: { passes: 2 },
    }),
  ].filter(Boolean),
  external: [],
};
