(() => {
  const component = document.querySelector(".location-autocomplete");
  if (!component) return;

  const input = component.querySelector("input");
  const list = component.querySelector("[role='listbox']");
  const hint = component.querySelector(".location-hint");
  let results = [];
  let activeIndex = -1;
  let debounceTimer;
  let activeRequest;

  const close = () => {
    results = [];
    activeIndex = -1;
    list.replaceChildren();
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
  };

  const choose = (result) => {
    input.value = result.formatted;
    hint.textContent = "Location selected.";
    close();
    input.focus();
  };

  const render = () => {
    list.replaceChildren();
    results.forEach((result, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "location-suggestion";
      button.role = "option";
      button.textContent = result.formatted;
      button.setAttribute("aria-selected", String(index === activeIndex));
      button.addEventListener("mousedown", (event) => {
        event.preventDefault();
        choose(result);
      });
      list.append(button);
    });
    list.hidden = results.length === 0;
    input.setAttribute("aria-expanded", String(results.length > 0));
  };

  const search = async () => {
    const query = input.value.trim();
    if (query.length < 3) {
      hint.textContent = "Start typing a venue or address to see suggestions.";
      close();
      return;
    }

    activeRequest?.abort();
    activeRequest = new AbortController();
    hint.textContent = "Searching locations…";
    try {
      const url = new URL(component.dataset.suggestionsUrl, window.location.origin);
      url.searchParams.set("q", query);
      const response = await fetch(url, { signal: activeRequest.signal });
      const payload = await response.json();
      results = Array.isArray(payload.results) ? payload.results : [];
      activeIndex = -1;
      render();
      hint.textContent = results.length ? "Choose a suggested location, or continue typing." : "No suggestions found. You can still enter a location manually.";
    } catch (error) {
      if (error.name !== "AbortError") {
        close();
        hint.textContent = "Suggestions are unavailable. You can still enter a location manually.";
      }
    }
  };

  input.addEventListener("input", () => {
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(search, 250);
  });

  input.addEventListener("keydown", (event) => {
    if (!results.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = event.key === "ArrowDown"
        ? (activeIndex + 1) % results.length
        : (activeIndex - 1 + results.length) % results.length;
      render();
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      choose(results[activeIndex]);
    } else if (event.key === "Escape") {
      close();
    }
  });

  input.addEventListener("blur", () => window.setTimeout(close, 120));
})();
