/* PaperFinder front end.
   Talks only to our own server (api/search, api/health), never to OpenAlex directly,
   so no API key is ever sent to the browser. 
   All text from the API is added with textContent, never innerHTML, so a paper title
   can't inject code into the page (XSS protection). */
"use strict";

(function () {
    var byId = function (id) { return document.getElementById(id); };

    var form = byId("search-form");
    var queryInput = byId("q");
    var freeInput = byId("free");
    var fromInput = byId("from");
    var toInput = byId("to");
    var typeInput = byId("type");
    var sortInput = byId("sort");
    var statusEl = byId("status");
    var resultsEl = byId("results");
    var pager = byId("pager");
    var prevButton = byId("prev");
    var nextButton = byId("next");
    var pageInfo = byId("page-info");
    var template = byId("paper-template");
    var servedByEl = byId("served-by");

    var LIST_KEY = "paperfinder.readingList";
    var thisYear = new Date().getFullYear();
    var currentPage = 1;
    var totalPages = 1;
    var activeRequest = null;

    fromInput.max = String(thisYear);
    toInput.max = String(thisYear);

    /* ------------- Reading list (saved in this browser) -------------- */
    function loadlist() {
        try {
            var saved = JSON.parse(localStorage.getItem(LIST_KEY) || "[]");
            return Array.isArray(saved) ? saved : [];
        } catch (error) {
            return [];
        }
    }


    function saveList() {
        try {
            localStorage.setItem(LIST_KEY, JSON.stringify(readingList));
        } catch (error) {
            /* Storage can be blocked (private mode). The list still works until the page is closes. */
        }
    }

    var readingList = loadlist();

    function isSaved(id) {
        return readingList.some(function (item) { return item.id === id; });
    }


    function toggleSaved(paper) {
        if (isSaved(paper.id)) {
            readingList = readingList.filter(function (item) { return item.id !== paper.id; });
        } else {
            readingList.push({
                id: paper.id,
                title: paper.title,
                authors: paper.authors,
                more_authors: paper.more_authors,
                year: paper.year,
                venue: paper.venue,
                url: paper.free_url || paper.link
            });
        }
        saveList();
        renderList();
        syncSaveButtons();
    }


    function renderList() {
        var listEl = byId("list-items");
        listEl.textContent = "";
        readingList.forEach(function (item) {
            var li = document.createElement("li");

            var link = document.createElement("a");
            link.href = item.url || "#";
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = item.title;

            var details = document.createElement("p");
            details.textContent = authorText(item.authors, item.more_authors) + (item.year ? ", " + item.year : "");

            var remove = document.createElement("button");
            remove.type = "button";
            remove.textContent = "Remove";
            remove.setAttribute("aria-label", "Remove " + item.title);
            remove.addEventListener("click", function () { toggleSaved(item); });

            li.append(link, details, remove);
            listEl.append(li);
        });

        byId("list-count").textContent = String(readingList.length);
        byId("list-empty").hidden = readingList.length > 0;
        byId("list-actions").hidden = readingList.length === 0;
    }


    function downloadList() {
        var lines = ["Reading list from PaperFinder (" + new Date().toLocaleDateString() + ")", ""];
        readingList.forEach(function (item, index) {
            lines.push((index + 1) + ". " + authorText(item.authors, item.more_authors) + " (" + (item.year || "n.d.") + "). " + item.title + "." + (item.venue ? " " + item.venue + "." : ""));
            if (item.url) { lines.push("  " + item.url); }
            lines.push("");
        });
        var file = new Blob([lines.join("\n")], { type: "text/plain" });
        var link = document.createElement("a");
        link.href = URL.createObjectURL(file);
        link.download = "reading-list.txt";
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
    }


    /* ------------- Helpers ---------------- */
    function authorText(authors, more) {
        if (!authors || authors.length === 0) { return "Unknown authors"; }
        var text = authors.join(", ");
        if (more > 0) { text += " and " + more + " more"; }
        return text;
    }


    function setStatus(message, isError) {
        statusEl.textContent = message;
        statusEl.classList.toggle("error", Boolean(isError));
    }


    /* Wrap the searched words in <mark>, using DOM nodes only. */
    function highlight(text, query) {
        var fragment = document.createDocumentFragment();
        var words = query.toLowerCase().split(/\s+/).filter(function (word, index, all) {
            return word.length >= 3 && all.indexOf(word) === index;
        });
        if (words.length === 0) {
            fragment.append(text);
            return fragment;
        }
        var escaped = words.map(function (word) {
            return word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        });
        var parts = text.split(new RegExp("(" + escaped.join("|") + ")", "gi"));
        parts.forEach(function (part, index) {
            if (!part) { return; }
            if (index % 2 === 1) {
                var mark = document.createElement("mark");
                mark.textContent = part;
                fragment.append(mark);
            } else {
                fragment.append(part);
            }
        });
        return fragment;
    }

    /* ------------- Search ----------------- */
    function readSettings(page) {
        return {
            q: queryInput.value.trim().replace(/\s+/g, " "),
            free: freeInput.checked ? "1" : "0",
            from: fromInput.value.trim(),
            to: toInput.value.trim(),
            type: typeInput.value,
            sort: sortInput.value,
            page: String(page)
        };
    }


    function toQueryString(settings) {
        var params = new URLSearchParams();
        Object.keys(settings).forEach(function (key) {
            if (settings[key] !== " ") { params.set(key, settings[key]); }
        });
        return params.toString();
    }


    function checkSettings(settings) {
        if (settings.q.length < 2) { return "Type at least 2 characters to search."; }
        var from = Number(settings.from);
        var to = Number(settings.to);
        if (settings.from && settings.to && from > to) {
            return "The 'From' year must come before the 'To' year.";
        }
        return null;
    }


    function runSearch(page, moveFocus) {
        var settings = readSettings(page);
        var problem = checkSettings(settings);
        if (problem) {
            setStatus(problem, true);
            queryInput.focus();
            return;
        }

        if (activeRequest) { activeRequest.abort(); }
        activeRequest = new AbortController();
        var queryString = toQueryString(settings);
        history.replaceState(null, "", "?" + queryString);

        setStatus("Searching...");
        resultsEl.setAttribute("aria-busy", "true");

        fetch("api/search?" + queryString, { signal: activeRequest.signal })
            .then(function (response) {
                return response.json().catch(function () { return null; }).then(function (body) {
                    if (!response.ok || !body) {
                        var message = body && body.error ? body.error
                            : "Something went wrong (error " + response.status + "). Try again.";
                        throw new Error(message);
                    }
                    return body;
                });
            })
            .then(function (body) {
                currentPage = body.page;
                totalPages = body.pages;
                showServer(body.served_by);
                renderResults(body, settings);
                if (moveFocus) { statusEl.focus(); }
            })
            .catch(function (error) {
                if (error.name === "AbortError") { return; }
                console.error(error);
                var message = error instanceof TypeError
                    ? "Couldn't reach PaperFinder. Check your internet connection and try again."
                    : error.message;
                resultsEl.textContent = "";
                pager.hidden = true;
                setStatus(message, true);
            })
            .finally(function () {
                resultsEl.removeAttribute("aria-busy");
            });
    }


    function renderResults(body, settings) {
        resultsEl.textContent = "";

        if (body.total === 0) {
            pager.hidden = true;
            setStatus(settings.free === "1"
                ? "No papers match. Try fewer words, or untick \"Free to read only\"."
                : "No papers match. Try fewer or different words. ");
            return;
        }

        var found = body.total.toLocaleString() + (body.total === 1 ? " paper" : " papers") + " found";
        setStatus(found + ". Page " + body.page + " of " + body.pages.toLocaleString() + ".");

        body.results.forEach(function (paper) {
            resultsEl.append(buildPaper(paper, settings.q));
        });

        pager.hidden = body.pages <= 1;
        prevButton.disabled = body.page <= 1;
        nextButton.disabled = body.page >= body.pages;
        pageInfo.textContent = "Page " + body.page + " of " + body.pages.toLocaleString();
    }


    function buildPaper(paper, query) {
        var item = template.content.firstElementChild.cloneNode(true);
        item.dataset.id = paper.id;

        var titleLink = item.querySelector(".paper-title a");
        titleLink.append(highlight(paper.title, query));
        if (paper.link) {
            titleLink.href = paper.link;
        } else {
            titleLink.removeAttribute("href");
        }

        item.querySelector(".paper-authors").textContent = authorText(paper.authors, paper.more_authors);

        var where = "";
        if (paper.year && paper.venue) { where = "Published " + paper.year + " in " + paper.venue; }
        else if (paper.year) { where = "Published " + paper.year; }
        else if (paper.venue) { where = "Published in " + paper.venue; }
        item.querySelector(".paper-where").textContent = where;

        var topic = item.querySelector(".paper-topic");
        if (paper.topic) { topic.textContent = paper.topic; } else { topic.remove(); }

        var readFree = item.querySelector(".read-free");
        var notFree = item.querySelector(".not-free");
        if (paper.is_free && paper.free_url) {
            readFree.href = paper.free_url;
            readFree.textContent = paper.free_is_pdf ? "Read free PDF" : "Read for free";
            notFree.remove();
        } else {
            readFree.remove();
        }

        var toggle = item.querySelector(".toggle-summary");
        var summary = item.querySelector(".summary");
        if (paper.abstract) {
            summary.textContent = paper.abstract;
            toggle.addEventListener("click", function () {
                var open = summary.hidden;
                summary.hidden = !open;
                toggle.setAttribute("aria-expanded", String(open));
                toggle.textContent = open ? "Hide summary" : "Show summary";
            });
        } else {
            toggle.remove();
            summary.remove();
        }

        var save = item.querySelector(".save");
        save.addEventListener("click", function () { toggleSaved(paper); });
        setSaveButton(save, isSaved(paper.id));

        item.querySelector(".cite-count").textContent = paper.citations.toLocaleString();
        item.querySelector(".cite-label").textContent = paper.citations === 1 ? "citation" : "citations";
        return item;
    }


    function setSaveButton(button, saved) {
        button.setAttribute("aria-pressed", String(saved));
        button.textContent = saved ? "Saved" : "Save";
    }


    function syncSaveButtons() {
        resultsEl.querySelectorAll(".paper").forEach(function (item) {
            setSaveButton(item.querySelector(".save"), isSaved(item.dataset.id));
        });
    }


    function showServer(name) {
        if (name) { servedByEl.textContent = "This page was answered by server " + name + "."; }
    }

    /* ------------- Events ----------------- */
    form.addEventListener("submit", function (event) {
        event.preventDefault();
        runSearch(1, false);
    });

    [freeInput, typeInput, sortInput, fromInput, toInput].forEach(function (input) {
        input.addEventListener("change", function () {
            if (queryInput.value.trim().length >= 2) { runSearch(1, false); }
        });
    });

    prevButton.addEventListener("click", function () {
        if (currentPage > 1) { runSearch(currentPage - 1, true); }
    });
    nextButton.addEventListener("click", function () {
        if (currentPage < totalPages) { runSearch(currentPage + 1, true); }
    });

    byId("download-list").addEventListener("click", downloadList);
    byId("clear-list").addEventListener("click", function () {
        readingList = [];
        saveList();
        renderList();
        syncSaveButtons();
    });
    /* ------------- Start ------------------ */
    renderList();

    /* Restore a search from the address bar, so links and refreshes work. */
    var start = new URLSearchParams(location.search);
    if (start.get("q")) {
        queryInput.value = start.get("q");
        freeInput.checked = start.get("free") !== "0";
        fromInput.value = start.get("from") || "";
        toInput.value = start.get("to") || "";
        if (start.get("type")) { typeInput.value = start.get("type"); }
        if (start.get("sort")) { sortInput.value = start.get("sort"); }
        runSearch(Number(start.get("page")) || 1, false);
    } else {
        fetch("api/health")
            .then(function (response) { return response.json(); })
            .then(function (body) { showServer(body.served_by); })
            .catch(function () { /* footer just stays empty */ });
    }


})();