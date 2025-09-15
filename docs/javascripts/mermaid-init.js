(function () {
  function currentTheme() {
    var scheme = document.documentElement.getAttribute('data-md-color-scheme') || '';
    // Material uses 'default' and 'slate' by default
    return scheme.indexOf('slate') !== -1 || scheme.indexOf('dark') !== -1 ? 'dark' : 'default';
  }

  function initMermaid() {
    if (window.mermaid) {
      try {
        window.mermaid.initialize({ startOnLoad: true, theme: currentTheme() });
      } catch (e) {
        /* ignore */
      }
    }
  }

  document.addEventListener('DOMContentLoaded', initMermaid);

  // Re-initialize on color scheme changes
  try {
    var mo = new MutationObserver(function () { initMermaid(); });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-md-color-scheme'] });
  } catch (e) {
    /* ignore */
  }
})();

