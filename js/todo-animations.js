const MOVE_DURATION = 280;
const ENTER_DURATION = 240;
const EXIT_DURATION = 200;
const PULSE_DURATION = 260;
const STAGGER_DELAY = 28;
const EASING = "cubic-bezier(0.22, 1, 0.36, 1)";

function supportsAnimations() {
  return typeof Element !== "undefined" && typeof Element.prototype.animate === "function";
}

function prefersReducedMotion() {
  return typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function getTodoItems(root) {
  if (!root) return [];
  return Array.from(root.querySelectorAll(".todo-item[data-id]"));
}

function captureState(root) {
  const items = new Map();
  getTodoItems(root).forEach((node) => {
    const id = node.dataset.id;
    if (!id) return;
    items.set(id, {
      node,
      rect: node.getBoundingClientRect(),
    });
  });
  return items;
}

function stopNodeAnimations(node) {
  if (!node || typeof node.getAnimations !== "function") return;
  node.getAnimations().forEach((animation) => {
    animation.cancel();
  });
}

function animateMove(node, previousRect) {
  const nextRect = node.getBoundingClientRect();
  const deltaX = previousRect.left - nextRect.left;
  const deltaY = previousRect.top - nextRect.top;
  if (Math.abs(deltaX) < 0.5 && Math.abs(deltaY) < 0.5) return;

  stopNodeAnimations(node);
  node.animate(
    [
      { transform: `translate(${deltaX}px, ${deltaY}px)` },
      { transform: "translate(0, 0)" },
    ],
    {
      duration: MOVE_DURATION,
      easing: EASING,
    },
  );
}

function animateEntry(node) {
  stopNodeAnimations(node);
  node.animate(
    [
      {
        opacity: 0,
        transform: "translateY(12px) scale(0.985)",
        filter: "blur(8px)",
      },
      {
        opacity: 1,
        transform: "translateY(0) scale(1)",
        filter: "blur(0px)",
      },
    ],
    {
      duration: ENTER_DURATION,
      easing: EASING,
    },
  );
}

function getExitKeyframes(action) {
  switch (action) {
    case "delete":
    case "clear":
      return [
        { opacity: 1, transform: "translate(0, 0) scale(1)", filter: "blur(0px)" },
        { opacity: 0, transform: "translateX(18px) scale(0.96)", filter: "blur(6px)" },
      ];
    case "done":
    case "hide-done":
    case "filter":
      return [
        { opacity: 1, transform: "translate(0, 0) scale(1)", filter: "blur(0px)" },
        { opacity: 0, transform: "translateY(-10px) scale(0.98)", filter: "blur(6px)" },
      ];
    default:
      return [
        { opacity: 1, transform: "translate(0, 0) scale(1)", filter: "blur(0px)" },
        { opacity: 0, transform: "translateY(8px) scale(0.98)", filter: "blur(6px)" },
      ];
  }
}

function animateExit(record, action) {
  const { node, rect } = record;
  if (!rect.width || !rect.height) return;

  const ghost = node.cloneNode(true);
  ghost.setAttribute("aria-hidden", "true");
  ghost.classList.add("todo-item-ghost");

  Object.assign(ghost.style, {
    position: "fixed",
    left: `${rect.left}px`,
    top: `${rect.top}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
    margin: "0",
    pointerEvents: "none",
    zIndex: "9999",
  });

  document.body.appendChild(ghost);

  ghost.animate(getExitKeyframes(action), {
    duration: EXIT_DURATION,
    easing: EASING,
    fill: "forwards",
  }).finished.finally(() => {
    ghost.remove();
  });
}

function pulseItem(node, action) {
  if (!node) return;

  const title = node.querySelector(".todo-title");
  const toggle = node.querySelector(".todo-toggle");
  const groups = Array.from(node.querySelectorAll(".todo-main, .todo-actions, .todo-edit-actions"));
  const formFields = Array.from(node.querySelectorAll(".todo-edit-form > *"));

  node.animate(
    [
      { filter: "brightness(1)" },
      { filter: action === "done" ? "brightness(1.14)" : "brightness(1.08)" },
      { filter: "brightness(1)" },
    ],
    {
      duration: PULSE_DURATION,
      easing: EASING,
    },
  );

  if (title && (action === "done" || action === "undone" || action === "save")) {
    title.animate(
      [
        { opacity: 0.8, transform: "translateX(0)" },
        { opacity: 1, transform: "translateX(3px)" },
        { opacity: 1, transform: "translateX(0)" },
      ],
      {
        duration: PULSE_DURATION,
        easing: EASING,
      },
    );
  }

  if (toggle && (action === "done" || action === "undone")) {
    toggle.animate(
      [
        { transform: "scale(1)" },
        { transform: "scale(1.16)" },
        { transform: "scale(1)" },
      ],
      {
        duration: PULSE_DURATION,
        easing: EASING,
      },
    );
  }

  if (action === "edit" && formFields.length > 0) {
    formFields.forEach((field, index) => {
      field.animate(
        [
          { opacity: 0, transform: "translateY(6px)" },
          { opacity: 1, transform: "translateY(0)" },
        ],
        {
          duration: ENTER_DURATION,
          easing: EASING,
          delay: index * STAGGER_DELAY,
        },
      );
    });
    return;
  }

  if (groups.length > 0 && (action === "save" || action === "cancel" || action === "add")) {
    groups.forEach((group, index) => {
      group.animate(
        [
          { opacity: 0, transform: "translateY(5px)" },
          { opacity: 1, transform: "translateY(0)" },
        ],
        {
          duration: ENTER_DURATION,
          easing: EASING,
          delay: index * STAGGER_DELAY,
        },
      );
    });
  }
}

export function createTodoAnimator(root) {
  function run(mutate, { action = "update", highlightId = null } = {}) {
    if (!root || !supportsAnimations() || prefersReducedMotion()) {
      mutate();
      return;
    }

    const previous = captureState(root);
    mutate();

    const currentItems = getTodoItems(root);
    const current = new Map(
      currentItems.map((node) => [node.dataset.id, node]),
    );

    current.forEach((node, id) => {
      const previousItem = previous.get(id);
      if (!previousItem) {
        animateEntry(node);
        return;
      }
      animateMove(node, previousItem.rect);
    });

    previous.forEach((record, id) => {
      if (current.has(id)) return;
      animateExit(record, action);
    });

    if (highlightId) {
      const target = current.get(highlightId);
      if (target) pulseItem(target, action);
    }
  }

  return { run };
}
