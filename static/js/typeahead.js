(function () {
    function initTypeahead(container) {
        var input = container.querySelector("[data-typeahead-input]");
        var hidden = container.querySelector("[data-typeahead-hidden]");
        var results = container.querySelector("[data-typeahead-results]");
        var url = container.getAttribute("data-typeahead-url");
        var minChars = parseInt(container.getAttribute("data-typeahead-min") || "2", 10);
        var limit = parseInt(container.getAttribute("data-typeahead-limit") || "8", 10);
        if (!input || !hidden || !results || !url) {
            return;
        }
        var timer = null;
        var lastQuery = "";
        var activeIndex = -1;
        var currentItems = [];
        var abortController = null;

        // Generate unique IDs for ARIA linkage
        var listboxId = "typeahead-listbox-" + Math.random().toString(36).slice(2, 8);

        // Set ARIA attributes on the input (combobox pattern)
        input.setAttribute("role", "combobox");
        input.setAttribute("autocomplete", "off");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("aria-controls", listboxId);
        input.setAttribute("aria-haspopup", "listbox");

        function clearResults() {
            results.innerHTML = "";
            activeIndex = -1;
            currentItems = [];
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
        }

        function setActiveOption(index) {
            var options = results.querySelectorAll("[role='option']");
            options.forEach(function (opt) {
                opt.classList.remove("bg-slate-100", "dark:bg-slate-700");
                opt.setAttribute("aria-selected", "false");
            });
            activeIndex = index;
            if (index >= 0 && index < options.length) {
                options[index].classList.add("bg-slate-100", "dark:bg-slate-700");
                options[index].setAttribute("aria-selected", "true");
                input.setAttribute("aria-activedescendant", options[index].id);
                options[index].scrollIntoView({ block: "nearest" });
            } else {
                input.removeAttribute("aria-activedescendant");
            }
        }

        function selectItem(item) {
            input.value = item.label || item.name || "";
            hidden.value = item.ref || item.id || "";
            clearResults();
        }

        function renderResults(items) {
            if (!items || !items.length) {
                clearResults();
                return;
            }
            currentItems = items;
            activeIndex = -1;
            var menu = document.createElement("div");
            menu.id = listboxId;
            menu.setAttribute("role", "listbox");
            menu.className = "absolute z-10 mt-2 w-full max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800";
            items.forEach(function (item, idx) {
                var option = document.createElement("div");
                option.id = listboxId + "-opt-" + idx;
                option.setAttribute("role", "option");
                option.setAttribute("aria-selected", "false");
                option.className = "w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-700 cursor-pointer";
                option.textContent = item.label || item.name || "";
                option.addEventListener("mousedown", function (e) {
                    e.preventDefault(); // Prevent input blur before selection
                    selectItem(item);
                });
                menu.appendChild(option);
            });
            results.innerHTML = "";
            results.appendChild(menu);
            input.setAttribute("aria-expanded", "true");
        }

        function fetchResults(query) {
            // Cancel previous in-flight request
            if (abortController) {
                abortController.abort();
            }
            abortController = new AbortController();
            var requestUrl = url + "?q=" + encodeURIComponent(query) + "&limit=" + limit;
            fetch(requestUrl, { signal: abortController.signal })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error("typeahead request failed");
                    }
                    return response.json();
                })
                .then(function (data) {
                    renderResults((data && data.items) || []);
                })
                .catch(function (err) {
                    if (err && err.name === "AbortError") return;
                    clearResults();
                });
        }

        function scheduleFetch(query) {
            if (timer) {
                window.clearTimeout(timer);
            }
            timer = window.setTimeout(function () {
                if (query !== lastQuery || query.length === 0) {
                    fetchResults(query);
                    lastQuery = query;
                }
            }, 250);
        }

        input.addEventListener("input", function () {
            var query = input.value.trim();
            hidden.value = "";
            if (query.length < minChars) {
                clearResults();
                lastQuery = query;
                return;
            }
            scheduleFetch(query);
        });

        input.addEventListener("focus", function () {
            var query = input.value.trim();
            if (query.length >= minChars || minChars === 0) {
                scheduleFetch(query);
            }
        });

        // Keyboard navigation
        input.addEventListener("keydown", function (e) {
            var optionCount = currentItems.length;
            if (!optionCount) return;

            if (e.key === "ArrowDown") {
                e.preventDefault();
                setActiveOption(activeIndex < optionCount - 1 ? activeIndex + 1 : 0);
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveOption(activeIndex > 0 ? activeIndex - 1 : optionCount - 1);
            } else if (e.key === "Enter") {
                if (activeIndex >= 0 && activeIndex < optionCount) {
                    e.preventDefault();
                    selectItem(currentItems[activeIndex]);
                }
            } else if (e.key === "Escape") {
                e.preventDefault();
                clearResults();
            }
        });

        input.addEventListener("blur", function () {
            // Delay to allow mousedown on option to fire first
            setTimeout(function () { clearResults(); }, 150);
        });

        // Store handler reference so it can be cleaned up
        function onDocumentClick(event) {
            if (!container.contains(event.target)) {
                clearResults();
            }
        }
        document.addEventListener("click", onDocumentClick);

        // Clean up when container is removed from DOM (e.g. HTMX swap)
        if (typeof MutationObserver !== 'undefined') {
            var parentEl = container.parentNode;
            if (parentEl) {
                var observer = new MutationObserver(function (mutations) {
                    for (var i = 0; i < mutations.length; i++) {
                        for (var j = 0; j < mutations[i].removedNodes.length; j++) {
                            if (mutations[i].removedNodes[j] === container || mutations[i].removedNodes[j].contains(container)) {
                                document.removeEventListener("click", onDocumentClick);
                                if (timer) window.clearTimeout(timer);
                                if (abortController) abortController.abort();
                                observer.disconnect();
                                return;
                            }
                        }
                    }
                });
                observer.observe(parentEl, { childList: true });
            }
        }
    }

    function initAll() {
        var containers = document.querySelectorAll("[data-typeahead-url]");
        containers.forEach(function (container) {
            initTypeahead(container);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAll);
    } else {
        initAll();
    }
})();
