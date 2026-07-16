/*
 * Редактируемые видимые подписи Mini App.
 * Замены применяются только к текстовым узлам и не меняют API, статусы и onclick.
 */
(function () {
  "use strict";

  window.OBORUDKA_UI_TEXTS = Object.assign({
    "Оборудыш — Mini App": "Оборудыш — Mini App",
    "Пользователь": "Пользователь",
    "Админ": "Админ",
    "Старший админ": "Старший админ",
    "Назад": "Назад",
    "Отмена": "Отмена",
    "Сохранить": "Сохранить",
    "Удалить": "Удалить",
    "Подтвердить": "Подтвердить",
    "Забронировать оборудование": "Забронировать оборудование",
    "Забронировать 626": "Забронировать 626",
    "Панель админа": "Панель админа",
    "Паспорта экземпляров": "Паспорта экземпляров",
    "Недельный календарь": "Недельный календарь"
  }, window.OBORUDKA_UI_TEXTS || {});

  function replaceTextNode(node) {
    var raw = node.nodeValue || "";
    var source = raw.trim();
    if (!source || !Object.prototype.hasOwnProperty.call(window.OBORUDKA_UI_TEXTS, source)) return;
    var replacement = String(window.OBORUDKA_UI_TEXTS[source]);
    if (replacement !== source) node.nodeValue = raw.replace(source, replacement);
  }

  function applyTexts(root) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) {
      replaceTextNode(root);
      return;
    }
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var node;
    while ((node = walker.nextNode())) replaceTextNode(node);
  }

  window.applyOborudkaUiTexts = applyTexts;
  applyTexts(document.documentElement);
  new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      mutation.addedNodes.forEach(applyTexts);
    });
  }).observe(document.body, {childList: true, subtree: true});
})();
