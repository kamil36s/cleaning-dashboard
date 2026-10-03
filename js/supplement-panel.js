import {
  fetchSupplementSnapshot, saveSupplementSlots, saveSupplementRegimen,
  changeSupplementProduct, claimSupplementSlot,
} from "./habits-app-api.js";
import { localDateKey } from "./habits-reminder-schedule.js";

const weekdayLabels = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"];
const slots = ["morning", "evening"];
const slotLabels = { morning: "Rano", evening: "Wieczorem" };

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function quantity(item) {
  return `${item.unitsPerIntake} ${item.unitName || ""}`.trim();
}

export function createSupplementPanel({ root, getHabits, getValue, markTaken, notificationsEnabled, toastStack }) {
  const button = element("button", "Suplementy", "habits-app-reminders-button");
  button.type = "button";
  button.id = "habits-supplements-open";
  root.querySelector(".habits-app-summary")?.appendChild(button);

  const dialog = element("dialog", null, "habits-app-dialog habits-supplements-dialog");
  dialog.id = "habits-supplements-dialog";
  const heading = element("div", null, "habits-app-dialog-head");
  heading.append(element("strong", "Suplementy"));
  const close = element("button", "×");
  close.type = "button";
  close.setAttribute("aria-label", "Zamknij");
  close.addEventListener("click", () => dialog.close());
  heading.append(close);
  const body = element("div", null, "habits-supplements-body");
  dialog.append(heading, body);
  root.appendChild(dialog);

  let snapshot = null;
  let pending = null;

  function habitFor(item) {
    return getHabits().find((habit) => String(habit.id) === String(item.habitId));
  }

  function statusFor(item) {
    const habit = habitFor(item);
    const value = habit ? getValue(habit, snapshot.date) : null;
    if (value != null) return Number(value) > 0 ? "TAKEN" : "MISSED";
    return item.status;
  }

  async function take(item, takenAt = null) {
    const habit = habitFor(item);
    if (!habit) throw new Error("Nie znaleziono pozycji Habits");
    const value = habit.type === "numeric" ? Number(item.unitsPerIntake) : 2;
    await markTaken(habit, snapshot.date, value, takenAt);
    await refresh();
  }

  function renderItems(slot) {
    const section = element("section", null, "habits-supplements-slot");
    const title = element("strong", `${slotLabels[slot]} · ${snapshot.slots[slot]}`);
    section.append(title);
    const items = snapshot.items.filter((item) => item.slot === slot && item.due);
    if (!items.length) section.append(element("p", "Brak suplementów w tym oknie."));
    for (const item of items) {
      const row = element("div", null, "habits-supplements-item");
      const copy = element("div");
      copy.append(element("strong", item.displayName), element("small", quantity(item)));
      row.append(copy);
      const status = statusFor(item);
      if (status === "TAKEN") {
        const time = habitFor(item)?.entryTakenAt?.get(snapshot.date) || item.takenAt;
        const label = time ? `Przyjęto ${new Date(time).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}` : "Przyjęto";
        const edit = element("button", `${label} · edytuj czas`);
        edit.type = "button";
        edit.addEventListener("click", async () => {
          const initial = time ? new Date(time).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" }) : "09:00";
          const answer = window.prompt("Godzina przyjęcia (HH:MM)", initial);
          if (answer == null) return;
          if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(answer)) return window.alert("Podaj godzinę HH:MM.");
          const instant = new Date(`${snapshot.date}T${answer}:00`).toISOString();
          try { await take(item, instant); } catch (error) { window.alert(error.message); }
        });
        row.append(edit);
      } else {
        row.append(element("span", status === "MISSED" ? "Pominięto" : "Brak wpisu"));
        const done = element("button", "Przyjęto");
        done.type = "button";
        done.addEventListener("click", async () => {
          done.disabled = true;
          try { await take(item); } catch (error) { window.alert(error.message); done.disabled = false; }
        });
        row.append(done);
      }
      section.append(row);
    }
    return section;
  }

  function renderSettings() {
    const details = element("details", null, "habits-supplements-settings");
    details.append(element("summary", "Produkty i harmonogram"));
    const times = element("div", null, "habits-supplements-times");
    const inputs = {};
    for (const slot of slots) {
      const label = element("label", slotLabels[slot]);
      const input = element("input");
      input.type = "time";
      input.value = snapshot.slots[slot];
      inputs[slot] = input;
      label.append(input);
      times.append(label);
    }
    const saveTimes = element("button", "Zapisz godziny");
    saveTimes.type = "button";
    saveTimes.addEventListener("click", async () => {
      try { await saveSupplementSlots({ slots: Object.fromEntries(slots.map((slot) => [slot, inputs[slot].value])) }); await refresh(); }
      catch (error) { window.alert(error.message); }
    });
    times.append(saveTimes);
    details.append(times);
    for (const catalog of snapshot.catalog) {
      const regimen = [...catalog.regimens].reverse().find((r) => r.effectiveTo == null);
      if (!regimen) continue;
      const product = catalog.products.find((p) => p.id === regimen.productId);
      const card = element("div", null, "habits-supplements-product");
      card.append(element("strong", catalog.displayName));
      card.append(element("small", product
        ? `${product.brand} · ${product.productName} · ${product.form} · od ${product.validFrom}`
        : `Domyślnie ${regimen.unitsPerIntake} g · od ${regimen.effectiveFrom}`));
      if (product) {
        card.append(element("small", product.ingredients.map((i) => `${i.name}: ${i.amount} ${i.unit}`).join(" · ")));
        const older = catalog.products.filter((p) => p.validTo);
        if (older.length) card.append(element("small", `Poprzednie: ${older.map((p) => `${p.productName} (${p.validFrom}–${p.validTo})`).join(", ")}`));
      }
      const select = element("select");
      for (const slot of slots) {
        const option = element("option", slotLabels[slot]);
        option.value = slot;
        option.selected = regimen.slot === slot;
        select.append(option);
      }
      const qty = element("input");
      qty.type = "number";
      qty.min = "0.001";
      qty.step = "any";
      qty.value = regimen.unitsPerIntake;
      qty.setAttribute("aria-label", "Liczba jednostek na przyjęcie");
      const dayControls = element("div", null, "habits-supplements-days");
      const boxes = weekdayLabels.map((label, index) => {
        const wrapper = element("label", label);
        const box = element("input");
        box.type = "checkbox";
        box.checked = Boolean(regimen.weekdaysMask & (1 << index));
        wrapper.prepend(box);
        dayControls.append(wrapper);
        return box;
      });
      const save = element("button", "Zapisz harmonogram");
      save.type = "button";
      save.addEventListener("click", async () => {
        const mask = boxes.reduce((n, box, index) => n | (box.checked ? 1 << index : 0), 0);
        try {
          await saveSupplementRegimen({ habitId: catalog.habitId, effectiveFrom: localDateKey(),
            slot: select.value, weekdaysMask: mask, unitsPerIntake: Number(qty.value) });
          await refresh();
        } catch (error) { window.alert(error.message); }
      });
      card.append(select, qty, dayControls, save);
      if (product) {
        const change = element("button", "Zmień produkt");
        change.type = "button";
        change.addEventListener("click", async () => {
          const validFrom = window.prompt("Nowy produkt od daty YYYY-MM-DD", localDateKey());
          if (validFrom == null) return;
          const brand = window.prompt("Marka", product.brand);
          if (brand == null) return;
          const productName = window.prompt("Nazwa produktu", "");
          if (productName == null) return;
          const form = window.prompt("Forma, np. tablet", product.form);
          if (form == null) return;
          const unitName = window.prompt("Jednostka, np. tablet", product.unitName);
          if (unitName == null) return;
          const ingredientText = window.prompt("Skład na jednostkę (po jednej pozycji w wierszu: nazwa; ilość; jednostka)", "");
          if (ingredientText == null) return;
          const ingredients = ingredientText.split("\n").filter((line) => line.trim()).map((line) => {
            const [name, amount, unit] = line.split(";").map((part) => part.trim());
            return { name, amount: Number(amount), unit };
          });
          try { await changeSupplementProduct({ habitId: catalog.habitId, validFrom,
            brand, productName, form, unitName, ingredients }); await refresh(); }
          catch (error) { window.alert(error.message); }
        });
        card.append(change);
      }
      details.append(card);
    }
    return details;
  }

  function render() {
    if (!snapshot) return;
    body.replaceChildren(element("p", snapshot.date), renderItems("morning"), renderItems("evening"), renderSettings());
  }

  async function refresh() {
    if (pending) return pending;
    pending = fetchSupplementSnapshot(localDateKey()).then((data) => {
      snapshot = data;
      if (dialog.open) render();
      return data;
    }).finally(() => { pending = null; });
    return pending;
  }

  async function tick(now = new Date()) {
    const data = await refresh();
    const day = localDateKey(now);
    if (data.date !== day) return;
    const minute = now.getHours() * 60 + now.getMinutes();
    for (const slot of slots) {
      const [hour, min] = data.slots[slot].split(":").map(Number);
      const late = minute - hour * 60 - min;
      if (late < 0 || late > 5) continue;
      const due = data.items.filter((item) => item.slot === slot && item.due && statusFor(item) !== "TAKEN");
      if (!due.length) continue;
      if (!notificationsEnabled() || typeof Notification === "undefined" || Notification.permission !== "granted") continue;
      const claimed = await claimSupplementSlot({ date: day, slot });
      if (!claimed.claimed) continue;
      const title = `${slotLabels[slot]} · suplementy`;
      const message = due.map((item) => `${item.displayName} ${quantity(item)}`).join(" · ");
      try { new Notification(title, { body: message, tag: `supplements:${day}:${slot}` }); } catch { /* toast below */ }
      const toast = element("article", null, "habits-reminder-toast");
      toast.append(element("strong", title), element("span", message));
      const open = element("button", "Otwórz listę");
      open.type = "button";
      open.addEventListener("click", () => { toast.remove(); button.click(); });
      toast.append(open);
      toastStack.append(toast);
    }
  }

  button.addEventListener("click", async () => {
    body.replaceChildren(element("p", "Ładowanie…"));
    dialog.showModal();
    try { await refresh(); render(); } catch (error) { body.replaceChildren(element("p", error.message)); }
  });
  return { refresh, tick };
}
