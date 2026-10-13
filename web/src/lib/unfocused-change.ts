/**
 * Whether a change reached `box` while it didn't have focus, so no blur will follow to commit it.
 *
 * Firefox's number spin buttons do this: clicking one changes the value without focusing the box
 * (issue #160). A field that saves on blur must save such a change at once; typing always has focus,
 * so it keeps waiting for blur or Enter and a half-typed number still never escapes.
 */
export function changedWithoutFocus(box: HTMLElement): boolean {
  return box.ownerDocument.activeElement !== box;
}
