const MONTH_NAMES_PL = [
  "Styczen",
  "Luty",
  "Marzec",
  "Kwiecien",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpien",
  "Wrzesien",
  "Pazdziernik",
  "Listopad",
  "Grudzien",
];

const WEEKDAY_NAMES_PL = ["Pn", "Wt", "Sr", "Cz", "Pt", "So", "Nd"];

let activePicker = null;

function pad2(value) {
  return String(value).padStart(2, "0");
}

function toIsoDate(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function fromIsoDate(day) {
  const date = new Date(`${day}T12:00:00`);
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

function todayIso() {
  return toIsoDate(new Date());
}

function monthStartOffset(date) {
  const first = new Date(date.getFullYear(), date.getMonth(), 1, 12);
  return (first.getDay() + 6) % 7;
}

function daysInMonth(date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
}

function sameMonth(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth();
}

function placePopover(popover, anchor) {
  const rect = anchor.getBoundingClientRect();
  const gap = 8;
  const width = popover.offsetWidth || 286;
  const height = popover.offsetHeight || 310;
  const spaceRight = window.innerWidth - rect.right;
  const openRight = spaceRight >= width + gap || rect.left < width + gap;
  const left = openRight
    ? Math.min(rect.right + gap, window.innerWidth - width - gap)
    : Math.max(gap, rect.left - width - gap);
  const top = Math.min(
    Math.max(gap, rect.top + rect.height / 2 - height / 2),
    window.innerHeight - height - gap,
  );

  popover.style.left = `${Math.round(left)}px`;
  popover.style.top = `${Math.round(top)}px`;
}

function closeActivePicker() {
  if (!activePicker) return;
  activePicker.cleanup();
  activePicker = null;
}

function renderPicker(state) {
  const { popover, selectedDay, viewDate } = state;
  const today = todayIso();
  const offset = monthStartOffset(viewDate);
  const count = daysInMonth(viewDate);
  const cells = [];

  for (let index = 0; index < offset; index += 1) {
    cells.push(`<span class="dashboard-date-popover-spacer" aria-hidden="true"></span>`);
  }

  for (let day = 1; day <= count; day += 1) {
    const iso = toIsoDate(new Date(viewDate.getFullYear(), viewDate.getMonth(), day, 12));
    cells.push(`
      <button
        class="dashboard-date-popover-day${iso === selectedDay ? " is-selected" : ""}${iso === today ? " is-today" : ""}"
        type="button"
        data-day="${iso}"
      >${day}</button>
    `);
  }

  popover.innerHTML = `
    <div class="dashboard-date-popover-head">
      <button class="dashboard-date-popover-nav" type="button" data-month="-1" aria-label="Poprzedni miesiac">&lsaquo;</button>
      <strong>${MONTH_NAMES_PL[viewDate.getMonth()]} ${viewDate.getFullYear()}</strong>
      <button class="dashboard-date-popover-nav" type="button" data-month="1" aria-label="Nastepny miesiac">&rsaquo;</button>
    </div>
    <div class="dashboard-date-popover-weekdays">
      ${WEEKDAY_NAMES_PL.map((day) => `<span>${day}</span>`).join("")}
    </div>
    <div class="dashboard-date-popover-grid">
      ${cells.join("")}
    </div>
    <div class="dashboard-date-popover-foot">
      <button type="button" data-today="true">Dzisiaj</button>
    </div>
  `;
}

export function openDatePopover(options) {
  const {
    anchor,
    selectedDay,
    parseInput,
    textInput,
    onSelect,
  } = options || {};

  if (!(anchor instanceof HTMLElement) || typeof onSelect !== "function") return;
  closeActivePicker();

  const resolvedDay = parseInput?.(textInput?.value) || selectedDay || todayIso();
  const viewDate = fromIsoDate(resolvedDay);
  const popover = document.createElement("div");
  popover.className = "dashboard-date-popover";
  popover.setAttribute("role", "dialog");
  popover.setAttribute("aria-label", "Kalendarz");

  const state = {
    popover,
    selectedDay: resolvedDay,
    viewDate: new Date(viewDate.getFullYear(), viewDate.getMonth(), 1, 12),
    cleanup: () => {},
  };

  const update = () => {
    renderPicker(state);
    requestAnimationFrame(() => placePopover(popover, anchor));
  };

  const handleClick = (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const month = target.closest("[data-month]")?.getAttribute("data-month");
    const day = target.closest("[data-day]")?.getAttribute("data-day");
    const today = target.closest("[data-today]");

    if (month) {
      state.viewDate.setMonth(state.viewDate.getMonth() + Number(month));
      update();
      return;
    }

    if (day || today) {
      const nextDay = day || todayIso();
      onSelect(nextDay);
      closeActivePicker();
    }
  };

  const handlePointerDown = (event) => {
    const target = event.target;
    if (target instanceof Node && (popover.contains(target) || anchor.contains(target))) return;
    closeActivePicker();
  };

  const handleKeyDown = (event) => {
    if (event.key === "Escape") closeActivePicker();
  };

  const handleReposition = () => placePopover(popover, anchor);

  state.cleanup = () => {
    popover.removeEventListener("click", handleClick);
    document.removeEventListener("pointerdown", handlePointerDown, true);
    document.removeEventListener("keydown", handleKeyDown);
    window.removeEventListener("resize", handleReposition);
    window.removeEventListener("scroll", handleReposition, true);
    popover.remove();
  };

  popover.addEventListener("click", handleClick);
  document.addEventListener("pointerdown", handlePointerDown, true);
  document.addEventListener("keydown", handleKeyDown);
  window.addEventListener("resize", handleReposition);
  window.addEventListener("scroll", handleReposition, true);
  document.body.appendChild(popover);
  activePicker = state;
  update();

  if (!sameMonth(fromIsoDate(state.selectedDay), state.viewDate)) {
    state.viewDate = fromIsoDate(state.selectedDay);
    update();
  }
}
