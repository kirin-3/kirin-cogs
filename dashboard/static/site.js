// Extras for the staff site. Every page also works without this file: the server still checks every change.
// Only text is ever written into the page (textContent), never HTML, and new editor rows are copies of
// server-rendered <template>s.
"use strict";

const MAX_ROWS = 50; // automod_forms.MAX_ROWS: the server ignores rows past this

// Times arrive in UTC; show them in the viewer's time zone, UTC on hover.
for (const time of document.querySelectorAll("time[datetime]")) {
  time.title = time.textContent;
  time.textContent = new Date(time.dateTime).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// Ask before deletes and dry-run switches.
for (const form of document.querySelectorAll("form[data-confirm]")) {
  form.addEventListener("submit", (event) => {
    if (!confirm(form.dataset.confirm)) event.preventDefault();
  });
}

// Filter boxes hide the rows (or list items) of the element right after them that don't contain the text.
function enhance(root) {
  for (const input of root.querySelectorAll("input.filter")) {
    const box = input.nextElementSibling;
    const items = [...(box.querySelector("tbody") ?? box).children];
    input.hidden = false;
    input.addEventListener("input", () => {
      const query = input.value.trim().toLowerCase();
      for (const item of items) item.hidden = query !== "" && !item.textContent.toLowerCase().includes(query);
    });
    // Enter would submit the surrounding editor.
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
  }
  for (const picker of root.querySelectorAll("details.picker")) {
    const chosen = picker.querySelector(".chosen");
    picker.addEventListener("change", () => {
      const names = [...picker.querySelectorAll("input:checked")].map((box) => box.parentElement.textContent.trim());
      chosen.textContent = names.join(", ") || "none";
    });
  }
}
enhance(document);

// Editors: add and remove rows in place, and warn before leaving with unsaved changes.
const dirty = new Set();

function renumber(fieldset) {
  // The server reads rows as <section>-0-…, <section>-1-…, and stops at the first gap.
  const section = fieldset.dataset.section;
  const prefix = new RegExp(`^${section}-\\d+-`);
  fieldset.querySelectorAll(":scope > .row").forEach((row, n) => {
    for (const field of row.querySelectorAll("[name]")) field.name = field.name.replace(prefix, `${section}-${n}-`);
    row.querySelector('button[value^="remove-"]').value = `remove-${section}-${n}`;
  });
}

for (const form of document.querySelectorAll("form.editor")) {
  form.addEventListener("input", (event) => {
    if (event.target.name) dirty.add(form);
  });
  form.addEventListener("submit", () => dirty.delete(form));
  form.addEventListener("click", (event) => {
    const button = event.target.closest('button[name="action"]');
    const fieldset = button?.closest("fieldset[data-section]");
    if (!fieldset) return;
    const section = fieldset.dataset.section;
    if (button.value.startsWith("remove-")) {
      button.closest(".row").remove();
    } else if (button.value === `add-${section}`) {
      const template = document.getElementById(`tpl-${section}-${fieldset.querySelector(".add select").value}`);
      if (!template || fieldset.querySelectorAll(":scope > .row").length >= MAX_ROWS) return; // let the server answer
      const row = template.content.firstElementChild.cloneNode(true);
      fieldset.querySelector(".add").before(row);
      enhance(row);
      row.querySelector("input:not([type=hidden]), select, textarea, summary")?.focus();
    } else {
      return;
    }
    event.preventDefault();
    renumber(fieldset);
    dirty.add(form);
  });
}

// Custom role page: preview the name and color while they're being edited. Colors go in through the style
// properties, which the CSP allows, not style attributes.
const preview = document.querySelector(".role-preview");
if (preview) {
  const colorForm = document.querySelector('form[action="/role/color"]');
  const color = colorForm.elements;
  const name = document.querySelector('form[action="/role/name"] input[name="name"]');
  const holographicButton = colorForm.querySelector('[formaction="/role/holographic"]');
  const parse = (list) => list.split(" ").map((hex) => `#${hex}`);
  // Start from the role's saved colors: a holographic role has three, more than the form can show.
  let colors = parse(preview.dataset.colors);
  const paint = (shown = colors) => {
    // Holographic loops back to its first color so the shimmer below can scroll without a seam.
    const stops = shown.length === 3 ? [...shown, shown[0]] : shown;
    const gradient = shown.length > 1 ? `linear-gradient(90deg, ${stops.join(", ")})` : "";
    const solid = shown[0] === "#000000" ? "" : shown[0]; // Discord treats black as "no color"
    for (const who of preview.querySelectorAll(".who")) {
      who.classList.toggle("gradient", gradient !== "");
      who.classList.toggle("holographic", shown.length === 3); // only the holographic preset has three
      who.style.backgroundImage = gradient;
      who.style.color = gradient ? "" : solid;
    }
    for (const dot of preview.querySelectorAll(".dot")) dot.style.background = gradient || solid;
    for (const label of preview.querySelectorAll(".role-label")) label.textContent = name.value.trim() || "\u00a0";
  };
  colorForm.addEventListener("input", () => {
    colors = color.gradient.checked ? [color.primary.value, color.secondary.value] : [color.primary.value];
    paint();
  });
  name.addEventListener("input", () => paint());
  // Hovering or focusing the button shows what it would do; it saves straight away when clicked.
  const holographic = parse(holographicButton.dataset.colors);
  for (const show of ["pointerenter", "focus"]) holographicButton.addEventListener(show, () => paint(holographic));
  for (const hide of ["pointerleave", "blur"]) holographicButton.addEventListener(hide, () => paint());
  paint();
  preview.hidden = false;
}

addEventListener("beforeunload", (event) => {
  if (dirty.size) {
    event.preventDefault();
    event.returnValue = "";
  }
});
