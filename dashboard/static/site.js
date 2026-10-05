// Extras for the staff and member sites. Every page also works without this file: the server still checks every change.
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

// A second click while a form is sending (an emoji upload, a purchase) would send it twice. This runs after the
// confirm prompts above, so a cancelled form stays usable; pages restored from the back/forward cache are reset.
document.addEventListener("submit", (event) => {
  if (event.defaultPrevented) return;
  if (event.target.classList.contains("busy")) event.preventDefault();
  else event.target.classList.add("busy");
});
addEventListener("pageshow", (event) => {
  if (event.persisted) for (const form of document.querySelectorAll("form.busy")) form.classList.remove("busy");
});

// On narrow screens the nav scrolls sideways; start with the current page in view.
document.querySelector(".nav a.on")?.scrollIntoView({ block: "nearest", inline: "center" });

// The account menu closes on a click outside it, or on Escape.
const account = document.querySelector("details.account");
if (account) {
  document.addEventListener("click", (event) => {
    if (!account.contains(event.target)) account.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !account.open) return;
    account.open = false;
    account.querySelector("summary").focus();
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

// Rank-card backgrounds. Leaderboard rows show a still and animate while hovered or focused (never with reduced
// motion). An image that fails to load, which inline onerror can't catch under the CSP, becomes its name on a panel.
const calm = matchMedia("(prefers-reduced-motion: reduce)");
for (const row of document.querySelectorAll(".lb-row")) {
  const image = row.querySelector("img.bg");
  const still = image.src;
  const animate = () => {
    if (!calm.matches && image.dataset.animated) image.src = image.dataset.animated;
  };
  const rest = () => {
    if (image.src !== still) image.src = still;
  };
  row.addEventListener("pointerenter", animate);
  row.addEventListener("focusin", animate);
  row.addEventListener("pointerleave", rest);
  row.addEventListener("focusout", rest);
}
const broken = (image) => {
  const placeholder = document.createElement("span");
  placeholder.className = "bg placeholder";
  placeholder.textContent = image.dataset.name || "";
  image.replaceWith(placeholder);
};
for (const image of document.querySelectorAll("img.bg")) {
  if (image.complete && image.naturalWidth === 0 && image.getAttribute("src")) broken(image);
  else image.addEventListener("error", () => broken(image));
}

// Gif votes save in place, so the gifs keep playing. The form works without this: any failure submits it the ordinary
// way. The site's CSP lets this script call the site itself and no one else.
for (const form of document.querySelectorAll("form.vote")) {
  form.addEventListener("submit", async (event) => {
    const button = event.submitter;
    if (form.dataset.plain || !button) return;
    event.preventDefault();
    if (form.classList.contains("busy")) return;
    form.classList.add("busy");
    let saved = false;
    try {
      // getAttribute: the form has a field named "action", which hides form.action
      const response = await fetch(form.getAttribute("action"), {
        method: "POST",
        body: new URLSearchParams(new FormData(form, button)),
        headers: { "X-Requested-With": "fetch" },
      });
      saved = response.status === 204;
    } catch {
      // the ordinary submit below shows what went wrong
    }
    form.classList.remove("busy");
    if (!saved) {
      form.dataset.plain = "1";
      form.requestSubmit(button);
      delete form.dataset.plain;
      return;
    }
    // Show the new vote: the pressed thumb takes it back when pressed again, the other one votes for itself.
    const chosen = button.value === "none" ? "" : button.value;
    const thumbs = form.querySelectorAll("button[name=value]"); // thumbs up, then thumbs down
    ["up", "down"].forEach((kind, n) => {
      thumbs[n].setAttribute("aria-pressed", String(chosen === kind));
      thumbs[n].value = chosen === kind ? "none" : kind;
    });
  });
}

addEventListener("beforeunload", (event) => {
  if (dirty.size) {
    event.preventDefault();
    event.returnValue = "";
  }
});

// Long answers show how much room is left, so the length limit never cuts anyone off by surprise.
for (const field of document.querySelectorAll("textarea[data-count]")) {
  const counter = document.createElement("small");
  counter.className = "count";
  const update = () => {
    const used = field.value.length;
    counter.textContent = `${used.toLocaleString()} / ${field.maxLength.toLocaleString()}`;
    counter.classList.toggle("near", used >= field.maxLength * 0.9);
  };
  field.addEventListener("input", update);
  field.after(counter);
  update();
}
