export function shouldRenderCorrectionAfterRefresh(editorState) {
  return !Boolean(editorState?.unsavedLine);
}
