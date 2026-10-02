// Escapes a string for safe use in BOTH HTML text content and inside a
// double- or single-quoted HTML attribute. A textContent->innerHTML
// round-trip alone escapes <, > and & but not quote characters, which is
// unsafe wherever the result is interpolated into an attribute (e.g.
// aria-label="...${escapeHtml(title)}...") rather than only between tags.
export function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML.replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
