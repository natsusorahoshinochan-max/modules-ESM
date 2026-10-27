export const styles = `
.ps-studio {
  display: flex;
  flex-direction: column;
  position: relative;
  height: 100%;
  min-height: 520px;
  overflow: hidden;
  font: 14px/1.45 system-ui, sans-serif;
  --ps-bg:#fff;
  --ps-panel:#f8f9fb;
  --ps-line:#d9dee7;
  --ps-muted:#626b79;
  --ps-text:#20242c;
  --ps-accent:#345bdb;
  background: #fff;
  color: #20242c;
}
.ps-studio * {
  box-sizing: border-box;
}
.ps-studio button {
  font: inherit;
  color: inherit;
}
.ps-studio input {
  font: inherit;
  color: inherit;
}
.ps-studio select {
  font: inherit;
  color: inherit;
}
.ps-studio button {
  border: 1px solid var(--ps-line);
  border-radius: 5px;
  padding: 7px 11px;
  cursor: pointer;
  transition: background-color .12s, border-color .12s;
  background: #fff;
  border-color: #d9dee7;
  color: #20242c;
}
.ps-studio select {
  border: 1px solid var(--ps-line);
  border-radius: 5px;
  padding: 7px 11px;
  cursor: pointer;
  transition: background-color .12s, border-color .12s;
  background: #fff;
  border-color: #d9dee7;
  color: #20242c;
}
.ps-studio button:hover {
  background: #eef1f6;
}
.ps-studio button:disabled {
  opacity: .4;
  cursor: default;
}
.ps-studio button:focus-visible {
  outline: 2px solid var(--ps-accent);
  outline-offset: 1px;
}
.ps-studio input:focus-visible {
  outline: 2px solid var(--ps-accent);
  outline-offset: 1px;
}
.ps-studio select:focus-visible {
  outline: 2px solid var(--ps-accent);
  outline-offset: 1px;
}
.ps-studio input {
  border: 1px solid #d9dee7;
  border-radius: 3px;
  padding: 5px;
  min-width: 0;
  background: #fff;
  border-color: #9ba8bd;
  color: #20242c;
}
.ps-studio .ps-primary {
  font-weight: 650;
  background: #345bdb;
  color: #fff;
  border-color: #345bdb;
}
.ps-spacer {
  flex: 1;
}
.ps-header {
  min-height: 60px;
  flex-wrap: wrap;
  height: auto;
  flex: none;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid var(--ps-line);
  background: #fff;
  border-color: #d9dee7;
  color: #20242c;
}
.ps-brand {
  font-weight: 650;
  font-size: 21px;
  white-space: nowrap;
}
.ps-object {
  font-size: 13px;
  color: var(--ps-muted);
}
.ps-header-actions {
  display: flex;
  gap: 7px;
}
.ps-header .ps-icon {
  font-size: 21px;
  line-height: 24px;
  padding: 4px 10px;
}
.ps-alert {
  position: absolute;
  z-index: 20;
  top: 64px;
  left: 90px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid #e7b9ae;
  border-radius: 5px;
  background: #fff0ed;
  color: #9d4633;
  border-color: #e7b9ae;
}
.ps-alert button {
  margin-left: auto;
  padding: 1px 6px;
}
.ps-viewport {
  flex: 1;
  min-height: 190px;
  position: relative;
  background: #fafbfc;
}
.ps-molecule {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.ps-view-surface {
  position: absolute;
  inset: 0;
  touch-action: none;
  outline: 0;
}
.ps-view-surface:focus-visible {
  box-shadow: inset 0 0 0 2px #345bdb66;
}
.ps-view-overlay {
  width: 100%;
  height: 100%;
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}
.ps-view-tools {
  position: absolute;
  left: 16px;
  top: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--ps-line);
  border-radius: 6px;
  padding: 4px;
  background: #ffffffed;
  border-color: #d9dee7;
  box-shadow: 0 2px 8px #20242c08;
}
.ps-view-tools button {
  padding: 5px 4px;
  width: 49px;
  font-size: 12px;
  background: none;
  border-color: transparent;
}
.ps-view-tools button span {
  display: block;
  font-size: 22px;
  line-height: 1.2;
}
.ps-view-tools button[aria-pressed=true] {
  background: #edf2ff;
  color: #345bdb;
  border-color: #c5d1f8;
}
.ps-camera-tools {
  position: absolute;
  top: 16px;
  right: 16px;
  display: flex;
  gap: 7px;
}
.ps-camera-tools button {
  font-size: 12px;
  background: #fff;
}
.ps-camera-tools select {
  font-size: 12px;
  background: #fff;
}
.ps-camera-tools [aria-pressed=true] {
  border-color: var(--ps-accent);
  background: #edf2ff;
  color: #345bdb;
}
.ps-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--ps-muted);
  pointer-events: none;
}
.ps-view-error {
  position: absolute;
  bottom: 10px;
  left: 90px;
  right: 16px;
  color: #a64e35;
}
.ps-transform-status {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  border: 1px solid #d9dee7;
  border-radius: 4px;
  padding: 7px 14px;
  pointer-events: none;
  background: #fff;
  border-color: #c5d1f8;
  color: #345bdb;
}
.ps-box {
  position: absolute;
  border: 1px solid #345bdb;
  pointer-events: none;
  border-color: #345bdb;
  background: #345bdb15;
}
.ps-divider {
  height: 9px;
  flex: none;
  cursor: ns-resize;
  border-block: 1px solid var(--ps-line);
  display: grid;
  place-items: center;
  touch-action: none;
  background: #f3f4f6;
  border-color: #d9dee7;
}
.ps-divider:after {
  content: "";
  width: 28px;
  height: 2px;
  background: #9ca6b4;
}
.ps-tracks {
  height: 333px;
  flex: none;
  min-height: 250px;
  max-height: 65%;
  display: flex;
  flex-direction: column;
  background: #fff;
}
.ps-track-top {
  height: 43px;
  flex: none;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--ps-line);
  background: #fff;
}
.ps-track-top strong {
  font-size: 13px;
  font-weight: 550;
}
.ps-track-top button {
  font-size: 12px;
  padding: 4px 9px;
}
.ps-legend {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--ps-muted);
}
.ps-legend span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.ps-legend i {
  width: 7px;
  height: 7px;
  border-radius: 2px;
}
.ps-track-scroll {
  overflow: auto;
  flex: 1;
  outline: 0;
  scrollbar-width: thin;
  scrollbar-color: #b6bfcd #f3f4f6;
}
.ps-track-scroll:focus-visible {
  box-shadow: inset 0 0 0 1px #345bdb;
}
.ps-grid {
  display: grid;
  grid-template-columns: 140px repeat(var(--ps-count), 48px);
  width: max-content;
  min-width: 100%;
}
.ps-ruler {
  height: 27px;
  text-align: center;
  font: 11px/27px ui-monospace, monospace;
  border-right: 1px solid #d9dee7;
  border-bottom: 1px solid var(--ps-line);
  background: #f8f9fb;
  border-color: #e2e6ec;
  color: #626b79;
}
.ps-ruler-label {
  position: sticky;
  left: 0;
  z-index: 3;
  padding-left: 14px;
  text-align: left;
}
.ps-track-label {
  position: sticky;
  left: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  border-right: 1px solid var(--ps-line);
  border-bottom: 1px solid #d9dee7;
  padding: 0 14px;
  background: #f8f9fb;
  border-color: #e2e6ec;
}
.ps-track-label button {
  white-space: normal;
  text-align: left;
  line-height: 1.2;
  padding: 0;
  font-weight: 550;
  background: none;
  border: 0;
}
.ps-track-label small {
  font-size: 11px;
  color: var(--ps-muted);
}
.ps-track-label.ps-active {
  background: #edf2ff;
  box-shadow: inset 3px 0 #345bdb;
}
.ps-cell {
  height: 45px;
  min-width: 48px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  border-right: 1px solid #d9dee7;
  border-bottom: 1px solid #d9dee7;
  user-select: none;
  touch-action: none;
  cursor: text;
  padding: 0 4px;
  transition: background-color .12s;
  outline: 0;
  border-color: #e5e8ee;
}
.ps-cell:hover {
  box-shadow: inset 0 0 0 1px #9ba8bd;
}
.ps-sequence {
  font: 21px ui-monospace, monospace;
}
.ps-replaced {
  background: #fff0ce;
}
.ps-cleared {
  background: #eceef1;
}
.ps-inserted {
  background: #e2f3e8;
}
.ps-deleted {
  background: #fce6e8;
  color: #a34a55;
}
.ps-cell.ps-deleted {
  text-decoration: line-through;
  text-decoration-thickness: 2px;
}
.ps-deleted:not(.ps-ruler)::after {
  content: "";
  position: absolute;
  left: 7px;
  right: 7px;
  top: 50%;
  border-top: 1px solid #bd5965;
  pointer-events: none;
}
.ps-ruler.ps-deleted {
  text-decoration: line-through;
  color: #a34a55;
}
.ps-ruler.ps-inserted {
  color: #247345;
}
.ps-cell.ps-selected {
  box-shadow: inset 0 2px #a2aab7, inset 0 -2px #a2aab7;
}
.ps-cell.ps-selected.ps-active-cell {
  box-shadow: inset 0 2px #345bdb, inset 0 -2px #345bdb;
}
.ps-cell.ps-cursor {
  outline: 2px solid #345bdb;
  outline-offset: -2px;
  z-index: 1;
  outline-color: #345bdb;
}
.ps-cell input {
  position: absolute;
  inset: 3px;
  width: calc(100% - 6px);
  padding: 2px;
  font-size: 13px;
  z-index: 3;
  text-align: center;
}
.ps-cell .ps-annotation-input {
  width: 220px;
  text-align: left;
  box-shadow: 0 3px 12px #20242c18;
}
.ps-coordinate {
  width: 11px;
  height: 11px;
  display: block;
  border-radius: 50%;
  border: 1px solid #657b94;
  background: #7e91a8;
  border-color: #657b94;
}
.ps-coordinate-empty {
  background: transparent;
  border-color: #9da9b9;
}
.ps-missing {
  color: #7c8797;
}
.ps-ss {
  height: 15px;
  width: 100%;
  font: 11px/15px ui-monospace, monospace;
  text-align: center;
  background: #cbd9ec;
  color: #344d70;
}
.ps-ss-E {
  clip-path: polygon(0 0, 76% 0, 100% 50%, 76% 100%, 0 100%);
}
.ps-ss-B {
  clip-path: polygon(0 0, 76% 0, 100% 50%, 76% 100%, 0 100%);
}
.ps-ss-H {
  border-radius: 8px;
}
.ps-ss-G {
  border-radius: 8px;
}
.ps-ss-I {
  border-radius: 8px;
}
.ps-sasa {
  height: 100%;
  position: relative;
  display: grid;
  place-items: center;
  width: 100%;
  font: 11px ui-monospace, monospace;
}
.ps-sasa i {
  position: absolute;
  bottom: 5px;
  width: 26px;
  border-top: 1px solid #7e91a8;
  background: #c6d9dc;
  border-color: #789fa4;
}
.ps-sasa span {
  position: relative;
}
.ps-annotation {
  display: block;
  width: 100%;
  font-size: 10px;
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
  padding: 3px 0;
  background: #e3def1;
  color: #67518b;
}
.ps-footer {
  height: 30px;
  flex: none;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 0 16px;
  border-top: 1px solid var(--ps-line);
  font-size: 11px;
  color: var(--ps-muted);
  background: #f8f9fb;
}
.ps-footer span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ps-modal-layer {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: grid;
  place-items: center;
  background: #20242c44;
}
.ps-modal {
  width: min(540px, 92%);
  max-height: 90%;
  overflow: auto;
  padding: 23px;
  border: 1px solid #d9dee7;
  border-radius: 7px;
  background: #fff;
  border-color: #d9dee7;
  box-shadow: 0 15px 50px #20242c22;
}
.ps-modal h2 {
  margin: 0 0 16px;
  font-size: 20px;
  font-weight: 600;
}
.ps-modal p {
  color: var(--ps-muted);
}
.ps-modal label {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
}
.ps-modal label input {
  flex: 1;
  min-width: 0;
}
.ps-modal label select {
  flex: 1;
  min-width: 0;
}
.ps-modal nav {
  display: flex;
  gap: 9px;
  margin-top: 18px;
}
.ps-source-positions {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 4px;
  max-height: 230px;
  overflow: auto;
  margin-top: 10px;
}
.ps-source-positions button {
  font-size: 11px;
  padding: 5px 2px;
}
.ps-source-positions button[aria-pressed=true] {
  background: #edf2ff;
  border-color: #345bdb;
  color: #345bdb;
}
.ps-menu {
  position: fixed;
  z-index: 15;
  display: flex;
  flex-direction: column;
  min-width: 170px;
  padding: 5px;
  border: 1px solid #d9dee7;
  border-radius: 5px;
  background: #fff;
  border-color: #d9dee7;
  box-shadow: 0 8px 24px #20242c18;
}
.ps-menu button {
  text-align: left;
  font-size: 13px;
  background: transparent;
  border: 0;
}
.ps-menu kbd {
  float: right;
  margin-left: 16px;
  color: var(--ps-muted);
}
@media (max-width: 900px) {
  .ps-header {
    padding: 0 12px;
    gap: 8px;
  }
  .ps-brand {
    font-size: 18px;
  }
  .ps-object {
    display: none;
  }
  .ps-header-actions {
    gap: 5px;
  }
  .ps-header-actions button {
    padding: 6px 8px;
  }
  .ps-legend {
    gap: 8px;
  }
  .ps-grid {
    grid-template-columns: 120px repeat(var(--ps-count), 43px);
  }
  .ps-cell {
    min-width: 43px;
  }
  .ps-camera-tools {
    gap: 4px;
    right: 10px;
  }
  .ps-camera-tools button {
    padding: 5px 7px;
  }
  .ps-camera-tools select {
    padding: 5px 7px;
  }
  .ps-view-tools {
    left: 10px;
  }
  .ps-footer span:last-child {
    max-width: 48%;
  }
}
@media (prefers-reduced-motion: reduce) {
  .ps-studio * {
    transition: none !important;
    animation: none !important;
  }
}
.ps-studio .ps-primary:hover {
  background: #294bc3;
}
.ps-track-label.ps-active button {
  color: #345bdb;
}
.ps-deleted:not(.ps-ruler):after {
  border-color: #bd5965;
}
`;
