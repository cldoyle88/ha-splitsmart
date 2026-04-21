// Shared styles and design tokens for the Splitsmart card.
//
// Two document-level <style> tags are installed lazily on first element
// mount: the @font-face rules (so the self-hosted DM Sans / DM Mono
// kick in) and the Splitsmart token variables (so every shadow root can
// read them via var()). Both are idempotent.
//
// HA's own theme variables (--primary-text-color, --card-background-color,
// etc.) are available directly via var() inside shadow DOM — we do not
// redeclare them here, only supply fallbacks at use sites.
//
// Typography, spacing, motion and semantic colours are owned by
// Splitsmart and exposed under the --ss-* prefix so users can override
// them from their custom theme if they want.

import { css } from 'lit';

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

/**
 * Install Splitsmart design tokens at :root scope so every shadow DOM
 * tree inherits them via var(). Called once on first element mount.
 */
export function ensureTokensInstalled(): void {
  if (document.getElementById('splitsmart-tokens')) return;
  const style = document.createElement('style');
  style.id = 'splitsmart-tokens';
  style.textContent = `
    :root {
      /* Semantic colours — override to match your theme. Fallbacks are
         chosen for WCAG AA contrast on both light and dark HA cards. */
      --ss-credit-color: #2e7d32;
      --ss-debit-color: #c62828;
      --ss-accent-color: var(--accent-color, #5b9f65);

      /* Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64 px. */
      --ss-space-1: 4px;
      --ss-space-2: 8px;
      --ss-space-3: 12px;
      --ss-space-4: 16px;
      --ss-space-5: 24px;
      --ss-space-6: 32px;
      --ss-space-7: 48px;
      --ss-space-8: 64px;

      /* Font stacks. */
      --ss-font-sans: 'DM Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
      --ss-font-mono: 'DM Mono', ui-monospace, 'SF Mono', Menlo, monospace;

      /* Typography tokens (size | weight | line-height). */
      --ss-text-display-size: 28px;
      --ss-text-display-weight: 600;
      --ss-text-display-line: 1.2;

      --ss-text-title-size: 20px;
      --ss-text-title-weight: 600;
      --ss-text-title-line: 1.3;

      --ss-text-body-size: 16px;
      --ss-text-body-weight: 400;
      --ss-text-body-line: 1.5;

      --ss-text-button-size: 15px;
      --ss-text-button-weight: 500;
      --ss-text-button-line: 1.4;

      --ss-text-caption-size: 13px;
      --ss-text-caption-weight: 400;
      --ss-text-caption-line: 1.4;

      --ss-text-mono-display-size: 28px;
      --ss-text-mono-display-weight: 500;
      --ss-text-mono-display-line: 1.2;

      --ss-text-mono-amount-size: 16px;
      --ss-text-mono-amount-weight: 500;
      --ss-text-mono-amount-line: 1.3;

      --ss-text-mono-caption-size: 13px;
      --ss-text-mono-caption-weight: 400;
      --ss-text-mono-caption-line: 1.4;

      /* Motion tokens. */
      --ss-duration-fast: 120ms;
      --ss-duration-base: 180ms;
      --ss-duration-slow: 260ms;
      --ss-easing-standard: cubic-bezier(0.2, 0, 0, 1);
      --ss-easing-enter: cubic-bezier(0, 0, 0, 1);
      --ss-easing-exit: cubic-bezier(0.4, 0, 1, 1);

      /* Hit-target minimum (SPEC §15: 44x44 CSS px throughout). */
      --ss-touch-min: 44px;

      /* Card internals. */
      --ss-card-radius: var(--ha-card-border-radius, 12px);
    }
  `;
  document.head.appendChild(style);
}

/** Call on every component's connectedCallback. Both helpers are idempotent. */
export function installGlobalStyles(): void {
  ensureFontsLoaded();
  ensureTokensInstalled();
}

// ------------------------------------------------------------------ shared css

/** Reset block used at the top of every component's static styles. */
export const baseStyles = css`
  :host {
    display: block;
    box-sizing: border-box;
    color: var(--primary-text-color, #1a1a1a);
    font-family: var(--ss-font-sans);
  }
  *,
  *::before,
  *::after {
    box-sizing: border-box;
  }
`;

/** Typography mixin helpers — apply one of these to a class to get the full
 *  font shorthand. Keeps components from repeating the size/weight/line
 *  trio in every stylesheet. */
export const typography = css`
  .ss-text-display {
    font-family: var(--ss-font-sans);
    font-size: var(--ss-text-display-size);
    font-weight: var(--ss-text-display-weight);
    line-height: var(--ss-text-display-line);
  }
  .ss-text-title {
    font-family: var(--ss-font-sans);
    font-size: var(--ss-text-title-size);
    font-weight: var(--ss-text-title-weight);
    line-height: var(--ss-text-title-line);
  }
  .ss-text-body {
    font-family: var(--ss-font-sans);
    font-size: var(--ss-text-body-size);
    font-weight: var(--ss-text-body-weight);
    line-height: var(--ss-text-body-line);
  }
  .ss-text-button {
    font-family: var(--ss-font-sans);
    font-size: var(--ss-text-button-size);
    font-weight: var(--ss-text-button-weight);
    line-height: var(--ss-text-button-line);
  }
  .ss-text-caption {
    font-family: var(--ss-font-sans);
    font-size: var(--ss-text-caption-size);
    font-weight: var(--ss-text-caption-weight);
    line-height: var(--ss-text-caption-line);
    color: var(--secondary-text-color, #5a5a5a);
  }
  .ss-mono-display {
    font-family: var(--ss-font-mono);
    font-size: var(--ss-text-mono-display-size);
    font-weight: var(--ss-text-mono-display-weight);
    line-height: var(--ss-text-mono-display-line);
    font-variant-numeric: tabular-nums;
  }
  .ss-mono-amount {
    font-family: var(--ss-font-mono);
    font-size: var(--ss-text-mono-amount-size);
    font-weight: var(--ss-text-mono-amount-weight);
    line-height: var(--ss-text-mono-amount-line);
    font-variant-numeric: tabular-nums;
  }
  .ss-mono-caption {
    font-family: var(--ss-font-mono);
    font-size: var(--ss-text-mono-caption-size);
    font-weight: var(--ss-text-mono-caption-weight);
    line-height: var(--ss-text-mono-caption-line);
    font-variant-numeric: tabular-nums;
  }
`;

/** Focus ring matching HA's default focus treatment — inset for controls
 *  that live inside a card, outset for standalone buttons. Uses the
 *  user's accent colour so it looks native in any theme. */
export const focusRing = css`
  .ss-focus-ring:focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4);
    outline-offset: 2px;
  }
`;
