/* Нижнее меню телефона и выезжающая панель «Ещё». */
(function () {
  const sheet = document.getElementById("mobile-sheet");
  if (!sheet) return;

  const openers = [
    document.getElementById("mobile-more-open"),
    document.getElementById("mobile-more-nav"),
  ].filter(Boolean);
  const closer = document.getElementById("mobile-more-close");

  function openSheet() {
    sheet.hidden = false;
    document.body.classList.add("sheet-open");
  }

  function closeSheet() {
    sheet.hidden = true;
    document.body.classList.remove("sheet-open");
  }

  openers.forEach((button) => button.addEventListener("click", openSheet));
  if (closer) closer.addEventListener("click", closeSheet);
  sheet.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeSheet));
})();
