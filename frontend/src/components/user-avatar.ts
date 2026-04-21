// <ss-user-avatar name="Chris" user-id="abc" size="32" ?former=${false}>
//
// Circular initials avatar with deterministic colour-from-user-id tint.
// When `former=true`, renders at 60% opacity to flag participants who
// were removed via Reconfigure but still appear in historical rows
// (decision 8 from M2_PLAN.md §8).

import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { baseStyles } from '../styles';

// Five tints picked for AA contrast with white initials on both light
// and dark themes. Order is stable — hashing a user_id to an index
// keeps the same avatar colour across sessions.
const TINTS = ['#5b9f65', '#4a7fbd', '#b86b4a', '#8e5ca0', '#c08a3e'];

function tintFor(userId: string): string {
  let hash = 0;
  for (let i = 0; i < userId.length; i++) {
    hash = (hash * 31 + userId.charCodeAt(i)) | 0;
  }
  return TINTS[Math.abs(hash) % TINTS.length]!;
}

function initialsFor(name: string): string {
  const cleaned = name.trim();
  if (!cleaned) return '?';
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0]!.charAt(0).toUpperCase();
  return (parts[0]!.charAt(0) + parts[parts.length - 1]!.charAt(0)).toUpperCase();
}

@customElement('ss-user-avatar')
export class SsUserAvatar extends LitElement {
  @property({ type: String })
  name = '';

  @property({ type: String, attribute: 'user-id' })
  userId = '';

  @property({ type: Number })
  size = 32;

  /** Render at 60% opacity for "former participant" historical rows. */
  @property({ type: Boolean, reflect: true })
  former = false;

  render() {
    const colour = tintFor(this.userId || this.name);
    const initials = initialsFor(this.name);
    const label = this.former ? `${this.name} (former participant)` : this.name;
    return html`
      <span
        class="avatar"
        style=${`--_size: ${this.size}px; --_bg: ${colour};`}
        title=${label}
        aria-label=${label}
        role="img"
      >
        ${initials}
      </span>
    `;
  }

  static styles = [
    baseStyles,
    css`
      :host {
        display: inline-block;
      }
      :host([former]) .avatar {
        opacity: 0.6;
      }
      .avatar {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: var(--_size);
        height: var(--_size);
        border-radius: 50%;
        background-color: var(--_bg);
        color: #ffffff;
        font-family: var(--ss-font-sans);
        font-weight: 600;
        font-size: calc(var(--_size) * 0.4);
        line-height: 1;
        letter-spacing: 0.5px;
        user-select: none;
      }
    `,
  ];
}

export { initialsFor, tintFor };

declare global {
  interface HTMLElementTagNameMap {
    'ss-user-avatar': SsUserAvatar;
  }
}
