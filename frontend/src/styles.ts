// Shared styles for the Splitsmart card.
//
// Step 2 scope: @font-face declarations only, installed into document.head
// so they apply inside every shadow root. Design tokens (CSS variables,
// typography, spacing, motion) land in step 6.

const FONTS_URL_BASE = '/splitsmart-static/fonts';

/**
 * Install @font-face rules into the light DOM once. @font-face inside a
 * shadow root does not register fonts for the document, so we inject a
 * <style> tag into <head> the first time any Splitsmart element mounts.
 * Idempotent.
 */
export function ensureFontsLoaded(): void {
  if (document.getElementById('splitsmart-fonts')) return;
  const style = document.createElement('style');
  style.id = 'splitsmart-fonts';
  style.textContent = `
    @font-face {
      font-family: 'DM Sans';
      src: url('${FONTS_URL_BASE}/DMSans-variable.woff2') format('woff2-variations');
      font-weight: 100 900;
      font-style: normal;
      font-display: swap;
    }
    @font-face {
      font-family: 'DM Mono';
      src: url('${FONTS_URL_BASE}/DMMono-400.woff2') format('woff2');
      font-weight: 400;
      font-style: normal;
      font-display: swap;
    }
    @font-face {
      font-family: 'DM Mono';
      src: url('${FONTS_URL_BASE}/DMMono-500.woff2') format('woff2');
      font-weight: 500;
      font-style: normal;
      font-display: swap;
    }
  `;
  document.head.appendChild(style);
}
