/* Канбан: мышь + палец, автосохранение без перезагрузки. */
(function () {
  const board = document.getElementById("crm-board");
  const saveState = document.getElementById("save-state");
  const searchInput = document.getElementById("kanban-search");
  if (!board) return;

  const readOnly = board.dataset.readonly === "1";
  const placeholder = document.createElement("div");
  placeholder.className = "deal-placeholder";

  let dragCard = null;
  let originParent = null;
  let originNext = null;
  let saveQueue = Promise.resolve();
  let ghost = null;
  let pointerId = null;
  let touchActive = false;
  let startX = 0;
  let startY = 0;
  let moved = false;

  function money(value) {
    const formatted = new Intl.NumberFormat("ru-RU", {
      maximumFractionDigits: 0,
    }).format(Number(value) || 0);
    return formatted + " ₽";
  }

  function setSaveState(state, text) {
    if (!saveState) return;
    saveState.dataset.state = state;
    saveState.textContent = text;
  }

  function refreshBoard() {
    const query = ((searchInput && searchInput.value) || "").trim().toLowerCase();
    let openCount = 0;
    let openSum = 0;
    let wonSum = 0;
    let loseCount = 0;

    board.querySelectorAll(".crm-col").forEach((column) => {
      let sum = 0;
      let count = 0;
      column.querySelectorAll(".deal-card").forEach((card) => {
        const haystack = card.dataset.search || "";
        const visible = !query || haystack.includes(query);
        card.hidden = !visible;
        if (!visible) return;
        const amount = Number(card.dataset.sum || 0);
        sum += amount;
        count += 1;
        if (column.dataset.semantics === "process") {
          openCount += 1;
          openSum += amount;
        } else if (column.dataset.semantics === "success") {
          wonSum += amount;
        } else if (column.dataset.semantics === "failure") {
          loseCount += 1;
        }
      });
      column.querySelector(".stage-count").textContent = String(count);
      column.querySelector(".stage-sum").textContent = money(sum);
      const empty = column.querySelector(".col-empty");
      if (empty) empty.hidden = count !== 0;
    });

    const openNode = document.getElementById("stat-open");
    const sumNode = document.getElementById("stat-sum");
    const wonNode = document.getElementById("stat-won");
    const loseNode = document.getElementById("stat-lose");
    if (openNode) openNode.textContent = String(openCount);
    if (sumNode) sumNode.textContent = money(openSum);
    if (wonNode) wonNode.textContent = money(wonSum);
    if (loseNode) loseNode.textContent = String(loseCount);
  }

  function columnOrder(column) {
    return [...column.querySelectorAll(".deal-card")].map((card) => Number(card.dataset.id));
  }

  function rememberOrigin(card) {
    originParent = card.parentElement;
    originNext = card.nextElementSibling;
  }

  function markSaved(card) {
    card.classList.remove("is-just-saved");
    void card.offsetWidth;
    card.classList.add("is-just-saved");
  }

  function saveMove(card, sourceColumn, targetColumn) {
    const payload = {
      stage_id: Number(targetColumn.dataset.stageId),
      columns: {},
    };
    payload.columns[sourceColumn.dataset.stageId] = columnOrder(sourceColumn);
    payload.columns[targetColumn.dataset.stageId] = columnOrder(targetColumn);
    const parent = originParent;
    const next = originNext;

    saveQueue = saveQueue.then(async () => {
      setSaveState("saving", "Сохраняю…");
      const response = await fetch("/deals/" + card.dataset.id + "/move", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "fetch",
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error("save");
      setSaveState("saved", "Сохранено");
      markSaved(card);
    }).catch(() => {
      if (parent) {
        if (next && next.parentElement === parent) parent.insertBefore(card, next);
        else parent.appendChild(card);
      }
      refreshBoard();
      setSaveState("error", "Не сохранилось");
    });
  }

  function cardAfterCursor(container, clientY) {
    const cards = [...container.querySelectorAll(".deal-card:not(.is-dragging)")].filter(
      (card) => !card.hidden
    );
    let closest = null;
    let closestOffset = Number.NEGATIVE_INFINITY;
    cards.forEach((card) => {
      const box = card.getBoundingClientRect();
      const offset = clientY - box.top - box.height / 2;
      if (offset < 0 && offset > closestOffset) {
        closestOffset = offset;
        closest = card;
      }
    });
    return closest;
  }

  function movePlaceholder(container, clientY) {
    const after = cardAfterCursor(container, clientY);
    if (after) container.insertBefore(placeholder, after);
    else container.appendChild(placeholder);
  }

  function columnAtPoint(x, y) {
    const node = document.elementFromPoint(x, y);
    return node ? node.closest(".crm-col") : null;
  }

  function clearDragClasses() {
    board.querySelectorAll(".crm-col.is-over, .crm-col-body.is-targeting").forEach((node) => {
      node.classList.remove("is-over", "is-targeting");
    });
  }

  function finishDrop(x, y) {
    if (!dragCard) return;
    const column = columnAtPoint(x, y) || (placeholder.parentElement && placeholder.parentElement.closest(".crm-col"));
    const sourceColumn = originParent ? originParent.closest(".crm-col") : null;
    if (column && sourceColumn) {
      const body = column.querySelector(".crm-col-body");
      body.insertBefore(dragCard, placeholder);
      refreshBoard();
      saveMove(dragCard, sourceColumn, column);
    }
    cleanupDrag();
  }

  function cleanupDrag() {
    if (dragCard) dragCard.classList.remove("is-dragging");
    if (ghost) ghost.remove();
    ghost = null;
    placeholder.remove();
    clearDragClasses();
    dragCard = null;
    pointerId = null;
    touchActive = false;
    moved = false;
  }

  function startTouchDrag(card, event) {
    const point = event.touches[0];
    dragCard = card;
    rememberOrigin(card);
    touchActive = true;
    moved = false;
    startX = point.clientX;
    startY = point.clientY;
    card.classList.add("is-dragging");
    ghost = card.cloneNode(true);
    ghost.className = "deal-card deal-ghost";
    ghost.style.width = card.getBoundingClientRect().width + "px";
    document.body.appendChild(ghost);
    moveGhost(point.clientX, point.clientY);
    const body = card.parentElement;
    body.insertBefore(placeholder, card);
  }

  function moveGhost(x, y) {
    if (!ghost) return;
    ghost.style.transform = "translate(" + (x - 40) + "px, " + (y - 28) + "px)";
  }

  function bindCard(card) {
    if (card.dataset.bound === "1") return;
    card.dataset.bound = "1";

    card.addEventListener("dragstart", (event) => {
      if (readOnly || touchActive || event.target.closest("input, button, form, a")) {
        event.preventDefault();
        return;
      }
      dragCard = card;
      rememberOrigin(card);
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.id);
      requestAnimationFrame(() => card.classList.add("is-dragging"));
    });

    card.addEventListener("dragend", () => {
      if (touchActive) return;
      card.classList.remove("is-dragging");
      placeholder.remove();
      clearDragClasses();
      dragCard = null;
    });

    // На телефоне HTML5 drag почти не работает — тащим пальцем сами
    card.addEventListener("touchstart", (event) => {
      if (readOnly || event.target.closest("input, button, form, a")) return;
      if (event.touches.length !== 1) return;
      pointerId = event.touches[0].identifier;
      startTouchDrag(card, event);
    }, { passive: true });

    card.addEventListener("click", (event) => {
      if (moved) {
        event.preventDefault();
        event.stopPropagation();
        moved = false;
        return;
      }
      if (event.target.closest("a, button, input")) return;
      if (card.dataset.href) window.location = card.dataset.href;
    });
  }

  board.querySelectorAll(".deal-card").forEach(bindCard);

  function columnUnderCursor(event) {
    return event.target.closest(".crm-col");
  }

  board.addEventListener("dragover", (event) => {
    if (readOnly || !dragCard || touchActive) return;
    const column = columnUnderCursor(event);
    if (!column) return;
    const body = column.querySelector(".crm-col-body");
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    board.querySelectorAll(".crm-col.is-over").forEach((item) => {
      if (item !== column) item.classList.remove("is-over");
    });
    column.classList.add("is-over");
    body.classList.add("is-targeting");
    movePlaceholder(body, event.clientY);
  });

  board.addEventListener("drop", (event) => {
    const column = columnUnderCursor(event);
    if (readOnly || touchActive || !dragCard || !column) return;
    event.preventDefault();
    const body = column.querySelector(".crm-col-body");
    const sourceColumn = originParent.closest(".crm-col");
    body.insertBefore(dragCard, placeholder);
    placeholder.remove();
    refreshBoard();
    saveMove(dragCard, sourceColumn, column);
  });

  document.addEventListener("touchmove", (event) => {
    if (!touchActive || !dragCard) return;
    const point = [...event.touches].find((item) => item.identifier === pointerId) || event.touches[0];
    if (!point) return;
    const dx = Math.abs(point.clientX - startX);
    const dy = Math.abs(point.clientY - startY);
    if (dx > 6 || dy > 6) moved = true;
    event.preventDefault();
    moveGhost(point.clientX, point.clientY);
    const column = columnAtPoint(point.clientX, point.clientY);
    clearDragClasses();
    if (!column) return;
    column.classList.add("is-over");
    const body = column.querySelector(".crm-col-body");
    body.classList.add("is-targeting");
    movePlaceholder(body, point.clientY);
  }, { passive: false });

  document.addEventListener("touchend", (event) => {
    if (!touchActive || !dragCard) return;
    const point = event.changedTouches[0];
    finishDrop(point.clientX, point.clientY);
  });

  document.addEventListener("touchcancel", () => {
    if (!touchActive) return;
    cleanupDrag();
  });

  board.addEventListener("wheel", (event) => {
    if (event.target.closest(".crm-col-body")) return;
    if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
    board.scrollLeft += event.deltaY;
    event.preventDefault();
  }, { passive: false });

  if (searchInput) searchInput.addEventListener("input", refreshBoard);

  board.querySelectorAll(".crm-col").forEach((column) => {
    const openButton = column.querySelector(".quick-open");
    const form = column.querySelector(".quick-form");
    const cancelButton = column.querySelector(".quick-cancel");
    const errorNode = column.querySelector(".quick-error");
    if (!openButton || !form) return;

    function closeForm() {
      form.hidden = true;
      openButton.hidden = false;
      errorNode.hidden = true;
      form.reset();
    }

    openButton.addEventListener("click", () => {
      openButton.hidden = true;
      form.hidden = false;
      form.querySelector("input[name='title']").focus();
    });

    cancelButton.addEventListener("click", closeForm);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const title = form.querySelector("input[name='title']").value.trim();
      const rawSum = form.querySelector("input[name='opportunity']").value
        .replace(/\s/g, "")
        .replace(",", ".");
      const carInput = form.querySelector("input[name='car']");
      errorNode.hidden = true;
      if (!title) {
        errorNode.hidden = false;
        errorNode.textContent = "Введите название";
        return;
      }

      setSaveState("saving", "Сохраняю…");
      const response = await fetch("/api/deals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title,
          car: carInput ? carInput.value.trim() : "",
          opportunity: rawSum || 0,
          stage_id: Number(column.dataset.stageId),
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        errorNode.hidden = false;
        errorNode.textContent = data.error || "Не получилось создать";
        setSaveState("error", "Не сохранилось");
        return;
      }

      const body = column.querySelector(".crm-col-body");
      const empty = body.querySelector(".col-empty");
      empty.insertAdjacentHTML("afterend", data.html);
      const newCard = empty.nextElementSibling;
      bindCard(newCard);
      markSaved(newCard);
      closeForm();
      refreshBoard();
      setSaveState("saved", "Сохранено");
    });
  });
})();
