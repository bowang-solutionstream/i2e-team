import { normalizeLabels } from "./labels.js";

const form = document.querySelector<HTMLFormElement>("form")!;
const input = document.querySelector<HTMLTextAreaElement>("#labels")!;
const results = document.querySelector<HTMLOListElement>("#results")!;

form.addEventListener("submit", event => {
  event.preventDefault();
  const labels = normalizeLabels(input.value.split("\n"));
  const items = labels.map(label => {
    const item = document.createElement("li");
    item.textContent = label;
    return item;
  });
  results.replaceChildren(...items);
});
